"""Johnny-specific technique animation: Tusk Act 4 telegraphs its pin with a
burst of nails radiating out from the impact point. Tusk Act 3's ricocheting
nail is drawn generically by draw_projectile (core/render.py) — a landed hit
gets its own screen-shake/ring/spark flourish from johnny_apply_tag_effects
(characters/johnny/ability.py), so it needs nothing bespoke here."""

import math

import pygame

from ...core.constants import NAIL_SILVER
from ...core.effects import draw_expanding_ring, draw_nail


class JohnnyFXMixin:
    def draw_johnny_effects(self, screen, shake_x):
        j = self.johnny
        if j is None or not (self.mode == "attack" and self.attacker is j):
            return
        name = self.ability.name
        phase, t = self.current_phase, self.phase_t

        if name == "Tusk Act 4" and phase == "impact":
            center = pygame.Vector2(self.defender_start) + pygame.Vector2(shake_x, 0)
            for i in range(8):
                ang = i * (math.pi / 4)
                nail_pos = center + pygame.Vector2(math.cos(ang), math.sin(ang)) * 30 * t
                draw_nail(screen, nail_pos, pygame.Vector2(math.cos(ang), math.sin(ang)), NAIL_SILVER, size=1.1)
            draw_expanding_ring(screen, center, 50 * t, NAIL_SILVER, width=4)
