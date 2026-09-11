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

from .constants import GOLD, GRAY, GREEN, ORANGE, WHITE
from .entities import in_cone
from .motions import MOTIONS, is_dodgeable


class CombatResolutionMixin:
    # px/s a "bolt"-motion projectile actually travels at — see start_attack(),
    # which derives its "fire" phase duration from this instead of using a
    # fixed duration regardless of distance.
    BOLT_SPEED = 800

    def choose_ability(self, attacker, defender):
        """Every ability off cooldown (and passing its own gating — melee
        range, ammo, the ultimate's HP/meter charge) is a fair candidate;
        whichever fires is picked at random from that pool. No kind takes
        priority over another (an ultimate coming off cooldown doesn't
        preempt a ready basic), and start_attack() is called every frame
        while roaming (see battle_loop.py's update()) so there's no
        artificial delay once something becomes ready."""
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
    def start_attack(self):
        if not (self.f1.is_alive() and self.f2.is_alive()):
            self.declare_winner()
            return

        attacker, defender = random.choice([(self.f1, self.f2), (self.f2, self.f1)])
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

        self.attacker, self.defender, self.ability = attacker, defender, ability
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
        self.seq_index = 0
        self.phase_elapsed = 0
        self.current_phase = self.seq[0][0]
        self.damage_applied = False
        self._miss = False

        self.strike_point = self.attacker_start + direction * 0.75

        self.projectile_pos = None
        self.projectile_origin = None
        self.projectile_travel = 0.0
        self.ricochet_pos = None
        self.ricochet_vel = None
        self.ricochet_bounces = 0
        self.ricochet_max_bounces = 0
        self.instant_ricochet_resolved = False
        self.projectile_hit_confirmed = False
        # Ability.tag == "swarm" — see spawn_swarm_projectiles/
        # update_swarm_projectiles/finalize_swarm in battle_loop.py.
        self.swarm_projectiles = []
        self.swarm_hit_count = 0
        self.swarm_dmg_total = 0
        self.swarm_finalized = False
        # Where the attacker actually ends up once the whole sequence
        # finishes (see battle_loop.py's update_attack) — every motion
        # already animates its own way back to attacker_start (or, for
        # moves_while_active abilities, is skipped entirely and left
        # wherever roam_step put them), so this is just that starting spot.
        self.attack_final_pos = pygame.Vector2(self.attacker_start)
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

        for plugin in self.plugins:
            override = plugin.strike_point_override(attacker, ability)
            if override is not None:
                self.strike_point = pygame.Vector2(override)

        # Neither fighter's vel is touched here — a fighter frozen for this
        # attack (the common case: not moves_while_active for the attacker,
        # not is_dodgeable for the defender) just doesn't get roam_step'd
        # while frozen (see apply_motion_frame/update_attack in
        # battle_loop.py), so their velocity sits untouched and they resume
        # on the exact same DVD-logo heading once roaming again — no
        # random relaunch, no direction change except off a wall.
        cooldown = ability.cooldown
        for plugin in self.plugins:
            cooldown = plugin.cooldown_bonus(attacker, ability, cooldown)
        ability.timer = cooldown * self.status_cooldown_multiplier(attacker)
        if ability.one_shot:
            ability.used = True
        for plugin in self.plugins:
            plugin.consume_ammo(attacker, ability)
        self.mode = "attack"
        tag_txt = "[ULTIMATE] " if ability.kind == "ultimate" else ""
        self.log = f"{tag_txt}{attacker.name} uses {ability.name}!"

    def apply_damage(self, target, dmg, ignore_armor=False):
        """The single funnel every source of HP loss goes through: a target
        with the generic Invulnerable status (is_invulnerable — see
        status_library.py; Berserker Rage applies it alongside its own
        attack/attack-speed/move-speed buffs) takes nothing at all,
        last-resort backstop for any damage path that doesn't already check
        it up front (the generic Vanished status — Phantom Lancer's
        Doppelganger, both-direction damage immunity — gets the same
        backstop treatment). Armor
        mitigates what's left (never past 100%, however high armor climbs),
        then each present character's own reactive passive gets a look at
        the hit (fury stacking, a death-save). `ignore_armor` skips that
        mitigation step entirely — bleed/poison/burn's own damage type per
        this game's rules (see status_library.tick_library_effects), not a
        general-purpose knob for other callers. Returns the actual amount
        subtracted."""
        if self.is_invulnerable(target) or self.is_vanished(target):
            return 0
        if not ignore_armor:
            armor = self.effective_armor(target)
            if armor > 0:
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

    def deal_damage(self, attacker, defender, dmg):
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
        dmg = self.apply_shield_absorb(defender, dmg)
        dmg = max(0, dmg)
        actual = self.apply_damage(defender, dmg)
        for plugin in self.plugins:
            plugin.on_damage_taken(defender, actual)
        self.apply_status_reflect(attacker, defender, actual)
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
        — a Phantasm clone's own Chaos Strike crit heals Chaos Knight itself
        exactly the same way the real Mace Slash does, same status, same
        formula, no separate bespoke heal of its own needed."""
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
        attacker, defender, ability = self.attacker, self.defender, self.ability

        if self.roll_blind_miss(attacker):
            self._miss = True
            self.floaters.append([attacker.pos.x, attacker.pos.y - 50, -0.5, 255, "Blinded!", GRAY])
            self.log = f"{attacker.name}'s {ability.name} misses — blinded!"
            return

        if self.is_invulnerable(defender):
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Immune!", ORANGE])
            self.log = f"{attacker.name}'s attack has no effect — {defender.name} is invulnerable!"
            return

        if self.is_untargetable(defender):
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE])
            self.log = f"{attacker.name}'s attack passes through {defender.name}!"
            return

        if self.is_vanished(defender):
            # Phantom Lancer's Doppelganger: both-direction damage immunity,
            # not just an evaded hit — the defender genuinely isn't there.
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Vanished!", WHITE])
            self.log = f"{attacker.name}'s attack finds nothing — {defender.name} has vanished!"
            return

        if self.is_vanished(attacker):
            # The mirror case: an attacker still vanished when their own
            # attack resolves (a very short window right as Doppelganger's
            # own animation hands back to roam) can't land a hit either.
            self._miss = True
            self.floaters.append([attacker.pos.x, attacker.pos.y - 50, -0.5, 255, "Vanished!", WHITE])
            self.log = f"{attacker.name} is vanished — the attack passes through nothing!"
            return

        for plugin in self.plugins:
            if plugin.on_attack_redirected():
                return

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
            return

        if ability.aoe_cone_deg and not in_cone(
            defender.pos, self.attacker_start, self.atk_dir, ability.aoe_cone_deg, ability.aoe_radius or 0
        ):
            # A cone-shaped ability (Axe Throw) is a real swept area, not a
            # guaranteed lock-on to whichever fighter got picked as
            # `defender` — the same entities.in_cone test splash_aoe_to_clones
            # runs against the defender's own clones below decides this too,
            # so a fighter that drifted out of the wedge since the throw was
            # aimed whiffs exactly like a clone standing in the same spot
            # would, no exception for which kind of body it is.
            self._miss = True
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE]
            )
            self.log = f"{attacker.name}'s {ability.name} sweeps past {defender.name}!"
            return

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

        if ability.kind == "ultimate":
            attacker.meter = 0
        else:
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

        self.splash_aoe_to_clones(attacker, defender, ability)

    def splash_aoe_to_clones(self, attacker, defender, ability):
        """An AoE-flavored ability (Ability.aoe_radius/aoe_cone_deg) always
        also damages `defender`'s own clone army (see CharacterPlugin.
        clone_army — Phantom Lancer's illusions, or any future character's
        own decoy/illusion kit), whichever character it belongs to — fully
        generic, no per-character wiring needed. No-op for a plain
        single-target ability, or a defender with no clone army at all.

        Called from do_damage()'s own tail for the normal pipeline; a
        resolve_special() override that deals its own damage outside
        do_damage() would need to call this itself too — Bat Swarm (tag ==
        "swarm") doesn't, since its own barrage already lets individual
        projectiles hit a clone directly instead (see _swarm_enemy_bodies
        in battle_loop.py), so it sets no aoe_radius at all."""
        if not (ability.aoe_radius or ability.aoe_cone_deg):
            return
        defender_plugin = self.plugin_for(defender)
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        if army is None:
            return
        dmg = round(attacker.atk * ability.dmg_mult)
        if ability.aoe_cone_deg:
            # A fan swept from the ATTACKER's own position (Axe Throw) —
            # centering a blast on the defender instead would put the whole
            # shape in the wrong place. Reach is aoe_radius itself here — a
            # genuine fixed size, same every cast — not derived from how far
            # the one resolved target happened to be standing (that would
            # make the fan a different size every time depending purely on
            # incidental target distance, not a constant area). By the time
            # we get here do_damage()'s own in_cone check has already
            # confirmed `defender` itself was inside this exact wedge — this
            # splash just extends the same wedge to `defender`'s clones too.
            army.splash_cone(
                self.attacker_start, self.atk_dir, ability.aoe_cone_deg, ability.aoe_radius or 0, dmg, ability=ability
            )
        else:
            # A blast that genuinely detonates at the defender's own impact
            # point (Kamino, Heaven's Verdict, Thunder God's Descent) —
            # centering on defender.pos is the correct origin.
            army.splash_aoe(defender.pos, ability.aoe_radius, dmg, ability=ability)

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
        if not (self.f1.is_alive() and self.f2.is_alive()):
            self.declare_winner()
            return
        # Fighters resume roaming on whatever heading they already had
        # (see start_attack()'s note above) — no reroll here, so the only
        # thing that ever changes a fighter's direction is bouncing off an
        # arena wall, same as a DVD logo.
        self.ability = None
        self.projectile_pos = None
        self.swarm_projectiles = []
        self.attack_target_clone = False
        self.redirect_target = None
        self.mode = "roam"

    def declare_winner(self):
        self.winner = self.f1 if self.f1.is_alive() else self.f2
        self.mode = "gameover"
