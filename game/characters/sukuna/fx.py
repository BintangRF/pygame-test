"""Sukuna-specific technique animation: Hachi and Kai land as bare-handed
curse-slashes with no travel time (a single cut for Hachi, a fanned-out
flurry of 3-5 for Kai), while Kamino is the exception — a fireball gathers
in Sukuna's palm (windup), a blazing arrow flies across the arena (see
draw_fire_arrow / draw_projectile in render.py), then it explodes into a
burst of curse-slashes on impact."""

import math
import random

import pygame

from ...core.constants import SUKUNA_PINK, WHITE
from ...core.effects import draw_expanding_ring, draw_slash, draw_slash_arc, draw_starburst


class SukunaFXMixin:
    def draw_sukuna_effects(self, screen, shake_x):
        s = self.sukuna
        if s is None or not (self.mode == "attack" and self.attacker is s):
            return
        name = self.ability.name
        phase, t = self.current_phase, self.phase_t

        if name == "Hachi" and phase == "impact":
            # no dash — the single cut appears directly on the target, same
            # as Kai below, just one slash instead of a fanned-out flurry
            center = pygame.Vector2(self.defender_start) + pygame.Vector2(shake_x, 0)
            draw_slash_arc(screen, center, self.atk_dir, radius=46, spread_deg=100,
                            color=SUKUNA_PINK, width=7, fade=1 - t)
            draw_slash(screen, center, self.atk_dir.rotate(20), SUKUNA_PINK, length=48, width=6)
            draw_starburst(screen, center, WHITE, size=28, fade=1 - t)

        elif name == "Kai" and phase == "impact":
            # no travel, no projectile — `hits` cuts appear on the target
            # all at once, fanned out around the attack direction
            center = pygame.Vector2(self.defender_start) + pygame.Vector2(shake_x, 0)
            hits = self._kai_hits
            spread_deg = 26
            draw_slash_arc(screen, center, self.atk_dir, radius=54, spread_deg=160,
                            color=SUKUNA_PINK, width=8, fade=1 - t)
            for i in range(hits):
                ang_deg = (i - (hits - 1) / 2) * spread_deg + random.uniform(-6, 6)
                d = self.atk_dir.rotate(ang_deg)
                draw_slash(screen, center, d, SUKUNA_PINK, length=50, width=6)
            draw_starburst(screen, center, WHITE, size=36, fade=1 - t)
            draw_expanding_ring(screen, center, 55 * t, SUKUNA_PINK, width=4)

        elif name == "Kamino" and phase == "windup":
            # a fireball gathers in Sukuna's palm before the arrow is loosed
            # — clear windup so the shot reads as fire from the first frame
            origin = pygame.Vector2(self.attacker_start) + pygame.Vector2(shake_x, 0)
            for _ in range(6):
                jitter = pygame.Vector2(random.uniform(-11, 11), random.uniform(-11, 11)) * t
                pygame.draw.circle(
                    screen, (255, 150, 40),
                    (int((origin + jitter).x), int((origin + jitter).y)), int(6 + 12 * t),
                )
            pygame.draw.circle(screen, (255, 230, 140), (int(origin.x), int(origin.y)), max(2, int(5 + 8 * t)))
            draw_starburst(screen, origin, (255, 200, 90), size=18 + 26 * t, fade=t)

        elif name == "Kamino" and phase == "impact":
            center = pygame.Vector2(self.defender_start) + pygame.Vector2(shake_x, 0)
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
