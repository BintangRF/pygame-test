"""Shared hit-feedback used by every ability resolution path in
combat_resolution.py: screen shake amount/duration, a brief hit-stop,
visual knockback, character-flavored impact particles (dispatched to the
attacker's own CharacterPlugin, see core/plugin.py), spawned afterimages,
and expanding shockwave rings for AoE casts — all keyed by attack tier
(basic < skill < heavy < ultimate) so ultimates read as visually heavier
without every attack looking busy. Pure presentation: none of it is read by
gameplay logic.
"""

import pygame

from .constants import WHITE
from .particles import emit_debris, emit_dust, emit_hit_spark


class ImpactFXMixin:
    TIER_SHAKE = {"basic": (6, 140), "skill": (11, 210), "heavy": (18, 280), "ultimate": (30, 420)}
    TIER_HIT_STOP = {"basic": 25, "skill": 50, "heavy": 90, "ultimate": 150}
    TIER_KNOCKBACK = {"basic": 8, "skill": 13, "heavy": 20, "ultimate": 30}
    # count scales with impact tier (basic < skill < heavy < ultimate) so
    # ultimates read as visually heavier without every attack looking busy
    TIER_PARTICLE_COUNT = {"basic": 14, "skill": 24, "heavy": 38, "ultimate": 60}
    TIER_RING = {"heavy": (60, 260), "ultimate": (110, 380)}
    TIER_FLASH = {"basic": 90, "skill": 130, "heavy": 200, "ultimate": 280}
    TIER_SQUASH = {"basic": (1.08, 0.92), "skill": (1.12, 0.88), "heavy": (1.2, 0.8), "ultimate": (1.3, 0.7)}
    TIER_ZOOM = {"heavy": 1.06, "ultimate": 1.18}
    ULTIMATE_TIME_SCALE = 0.3
    TIME_SCALE_RECOVER_MS = 550
    MAX_RINGS = 20

    def impact_tier(self, ability):
        if ability.kind == "ultimate":
            return "ultimate"
        if self.motion == "melee_slam":
            return "heavy"
        if ability.kind == "skill":
            return "skill"
        return "basic"

    def apply_impact(self, defender, ability, knock_dir=None):
        """Shared impact feedback for a landed hit: screen shake, a brief
        hit-stop, a visual (non-gameplay) knockback nudge on the defender,
        and a character-flavored particle burst at the contact point."""
        tier = self.impact_tier(ability)
        shake_amount, shake_duration = self.TIER_SHAKE[tier]
        self.add_screen_shake(shake_amount, shake_duration)
        self.add_hit_stop(self.TIER_HIT_STOP[tier])
        if defender is not None:
            direction = knock_dir if knock_dir and knock_dir.length_squared() else self.atk_dir
            defender.visual_recoil += direction * self.TIER_KNOCKBACK[tier]
            defender.hit_flash = defender.hit_flash_max = self.TIER_FLASH[tier]
            defender.hit_flash_heavy = tier in ("heavy", "ultimate")
            defender.scale_x, defender.scale_y = self.TIER_SQUASH[tier]
            if tier in self.TIER_ZOOM:
                self.zoom = max(self.zoom, self.TIER_ZOOM[tier])
            self.spawn_impact_particles(self.attacker, defender.pos, tier)
            if tier in self.TIER_RING:
                radius, duration = self.TIER_RING[tier]
                color = self.attacker.color if self.attacker else WHITE
                self.add_ring(defender.pos, radius, duration, color, width=5 if tier == "ultimate" else 3)
            if tier == "ultimate":
                self.flash_timer = max(self.flash_timer, 260)
                self.time_scale = min(self.time_scale, self.ULTIMATE_TIME_SCALE)

    def spawn_impact_particles(self, attacker, pos, tier):
        """Character-flavored hit particles, dispatched to the attacker's
        own CharacterPlugin.impact_particles — falls back to a generic
        color spark for a fighter whose plugin doesn't override it."""
        count = self.TIER_PARTICLE_COUNT[tier]
        plugin = self.plugin_for(attacker)
        handled = plugin.impact_particles(pos, count) if plugin is not None else False
        if not handled:
            emit_hit_spark(self.fx, pos, attacker.color if attacker else WHITE, count=count)
        if tier in ("heavy", "ultimate"):
            emit_dust(self.fx, pos, count=count // 2)
            emit_hit_spark(self.fx, pos, WHITE, count=count // 2)
        if tier == "ultimate":
            emit_debris(self.fx, pos, count=count // 3)

    def add_screen_shake(self, amount, duration_ms=150):
        self.camera_shake.add(amount, duration_ms)

    def add_hit_stop(self, duration_ms):
        self.hit_stop_timer = max(self.hit_stop_timer, duration_ms)

    def spawn_afterimage(self, f):
        img = f.image.copy()
        img.set_alpha(140)
        self.afterimages.append({"image": img, "pos": pygame.Vector2(f.pos), "alpha": 170.0})
        if len(self.afterimages) > 14:
            self.afterimages.pop(0)

    def add_ring(self, pos, max_radius, duration_ms, color, start_radius=8, width=3):
        """An expanding shockwave ring — used for AoE casts and ultimate
        impacts. Pure decoration: owns no gameplay state, just fades out."""
        self.rings.append({
            "pos": pygame.Vector2(pos), "start_radius": start_radius, "max_radius": max_radius,
            "duration": duration_ms, "elapsed": 0, "color": color, "width": width,
        })
        if len(self.rings) > self.MAX_RINGS:
            self.rings.pop(0)
