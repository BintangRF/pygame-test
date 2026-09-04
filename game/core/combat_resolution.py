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
        self.seq = [(n, int(d * dur_mult)) for n, d in MOTIONS[self.motion]]
        if self.motion == "bolt":
            # A fixed "fire" duration would make the bolt's PERCEIVED speed
            # swing wildly with however far apart the two fighters happen to
            # be standing (DVD-logo bounce movement puts them anywhere from
            # right next to each other to opposite corners) — a short hop
            # crawls across in the same time a full-arena shot needs, and
            # reads as randomly "slow" or "normal" from one cast to the
            # next. Derive it from BOLT_SPEED instead, so the bolt always
            # travels at the same real speed regardless of distance.
            travel_ms = max(1, round(direction.length() / self.BOLT_SPEED * 1000 * dur_mult))
            self.seq = [(n, travel_ms if n == "fire" else d) for n, d in self.seq]
        self.seq_index = 0
        self.phase_elapsed = 0
        self.current_phase = self.seq[0][0]
        self.damage_applied = False
        self._miss = False

        if ability.tag == "swarm":
            self.strike_point = self.defender_start - self.atk_dir * 60
        else:
            self.strike_point = self.attacker_start + direction * 0.75

        self.projectile_pos = None
        self.projectile_origin = None
        self.projectile_travel_ms = 0.0
        self.ricochet_pos = None
        self.ricochet_vel = None
        self.ricochet_bounces = 0
        self.projectile_hit_confirmed = False
        # Where the attacker actually ends up once the whole sequence
        # finishes (see battle_loop.py's update_attack) — every motion
        # already animates its own way back to attacker_start (or, for
        # moves_while_active abilities, is skipped entirely and left
        # wherever roam_step put them), so this is just that starting spot.
        self.attack_final_pos = pygame.Vector2(self.attacker_start)
        self.attack_target_clone = self.taunt_redirect(attacker, defender, ability) is not None
        if self.attack_target_clone:
            self.defender_start = pygame.Vector2(self.clone.pos)
            self.strike_point = self.attacker_start + (self.defender_start - self.attacker_start) * 0.75

        # Neither fighter's vel is touched here — a fighter frozen for this
        # attack (the common case: not moves_while_active for the attacker,
        # not is_dodgeable for the defender) just doesn't get roam_step'd
        # while frozen (see apply_motion_frame/update_attack in
        # battle_loop.py), so their velocity sits untouched and they resume
        # on the exact same DVD-logo heading once roaming again — no
        # random relaunch, no direction change except off a wall.
        cooldown = ability.cooldown_ms
        for plugin in self.plugins:
            cooldown = plugin.cooldown_bonus(attacker, ability, cooldown)
        ability.timer = round(cooldown * self.status_cooldown_multiplier(attacker))
        if ability.one_shot:
            ability.used = True
        for plugin in self.plugins:
            plugin.consume_ammo(attacker, ability)
        self.mode = "attack"
        tag_txt = "[ULTIMATE] " if ability.kind == "ultimate" else ""
        self.log = f"{tag_txt}{attacker.name} uses {ability.name}!"

    def apply_damage(self, target, dmg):
        """The single funnel every source of HP loss goes through: a target
        with the generic Invulnerable status (is_invulnerable — see
        status_library.py; Berserker Rage applies it alongside its own
        attack/attack-speed/move-speed buffs) takes nothing at all,
        last-resort backstop for any damage path that doesn't already check
        it up front. Armor
        mitigates what's left (never past 100%, however high armor climbs),
        then each present character's own reactive passive gets a look at
        the hit (fury stacking, a death-save). Returns the actual amount
        subtracted."""
        if self.is_invulnerable(target):
            return 0
        armor = target.armor * self.armor_break_multiplier(target)
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
        for plugin in self.plugins:
            dmg = plugin.incoming_defense(attacker, defender, dmg)
        dmg = round(dmg * self.status_damage_multiplier(defender))
        dmg = self.apply_shield_absorb(defender, dmg)
        dmg = max(0, dmg)
        actual = self.apply_damage(defender, dmg)
        for plugin in self.plugins:
            plugin.on_damage_taken(defender, actual)
        self.apply_status_reflect(attacker, defender, actual)
        return actual

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

        heal_mult = self.heal_reduction_multiplier(attacker)
        for plugin in self.plugins:
            heal_mult = plugin.heal_bonus(attacker, heal_mult)
        if ability.heal_ratio > 0:
            heal = round(actual * ability.heal_ratio * heal_mult)
            attacker.hp = min(attacker.max_hp, attacker.hp + heal)
            self.floaters.append([attacker.pos.x, attacker.pos.y - 40, -0.6, 255, f"+{heal}", GREEN])

        ls_pct = self.lifesteal_pct(attacker)
        if ls_pct:
            ls_heal = round(actual * ls_pct * heal_mult)
            if ls_heal > 0:
                attacker.hp = min(attacker.max_hp, attacker.hp + ls_heal)
                self.floaters.append([attacker.pos.x, attacker.pos.y - 40, -0.6, 255, f"+{ls_heal}", GREEN])

        for plugin in self.plugins:
            plugin.on_damage_dealt(attacker, defender, actual)

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
        self.attack_target_clone = False
        self.mode = "roam"

    def declare_winner(self):
        self.winner = self.f1 if self.f1.is_alive() else self.f2
        self.mode = "gameover"
