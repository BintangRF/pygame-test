"""Shared hit-feedback used by every ability resolution path in
combat_resolution.py: screen shake amount/duration, visual knockback,
character-flavored impact particles (dispatched to the attacker's own
CharacterPlugin, see core/plugin.py), spawned afterimages, and expanding
shockwave rings for AoE casts — all keyed by attack tier (basic < skill <
heavy < ultimate) so ultimates read as visually heavier without every
attack looking busy. Pure presentation: none of it is read by gameplay
logic, and none of it ever pauses or slows the simulation itself — combat
keeps running at real speed through every hit.
"""

import random

import pygame

from .asset_loading import load_animation_frames
from .constants import WHITE
from .effects import rotate_to_dir
from .particles import emit_debris, emit_dust, emit_hit_spark
from .status_library import BLOCKS_MOVE

# Every projectile-flight motion (core/motions.py) — a landed hit from one of
# these gets the painted assets/animation/range/range-1.png flash stamped at
# the point of impact (see apply_impact), marking where the shot actually
# connected the way a melee swing's own cut mark already does. "sky_strike"
# (Raiju's Thunder God's Descent) is deliberately excluded — it already has
# its own elaborate lightning-from-the-sky flourish, a small flash stamp on
# top would just be lost in it.
RANGED_MOTIONS = {"bolt", "swarm", "homing_bolt", "ricochet", "instant_ricochet"}


class ImpactFXMixin:
    TIER_SHAKE = {
        "basic": (6, 0.14), "skill": (11, 0.21), "critical": (15, 0.24), "heavy": (18, 0.28), "ultimate": (30, 0.42),
    }
    TIER_KNOCKBACK = {"basic": 8, "skill": 13, "critical": 17, "heavy": 20, "ultimate": 30}
    # Real (gameplay, not just cosmetic) launch speed a landed hit sets its
    # defender's own vel to, away from the attacker — see knock_back/
    # decay_launch_speed below. Every ability kind gets this (basic, skill,
    # and ultimate alike); only a fighter currently pinned in place
    # (BLOCKS_MOVE — stunned/frozen/rooted/asleep) is ever exempt, which is
    # what already keeps Legion Commander's Duel (mutual root at one exact
    # distance) safe regardless of tier.
    TIER_LAUNCH_SPEED = {"basic": 480, "skill": 620, "critical": 700, "heavy": 760, "ultimate": 900}
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
    TIER_PARTICLE_COUNT = {"basic": 14, "skill": 24, "critical": 34, "heavy": 38, "ultimate": 60}
    TIER_RING = {"critical": (55, 0.24), "heavy": (60, 0.26), "ultimate": (110, 0.38)}
    TIER_FLASH = {"basic": 0.09, "skill": 0.13, "critical": 0.18, "heavy": 0.2, "ultimate": 0.28}
    TIER_ZOOM = {"critical": 1.05, "heavy": 1.06, "ultimate": 1.18}
    MAX_RINGS = 20

    def impact_tier(self, ability):
        if ability.kind == "ultimate":
            return "ultimate"
        # A critical hit (see combat_resolution._strike_defender's generic
        # crit roll, or a character's own bespoke crit passive flagging
        # self.crit itself) always reads as its own tier, even on top of a
        # melee_slam basic — the crit itself is the more specifically
        # "special" thing that just happened, not the motion carrying it.
        if self.crit:
            return "critical"
        if self.motion == "melee_slam":
            return "heavy"
        if ability.kind == "skill":
            return "skill"
        return "basic"

    def apply_impact(self, defender, ability, knock_dir=None):
        """Shared impact feedback for a landed hit: screen shake, a visual
        (non-gameplay) knockback nudge on the defender, and a
        character-flavored particle burst at the contact point."""
        tier = self.impact_tier(ability)
        shake_amount, shake_duration = self.TIER_SHAKE[tier]
        self.add_screen_shake(shake_amount, shake_duration)
        if defender is not None:
            direction = knock_dir if knock_dir and knock_dir.length_squared() else self.atk_dir
            defender.visual_recoil += direction * self.TIER_KNOCKBACK[tier]
            defender.hit_flash = defender.hit_flash_max = self.TIER_FLASH[tier]
            defender.hit_flash_heavy = tier in ("heavy", "ultimate")
            defender.hit_flash_crit = tier == "critical"
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
            if self.motion in RANGED_MOTIONS:
                self.add_impact_stamp(defender.pos, self.range_stamp_frames())
            if tier == "critical":
                self.add_impact_stamp(defender.pos, self.crit_stamp_frames())

    def range_stamp_frames(self):
        # A single-frame flipbook — see load_animation_frames, cached the
        # same way as any other painted flipbook (draw_slash_fx/draw_hold_fx
        # in effects.py) even though there's only one frame to cache.
        return load_animation_frames("animation/range", "range", 1, 46)

    def crit_stamp_frames(self):
        return load_animation_frames("animation/crit", "crit", 3, 60)

    def add_impact_stamp(self, pos, frames, duration=0.24):
        """Queue one play-through of a painted one-shot flourish (assets/
        animation/range/ or assets/animation/crit/, see range_stamp_frames/
        crit_stamp_frames) at `pos` — advanced by update_impact_stamps and
        drawn by draw_impact_stamps (render.py), independent of any specific
        attack's own phase state so it keeps playing/fading out even once
        the attack itself has moved on to its next phase."""
        self.impact_stamps.append({"pos": pygame.Vector2(pos), "frames": frames, "elapsed": 0.0, "duration": duration})
        if len(self.impact_stamps) > self.MAX_RINGS:
            self.impact_stamps.pop(0)

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

    # How much a spawned afterimage gets elongated along its own direction of
    # travel (and squashed across it) before being rotated to face that
    # heading — see spawn_afterimage — so a fast dash/sprint leaves a
    # directional motion-blur streak instead of a plain static copy of the
    # sprite repeated a few times.
    AFTERIMAGE_STRETCH = 1.4
    AFTERIMAGE_SQUASH = 0.82

    def spawn_afterimage(self, f):
        img = f.image.copy()
        img.set_alpha(140)
        # `direction` prefers the currently-bound attack's own atk_dir
        # (battle_loop.py's trailing_phase calls this while self._current is
        # bound, and a dashing attacker's own f.vel is stale there —
        # apply_motion_frame moves it by assigning f.pos directly, never
        # through vel) and otherwise falls back to the fighter's own live vel
        # (VampirePlugin's Eternal Night sprint calls this with no attack in
        # flight at all, but is genuinely moving through roam_step/
        # bounce_move, which does drive vel).
        direction = self.atk_dir if self._current is not None else None
        if direction is None or direction.length_squared() < 1e-6:
            direction = f.vel
        if direction is not None and direction.length_squared() > 1e-6:
            w, h = img.get_size()
            stretched = pygame.transform.smoothscale(
                img, (max(1, round(w * self.AFTERIMAGE_SQUASH)), max(1, round(h * self.AFTERIMAGE_STRETCH)))
            )
            img = rotate_to_dir(stretched, direction)
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
