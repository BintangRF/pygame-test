"""Paladin-specific ability logic: Radiant Energy build-up and its
bonus-damage payoff, Divine Shield's mitigation/absorb (with the Holy Nova
retaliation once the barrier breaks), Judgment Mark's detonation, and
Sacred Ground's healing zone. The generic damage pipeline in
combat_resolution.py and the generic dispatchers in status_effects.py just
call into these hooks — every method here guards on `attacker`/`defender`/
`target is self.paladin` so it's a no-op in any matchup without a Paladin."""

import pygame

from ...core.constants import GOLD, SHIELD_COLOR, WHITE
from ...core.entities import Zone, set_status
from ...core.particles import emit_holy


class PaladinAbilityMixin:
    def paladin_radiant_bonus(self, attacker, defender, ability, dmg, note):
        if attacker is self.paladin and attacker.radiant_energy > 0:
            bonus = round(attacker.radiant_energy)
            attacker.radiant_energy = 0.0
            return dmg + bonus, note + f" (+{bonus} Radiant)"
        return dmg, note

    def paladin_gain_radiant_energy(self, defender, actual):
        if defender is self.paladin:
            defender.radiant_energy += actual * 0.3

    def paladin_shield_defense(self, attacker, defender, dmg):
        if defender is not self.paladin or "shield" not in defender.statuses:
            return dmg
        sh = defender.statuses["shield"]
        reduction_pct = sh.get("reduction", 0)
        if reduction_pct > 0:
            dmg = round(dmg * (1 - reduction_pct))
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 55, -0.5, 255, "Mitigated", SHIELD_COLOR]
            )
        if sh["absorb"] > 0:
            absorbed = min(sh["absorb"], dmg)
            sh["absorb"] -= absorbed
            dmg -= absorbed
            if absorbed > 0:
                self.floaters.append(
                    [defender.pos.x, defender.pos.y - 68, -0.5, 255, "Absorbed", SHIELD_COLOR]
                )
            if sh["absorb"] <= 0:
                del defender.statuses["shield"]
                nova = round(self.paladin.atk * 0.8)
                self.apply_damage(attacker, nova)
                self.floaters.append(
                    [attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "Holy Nova!", GOLD]
                )
                self.add_screen_shake(17, 260)
                self.flash_timer = max(self.flash_timer, 340)
                self.add_ring(attacker.pos, 90, 450, GOLD, width=5)
                emit_holy(self.fx, attacker.pos, count=26, radius=50)
        return dmg

    def cast_divine_shield(self):
        p = self.paladin
        set_status(p, "shield", 5000, absorb=round(p.max_hp * 0.25), reduction=0.3)
        p.meter = min(p.meter_max, p.meter + p.meter_gain)
        self.log = f"{p.name} raises Divine Shield!"

    def paladin_apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.paladin:
            return
        tag = ability.tag
        if tag == "mark" and defender is not None and self.damage_applied:
            set_status(defender, "mark", 4000, bonus=0.5, explode=round(attacker.atk * 1.2))
            self.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Marked!", GOLD])
            self.log = f"{attacker.name} brands {defender.name} with Judgment Mark!"
        elif tag == "shield":
            self.cast_divine_shield()
            self.add_ring(attacker.pos, 90, 500, SHIELD_COLOR, width=4)
            emit_holy(self.fx, attacker.pos, count=24, radius=48)
        elif tag == "sacred_ground":
            self.zones.append(Zone("sacred", pygame.Vector2(attacker.pos), 75, 2000, attacker))
            self.log = f"{attacker.name} creates Sacred Ground!"
            self.add_ring(attacker.pos, 130, 700, GOLD, width=5)
            emit_holy(self.fx, attacker.pos, count=40, radius=90)
        elif tag == "heavens_verdict":
            if defender is not None:
                set_status(defender, "healing_reduced", 4000, pct=0.6)
            set_status(attacker, "shield", 3000, absorb=round(attacker.max_hp * 0.2), reduction=0.2)
            self.flash_timer = 450
            impact_pos = defender.pos if defender is not None else attacker.pos
            self.add_ring(impact_pos, 180, 750, GOLD, width=6)
            self.add_ring(impact_pos, 120, 700, WHITE, width=3)
            emit_holy(self.fx, impact_pos, count=50, radius=80)

    def paladin_on_status_expire(self, f, name, data):
        if name != "mark" or f.statuses.get("rage"):
            return
        dmg = data.get("explode", 10)
        actual = self.apply_damage(f, dmg)
        self.floaters.append([f.pos.x, f.pos.y - 50, -0.6, 255, f"-{actual} MARK", GOLD])
        self.log = f"Judgment Mark detonates on {f.name}!"
        self.add_screen_shake(13, 220)
        self.add_ring(f.pos, 70, 400, GOLD, width=4)

    def paladin_zone_tick(self, f, z, dt):
        if f is z.owner:
            f.hp = min(f.max_hp, f.hp + 6 * dt)
        elif not f.statuses.get("rage"):
            self.apply_damage(f, 5 * dt)
            set_status(f, "healing_reduced", 500, pct=0.5)
