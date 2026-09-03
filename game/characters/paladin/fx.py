"""Paladin-specific weapon animation: the idle/Lunge-Strike sword (the same
prop that rests against the shield, not a second sword), and the per-skill
weapon swap for Judgment Mark (spear), Divine Shield (shield), Sacred
Ground (warhammer), and Heaven's Verdict (the oversized sword)."""

import math

import pygame

from ...core.constants import ARENA_RECT, AVATAR_R, GOLD, SHIELD_COLOR, WHITE
from ...core.effects import draw_expanding_ring, draw_lightning, draw_rotated, draw_starburst, weapon_angle
from ...core.motions import ease_back, ease_in, ease_out

# which weapon prop each Paladin ability draws, by ability name
# (Lunge Strike is handled separately by draw_paladin_sword — it swings the
# same sword prop that rests on the shield when idle, not a second sword)
WEAPON_BY_ABILITY = {
    "Judgment Mark": "spear",
    "Divine Shield": "shield",
    "Sacred Ground": "warhammer",
    "Heaven's Verdict": "sword_big",
}

PALADIN_SWORD_IDLE_ANGLE = 320  # resting angle against the shield (140 + 180)
PALADIN_SWORD_IDLE_OFFSET = pygame.Vector2(-15, 20)


class PaladinFXMixin:
    def draw_paladin_sword(self, screen, shake_x):
        """The Paladin's sword: rests against the shield when idle, and is
        the very same prop that swings for Lunge Strike — not a second sword."""
        if self.paladin is None or not self.paladin.is_alive():
            return
        img = self.weapons["sword"]  # already loaded big (see load_paladin_weapons)
        p = self.paladin.pos + pygame.Vector2(shake_x, 0)

        active_ability = (
            self.ability.name if (self.mode == "attack" and self.attacker is self.paladin) else None
        )
        is_lunge = active_ability == "Lunge Strike"

        if not is_lunge:
            self.weapon_trail.clear()
            if active_ability == "Heaven's Verdict":
                return  # the big sword prop (drawn elsewhere) already covers this
            pos = p + PALADIN_SWORD_IDLE_OFFSET
            draw_rotated(screen, img, pos, PALADIN_SWORD_IDLE_ANGLE)
            return

        phase, t = self.current_phase, self.phase_t
        if phase == "strike":
            reach = 10 + (AVATAR_R + 30 - 10) * ease_back(t)  # slight overshoot before settling
        else:
            reach = {"windup": 10, "impact": AVATAR_R + 30, "return": 12}.get(phase, 12)
        if phase == "windup":
            extra = -30 * ease_out(t)
        elif phase == "strike":
            extra = -30 + 35 * ease_in(t)
        elif phase == "impact":
            extra = 5 + 6 * math.sin(t * math.pi)
            draw_starburst(screen, p + self.atk_dir * reach, WHITE, size=30, fade=1 - t)
            draw_expanding_ring(screen, p + self.atk_dir * reach, 45 * t, GOLD, width=3)
        else:  # return
            extra = 5 - 25 * ease_out(t)
        angle = weapon_angle(self.atk_dir, extra + 180)
        pos = p + self.atk_dir * reach

        if phase in ("strike", "impact"):
            self.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(self.weapon_trail) > 7:
                self.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(self.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(self.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            self.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

    def draw_paladin_weapon(self, screen, shake_x):
        if not (self.mode == "attack" and self.attacker is self.paladin):
            return
        weapon_key = WEAPON_BY_ABILITY.get(self.ability.name)
        if weapon_key is None:
            return

        img = self.weapons[weapon_key]
        phase, t = self.current_phase, self.phase_t
        p = self.paladin.pos + pygame.Vector2(shake_x, 0)
        pos = pygame.Vector2(p)
        angle = 0.0
        scale = 1.0
        trail_ok = False

        if weapon_key == "sword_big":
            # overhead diagonal chop: tilts back, sweeps through in an arc,
            # snaps on impact, then retracts — not a plain vertical bob
            height = 70
            if phase == "windup":
                pos = p + pygame.Vector2(0, -55)
                angle = -35
            elif phase == "arc":
                pos = p + pygame.Vector2(0, -55 * (1 - t) - height * 0.15 * math.sin(math.pi * t))
                angle = -35 + 60 * ease_in(t)
            elif phase == "impact":
                pos = p + pygame.Vector2(0, -4)
                angle = 25 + 8 * math.sin(t * math.pi)
                scale = 1.0 + 0.15 * (1 - t)
                draw_starburst(screen, pos, GOLD, size=42, fade=1 - t)
                draw_expanding_ring(screen, pos, 70 * t, GOLD, width=4)
            else:  # return
                pos = p + pygame.Vector2(0, -55 * t)
                angle = 25 - 60 * ease_out(t)
            if phase == "impact":
                draw_lightning(screen, pygame.Vector2(pos.x, ARENA_RECT.top - 10),
                                pygame.Vector2(pos.x, pos.y - 10), GOLD, segments=9, jitter=20, branches=3)
                for side in (-1, 1):
                    draw_lightning(screen, pygame.Vector2(pos.x + side * 26, ARENA_RECT.top - 10),
                                    pygame.Vector2(pos.x + side * 10, pos.y - 6), GOLD,
                                    segments=6, jitter=14, branches=1)
            trail_ok = phase in ("arc", "impact")

        elif weapon_key == "spear":
            # cocked back over the shoulder during windup, then a clean
            # forward release instead of holding steady the whole time
            if self.projectile_pos is not None:
                pos = self.projectile_pos + pygame.Vector2(shake_x, 0)
                angle = weapon_angle(self.atk_dir, 0)
                trail_ok = True
            else:
                cock = -110 * ease_out(t) if phase == "windup" else 0
                pos = p - self.atk_dir * 8 + pygame.Vector2(0, -6)
                angle = weapon_angle(self.atk_dir, cock)

        elif weapon_key == "shield":
            # rises into a guard position with a swing, then flashes a
            # ward ring outward once the barrier locks in
            if phase == "windup":
                rise = 30 * (1 - ease_out(t))
                pos = p + self.atk_dir * 20 + pygame.Vector2(0, rise)
                angle = weapon_angle(self.atk_dir, -20 * (1 - ease_out(t)))
            else:
                pulse = 1.0 + 0.08 * math.sin(pygame.time.get_ticks() * 0.01)
                scale = pulse
                pos = p + self.atk_dir * 20
                angle = weapon_angle(self.atk_dir, 0)
                if phase == "release" and t < 0.4:
                    draw_expanding_ring(screen, pos, 20 + 60 * (t / 0.4), SHIELD_COLOR, width=4)
                    draw_starburst(screen, pos, SHIELD_COLOR, size=24, fade=1 - t / 0.4)

        elif weapon_key == "warhammer":
            # raised with a backward tilt, then a real diagonal smash down
            # with a dust ring on landing, instead of a pure vertical drop
            if phase in ("windup", "channel"):
                lift = -40 if phase == "windup" else -48
                angle = -20
            else:  # release
                lift = -48 + 48 * ease_in(t)
                angle = -20 + 35 * ease_in(t)
                if t > 0.7:
                    draw_expanding_ring(screen, p + pygame.Vector2(0, -6),
                                         65 * ((t - 0.7) / 0.3), GOLD, width=4)
                    draw_starburst(screen, p + pygame.Vector2(0, -6), WHITE, size=26, fade=(t - 0.7) / 0.3)
            pos = p + pygame.Vector2(0, lift - 10)
            trail_ok = phase == "release"

        scaled_img = img
        if scale != 1.0:
            w, h = img.get_size()
            scaled_img = pygame.transform.smoothscale(img, (max(1, int(w * scale)), max(1, int(h * scale))))

        if trail_ok:
            self.weapon_trail.append((scaled_img, pygame.Vector2(pos), angle))
            if len(self.weapon_trail) > 7:
                self.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(self.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(self.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            self.weapon_trail.clear()

        draw_rotated(screen, scaled_img, pos, angle)
