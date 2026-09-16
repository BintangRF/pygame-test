"""Shared hit-feedback used by every ability resolution path in
combat_resolution.py: screen shake amount/duration, a brief hit-stop,
visual knockback, character-flavored impact particles (dispatched to the
attacker's own CharacterPlugin, see core/plugin.py), spawned afterimages,
and expanding shockwave rings for AoE casts — all keyed by attack tier
(basic < skill < heavy < ultimate) so ultimates read as visually heavier
without every attack looking busy. Pure presentation: none of it is read by
gameplay logic.
"""

import random

import pygame

from .constants import WHITE
from .particles import emit_debris, emit_dust, emit_hit_spark
from .status_library import BLOCKS_MOVE


class ImpactFXMixin:
    TIER_SHAKE = {"basic": (6, 0.14), "skill": (11, 0.21), "heavy": (18, 0.28), "ultimate": (30, 0.42)}
    TIER_HIT_STOP = {"basic": 0.025, "skill": 0.05, "heavy": 0.09, "ultimate": 0.15}
    TIER_KNOCKBACK = {"basic": 8, "skill": 13, "heavy": 20, "ultimate": 30}
    # Real (gameplay, not just cosmetic) launch speed a landed hit sets its
    # defender's own vel to, away from the attacker — see knock_back/
    # decay_launch_speed below. Every ability kind gets this (basic, skill,
    # and ultimate alike); only a fighter currently pinned in place
    # (BLOCKS_MOVE — stunned/frozen/rooted/asleep) is ever exempt, which is
    # what already keeps Legion Commander's Duel (mutual root at one exact
    # distance) safe regardless of tier.
    TIER_LAUNCH_SPEED = {"basic": 480, "skill": 620, "heavy": 760, "ultimate": 900}
    # Time constant the launch speed above eases back down to the target's
    # own resting Character.base_speed over — see decay_launch_speed.
    LAUNCH_DECAY_S = 0.3
    # knock_back rotates the dead-on-axis attacker->defender direction by a
    # random angle within +/- this many degrees each time, so a launch reads
    # as a real, varied bounce instead of the same fixed straight-back line
    # on every single hit.
    KNOCKBACK_SPREAD_DEG = 75
    # count scales with impact tier (basic < skill < heavy < ultimate) so
    # ultimates read as visually heavier without every attack looking busy
    TIER_PARTICLE_COUNT = {"basic": 14, "skill": 24, "heavy": 38, "ultimate": 60}
    TIER_RING = {"heavy": (60, 0.26), "ultimate": (110, 0.38)}
    TIER_FLASH = {"basic": 0.09, "skill": 0.13, "heavy": 0.2, "ultimate": 0.28}
    TIER_SQUASH = {"basic": (1.08, 0.92), "skill": (1.12, 0.88), "heavy": (1.2, 0.8), "ultimate": (1.3, 0.7)}
    TIER_ZOOM = {"heavy": 1.06, "ultimate": 1.18}
    ULTIMATE_TIME_SCALE = 0.3
    TIME_SCALE_RECOVER_S = 0.55
    MAX_RINGS = 20
    # A brace flinch (start_brace) reads as a much lighter beat than a
    # landed hit's own apply_impact squash/recoil — just enough to tell
    # "holding ground" apart from "stopped working".
    BRACE_SQUASH = (0.96, 1.04)
    BRACE_RECOIL = 4

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
            self.knock_back(defender, direction, self.TIER_LAUNCH_SPEED[tier])
            if tier in self.TIER_ZOOM:
                self.zoom = max(self.zoom, self.TIER_ZOOM[tier])
            self.spawn_impact_particles(self.attacker, defender.pos, tier)
            if tier in self.TIER_RING:
                radius, duration = self.TIER_RING[tier]
                color = self.attacker.color if self.attacker else WHITE
                self.add_ring(defender.pos, radius, duration, color, width=5 if tier == "ultimate" else 3)
            if tier == "ultimate":
                self.flash_timer = max(self.flash_timer, 0.26)
                self.time_scale = min(self.time_scale, self.ULTIMATE_TIME_SCALE)

    def knock_back(self, defender, direction, launch_speed):
        """Any landed hit — basic, skill, or ultimate alike — sets the
        target's own real vel (not just the cosmetic visual_recoil above)
        to point away from the attacker — real gameplay velocity, moved
        through the ordinary
        bounce_move position update every other frame of roam already uses
        (see roam_step in battle_loop.py), so it glides away exactly as
        smoothly as a wall bounce instead of snapping to a new spot. The
        dead-on-axis attacker->defender direction is rotated by a random
        angle (KNOCKBACK_SPREAD_DEG) first, so repeated hits don't all send
        the target flying dead straight back along the same line —
        decay_launch_speed eases the elevated speed back down to the
        target's own normal cruising speed every frame afterward (see
        Character.base_speed), so the hit reads as being thrown — a fast
        launch that settles back into its own regular pace — rather than an
        instant teleport. Without any of this, both fighters' own
        independent try_start_attack() (battle_loop.py) lets one side's
        basic attack chain straight into the next the instant its cooldown
        clears, since nothing else ever moves them apart. Skipped for
        anyone currently pinned in place (BLOCKS_MOVE — stunned/frozen/
        rooted/asleep), the same exemption resolve_character_collision
        (entities.py) already gives a pinned fighter, so Legion Commander's
        Duel (mutual root, both fighters held at one exact distance for its
        whole window) is never shoved out of it by its own rapid-trade
        basic attacks."""
        if direction.length_squared() == 0 or defender.statuses.keys() & BLOCKS_MOVE:
            return
        angle = random.uniform(-self.KNOCKBACK_SPREAD_DEG, self.KNOCKBACK_SPREAD_DEG)
        defender.vel = direction.normalize().rotate(angle) * launch_speed

    def decay_launch_speed(self, f, dt):
        """Eases f.vel's own magnitude back down toward its resting
        Character.base_speed every frame, direction untouched — normal wall
        bounces (entities.bounce_move) already flip vel component-wise
        without ever changing its magnitude, so this is a no-op the rest of
        the time and only actually does anything for the brief window right
        after knock_back sets vel to something faster. Called once per
        fighter per frame from battle_loop.py's update(), alongside every
        other per-frame decay (shake, visual_recoil, hit_flash, ...)."""
        if f.base_speed <= 0:
            return
        speed = f.vel.length()
        if speed <= f.base_speed:
            return
        new_speed = f.base_speed + (speed - f.base_speed) * (1 - min(1.0, dt / self.LAUNCH_DECAY_S))
        if new_speed - f.base_speed < 0.5:
            new_speed = f.base_speed
        f.vel.scale_to_length(new_speed)

    def start_brace(self, defender, defending):
        """Fired once, the instant update_roam() (battle_loop.py) freezes
        `defender` in place for an opponent's still-unresolved non-dodgeable
        strike — a quick squash-toward-the-attacker plus a small recoil away
        from them, so the freeze itself reads as the target bracing for a
        hit that hasn't landed yet instead of its movement just cutting out
        with zero warning. Both ease straight back via the same scale_x/
        scale_y/visual_recoil decay every other impact beat already uses
        (see update() in battle_loop.py) — no extra timer to manage."""
        defender.scale_x, defender.scale_y = self.BRACE_SQUASH
        away = pygame.Vector2(defending.atk_dir)
        if away.length_squared() > 0:
            defender.visual_recoil += away.normalize() * self.BRACE_RECOIL

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

    def add_screen_shake(self, amount, duration=0.15):
        self.camera_shake.add(amount, duration)

    def add_hit_stop(self, duration):
        self.hit_stop_timer = max(self.hit_stop_timer, duration)

    def spawn_afterimage(self, f):
        img = f.image.copy()
        img.set_alpha(140)
        self.afterimages.append({"image": img, "pos": pygame.Vector2(f.pos), "alpha": 170.0})
        if len(self.afterimages) > 14:
            self.afterimages.pop(0)

    def add_ring(self, pos, max_radius, duration, color, start_radius=8, width=3):
        """An expanding shockwave ring — used for AoE casts and ultimate
        impacts. Pure decoration: owns no gameplay state, just fades out."""
        self.rings.append({
            "pos": pygame.Vector2(pos), "start_radius": start_radius, "max_radius": max_radius,
            "duration": duration, "elapsed": 0, "color": color, "width": width,
        })
        if len(self.rings) > self.MAX_RINGS:
            self.rings.pop(0)
