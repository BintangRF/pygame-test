"""Ability resolution pipeline: pick a move for the acting fighter, run the
damage/heal formula through every present character's CharacterPlugin hooks
(marks, shields, curses, rage, radiant energy, static overcharge...), and
wrap up the attack sequence once it lands. Every character-specific number
and side effect lives in that character's own characters/<name>/plugin.py
(see core/plugin.py for the hook contract) — this file only owns the
generic pipeline and the roam/attack sequencing around it, looping over
self.plugins at each step instead of naming characters.
"""

import random

import pygame

from .attack_state import AttackState
from .constants import GOLD, GRAY, GREEN, ORANGE, RED, WHITE
from .entities import in_cone
from .motions import MOTIONS, is_dodgeable
from .particles import emit_spark_burst


class CombatResolutionMixin:
    # px/s a "bolt"-motion projectile actually travels at — see
    # try_start_attack(), which derives its "fire" phase duration from this
    # instead of using a fixed duration regardless of distance.
    BOLT_SPEED = 800

    def choose_ability(self, attacker, defender):
        """Every ability off cooldown (and passing its own gating — melee
        range, ammo, the ultimate's HP/meter charge) is a fair candidate;
        whichever fires is picked at random from that pool. No kind takes
        priority over another (an ultimate coming off cooldown doesn't
        preempt a ready basic), and try_start_attack() is called every frame
        for each fighter not already mid-attack (see battle_loop.py's
        update()) so there's no artificial delay once something becomes
        ready."""
        for plugin in self.plugins:
            forced = plugin.forced_ability(attacker)
            if forced is not None:
                return forced

        candidates = []

        basic = attacker.abilities["basic"]
        melee_range = basic.melee_range
        for plugin in self.plugins:
            melee_range = plugin.melee_range_bonus(attacker, melee_range)
        ammo_ok = all(plugin.ammo_ready(attacker, basic) for plugin in self.plugins)
        basic_ready = basic.timer <= 0 and ammo_ok and self.can_basic_attack(attacker) and (
            melee_range is None
            or (attacker.pos - defender.pos).length() <= melee_range
        )
        if basic_ready:
            candidates.append(basic)

        for skill in attacker.abilities["skills"]:
            ammo_ok = all(plugin.ammo_ready(attacker, skill) for plugin in self.plugins)
            if skill.timer <= 0 and ammo_ok and self.can_use_skill(attacker):
                candidates.append(skill)

        ult = attacker.abilities["ultimate"]
        if not ult.used and ult.timer <= 0 and self.can_use_ultimate(attacker):
            if ult.hp_threshold is not None:
                ult_ready = attacker.hp / attacker.max_hp < ult.hp_threshold
            else:
                ult_ready = attacker.meter >= attacker.meter_max
            if ult_ready:
                candidates.append(ult)

        return random.choice(candidates) if candidates else None

    # ---- attack sequence control ---------------------------------------------
    def try_start_attack(self, attacker, defender):
        """Called once per frame for each fighter not already mid-attack
        (see battle_loop.update()) — each fighter is considered
        independently, so both can start a cast the same frame instead of
        one locking the other out until its whole animation finishes."""
        if not self.can_act(attacker):
            return  # stunned/frozen/asleep/feared — retried next frame
        if self.is_vanished(attacker) or self.is_vanished(defender):
            # Vanished isn't a dodge/evade — the vanished fighter is treated
            # as not there at all, on both sides: it can't be picked as a
            # target, and it can't pick a target either, so no attack is
            # ever chosen against (or by) it in the first place. No windup
            # plays, no miss/evaded floater fires — do_damage()'s own
            # is_vanished checks stay only as a backstop for a dodgeable
            # projectile already mid-flight when the target vanishes.
            return  # retried next frame, same as any other unready attack
        ability = self.choose_ability(attacker, defender)
        if ability is None:
            return  # nothing ready yet — retried next frame, no artificial delay

        self._current = AttackState(attacker, defender, ability)
        self.motion = ability.motion

        self.attacker_start = pygame.Vector2(attacker.pos)
        self.defender_start = pygame.Vector2(defender.pos)
        direction = self.defender_start - self.attacker_start
        if direction.length_squared() == 0:
            direction = pygame.Vector2(1, 0)
        self.atk_dir = direction.normalize()

        dur_mult = 1.3 if ability.big else 1.0
        self.seq = [(n, d * dur_mult) for n, d in MOTIONS[self.motion]]
        if self.motion == "bolt":
            # A fixed "fire" duration would make the bolt's PERCEIVED speed
            # swing wildly with however far apart the two fighters happen to
            # be standing (DVD-logo bounce movement puts them anywhere from
            # right next to each other to opposite corners) — a short hop
            # crawls across in the same time a full-arena shot needs, and
            # reads as randomly "slow" or "normal" from one cast to the
            # next. Derive it from BOLT_SPEED instead, so the bolt always
            # travels at the same real speed regardless of distance.
            travel = max(0.001, direction.length() / self.BOLT_SPEED * dur_mult)
            self.seq = [(n, travel if n == "fire" else d) for n, d in self.seq]
        self.current_phase = self.seq[0][0]
        # Every other per-attack field (seq_index, phase_elapsed,
        # damage_applied, _miss, the projectile/ricochet/swarm bookkeeping)
        # already starts at AttackState's own defaults — nothing else to
        # reset here.

        self.strike_point = self.attacker_start + direction * 0.75

        # redirect_target is whichever decoy taunt_redirect actually picked
        # (Vampire's clone, one of Phantom Lancer's illusions, or None) —
        # attack_target_clone stays a plain bool for the rest of the engine
        # (is_dodgeable's evade check below, etc.) that never needs to know
        # which kind of decoy it was.
        self.redirect_target = self.taunt_redirect(attacker, defender, ability)
        self.attack_target_clone = self.redirect_target is not None
        if self.attack_target_clone:
            self.defender_start = pygame.Vector2(self.redirect_target.pos)
            self.strike_point = self.attacker_start + (self.defender_start - self.attacker_start) * 0.75

        if self.motion == "charge":
            # Overrides the defender-relative 0.75 point above — a charge
            # always runs out to the arena edge along atk_dir (see
            # _charge_end_point in battle_loop.py), same as Piercing Ox,
            # regardless of where the (possibly redirected) defender is
            # actually standing.
            self.strike_point = self._charge_end_point()

        for plugin in self.plugins:
            override = plugin.strike_point_override(attacker, ability)
            if override is not None:
                self.strike_point = pygame.Vector2(override)

        # Neither fighter's vel is touched here — the defender never stops
        # roaming for this (see update_roam in battle_loop.py), and an
        # attacker not already moves_while_active just has its own scripted
        # dash/lean own the position field directly instead of vel, so
        # nothing here ever needs a random relaunch or direction change
        # except off a wall.
        cooldown = ability.cooldown
        for plugin in self.plugins:
            cooldown = plugin.cooldown_bonus(attacker, ability, cooldown)
        ability.timer = cooldown * self.status_cooldown_multiplier(attacker)
        if ability.one_shot:
            ability.used = True
        if ability.kind == "ultimate":
            # Reset the instant the cast starts, not once do_damage() lands
            # a hit (that path only ever runs for a dmg_mult > 0 ultimate
            # with a live defender — see resolve_ability() — so a pure
            # self-cast ultimate like Zabaniya/Phantasm/Juxtapose, or one
            # that whiffs/gets evaded, would otherwise never clear the
            # meter at all). One global reset here covers every ultimate
            # the same way regardless of what it does or whether it
            # connects, instead of leaving each character's plugin to
            # remember its own (Eternal Night/Duel used to do this by
            # hand — see vampire/plugin.py, legion_commander/plugin.py).
            attacker.meter = 0
        for plugin in self.plugins:
            plugin.consume_ammo(attacker, ability)
        tag_txt = "[ULTIMATE] " if ability.kind == "ultimate" else ""
        self.log = f"{tag_txt}{attacker.name} uses {ability.name}!"

        self.attacks[attacker] = self._current
        self._current = None

    def apply_damage(self, target, dmg, ignore_armor=False):
        """The single funnel every source of HP loss goes through: a target
        with the generic Invulnerable status (is_invulnerable — see
        status_library.py; Berserker Rage applies it alongside its own
        attack/attack-speed/move-speed buffs) takes nothing at all,
        last-resort backstop for any damage path that doesn't already check
        it up front (the generic Vanished status — Phantom Lancer's
        Doppelganger, both-direction damage immunity — gets the same
        backstop treatment). Armor mitigates what's left (never past 100%,
        however high armor climbs) — and, symmetrically, effective_armor is
        allowed to go negative (Armor Break/Vulnerability outweighing the
        armor actually on hand), in which case this formula amplifies the
        hit past its raw strength instead of just dropping mitigation to
        zero — then each present character's own reactive passive gets a
        look at the hit (fury stacking, a death-save). `ignore_armor` skips
        that mitigation step entirely — bleed/poison/burn's own damage type
        per this game's rules (see status_library.tick_library_effects), not
        a general-purpose knob for other callers. Returns the actual amount
        subtracted."""
        if self.is_invulnerable(target) or self.is_vanished(target):
            return 0
        if not ignore_armor:
            armor = self.effective_armor(target)
            dmg = round(dmg * max(0.0, 1 - armor / 100))
        dmg = max(0, dmg)

        for plugin in self.plugins:
            actual = plugin.pre_damage(target, dmg)
            if actual is not None:
                if actual > 0:
                    self.wake_from_sleep(target)
                return actual

        if dmg > 0:
            self.wake_from_sleep(target)
        target.hp = max(0, target.hp - dmg)
        return dmg

    def deal_damage(self, attacker, defender, dmg, reflect_target=None):
        """`reflect_target` is who actually eats a Reflect bounce-back —
        `attacker` itself by default, but a CloneArmy illusion's own swing
        (see clone_army._clone_attack/on_owner_skill_landed) passes the
        clone here instead: `attacker` there stays the owner for
        lifesteal/incoming_defense/etc. (a clone never carries the owner's
        own lifesteal status — see apply_lifesteal's own note), but the hit
        Reflect is punishing was physically the clone's, so that's who
        should take it back, not the owner standing somewhere else
        entirely."""
        if self.is_vanished(attacker):
            # Closes the gap do_damage()'s own is_vanished(attacker) check
            # can't reach: a source that calls deal_damage() directly
            # instead of going through the full do_damage() pipeline (Bat
            # Swarm/Kai's multi-hit resolve_special, and — the one that
            # actually matters, since only Phantom Lancer ever vanishes —
            # its own clones auto-attacking via _clone_attack while Phantom
            # Lancer itself is vanished).
            return 0
        for plugin in self.plugins:
            dmg = plugin.incoming_defense(attacker, defender, dmg)
        dmg = round(dmg * self.status_damage_multiplier(defender))
        # Reflect punishes the hit itself, not what's left of it once a
        # shield has already eaten some or all of it — a fully-absorbed
        # swing still bounces back at full strength instead of reflecting
        # nothing just because it never touched real hp (see
        # apply_status_reflect's own note on this).
        incoming_dmg = max(0, dmg)
        dmg = self.apply_shield_absorb(attacker, defender, dmg)
        dmg = max(0, dmg)
        actual = self.apply_damage(defender, dmg)
        for plugin in self.plugins:
            plugin.on_damage_taken(defender, actual)
        self.apply_status_reflect(reflect_target if reflect_target is not None else attacker, defender, incoming_dmg)
        self.apply_lifesteal(attacker, actual)
        return actual

    def apply_lifesteal(self, attacker, actual):
        """The generic lifesteal status (StatusLibraryMixin.lifesteal_pct —
        flat 100% of whatever damage actually landed, system-wide) — lives
        here in deal_damage() itself rather than only in do_damage(), so
        every source of damage that funnels through deal_damage() shares it:
        a real fighter's own full ability cast (do_damage() below, right
        after its own actual = self.deal_damage(...)), and anything that
        calls deal_damage() directly without the full ability state machine
        (a CloneArmy illusion's own basic-attack-alike/skill-mirror with the
        owner as the nominal attacker, Bat Swarm's per-projectile hits, ...)
        — attacker here is only ever the real fighter, never a clone itself,
        so this only ever heals whoever owns the "lifesteal" status; a
        Phantasm clone's own Chaos Strike crit deliberately does NOT set
        that status (see ChaosKnightPlugin.clone_basic_attack_roll), so a
        clone's own swing never heals Chaos Knight back."""
        if actual <= 0 or not self.lifesteal_pct(attacker):
            return
        heal_mult = self.heal_reduction_multiplier(attacker)
        for plugin in self.plugins:
            heal_mult = plugin.heal_bonus(attacker, heal_mult)
        heal = round(actual * heal_mult)
        if heal > 0:
            attacker.hp = min(attacker.max_hp, attacker.hp + heal)
            self.floaters.append([attacker.pos.x, attacker.pos.y - 40, -0.6, 255, f"+{heal}", GREEN])

    def do_damage(self):
        """One cast resolving: the strike on this ability's own nominal
        `defender` first, then — for an area ability (Ability.aoe_radius/
        aoe_cone_deg) — that same attack landing on every other body
        standing inside its area (see splash_aoe_to_clones).

        The area half never depends on the outcome of the first: an area
        attack damages whoever is physically standing in its shape, so the
        nominal defender evading it, being immune to it, or having drifted
        clean out of the cone doesn't shield that defender's own clones
        standing inside it. Only an attacker-side abort — the swing
        genuinely never happened — skips the area along with it."""
        if not self._strike_defender():
            return
        self.splash_aoe_to_clones(self.attacker, self.defender, self.ability)

    def _strike_defender(self):
        """Resolve this cast against its own nominal `defender` alone — see
        do_damage(), the only caller, for the area half that runs after
        this. Returns False only when the attack never actually happened
        (the attacker was blinded, or vanished mid-cast) or was already
        resolved in full somewhere else (a plugin's own
        on_attack_redirected); True for every defender-side outcome, landed
        hit and whiff alike, since an area ability still covers its own
        area either way."""
        attacker, defender, ability = self.attacker, self.defender, self.ability

        if self.roll_blind_miss(attacker):
            self._miss = True
            self.floaters.append([attacker.pos.x, attacker.pos.y - 50, -0.5, 255, "Blinded!", GRAY])
            self.log = f"{attacker.name}'s {ability.name} misses — blinded!"
            return False

        if self.is_invulnerable(defender):
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Immune!", ORANGE])
            self.log = f"{attacker.name}'s attack has no effect — {defender.name} is invulnerable!"
            return True

        if self.is_untargetable(defender):
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE])
            self.log = f"{attacker.name}'s attack passes through {defender.name}!"
            return True

        if self.is_vanished(defender):
            # Phantom Lancer's Doppelganger: both-direction damage immunity,
            # not just an evaded hit — the defender genuinely isn't there.
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Vanished!", WHITE])
            self.log = f"{attacker.name}'s attack finds nothing — {defender.name} has vanished!"
            return True

        if self.is_vanished(attacker):
            # The mirror case: an attacker still vanished when their own
            # attack resolves (a very short window right as Doppelganger's
            # own animation hands back to roam) can't land a hit either.
            self._miss = True
            self.floaters.append([attacker.pos.x, attacker.pos.y - 50, -0.5, 255, "Vanished!", WHITE])
            self.log = f"{attacker.name} is vanished — the attack passes through nothing!"
            return False

        for plugin in self.plugins:
            if plugin.on_attack_redirected():
                return False

        if is_dodgeable(ability) and not self.attack_target_clone and not self.projectile_hit_confirmed:
            # projectile_hit_confirmed is set the instant the nail's actual
            # flown position (see apply_motion_frame's "bolt" branch) ever
            # comes within the defender's hit-box during flight — checked
            # continuously frame by frame, not guessed from one distance
            # snapshot, so a real mid-flight touch always counts as a hit.
            self._miss = True
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE]
            )
            self.log = f"{attacker.name}'s {ability.name} whistles past {defender.name}!"
            return True

        if ability.aoe_cone_deg and not in_cone(
            defender.pos, self.attacker_start, self.atk_dir, ability.aoe_cone_deg, ability.aoe_radius or 0
        ):
            # A cone-shaped ability (Axe Throw) is a real swept area, not a
            # guaranteed lock-on to whichever fighter got picked as
            # `defender` — the same entities.in_cone test splash_aoe_to_clones
            # runs against the defender's own clones decides this too, so a
            # fighter that drifted out of the wedge since the throw was
            # aimed whiffs exactly like a clone standing in the same spot
            # would, no exception for which kind of body it is. True, not
            # False: this fighter personally dodged the fan, which says
            # nothing about its own clones — whichever of those are standing
            # in the fan still get swept by do_damage()'s own area half.
            self._miss = True
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE]
            )
            self.log = f"{attacker.name}'s {ability.name} sweeps past {defender.name}!"
            return True

        dmg = round(attacker.atk * ability.dmg_mult)
        dmg = round(dmg * self.status_outgoing_multiplier(attacker))
        note = ""
        for plugin in self.plugins:
            dmg, note = plugin.outgoing_damage(attacker, defender, ability, dmg, note)
        if ability.kind == "ultimate" and defender.hp / defender.max_hp < 0.3:
            dmg = round(dmg * 1.5)
            note += " [EXECUTE]"

        actual = self.deal_damage(attacker, defender, dmg)
        self.damage_applied = True

        defender.shake = 22 if ability.big else (18 if self.motion == "melee_slam" else 13)
        self.apply_impact(defender, ability)
        color = GOLD if ability.kind == "ultimate" else attacker.color
        text = f"-{actual}"
        if ability.kind == "ultimate":
            text += " ULT!"
        if "[EXECUTE]" in note:
            text += " EXECUTE"
        self.floaters.append([defender.pos.x, defender.pos.y - 40, -0.6, 255, text, color])
        self.log = f"{attacker.name} hits {defender.name} for {actual} ({ability.name}){note}!"

        # Ultimates already reset attacker.meter to 0 in try_start_attack()
        # the instant they're cast — only a landed non-ultimate hit still
        # needs to gain meter here.
        if ability.kind != "ultimate":
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)

        # Generic lifesteal (StatusLibraryMixin.lifesteal_pct) is no longer
        # applied here — it already ran inside deal_damage() above (see
        # apply_lifesteal), the instant `actual` was known, so every
        # deal_damage() caller shares it instead of just a full ability cast.
        if ability.heal_ratio > 0:
            heal_mult = self.heal_reduction_multiplier(attacker)
            for plugin in self.plugins:
                heal_mult = plugin.heal_bonus(attacker, heal_mult)
            heal = round(actual * ability.heal_ratio * heal_mult)
            attacker.hp = min(attacker.max_hp, attacker.hp + heal)
            self.floaters.append([attacker.pos.x, attacker.pos.y - 40, -0.6, 255, f"+{heal}", GREEN])

        for plugin in self.plugins:
            plugin.on_damage_dealt(attacker, defender, actual)

        return True

    def splash_aoe_to_clones(self, attacker, defender, ability):
        """An AoE-flavored ability (Ability.aoe_radius/aoe_cone_deg) always
        also damages `defender`'s own clone army (see CharacterPlugin.
        clone_army — Phantom Lancer's illusions, Chaos Knight's Phantasm, or
        any future character's own decoy/illusion kit), whichever character
        it belongs to — fully generic, no per-character wiring needed. Also
        reaches Vampire's own Crimson Doppelganger (self.clone — a single
        decoy tracked outside any CloneArmy entirely, see entities.Clone),
        which a plain clone_army() lookup alone would never see; previously
        only Raiju's own bespoke Volt Fang bothered to check for that one
        separately. No-op for a plain single-target ability, or a defender
        with neither kind of decoy at all.

        Called from do_damage() for the normal pipeline, unconditionally —
        an area ability covers its own area whatever happened to the one
        nominal `defender` (it may well have evaded/been immune/never been
        inside the shape at all), so nothing here may assume that fighter
        was hit, or even that it was standing in the area. A
        resolve_special() override that deals its own damage outside
        do_damage() would need to call this itself too — Bat Swarm (tag ==
        "swarm") doesn't, since its own barrage already lets individual
        projectiles hit a clone directly instead (see _swarm_enemy_bodies
        in battle_loop.py), so it sets no aoe_radius at all."""
        if not (ability.aoe_radius or ability.aoe_cone_deg):
            return
        defender_plugin = self.plugin_for(defender)
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        vampire_clone = self.clone if (self.clone is not None and self.clone.owner is defender) else None
        if army is None and vampire_clone is None:
            return
        dmg = round(attacker.atk * ability.dmg_mult)
        if ability.aoe_cone_deg:
            # A fan swept from the ATTACKER's own position (Axe Throw) —
            # centering a blast on the defender instead would put the whole
            # shape in the wrong place. Reach is aoe_radius itself here — a
            # genuine fixed size, same every cast — not derived from how far
            # the one resolved target happened to be standing (that would
            # make the fan a different size every time depending purely on
            # incidental target distance, not a constant area). This is the
            # exact same wedge do_damage()'s own in_cone check tested
            # `defender` itself against, extended to `defender`'s clones —
            # independently of how that test came out, so every body in the
            # fan is judged by the fan alone, never by what the fighter it
            # belongs to happened to do.
            if army is not None:
                army.splash_cone(
                    self.attacker_start, self.atk_dir, ability.aoe_cone_deg, ability.aoe_radius or 0, dmg,
                    ability=ability,
                )
            if vampire_clone is not None and in_cone(
                vampire_clone.pos, self.attacker_start, self.atk_dir, ability.aoe_cone_deg, ability.aoe_radius or 0
            ):
                self._splash_vampire_clone(vampire_clone, dmg)
        else:
            # A blast that genuinely detonates at the defender's own impact
            # point (Kamino, Heaven's Verdict, Thunder God's Descent) —
            # centering on defender.pos is the correct origin.
            if army is not None:
                army.splash_aoe(defender.pos, ability.aoe_radius, dmg, ability=ability)
            if vampire_clone is not None and (vampire_clone.pos - defender.pos).length() <= ability.aoe_radius:
                self._splash_vampire_clone(vampire_clone, dmg)

    def _splash_vampire_clone(self, clone, dmg):
        """Damages Vampire's own Crimson Doppelganger the same way
        CloneArmy.damage_clone treats any of its own illusions — doubled
        ("no armor of its own to mitigate it further" — same clone tax,
        see clone_army.py's own docstring), a hit floater/spark, and
        destroyed outright at 0 hp (popping battle.clone so nothing keeps
        treating it as still standing in for its owner) — see
        splash_aoe_to_clones."""
        if dmg <= 0:
            return
        dmg = round(dmg * 2)
        clone.hp -= dmg
        self.floaters.append([clone.pos.x, clone.pos.y - 30, -0.5, 200, f"-{dmg}", RED])
        emit_spark_burst(self.fx, clone.pos, clone.owner.color, count=6)
        if clone.hp <= 0 and self.clone is clone:
            self.floaters.append([clone.pos.x, clone.pos.y - 45, -0.6, 220, "Destroyed!", WHITE])
            self.clone = None

    def resolve_ability(self):
        ability = self.ability
        self._miss = False
        for plugin in self.plugins:
            if plugin.resolve_special():
                return
        if ability.dmg_mult > 0 and self.defender is not None:
            self.do_damage()
        self.apply_ability_tag_effects()

    def finish_attack(self):
        # Fighters resume roaming on whatever heading they already had
        # (see try_start_attack()'s note above) — no reroll here, so the
        # only thing that ever changes a fighter's direction is bouncing
        # off an arena wall, same as a DVD logo.
        self.attacks.pop(self.attacker, None)
        if not (self.f1.is_alive() and self.f2.is_alive()):
            # A fatal blow ends the match immediately, even if the other
            # fighter had its own attack mid-flight at the same instant —
            # simpler than staging a double-KO replay of both animations.
            self.declare_winner()

    def declare_winner(self):
        self.winner = self.f1 if self.f1.is_alive() else self.f2
        self.attacks.clear()
