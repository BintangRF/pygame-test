"""Raiju-specific technique animation: Fang Flicker/Blink Strike land as a
teleport vanish-reappear-slash (see is_flicker_hidden in render.py for the
vanish/reappear puff drawn on the fighter itself), and Thunder God's
Descent telegraphs with rising static before a single bolt splits the sky
onto the target."""

import random

import pygame

from ...core.constants import ARENA_RECT, RAIJU_CYAN, WHITE
from ...core.effects import draw_expanding_ring, draw_lightning, draw_slash, draw_slash_arc, draw_starburst


class RaijuFXMixin:
    def draw_raiju_effects(self, screen, shake_x):
        r = self.raiju
        if r is None or not (self.mode == "attack" and self.attacker is r):
            return
        name = self.ability.name
        phase, t = self.current_phase, self.phase_t

        if name in ("Fang Flicker", "Blink Strike"):
            origin = pygame.Vector2(self.attacker_start) + pygame.Vector2(shake_x, 0)
            landing = pygame.Vector2(self.strike_point) + pygame.Vector2(shake_x, 0)
            if phase == "vanish":
                draw_starburst(screen, origin, RAIJU_CYAN, size=26, fade=t)
            elif phase == "reappear":
                draw_starburst(screen, landing, RAIJU_CYAN, size=30, fade=1 - t)
            elif phase == "strike":
                center = pygame.Vector2(self.defender_start) + pygame.Vector2(shake_x, 0)
                draw_slash_arc(screen, center, self.atk_dir, radius=42, spread_deg=100,
                                color=RAIJU_CYAN, width=7, fade=1 - t)
                draw_slash(screen, center, self.atk_dir.rotate(-15), RAIJU_CYAN, length=46, width=6)
                draw_starburst(screen, center, WHITE, size=30, fade=1 - t)
                draw_expanding_ring(screen, center, 40 * t, RAIJU_CYAN, width=3)

        elif name == "Thunder God's Descent":
            origin = pygame.Vector2(self.attacker_start) + pygame.Vector2(shake_x, 0)
            if phase == "channel":
                for _ in range(4):
                    top = origin + pygame.Vector2(random.uniform(-24, 24), -60 - random.uniform(0, 30) * t)
                    draw_lightning(screen, origin, top, RAIJU_CYAN, segments=4, jitter=10, branches=1)
                draw_starburst(screen, origin, RAIJU_CYAN, size=16 + 14 * t, fade=t)
            elif phase == "impact":
                target = pygame.Vector2(self.defender_start) + pygame.Vector2(shake_x, 0)
                sky = pygame.Vector2(target.x, ARENA_RECT.top - 30)
                draw_lightning(screen, sky, target, RAIJU_CYAN, segments=10, jitter=24, branches=4)
                for frac in (-1.4, -0.7, 0.7, 1.4):
                    branch = target + pygame.Vector2(frac * 40, -70)
                    draw_lightning(screen, sky.lerp(target, 0.35), branch, RAIJU_CYAN,
                                    segments=4, jitter=12, branches=1)
                draw_expanding_ring(screen, target, 90 * t, RAIJU_CYAN, width=5)
                draw_expanding_ring(screen, target, 60 * t, WHITE, width=3)
                draw_starburst(screen, target, WHITE, size=46, fade=1 - t)
