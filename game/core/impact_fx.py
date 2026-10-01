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

import math
import random

import pygame

from .asset_loading import load_animation_frames
from .constants import WHITE
from .glow import lighten
from .anime_fx import build_scratch_decal, build_impact_burst_frames, build_smoke_ring_frames
from .effects import cleave_wave_blade, colorize_sprite, crescent_edge_point, rotate_to_dir, tinted_frames
from .particles import Particle, emit_debris, emit_hit_spark
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
    # Real seconds the whole match freezes on a landed hit of this tier
    # (see battle_loop.update) — the "weight" beat; basics stay snappy.
    TIER_HITSTOP = {"basic": 0.0, "skill": 0.035, "critical": 0.07, "heavy": 0.08, "ultimate": 0.12}
    # Anime hit-spark (anime_fx.build_impact_burst_frames) every landed hit
    # stamps on the defender: peak size in px and how long it plays.
    # Basics get none (their own character particles are enough), and a
    # plain ranged skill hit skips it too since it already gets the painted
    # range stamp; kept for the hits that should feel special.
    TIER_BURST = {"skill": (64, 0.22), "critical": (84, 0.26), "heavy": (90, 0.26), "ultimate": (116, 0.32)}
    # Elastic squash strength per tier (render.py's squash_sprite) — kept
    # subtle, since big sprites (the dummy) balloon badly on a strong wobble.
    TIER_SQUASH = {"basic": 0.05, "skill": 0.08, "critical": 0.1, "heavy": 0.12, "ultimate": 0.14}
    # Dust clouds kicked up in a ring around a heavy/ultimate impact.
    TIER_DUST_RING = {"heavy": 4, "ultimate": 6}
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
            fx = self.fx_color(self.attacker)
            # the sprite flashes a pale tint of the attacker's own color
            # rather than blank white (see RenderMixin.hit_flash_sprite)
            defender.hit_flash_color = lighten(fx, 0.35)
            defender.hit_flash_heavy = tier in ("heavy", "ultimate")
            defender.hit_flash_crit = tier == "critical"
            # Launch-on-hit disabled: the defender keeps its own roam vel.
            # self.knock_back(defender, direction, self.TIER_LAUNCH_SPEED[tier])
            if tier in self.TIER_ZOOM:
                self.zoom = max(self.zoom, self.TIER_ZOOM[tier])
            self.hitstop = max(self.hitstop, self.TIER_HITSTOP[tier])
            defender.squash_t = 0.0
            defender.squash_dir = pygame.Vector2(direction)
            defender.squash_amp = self.TIER_SQUASH[tier]
            if tier in self.TIER_BURST and not (tier == "skill" and self.motion in RANGED_MOTIONS):
                size, duration = self.TIER_BURST[tier]
                burst_color = fx
                burst_plugin = self.plugin_for(self.attacker) if self.attacker else None
                flare = burst_plugin.BURST_TEXTURE if burst_plugin is not None else None
                # Nudged toward the attacker so the spark sits on the struck
                # side of the body instead of dead center under the sprite.
                self.add_impact_stamp(
                    defender.pos - direction.normalize() * 10 if direction.length_squared() else defender.pos,
                    build_impact_burst_frames(burst_color, size, flare=flare), duration,
                )
            if tier in self.TIER_DUST_RING:
                self.add_dust_ring(defender.pos, self.TIER_DUST_RING[tier])
            self.spawn_impact_particles(self.attacker, defender.pos, tier)
            if tier in self.TIER_RING:
                radius, duration = self.TIER_RING[tier]
                self.add_ring(defender.pos, radius, duration, fx, width=5 if tier == "ultimate" else 3)
            if tier == "ultimate":
                self.flash_timer = max(self.flash_timer, 0.26)
            if self.motion in RANGED_MOTIONS:
                self.add_impact_stamp(defender.pos, self.range_stamp_frames(fx))
            if tier == "critical":
                self.add_impact_stamp(defender.pos, self.crit_stamp_frames(fx))

    def fx_color(self, fighter):
        """Signature color of `fighter`'s generic hit effects: its plugin's
        FX_COLOR if set, else the fighter's own color (WHITE for none)."""
        if fighter is None:
            return WHITE
        plugin = self.plugin_for(fighter)
        if plugin is not None and plugin.FX_COLOR is not None:
            return plugin.FX_COLOR
        return tuple(fighter.color[:3])

    def range_stamp_frames(self, color=None):
        # A single-frame flipbook — see load_animation_frames, cached the
        # same way as any other painted flipbook (draw_slash_fx/draw_hold_fx
        # in effects.py) even though there's only one frame to cache —
        # recolored to the shooter's own color.
        return tinted_frames(load_animation_frames("animation/range", "range", 1, 46), color)

    def crit_stamp_frames(self, color=None):
        return tinted_frames(load_animation_frames("animation/crit", "crit", 3, 60), color)

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

    MAX_DECALS = 6
    MAX_DUST_PUFFS = 40

    def add_dust_puff(self, pos, vel=(0, 0), size=30, duration=0.55):
        """One cartoon dust cloud (anime_fx.draw_dust_puff) drifting at
        `vel` px/s and slowing down, advanced by update_dust_puffs."""
        self.dust_puffs.append({
            "pos": pygame.Vector2(pos), "vel": pygame.Vector2(vel), "size": size, "elapsed": 0.0,
            "duration": duration, "variant": random.randrange(6),
        })
        if len(self.dust_puffs) > self.MAX_DUST_PUFFS:
            self.dust_puffs.pop(0)

    def add_smoke_ring(self, pos, size=170, duration=0.55):
        """A Kenney smoke ring blowing outward along the ground (the KO
        beat's shockwave), played through the impact-stamp queue."""
        self.add_impact_stamp(pos, build_smoke_ring_frames(size), duration)

    def add_dust_ring(self, pos, count):
        """A ring of dust clouds bursting outward from a heavy landing."""
        start = random.uniform(0, math.tau)
        for i in range(count):
            a = start + math.tau * i / count
            d = pygame.Vector2(math.cos(a), math.sin(a) * 0.7)
            self.add_dust_puff(pos + d * 18, d * random.uniform(110, 170), size=random.uniform(30, 42), duration=0.6)

    def update_dust_puffs(self, dt):
        for d in self.dust_puffs:
            d["elapsed"] += dt
            d["pos"] += d["vel"] * dt
            d["vel"] *= max(0.0, 1 - dt * 5)
        self.dust_puffs = [d for d in self.dust_puffs if d["elapsed"] < d["duration"]]

    def add_decal(self, pos, color, size, duration=4.0, angle=0.0):
        """Leave a scratch mark (anime_fx.build_scratch_decal) at `pos` for
        `duration` seconds, fading out
        over its last second — drawn under the fighters by draw_decals."""
        surf = build_scratch_decal(tuple(color[:3]), size, random.randrange(1 << 30), angle)
        self.decals.append({"pos": pygame.Vector2(pos), "surf": surf, "elapsed": 0.0, "duration": duration})
        if len(self.decals) > self.MAX_DECALS:
            self.decals.pop(0)

    def update_decals(self, dt):
        for d in self.decals:
            d["elapsed"] += dt
        self.decals = [d for d in self.decals if d["elapsed"] < d["duration"]]

    #: Embers shed per second along a travelling cleave wave's blade.
    CLEAVE_EMBER_RATE = 110

    def add_cleave_wave(self, origin, direction, color, size, travel, duration=0.5):
        """Launch a crescent cleave shockwave (effects.draw_cleave_wave)
        from `origin` along `direction`, `size` px tip to tip, sweeping
        `travel` px out over `duration` seconds — advanced by
        update_cleave_waves and drawn by draw_cleave_waves (render.py),
        independent of the attack's own phase so it outlives the swing."""
        if direction.length_squared() == 0:
            return
        self.cleave_waves.append({
            "origin": pygame.Vector2(origin), "dir": pygame.Vector2(direction).normalize(), "color": color,
            "size": size, "travel": travel, "elapsed": 0.0, "duration": duration, "ember_acc": 0.0,
        })
        if len(self.cleave_waves) > self.MAX_RINGS:
            self.cleave_waves.pop(0)

    def update_cleave_waves(self, dt):
        for w in self.cleave_waves:
            w["elapsed"] += dt
            t = w["elapsed"] / w["duration"]
            placed = cleave_wave_blade(w["origin"], w["dir"], t, w["size"], w["travel"])
            if placed is None or t > 0.8:
                continue
            blade, size = placed
            w["ember_acc"] += dt * self.CLEAVE_EMBER_RATE
            light = tuple(min(255, int(c * 0.4 + 255 * 0.6)) for c in w["color"])
            while w["ember_acc"] >= 1:
                w["ember_acc"] -= 1
                pos = crescent_edge_point(blade, w["dir"], size, random.uniform(-0.9, 0.9))
                vel = w["dir"] * random.uniform(30, 150) + pygame.Vector2(
                    random.uniform(-50, 50), random.uniform(-50, 50)
                )
                self.fx.emit(Particle(
                    pos, vel, random.uniform(0.3, 0.6), random.uniform(1.5, 3.2),
                    random.choice((w["color"], light)), drag=0.93, kind="square",
                    rotation=random.uniform(0, math.tau), rotation_speed=random.uniform(-6, 6),
                ))
        self.cleave_waves = [w for w in self.cleave_waves if w["elapsed"] < w["duration"]]

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
        if abs(speed - f.base_speed) < 0.5:
            return
        # Eases both ways: character collisions (entities.resolve_character_
        # collision) trade vel between bodies and can leave f slower than
        # base_speed. Only easing down used to ratchet roam speed toward
        # zero over a long match.
        new_speed = f.base_speed + (speed - f.base_speed) * (1 - min(1.0, dt / self.LAUNCH_DECAY_S))
        if abs(new_speed - f.base_speed) < 0.5:
            new_speed = f.base_speed
        if speed < 1e-6:
            angle = random.uniform(0, math.tau)
            f.vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * new_speed
        else:
            f.vel.scale_to_length(new_speed)

    def spawn_impact_particles(self, attacker, pos, tier):
        """Character-flavored hit particles, dispatched to the attacker's
        own CharacterPlugin.impact_particles — falls back to a generic
        color spark for a fighter whose plugin doesn't override it."""
        count = self.TIER_PARTICLE_COUNT[tier]
        plugin = self.plugin_for(attacker)
        handled = plugin.impact_particles(pos, count) if plugin is not None else False
        fx = self.fx_color(attacker)
        if not handled:
            emit_hit_spark(self.fx, pos, fx, count=count)
        if tier in ("heavy", "ultimate"):
            emit_hit_spark(self.fx, pos, lighten(fx, 0.6), count=count // 2)
        if tier == "ultimate":
            emit_debris(self.fx, pos, count=count // 5)

    def add_screen_shake(self, amount, duration=0.15):
        self.camera_shake.add(amount, duration)

    # How much a spawned afterimage gets elongated along its own direction of
    # travel (and squashed across it) before being rotated to face that
    # heading — see spawn_afterimage — so a fast dash/sprint leaves a
    # directional motion-blur streak instead of a plain static copy of the
    # sprite repeated a few times.
    AFTERIMAGE_STRETCH = 1.22
    AFTERIMAGE_SQUASH = 0.9
    #: Starting opacity of an afterimage ghost (fades from there).
    AFTERIMAGE_ALPHA = 120.0

    def spawn_afterimage(self, f):
        # A ghost in the fighter's own effect color (see afterimage_ghost),
        # not a full-color copy of the sprite, so a dash leaves a clean
        # colored trail instead of a smear of stacked sprites.
        img = self.afterimage_ghost(f)
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
        self.afterimages.append({"image": img, "pos": pygame.Vector2(f.pos), "alpha": self.AFTERIMAGE_ALPHA})
        if len(self.afterimages) > 14:
            self.afterimages.pop(0)

    def afterimage_ghost(self, f):
        """`f`'s sprite recolored to its effect color (colorize_sprite keeps
        the sprite's shading, so the ghost still reads as that fighter),
        cached per (sprite, color)."""
        color = self.fx_color(f)
        cache = self.__dict__.setdefault("_ghost_cache", {})
        key = (id(f.image), color)
        ghost = cache.get(key)
        if ghost is None:
            ghost = colorize_sprite(f.image, color)
            cache[key] = ghost
        return ghost.copy()

    def add_ring(self, pos, max_radius, duration, color, start_radius=8, width=3):
        """An expanding shockwave ring — used for AoE casts and ultimate
        impacts. Pure decoration: owns no gameplay state, just fades out."""
        self.rings.append({
            "pos": pygame.Vector2(pos), "start_radius": start_radius, "max_radius": max_radius,
            "duration": duration, "elapsed": 0, "color": color, "width": width,
        })
        if len(self.rings) > self.MAX_RINGS:
            self.rings.pop(0)
