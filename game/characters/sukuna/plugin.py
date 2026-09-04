"""Sukuna plugin: Hachi's bleed application, Kai's multi-hit flurry resolve
(it doesn't deal its own damage — it procs Hachi's basic-attack formula 3-5
times at once), Kamino's cursed detonation, and the bare-handed curse-slash
animation for all three techniques."""

import math
import random

import pygame

from ...core.constants import RED, SUKUNA_PINK, WHITE
from ...core.effects import draw_expanding_ring, draw_fire_arrow, draw_slash, draw_slash_arc, draw_starburst
from ...core.entities import set_status
from ...core.particles import emit_dark, emit_explosion
from ...core.plugin import CharacterPlugin
from ...core.status_library import apply_anti_heal

# Kai: guaranteed 3 procs of the basic attack, then each hit past that
# (up to 5 total) independently rolls to proc as well.
KAI_BASE_HITS = 3
KAI_MAX_HITS = 5
KAI_EXTRA_HIT_CHANCE = 0.5


class SukunaPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.kai_hits = KAI_BASE_HITS  # updated each time Kai resolves; read by draw_fx

    def resolve_special(self):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "kai_flurry"):
            return False
        attacker, defender, ability = battle.attacker, battle.defender, battle.ability
        hits = KAI_BASE_HITS
        while hits < KAI_MAX_HITS and random.random() < KAI_EXTRA_HIT_CHANCE:
            hits += 1
        self.kai_hits = hits

        total = 0
        for _ in range(hits):
            dmg = round(attacker.atk * ability.dmg_mult)
            total += battle.deal_damage(attacker, defender, dmg)
        battle.damage_applied = True

        set_status(defender, "bleed", 3500, dps=max(1, round(total * 0.08)))
        apply_anti_heal(defender, 3000, pct=0.5)
        defender.shake = 20
        battle.apply_impact(defender, ability)
        battle.floaters.append(
            [defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{total} x{hits}", SUKUNA_PINK]
        )
        battle.log = f"{attacker.name}'s Kai lands {hits} simultaneous cuts on {defender.name} for {total}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "dismantle":
            set_status(defender, "bleed", 3000, dps=round(attacker.atk * 0.12))
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Sliced!", RED])
            battle.log = f"{attacker.name}'s Hachi leaves deep gashes on {defender.name}!"
        elif tag == "kamino":
            set_status(defender, "bleed", 6000, dps=round(attacker.atk * 0.3))
            apply_anti_heal(defender, 6000, pct=0.7)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "KAMINO!", SUKUNA_PINK])
            battle.log = f"{attacker.name} unleashes the cursed technique Kamino on {defender.name}!"
            battle.flash_timer = max(battle.flash_timer, 500)
            battle.add_screen_shake(24, 320)
            battle.add_ring(defender.pos, 190, 600, (255, 150, 40), width=7)
            battle.add_ring(defender.pos, 170, 750, SUKUNA_PINK, width=5)
            emit_explosion(battle.fx, defender.pos, (255, 140, 40), count=46)
            emit_dark(battle.fx, defender.pos, count=34, radius=70)

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_dark(self.battle.fx, pos, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos and battle.ability.name == "Kamino"):
            return False
        draw_fire_arrow(screen, battle.projectile_pos, battle.atk_dir, size=1.5)
        return True

    def draw_fx(self, screen, shake_x):
        """Hachi and Kai land as bare-handed curse-slashes with no travel
        time (a single cut for Hachi, a fanned-out flurry of 3-5 for Kai),
        while Kamino is the exception — a fireball gathers in Sukuna's palm
        (windup), a blazing arrow flies across the arena (draw_projectile
        above), then it explodes into a burst of curse-slashes on impact."""
        battle, s = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is s):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t

        if name == "Hachi" and phase == "impact":
            # no dash — the single cut appears directly on the target, same
            # as Kai below, just one slash instead of a fanned-out flurry
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            draw_slash_arc(screen, center, battle.atk_dir, radius=46, spread_deg=100,
                            color=SUKUNA_PINK, width=7, fade=1 - t)
            draw_slash(screen, center, battle.atk_dir.rotate(20), SUKUNA_PINK, length=48, width=6)
            draw_starburst(screen, center, WHITE, size=28, fade=1 - t)

        elif name == "Kai" and phase == "impact":
            # no travel, no projectile — `hits` cuts appear on the target
            # all at once, fanned out around the attack direction
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            hits = self.kai_hits
            spread_deg = 26
            draw_slash_arc(screen, center, battle.atk_dir, radius=54, spread_deg=160,
                            color=SUKUNA_PINK, width=8, fade=1 - t)
            for i in range(hits):
                ang_deg = (i - (hits - 1) / 2) * spread_deg + random.uniform(-6, 6)
                d = battle.atk_dir.rotate(ang_deg)
                draw_slash(screen, center, d, SUKUNA_PINK, length=50, width=6)
            draw_starburst(screen, center, WHITE, size=36, fade=1 - t)
            draw_expanding_ring(screen, center, 55 * t, SUKUNA_PINK, width=4)

        elif name == "Kamino" and phase == "windup":
            # a fireball gathers in Sukuna's palm before the arrow is loosed
            # — clear windup so the shot reads as fire from the first frame
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            for _ in range(6):
                jitter = pygame.Vector2(random.uniform(-11, 11), random.uniform(-11, 11)) * t
                pygame.draw.circle(
                    screen, (255, 150, 40),
                    (int((origin + jitter).x), int((origin + jitter).y)), int(6 + 12 * t),
                )
            pygame.draw.circle(screen, (255, 230, 140), (int(origin.x), int(origin.y)), max(2, int(5 + 8 * t)))
            draw_starburst(screen, origin, (255, 200, 90), size=18 + 26 * t, fade=t)

        elif name == "Kamino" and phase == "impact":
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, center, 95 * t, (255, 150, 40), width=7)
            draw_expanding_ring(screen, center, 65 * t, (255, 210, 110), width=4)
            draw_starburst(screen, center, (255, 210, 110), size=50, fade=1 - t)
            for i in range(6):
                ang = i * (math.pi / 3) + t * 2
                d = pygame.Vector2(math.cos(ang), math.sin(ang))
                draw_slash(screen, center, d, SUKUNA_PINK, length=56, width=7)
                draw_slash_arc(screen, center, d, radius=40, spread_deg=80,
                                color=SUKUNA_PINK, width=5, fade=1 - t * 0.6)
            draw_expanding_ring(screen, center, 70 * t, SUKUNA_PINK, width=4)
