"""Vampire-specific ability logic: Bat Swarm's own damage resolve, Crimson
Doppelganger conjuring/deception (and the retaliation when it's attacked —
works against whichever opponent falls for it), Blood Curse's reflect-heal
off any cursed opponent, Blood Pool's healing zone, Eternal Night's
lifesteal window, and the Vampire's own weakness to Judgment Mark. The
generic damage pipeline in combat_resolution.py and the generic dispatchers
in status_effects.py just call into these hooks — every method here guards
on identity so it's a no-op in any matchup without a Vampire."""

import math
import random

import pygame

from ...core.constants import ARENA_RECT, AVATAR_R, CURSE_COLOR, RED
from ...core.entities import Clone, Zone, set_status
from ...core.particles import emit_blood, emit_dark


class VampireAbilityMixin:
    def vampire_mark_weakness(self, defender, dmg):
        if defender is self.vampire and "mark" in defender.statuses:
            return round(dmg * (1 + defender.statuses["mark"].get("bonus", 0.5)))
        return dmg

    def vampire_heal_bonus(self, attacker, heal_mult):
        if attacker is not self.vampire:
            return heal_mult
        if attacker.hp / attacker.max_hp < 0.3:
            heal_mult += 0.15  # Blood Hunger passive
        if self.night_timer > 0:
            heal_mult += 0.25  # Eternal Night lifesteal boost
        return heal_mult

    def vampire_curse_reflect(self, attacker, actual):
        """Blood Curse: while any opponent carries the vampire's curse
        status, every hit they land heals the Vampire back — works against
        whoever it's cast on, not just the Paladin."""
        if attacker is self.vampire or "cursed" not in attacker.statuses:
            return
        curse = attacker.statuses["cursed"]
        curse["stacks"] = curse.get("stacks", 0) + 1
        heal_c = round(actual * (curse["heal_pct"] + curse["stacks"] * 0.05))
        self.vampire.hp = min(self.vampire.max_hp, self.vampire.hp + heal_c)
        self.vampire.meter = min(self.vampire.meter_max, self.vampire.meter + 3)
        self.floaters.append(
            [self.vampire.pos.x, self.vampire.pos.y - 40, -0.6, 255, f"+{heal_c} Curse", CURSE_COLOR]
        )

    def vampire_night_extend(self, attacker):
        if attacker is self.vampire and self.night_timer > 0:
            self.night_timer = min(12000, self.night_timer + 1500)

    def vampire_clone_deception_check(self, attacker, defender, ability):
        return bool(
            attacker is not self.vampire and defender is self.vampire and self.clone is not None
            and ability.dmg_mult > 0 and random.random() < 0.5
        )

    def vampire_clone_retaliation(self):
        """If the attacker's hit was quietly redirected onto the
        Doppelganger (see vampire_clone_deception_check), pop the decoy and
        strike back at whoever fell for it instead of resolving a normal
        hit — works against any opponent, not just the Paladin."""
        if not (self.attack_target_clone and self.clone is not None):
            return False
        self.clone = None
        fooled = self.attacker
        retal = random.randint(8, 14)
        actual = self.apply_damage(fooled, retal)
        self.floaters.append(
            [fooled.pos.x, fooled.pos.y - 40, -0.6, 255, f"-{actual}", RED]
        )
        self.floaters.append(
            [fooled.pos.x, fooled.pos.y - 55, -0.5, 255, "Fooled!", CURSE_COLOR]
        )
        self.log = f"{fooled.name} strikes a Crimson Doppelganger — Blood Explosion!"
        self._miss = True
        self.damage_applied = True
        return True

    def spawn_clone(self):
        v = self.vampire
        offset = pygame.Vector2(random.uniform(-40, 40), random.uniform(-40, 40))
        pos = pygame.Vector2(v.pos) + offset
        pos.x = max(ARENA_RECT.left + AVATAR_R, min(ARENA_RECT.right - AVATAR_R, pos.x))
        pos.y = max(ARENA_RECT.top + AVATAR_R, min(ARENA_RECT.bottom - AVATAR_R, pos.y))
        angle = random.uniform(0, math.tau)
        vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * random.uniform(60, 100)
        self.clone = Clone(v.image, v.color, pos, vel, 5000)
        self.log = f"{v.name} conjures a Crimson Doppelganger!"

    def start_eternal_night(self):
        self.night_timer = max(self.night_timer, 6000)
        self.vampire.meter = 0
        self.log = f"{self.vampire.name} unleashes Eternal Night!"

    def vampire_apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.vampire:
            return
        tag = ability.tag
        if tag == "curse":
            set_status(defender, "cursed", 5000, heal_pct=0.25, stacks=0)
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            self.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Cursed!", CURSE_COLOR])
            self.log = f"{attacker.name} places Blood Curse on {defender.name}!"
        elif tag == "blood_pool":
            self.zones.append(Zone("blood", pygame.Vector2(attacker.pos), 75, 6000, attacker))
            self.log = f"{attacker.name} spills a Blood Pool!"
            self.add_ring(attacker.pos, 130, 700, CURSE_COLOR, width=5)
            emit_blood(self.fx, attacker.pos, count=38)
        elif tag == "clone":
            self.spawn_clone()
            emit_dark(self.fx, self.vampire.pos, count=32)
        elif tag == "eternal_night":
            self.start_eternal_night()
            self.add_ring(self.vampire.pos, 220, 950, (140, 30, 170), width=6)
            self.add_ring(self.vampire.pos, 150, 900, (200, 60, 220), width=3)
            emit_dark(self.fx, self.vampire.pos, count=60, radius=90)

    def vampire_resolve_swarm(self):
        attacker, defender, ability = self.attacker, self.defender, self.ability
        dmg = round(attacker.atk * ability.dmg_mult)
        actual = self.deal_damage(attacker, defender, dmg)
        self.damage_applied = True
        defender.shake = 16
        self.apply_impact(defender, ability)
        self.floaters.append([defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{actual}", attacker.color])
        self.log = f"{attacker.name}'s Bat Swarm strike hits {defender.name} for {actual}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        set_status(attacker, "untargetable", 700)

    def vampire_zone_tick(self, f, z, dt):
        if f is z.owner:
            f.hp = min(f.max_hp, f.hp + 6 * dt)
            f.meter = min(f.meter_max, f.meter + 8 * dt)
        elif not f.statuses.get("rage"):
            self.apply_damage(f, 5 * dt)
