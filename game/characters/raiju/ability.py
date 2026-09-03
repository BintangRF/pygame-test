"""Raiju-specific ability logic: Fang Flicker/Blink Strike's ambush bonus
against a target struck from far away, Chain Bolt/Static Bite stacking
into Static (and the discharge burst once it caps), Static Field's charge
zone, and Thunder God's Descent's overcharge payoff. The generic damage
pipeline in combat_resolution.py and the generic dispatchers in
status_effects.py just call into these hooks — every method here guards on
`attacker is self.raiju` so it's a no-op in any matchup without Raiju."""

import pygame

from ...core.constants import RAIJU_CYAN, WHITE
from ...core.entities import Zone, set_status
from ...core.particles import emit_spark_burst


class RaijuAbilityMixin:
    def raiju_ambush_bonus(self, attacker, defender, ability, dmg, note):
        if attacker is self.raiju and ability.tag == "blink_strike":
            dist = (self.defender_start - self.attacker_start).length()
            if dist > 150:
                return round(dmg * 1.3), note + " [AMBUSH]"
        return dmg, note

    def raiju_overcharge_bonus(self, attacker, defender, ability, dmg, note):
        if attacker is self.raiju and ability.tag == "thunder_descent":
            static = defender.statuses.get("static")
            stacks = static.get("stacks", 0) if static else 0
            if stacks > 0:
                bonus = round(attacker.atk * 0.4 * stacks)
                del defender.statuses["static"]
                return dmg + bonus, note + f" (+{bonus} Overcharge)"
        return dmg, note

    def raiju_static_defense_bonus(self, defender, dmg):
        static = defender.statuses.get("static")
        if static and static.get("stacks", 0) > 0:
            return round(dmg * (1 + static["stacks"] * 0.05))
        return dmg

    def apply_static_stack(self, attacker, defender, gain):
        """Add Static stacks to defender (capped at 5); at the cap the next
        hit instead discharges — a burst of bonus damage that resets the
        stack to zero, rewarding a build-then-release rhythm."""
        cur = defender.statuses.get("static", {})
        stacks = min(5, cur.get("stacks", 0) + gain)
        if stacks >= 5:
            nova = round(attacker.atk * 0.6)
            actual = self.apply_damage(defender, nova)
            defender.statuses.pop("static", None)
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 60, -0.6, 255, f"-{actual} DISCHARGE!", RAIJU_CYAN]
            )
            self.add_screen_shake(15, 220)
            self.add_ring(defender.pos, 60, 350, RAIJU_CYAN, width=4)
            emit_spark_burst(self.fx, defender.pos, RAIJU_CYAN, count=20)
            self.log = f"{defender.name} overloads and discharges {actual} bonus damage!"
        else:
            set_status(defender, "static", 6000, stacks=stacks)

    def raiju_apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.raiju:
            return
        tag = ability.tag
        if tag in ("static_bite", "chain_bolt") and defender is not None and self.damage_applied:
            self.apply_static_stack(attacker, defender, gain=1 if tag == "static_bite" else 2)
        elif tag == "static_field":
            self.zones.append(Zone("static", pygame.Vector2(attacker.pos), 70, 6000, attacker))
            self.log = f"{attacker.name} charges the ground with a Static Field!"
            self.add_ring(attacker.pos, 120, 600, RAIJU_CYAN, width=5)
            emit_spark_burst(self.fx, attacker.pos, RAIJU_CYAN, count=30)
        elif tag == "thunder_descent":
            if defender is not None:
                set_status(defender, "healing_reduced", 4000, pct=0.5)
            self.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "THUNDER GOD!", RAIJU_CYAN])
            self.log = f"{attacker.name} calls down Thunder God's Descent on {defender.name}!"
            self.flash_timer = max(self.flash_timer, 480)
            self.add_screen_shake(24, 300)
            self.add_ring(defender.pos, 180, 750, RAIJU_CYAN, width=6)
            self.add_ring(defender.pos, 120, 650, WHITE, width=3)
            emit_spark_burst(self.fx, defender.pos, RAIJU_CYAN, count=50)

    def raiju_zone_tick(self, f, z, dt):
        if f is z.owner:
            f.meter = min(f.meter_max, f.meter + 10 * dt)
        elif not f.statuses.get("rage"):
            self.apply_damage(f, 4 * dt)
