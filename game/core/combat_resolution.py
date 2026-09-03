"""Ability resolution pipeline: pick a move for the acting fighter, run the
damage/heal formula through every character's own modifier hooks (marks,
shields, curses, rage, radiant energy, static overcharge...), and wrap up
the attack sequence once it lands. Every character-specific number and
side effect lives in that character's own ability_*.py module (see
battle.py for the full list) — this file only owns the generic pipeline
and the roam/attack sequencing around it, calling out to those hooks at
each step. Character-specific *tag* side effects (statuses spawned, zones
dropped, ultimates triggered) are dispatched from status_effects.py.
"""

import random

import pygame

from .constants import GOLD, GREEN, ORANGE, WHITE
from .motions import MOTIONS, is_dodgeable


class CombatResolutionMixin:
    def choose_ability(self, attacker, defender):
        """Every ability off cooldown (and passing its own gating — melee
        range, Johnny's Nail Bullet ammo, the ultimate's HP/meter charge) is
        a fair candidate; whichever fires is picked at random from that
        pool. No kind takes priority over another (an ultimate coming off
        cooldown doesn't preempt a ready basic), and start_attack() is
        called every frame while roaming (see battle_loop.py's update()) so
        there's no artificial delay once something becomes ready."""
        candidates = []

        basic = attacker.abilities["basic"]
        melee_range = self.berserker_melee_range_bonus(attacker, basic.melee_range)
        basic_ready = basic.timer <= 0 and self.johnny_ammo_ready(attacker, basic) and (
            melee_range is None
            or (attacker.pos - defender.pos).length() <= melee_range
        )
        if basic_ready:
            candidates.append(basic)

        for skill in attacker.abilities["skills"]:
            if skill.timer <= 0 and self.johnny_ammo_ready(attacker, skill):
                candidates.append(skill)

        ult = attacker.abilities["ultimate"]
        if not ult.used and ult.timer <= 0:
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
        if self.is_stunned(attacker):
            return  # stunned — can't act until it wears off, retried next frame
        ability = self.choose_ability(attacker, defender)
        if ability is None:
            return  # nothing ready yet — retried next frame, no artificial delay

        self.attacker, self.defender, self.ability = attacker, defender, ability
        self.motion = ability.motion
        dur_mult = 1.3 if ability.big else 1.0
        self.seq = [(n, int(d * dur_mult)) for n, d in MOTIONS[self.motion]]
        self.seq_index = 0
        self.phase_elapsed = 0
        self.current_phase = self.seq[0][0]
        self.damage_applied = False
        self._miss = False

        self.attacker_start = pygame.Vector2(attacker.pos)
        self.defender_start = pygame.Vector2(defender.pos)
        direction = self.defender_start - self.attacker_start
        if direction.length_squared() == 0:
            direction = pygame.Vector2(1, 0)
        self.atk_dir = direction.normalize()

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
        self.attack_target_clone = self.vampire_clone_deception_check(attacker, defender, ability)
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
        cooldown = self.berserker_cooldown_bonus(attacker, ability, ability.cooldown_ms)
        ability.timer = cooldown
        if ability.one_shot:
            ability.used = True
        self.johnny_consume_nail_bullet(attacker, ability)
        self.mode = "attack"
        tag_txt = "[ULTIMATE] " if ability.kind == "ultimate" else ""
        self.log = f"{tag_txt}{attacker.name} uses {ability.name}!"

    def apply_damage(self, target, dmg):
        """The single funnel every source of HP loss goes through: a target
        already in Berserker Rage takes nothing at all (last-resort backstop
        for any damage path that doesn't already check "rage" up front),
        armor mitigates what's left (never past 100%, however high armor
        climbs), then each character's own reactive passive gets a look at
        the hit (Berserker's Fury stacking, Berserker's last-stand death
        save). Returns the actual amount subtracted."""
        if target.statuses.get("rage"):
            return 0
        if target.armor > 0:
            dmg = round(dmg * max(0.0, 1 - target.armor / 100))
        dmg = max(0, dmg)

        self.berserker_fury_check(target, dmg)
        death_save_actual = self.berserker_death_save(target, dmg)
        if death_save_actual is not None:
            return death_save_actual

        target.hp = max(0, target.hp - dmg)
        return dmg

    def deal_damage(self, attacker, defender, dmg):
        dmg = self.vampire_mark_weakness(defender, dmg)
        dmg = self.paladin_shield_defense(attacker, defender, dmg)
        dmg = self.raiju_static_defense_bonus(defender, dmg)
        dmg = max(0, dmg)
        actual = self.apply_damage(defender, dmg)
        self.paladin_gain_radiant_energy(defender, actual)
        return actual

    def do_damage(self):
        attacker, defender, ability = self.attacker, self.defender, self.ability

        if defender.statuses.get("rage"):
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Immune!", ORANGE])
            self.log = f"{attacker.name}'s attack has no effect — {defender.name} is raging!"
            return

        if defender.statuses.get("untargetable"):
            self._miss = True
            self.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE])
            self.log = f"{attacker.name}'s attack passes through {defender.name}!"
            return

        if self.vampire_clone_retaliation():
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
        note = ""
        dmg, note = self.berserker_rage_bonus(attacker, defender, ability, dmg, note)
        dmg, note = self.paladin_radiant_bonus(attacker, defender, ability, dmg, note)
        dmg, note = self.raiju_ambush_bonus(attacker, defender, ability, dmg, note)
        dmg, note = self.raiju_overcharge_bonus(attacker, defender, ability, dmg, note)
        dmg, note = self.johnny_critical_bonus(attacker, defender, ability, dmg, note)
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

        heal_mult = 1.0
        if attacker.statuses.get("healing_reduced"):
            heal_mult *= (1 - attacker.statuses["healing_reduced"]["pct"])
        heal_mult = self.vampire_heal_bonus(attacker, heal_mult)
        if ability.heal_ratio > 0:
            heal = round(actual * ability.heal_ratio * heal_mult)
            attacker.hp = min(attacker.max_hp, attacker.hp + heal)
            self.floaters.append([attacker.pos.x, attacker.pos.y - 40, -0.6, 255, f"+{heal}", GREEN])

        self.vampire_curse_reflect(attacker, actual)
        self.vampire_night_extend(attacker)

    def resolve_ability(self):
        ability = self.ability
        self._miss = False
        if ability.tag == "swarm":
            self.vampire_resolve_swarm()
            return
        if ability.tag == "kai_flurry":
            self.sukuna_resolve_kai_flurry()
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
