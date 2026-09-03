"""Berserker-specific weapon animation: the axe's crossing claw-rake basic
attack, the Axe Throw fan/cone AoE (a scatter of spinning axes inside a
widening wedge, not a single bolt), and the axe raised overhead during the
Berserker Rage roar."""

import math

import pygame

from ...core.constants import AVATAR_R, ORANGE, WHITE
from ...core.effects import draw_expanding_ring, draw_fan, draw_rotated, draw_starburst, weapon_angle
from ...core.motions import ease_in, ease_out


class BerserkerFXMixin:
    def draw_berserker_axe(self, screen, shake_x):
        """The Berserker's axe: swung for Reckless Cleave, thrown as the
        Axe Throw projectile (see draw_axe_fan), and raised overhead
        during the Berserker Rage roar."""
        b = self.berserker
        if b is None or not b.is_alive():
            return
        if not (self.mode == "attack" and self.attacker is b):
            return
        name = self.ability.name
        if name not in ("Reckless Cleave", "Berserker Rage"):
            return

        img = self.weapons["axe"]
        p = b.pos + pygame.Vector2(shake_x, 0)
        phase, t = self.current_phase, self.phase_t

        if name == "Berserker Rage":
            lift = 40 + 8 * math.sin(pygame.time.get_ticks() * 0.02)
            pos = p + pygame.Vector2(0, -lift)
            if phase == "channel":
                draw_expanding_ring(screen, p, 20 + 80 * t, ORANGE, width=5)
                draw_starburst(screen, p, ORANGE, size=20 + 20 * t, fade=t)
            draw_rotated(screen, img, pos, 0)
            return

        # Two crossing rakes (like a claw swipe), not a dash-in strike: the
        # axe sweeps one diagonal on slash1, the opposite diagonal on
        # slash2, while the body barely moves (see apply_motion_frame).
        if phase == "windup":
            reach, extra = 10, -60 * ease_out(t)
        elif phase == "slash1":
            reach = AVATAR_R + 14
            extra = -60 + 120 * ease_in(t)
            if t > 0.55:
                draw_starburst(screen, p + self.atk_dir * reach, WHITE, size=26, fade=(1 - t) / 0.45)
        elif phase == "slash2":
            reach = AVATAR_R + 14
            extra = 60 - 120 * ease_in(t)
            if t > 0.55:
                draw_starburst(screen, p + self.atk_dir * reach, WHITE, size=30, fade=(1 - t) / 0.45)
        else:  # return
            reach = AVATAR_R + 14 - (AVATAR_R + 4) * ease_out(t)
            extra = -60 + 60 * ease_out(t)
        angle = weapon_angle(self.atk_dir, extra + 180)
        pos = p + self.atk_dir * reach

        if phase in ("slash1", "slash2"):
            self.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(self.weapon_trail) > 7:
                self.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(self.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(self.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            self.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

    def draw_axe_fan(self, screen):
        """Axe Throw hits as a widening fan/cone swept out from the
        Berserker, with a scatter of spinning axes inside it, rather than a
        single bolt travelling in a straight line."""
        phase, t = self.current_phase, self.phase_t
        color = self.attacker.color
        base_angle = math.atan2(self.atk_dir.y, self.atk_dir.x)
        full_reach = (self.defender_start - self.attacker_start).length()

        if phase == "fire":
            reach = full_reach * ease_out(t)
            spread = math.radians(20 + 34 * t)
            draw_fan(screen, self.attacker_start, base_angle, spread, reach, color, fill_alpha=130)
            for frac in (-0.9, -0.45, 0.0, 0.45, 0.9):
                a = base_angle + spread / 2 * frac
                pos = self.attacker_start + pygame.Vector2(math.cos(a), math.sin(a)) * reach
                angle_deg = (pygame.time.get_ticks() * 0.9 + frac * 140) % 360
                draw_rotated(screen, self.weapons["axe"], pos, angle_deg)
        elif phase == "impact":
            spread = math.radians(64)
            draw_fan(screen, self.attacker_start, base_angle, spread, full_reach, color,
                      fill_alpha=int(120 * (1 - t)))
            draw_starburst(screen, self.defender_start, WHITE, size=38, fade=1 - t)
            draw_expanding_ring(screen, self.defender_start, 60 * t, color, width=4)
