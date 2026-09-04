"""Raiju plugin: Fang Flicker/Blink Strike's ambush bonus against a target
struck from far away, Chain Bolt/Static Bite stacking into Static (and the
discharge burst once it caps), Static Field's charge zone, Thunder God's
Descent's overcharge payoff, and the teleport-slash/lightning animation."""

import math
import random

import pygame

from ...core.constants import ARENA_RECT, RAIJU_CYAN, WHITE
from ...core.effects import draw_expanding_ring, draw_lightning, draw_slash, draw_slash_arc, draw_starburst
from ...core.entities import Zone, set_status
from ...core.particles import emit_spark_burst
from ...core.plugin import CharacterPlugin

STATIC_VULN_PER_STACK = 0.05


class RaijuPlugin(CharacterPlugin):
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is not self.fighter:
            return dmg, note
        battle = self.battle
        if ability.tag == "blink_strike":
            dist = (battle.defender_start - battle.attacker_start).length()
            if dist > 150:
                return round(dmg * 1.3), note + " [AMBUSH]"
        elif ability.tag == "thunder_descent":
            static = defender.statuses.get("static")
            stacks = static.get("stacks", 0) if static else 0
            if stacks > 0:
                bonus = round(attacker.atk * 0.4 * stacks)
                del defender.statuses["static"]
                defender.statuses.pop("vulnerability", None)
                return dmg + bonus, note + f" (+{bonus} Overcharge)"
        return dmg, note

    def apply_static_stack(self, attacker, defender, gain):
        """Add Static stacks to defender (capped at 5); at the cap the next
        hit instead discharges — a burst of bonus damage that resets the
        stack to zero, rewarding a build-then-release rhythm.

        The extra-damage-taken part of each stack is the generic
        Vulnerability status (status_library.py) — status_damage_multiplier
        already applies it to every hit against `defender`, so there's no
        bespoke incoming_defense hook here anymore; "static" itself is kept
        purely for the stack count/discharge tracking and its own visual
        (the pip counter in render.py, the crackling zone_decorate arcs)."""
        battle = self.battle
        cur = defender.statuses.get("static", {})
        stacks = min(5, cur.get("stacks", 0) + gain)
        if stacks >= 5:
            nova = round(attacker.atk * 0.6)
            actual = battle.apply_damage(defender, nova)
            defender.statuses.pop("static", None)
            defender.statuses.pop("vulnerability", None)
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 60, -0.6, 255, f"-{actual} DISCHARGE!", RAIJU_CYAN]
            )
            battle.add_screen_shake(15, 220)
            battle.add_ring(defender.pos, 60, 350, RAIJU_CYAN, width=4)
            emit_spark_burst(battle.fx, defender.pos, RAIJU_CYAN, count=20)
            battle.log = f"{defender.name} overloads and discharges {actual} bonus damage!"
        else:
            set_status(defender, "static", 6000, stacks=stacks)
            set_status(defender, "vulnerability", 6000, pct=stacks * STATIC_VULN_PER_STACK)

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag in ("static_bite", "chain_bolt") and defender is not None and battle.damage_applied:
            self.apply_static_stack(attacker, defender, gain=1 if tag == "static_bite" else 2)
        elif tag == "static_field":
            battle.zones.append(Zone("static", pygame.Vector2(attacker.pos), 70, 6000, attacker))
            battle.log = f"{attacker.name} charges the ground with a Static Field!"
            battle.add_ring(attacker.pos, 120, 600, RAIJU_CYAN, width=5)
            emit_spark_burst(battle.fx, attacker.pos, RAIJU_CYAN, count=30)
        elif tag == "thunder_descent":
            if defender is not None:
                set_status(defender, "anti_heal", 4000, pct=0.5)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "THUNDER GOD!", RAIJU_CYAN])
            battle.log = f"{attacker.name} calls down Thunder God's Descent on {defender.name}!"
            battle.flash_timer = max(battle.flash_timer, 480)
            battle.add_screen_shake(24, 300)
            battle.add_ring(defender.pos, 180, 750, RAIJU_CYAN, width=6)
            battle.add_ring(defender.pos, 120, 650, WHITE, width=3)
            emit_spark_burst(battle.fx, defender.pos, RAIJU_CYAN, count=50)

    # ---- zone (Static Field) -----------------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        battle = self.battle
        if fighter is zone.owner:
            fighter.meter = min(fighter.meter_max, fighter.meter + 10 * dt)
        elif not fighter.statuses.get("invulnerable"):
            battle.apply_damage(fighter, 4 * dt)

    def zone_style(self, zone):
        return RAIJU_CYAN, "Static Field"

    def zone_decorate(self, screen, zone):
        for _ in range(2):
            a = random.uniform(0, math.tau)
            inner = pygame.Vector2(zone.center) + pygame.Vector2(math.cos(a), math.sin(a)) * random.uniform(
                0, zone.radius * 0.6
            )
            outer = pygame.Vector2(zone.center) + pygame.Vector2(math.cos(a), math.sin(a)) * zone.radius
            draw_lightning(screen, inner, outer, RAIJU_CYAN, segments=3, jitter=6)

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_spark_burst(self.battle.fx, pos, RAIJU_CYAN, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos and battle.ability.name == "Chain Bolt"):
            return False
        draw_lightning(screen, battle.attacker_start, battle.projectile_pos, RAIJU_CYAN, segments=5, jitter=8)
        pygame.draw.circle(screen, WHITE, (int(battle.projectile_pos.x), int(battle.projectile_pos.y)), 4)
        return True

    def draw_fx(self, screen, shake_x):
        """Fang Flicker/Blink Strike land as a teleport vanish-reappear-slash
        (see is_flicker_hidden in render.py for the vanish/reappear puff
        drawn on the fighter itself), and Thunder God's Descent telegraphs
        with rising static before a single bolt splits the sky onto the
        target."""
        battle, r = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is r):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t

        if name in ("Fang Flicker", "Blink Strike"):
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            landing = pygame.Vector2(battle.strike_point) + pygame.Vector2(shake_x, 0)
            if phase == "vanish":
                draw_starburst(screen, origin, RAIJU_CYAN, size=26, fade=t)
            elif phase == "reappear":
                draw_starburst(screen, landing, RAIJU_CYAN, size=30, fade=1 - t)
            elif phase == "strike":
                center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
                draw_slash_arc(screen, center, battle.atk_dir, radius=42, spread_deg=100,
                                color=RAIJU_CYAN, width=7, fade=1 - t)
                draw_slash(screen, center, battle.atk_dir.rotate(-15), RAIJU_CYAN, length=46, width=6)
                draw_starburst(screen, center, WHITE, size=30, fade=1 - t)
                draw_expanding_ring(screen, center, 40 * t, RAIJU_CYAN, width=3)

        elif name == "Thunder God's Descent":
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            if phase == "channel":
                for _ in range(4):
                    top = origin + pygame.Vector2(random.uniform(-24, 24), -60 - random.uniform(0, 30) * t)
                    draw_lightning(screen, origin, top, RAIJU_CYAN, segments=4, jitter=10, branches=1)
                draw_starburst(screen, origin, RAIJU_CYAN, size=16 + 14 * t, fade=t)
            elif phase == "impact":
                target = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
                sky = pygame.Vector2(target.x, ARENA_RECT.top - 30)
                draw_lightning(screen, sky, target, RAIJU_CYAN, segments=10, jitter=24, branches=4)
                for frac in (-1.4, -0.7, 0.7, 1.4):
                    branch = target + pygame.Vector2(frac * 40, -70)
                    draw_lightning(screen, sky.lerp(target, 0.35), branch, RAIJU_CYAN,
                                    segments=4, jitter=12, branches=1)
                draw_expanding_ring(screen, target, 90 * t, RAIJU_CYAN, width=5)
                draw_expanding_ring(screen, target, 60 * t, WHITE, width=3)
                draw_starburst(screen, target, WHITE, size=46, fade=1 - t)
