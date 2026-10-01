"""Per-frame scene rendering: the `draw()` orchestrator plus the arena
layer beneath the HUD — ambient dust, zone circles, shockwave rings,
afterimages, fighter avatars with their status rings, the Vampire's clone
decoy, and ability projectiles. Character-specific weapon/technique
animation is dispatched to each fighter's own CharacterPlugin (draw_fx /
draw_projectile — see core/plugin.py); HUD/overlay drawing lives in hud.py.
"""

import math
import random

import pygame

from .constants import (
    ARENA_RECT, AVATAR_R, BLACK, CRIT_COLOR, GOLD, HEIGHT, NAIL_SILVER, POISON_COLOR, RAIJU_CYAN,
    RED, SHIELD_COLOR, STUN_COLOR, WHITE, WIDTH,
)
from .anime_fx import draw_cast_circle, draw_dust_puff, draw_speed_lines, draw_twirl
from .effects import blend_flash, build_vignette, draw_cleave_wave, draw_impact_stamp, draw_shockwave, draw_status_rings
from .motions import ease_out
from .status_library import RING_COLOR as STATUS_RING_COLOR


class RenderMixin:
    # apply_bloom's own tuning: how far the scene is shrunk before growing it
    # back (bigger = blurrier glow, cheaper) and how bright the blurred copy
    # is before it's added back on top (0-255).
    BLOOM_DOWNSCALE = 6
    BLOOM_INTENSITY = 70

    def draw(self, screen, show_winner=True):
        """The world layer (arena, fighters, particles, projectiles, floaters)
        is drawn onto an offscreen `scene` first so a heavy/ultimate impact
        can punch the camera in around the arena (self.zoom) without also
        zooming the HUD — overlay tints, vignette, hit-flash and the status
        panels are composited straight onto `screen` afterward, unzoomed."""
        screen.fill(BLACK)
        self.draw_title(screen)

        scene = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shake_vec = self.camera_shake.offset()
        shake_x = int(shake_vec.x)

        pygame.draw.rect(
            scene, WHITE,
            (ARENA_RECT.left + shake_x, ARENA_RECT.top, ARENA_RECT.width, ARENA_RECT.height),
            width=3,
        )
        self.draw_particles(scene)
        self.draw_decals(scene, shake_x)
        self.draw_dust_puffs(scene, shake_x)
        self.draw_zones(scene)
        self.draw_rings(scene, shake_x)
        self.draw_afterimages(scene, shake_x)
        self.draw_fighter(scene, self.f1, shake_x)
        self.draw_fighter(scene, self.f2, shake_x)
        # draw_fx runs once per plugin every frame — idle weapon props (e.g.
        # Legion Commander's rested scepter) need it even when self.attacks
        # is empty (nobody mid-cast), and each plugin's own self._current
        # binding must be its own fighter's AttackState (or None), not just
        # whichever attack happens to be bound — looping self.attacks.values()
        # and calling every plugin for each state (the old approach) skipped
        # draw_fx entirely while idle, and during simultaneous dual attacks
        # would call each plugin twice, once bound to the wrong fighter's
        # state, clobbering its own active swing with an idle-pose redraw.
        for plugin in self.plugins:
            self._current = self.attacks.get(plugin.fighter)
            plugin.draw_fx(scene, shake_x)
        self._current = None
        self.fx.draw(scene, bg_color=BLACK, offset=(shake_x, 0))
        self.draw_clone(scene)
        for state in self.attacks.values():
            self._current = state
            self.draw_projectile(scene)
        self._current = None
        self.draw_cleave_waves(scene, shake_x)
        self.draw_impact_stamps(scene, shake_x)
        self.draw_floaters(scene)
        self.apply_bloom(scene)

        self.blit_zoomed_scene(screen, scene)
        self.draw_ko_overlay(screen)
        for plugin in self.plugins:
            plugin.full_screen_overlay(screen)
        self.draw_vignette(screen)
        self.draw_flash(screen)
        self.draw_status_panel(screen, self.f1, left_side=True)
        self.draw_status_panel(screen, self.f2, left_side=False)
        self.draw_log(screen)

        if self.mode == "gameover" and show_winner:
            self.draw_winner(screen)
        if self.debug:
            self.draw_debug(screen)

    def apply_bloom(self, scene):
        """Cheap poor-man's bloom: shrink the whole `scene` surface way down
        (the resample itself blurs it) then grow it back to full size and
        add that blurred copy on top with BLEND_RGB_ADD — no per-pixel
        brightness threshold needed, since the near-black arena background
        (BLACK, see constants.py) contributes almost nothing when added back
        while a saturated particle/projectile/lightning color contributes a
        lot, so magic/impact effects read as genuinely glowing instead of
        flat-shaded. BLEND_RGB_ADD only touches RGB (see tint_flash's own use
        of the same flag in effects.py) — `scene`'s own per-pixel alpha,
        which is what actually decides what's visible once it's composited
        onto `screen`, is untouched, so this can never make empty background
        space visible.

        Per-surface set_alpha() is ignored by a special-flags blit like this
        one (same reason tint_flash pre-scales its own tint color instead of
        relying on it) — BLOOM_INTENSITY dims the blurred copy for real via
        BLEND_RGB_MULT before it's added back, rather than a set_alpha call
        that would silently do nothing here."""
        small_size = (max(1, WIDTH // self.BLOOM_DOWNSCALE), max(1, HEIGHT // self.BLOOM_DOWNSCALE))
        glow = pygame.transform.smoothscale(scene, small_size)
        glow = pygame.transform.smoothscale(glow, (WIDTH, HEIGHT))
        dim = (self.BLOOM_INTENSITY,) * 3
        glow.fill(dim, special_flags=pygame.BLEND_RGB_MULT)
        scene.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def blit_zoomed_scene(self, screen, scene):
        """Composite the world layer onto `screen`, punched in by self.zoom
        around the arena's center — a no-op scale skips the resample."""
        if abs(self.zoom - 1.0) < 0.01:
            screen.blit(scene, (0, 0))
            return
        cx, cy = self.zoom_focus if self.zoom_focus is not None else ARENA_RECT.center
        new_size = (max(1, round(WIDTH * self.zoom)), max(1, round(HEIGHT * self.zoom)))
        scaled = pygame.transform.smoothscale(scene, new_size)
        # Clipped to the arena: an off-center punch-in (the KO beat's
        # zoom_focus) would otherwise slide the world over the title/HUD.
        # Any zoom >1 around a point inside the arena still covers the
        # whole arena, so the clip never exposes a gap.
        screen.set_clip(ARENA_RECT.inflate(6, 6))
        screen.blit(scaled, (cx - cx * self.zoom, cy - cy * self.zoom))
        screen.set_clip(None)

    def draw_vignette(self, screen):
        if getattr(self, "_vignette_surf", None) is None:
            self._vignette_surf = build_vignette(WIDTH, HEIGHT)
        screen.blit(self._vignette_surf, (0, 0))

    def draw_particles(self, screen):
        for p in self.particles:
            pygame.draw.circle(screen, p["shade"], (int(p["pos"].x), int(p["pos"].y)), max(1, int(p["r"])))

    def draw_zones(self, screen):
        for z in self.zones:
            owner_plugin = self.plugin_for(z.owner)
            # zone_style's own name (Static Field/Blood Pool/Sacred Ground)
            # is deliberately not drawn in the arena anymore — just the
            # color, for the ring/decoration below.
            color, _label = owner_plugin.zone_style(z) if owner_plugin is not None else (WHITE, z.kind.title())
            pygame.draw.circle(screen, color, (int(z.center.x), int(z.center.y)), int(z.radius), width=2)
            if owner_plugin is not None:
                owner_plugin.zone_decorate(screen, z)

    def draw_rings(self, screen, shake_x):
        for r in self.rings:
            progress = min(1.0, r["elapsed"] / r["duration"])
            radius = r["start_radius"] + (r["max_radius"] - r["start_radius"]) * ease_out(progress)
            fade = 1.0 - progress
            pos = r["pos"] + pygame.Vector2(shake_x, 0)
            draw_shockwave(screen, pos, radius, r["color"], width=r["width"], bg_color=BLACK, fade=fade)

    #: Attack phases during which an ultimate shows its casting circle
    #: (the build-up phases of every motion, before anything lands).
    CAST_CIRCLE_PHASES = ("windup", "channel", "charge")

    def draw_decals(self, screen, shake_x):
        for d in self.decals:
            fade = min(1.0, (d["duration"] - d["elapsed"]) / 1.0)
            surf = d["surf"]
            if fade < 1.0:
                surf = surf.copy()
                surf.set_alpha(int(255 * fade))
            screen.blit(surf, surf.get_rect(center=(round(d["pos"].x + shake_x), round(d["pos"].y))))

    def draw_dust_puffs(self, screen, shake_x):
        for d in self.dust_puffs:
            t = min(1.0, d["elapsed"] / d["duration"])
            draw_dust_puff(screen, d["pos"] + pygame.Vector2(shake_x, 0), d["size"], t, d["variant"])

    #: Elastic squash-and-stretch after a landed hit: a damped wobble
    #: (squash along the hit's axis, overshoot into a stretch, settle) over
    #: SQUASH_S seconds, strength set per tier by ImpactFXMixin.TIER_SQUASH.
    SQUASH_S = 0.4
    SQUASH_DAMPING = 8.0
    SQUASH_FREQ = 30.0

    def squash_sprite(self, img, f):
        t = f.squash_t
        if t >= self.SQUASH_S or f.squash_amp <= 0:
            return img
        k = f.squash_amp * math.exp(-t * self.SQUASH_DAMPING) * math.cos(t * self.SQUASH_FREQ)
        if abs(k) < 0.01:
            return img
        w, h = img.get_size()
        # Squash along whichever screen axis the hit mostly travelled on,
        # bulge out across it (volume roughly kept).
        if abs(f.squash_dir.x) >= abs(f.squash_dir.y):
            size = (w * (1 - k), h * (1 + k * 0.8))
        else:
            size = (w * (1 + k * 0.8), h * (1 - k))
        return pygame.transform.smoothscale(img, (max(1, round(size[0])), max(1, round(size[1]))))

    def draw_ko_overlay(self, screen):
        """The KO slow-motion beat's anime framing, over the zoomed world
        but under the HUD: flickering manga focus lines converging on the
        fallen fighter (the zoom focus, which stays put on screen)."""
        if self.ko_slowmo <= 0 or self.zoom_focus is None:
            return
        elapsed = self.KO_SLOWMO_S - self.ko_slowmo
        fade = min(1.0, self.ko_slowmo / 0.25)
        seed = int(elapsed * 30)  # new line pattern every ~2 frames
        screen.set_clip(ARENA_RECT)
        draw_speed_lines(screen, self.zoom_focus, ARENA_RECT, seed, alpha=int(150 * fade), clear_radius=80)
        screen.set_clip(None)

    def draw_cleave_waves(self, screen, shake_x):
        for w in self.cleave_waves:
            t = min(1.0, w["elapsed"] / w["duration"])
            origin = w["origin"] + pygame.Vector2(shake_x, 0)
            draw_cleave_wave(screen, origin, w["dir"], t, color=w["color"], size=w["size"], travel=w["travel"])

    def draw_impact_stamps(self, screen, shake_x):
        for s in self.impact_stamps:
            t = min(1.0, s["elapsed"] / s["duration"])
            pos = s["pos"] + pygame.Vector2(shake_x, 0)
            draw_impact_stamp(screen, pos, s["frames"], t)

    def draw_afterimages(self, screen, shake_x):
        for ai in self.afterimages:
            img = ai["image"]
            img.set_alpha(max(0, int(ai["alpha"])))
            rect = img.get_rect(center=(int(ai["pos"].x + shake_x), int(ai["pos"].y)))
            screen.blit(img, rect)

    #: Strongest mix toward the flash color a hit puts on a sprite (0-255).
    HIT_FLASH_PEAK = 125

    def hit_flash_sprite(self, img, f):
        """NORMAL -> WHITE -> NORMAL on a light/skill hit; NORMAL -> WHITE ->
        RED -> NORMAL on a heavy/ultimate hit (f.hit_flash_heavy); NORMAL ->
        WHITE -> CRIT_COLOR -> NORMAL on a critical hit (f.hit_flash_crit) —
        its own distinct tint instead of just reusing the heavy hit's RED, so
        a crit reads as its own flourish rather than another heavy hit that
        happens to also be bigger."""
        ratio = f.hit_flash / f.hit_flash_max if f.hit_flash_max else 0.0
        # The "white" beat is a pale tint of the attacker's own color (set
        # by apply_impact as f.hit_flash_color), and the whole flash is
        # capped below full strength so the sprite never blows out into a
        # flat white disc.
        light = getattr(f, "hit_flash_color", None) or WHITE
        if getattr(f, "hit_flash_crit", False):
            if ratio > 0.5:
                color, alpha = light, self.HIT_FLASH_PEAK * ((ratio - 0.5) / 0.5)
            else:
                color, alpha = CRIT_COLOR, self.HIT_FLASH_PEAK * 0.8 * (ratio / 0.5)
        elif f.hit_flash_heavy:
            if ratio > 0.5:
                color, alpha = light, self.HIT_FLASH_PEAK * ((ratio - 0.5) / 0.5)
            else:
                color, alpha = RED, self.HIT_FLASH_PEAK * 0.7 * (ratio / 0.5)
        else:
            color, alpha = light, self.HIT_FLASH_PEAK * ratio
        return blend_flash(img, color, alpha)

    def draw_fighter(self, screen, f, shake_x):
        # f can simultaneously be the attacker of its own AttackState and
        # the defender of the opponent's — unlike the fx/projectile draws
        # above, this needs both roles for the *same* fighter, so it looks
        # them up directly instead of relying on a single bound
        # self._current (which can only ever answer one role at a time).
        atk_state = self.attacks.get(f)
        def_state = self.defending_state(f)

        jitter = pygame.Vector2(
            random.uniform(-1, 1) * f.shake * 0.5, random.uniform(-1, 1) * f.shake * 0.5
        )
        x = f.pos.x + shake_x + jitter.x + f.visual_recoil.x
        y = f.pos.y + jitter.y + f.visual_recoil.y

        is_flicker_hidden = (
            atk_state is not None and atk_state.motion == "flicker_slash"
            and atk_state.current_phase in ("vanish", "reappear")
        )
        if atk_state is not None and atk_state.motion == "spin":
            draw_twirl(screen, (x, y), self.fx_color(f), (AVATAR_R + 14) * 2.4, -math.degrees(f.spin_angle))
        # An ultimate's wind-up: a magic circle turning on the ground under
        # the caster until the ability actually goes off.
        if (atk_state is not None and atk_state.ability is not None and atk_state.ability.kind == "ultimate"
                and atk_state.current_phase in self.CAST_CIRCLE_PHASES):
            fade_in = min(1.0, (atk_state.phase_t + (1 if atk_state.current_phase != "windup" else 0)) * 2)
            draw_cast_circle(screen, (x, y + 6), self.fx_color(f), AVATAR_R * 4, pygame.time.get_ticks() * 0.12,
                             alpha=200 * fade_in)

        # Everything drawn below the sprite itself — the outer color ring,
        # every status ring/pip, and the HP badge — fades in lockstep with
        # f.vanish_alpha too (battle_loop.py's update()), so Vanished (see
        # core/status_library.py) reads as the whole character genuinely
        # gone, not just its sprite. 1.0 the overwhelming rest of the time
        # (not vanished), so this is a no-op fade for every other fighter.
        alpha_mult = max(0.0, min(1.0, f.vanish_alpha / 255.0))

        def faded(color):
            return (color[0], color[1], color[2], round(255 * alpha_mult))

        ring_r = round((AVATAR_R + 6) * f.ring_scale)
        if (def_state is not None and def_state.ability and def_state.ability.kind == "ultimate"
                and def_state.current_phase == "impact"):
            ring_r += 8
            pygame.draw.circle(screen, faded(GOLD), (int(x), int(y)), ring_r, width=4)
        else:
            pygame.draw.aacircle(screen, faded(f.color), (int(x), int(y)), ring_r, width=3)

        if is_flicker_hidden:
            for _ in range(7):
                ang = random.uniform(0, math.tau)
                dist = random.uniform(4, AVATAR_R)
                sx = x + math.cos(ang) * dist
                sy = y + math.sin(ang) * dist
                pygame.draw.circle(screen, RAIJU_CYAN, (int(sx), int(sy)), 2)
        else:
            img = f.image
            is_untargetable = "untargetable" in f.statuses
            # Keyed off the eased f.vanish_alpha (battle_loop.py's update()),
            # not the raw "vanished" status flag, so the fade keeps playing
            # for the few frames it takes to ease back to full opacity even
            # after the status itself has already expired — an instant snap
            # back otherwise wouldn't read as an animation at all.
            is_vanishing = f.vanish_alpha < 254.5
            if is_untargetable or is_vanishing:
                img = img.copy()
            if f.hit_flash > 0:
                img = self.hit_flash_sprite(img, f)
            img = self.squash_sprite(img, f)
            if is_vanishing:
                # per-surface alpha doesn't survive a transform (see draw_rotated
                # above), so it's (re)applied last, after any tint/scale —
                # eases all the way to fully invisible (0), unlike
                # untargetable's dodge-window fade below, since Vanished
                # means genuinely not there rather than just evasive.
                img.set_alpha(max(0, int(f.vanish_alpha)))
            elif is_untargetable:
                img.set_alpha(120)
            img_rect = img.get_rect(center=(int(x), int(y)))
            screen.blit(img, img_rect)

        # Shared with draw_clone/CloneArmy.draw (core/clone_army.py) — a
        # clone can now carry the same statuses a real fighter can (see
        # core/status_library.py's generic pipeline), so it reads the same
        # visual feedback too. `radius` follows this fighter's own sprite
        # size (f.image.get_width()/2) rather than the flat AVATAR_R every
        # fighter used to share, so e.g. the dummy's much bigger sprite gets
        # status rings sized to match it instead of a fixed ring that reads
        # too small on it.
        avatar_radius = f.image.get_width() / 2
        draw_status_rings(
            screen, pygame.Vector2(x, y), f.statuses, font=self.font_small, alpha_mult=alpha_mult,
            radius=avatar_radius,
        )

        hp_val = max(0, round(f.display_hp))
        txt = self.font_small.render(str(hp_val), True, WHITE)
        txt.set_alpha(round(255 * alpha_mult))
        bx, by = x, y - AVATAR_R - 22
        bg_rect = pygame.Rect(0, 0, txt.get_width() + 10, txt.get_height() + 4)
        bg_rect.center = (bx, by)
        pygame.draw.rect(screen, faded((25, 25, 25)), bg_rect, border_radius=4)
        pygame.draw.rect(screen, faded(RED), bg_rect, width=1, border_radius=4)
        screen.blit(txt, (bx - txt.get_width() / 2, by - txt.get_height() / 2))

    def draw_clone(self, screen):
        if self.clone is None:
            return
        c = self.clone
        rect = c.image.get_rect(center=(int(c.pos.x), int(c.pos.y)))
        screen.blit(c.image, rect)
        pygame.draw.circle(screen, c.color, (int(c.pos.x), int(c.pos.y)), AVATAR_R + 6, width=3)
        if "taunt" in c.statuses:
            pulse = 3 + 3 * math.sin(pygame.time.get_ticks() * 0.02)
            pygame.draw.circle(
                screen, STATUS_RING_COLOR["taunt"], (int(c.pos.x), int(c.pos.y)), int(AVATAR_R + 9 + pulse), width=2
            )
        # Same status-ring feedback a real fighter gets (see draw_fighter) —
        # a decoy can now carry poison/corruption/etc. from an enemy zone
        # tick or a redirected hit's own tag effect (see core/status_
        # library.py), so it reads that just as visibly. `radius` follows
        # this decoy's own (already scaled) sprite, same reasoning as
        # draw_fighter's own avatar_radius above.
        draw_status_rings(
            screen, c.pos, c.statuses, font=self.font_small, exclude=("taunt",), radius=c.image.get_width() / 2,
        )

    def draw_projectile(self, screen):
        if not (
            self.mode == "attack"
            and self.motion in ("bolt", "homing_bolt", "ricochet", "instant_ricochet", "swarm")
        ):
            return
        plugin = self.plugin_for(self.attacker)
        if plugin is not None and plugin.draw_projectile(screen):
            return
        if not self.projectile_pos:
            return
        # Generic fallback for any bolt-type ability whose plugin doesn't
        # draw its own projectile visual.
        radius = 11 if self.ability.big else 8
        pygame.draw.line(screen, self.attacker.color, self.attacker_start, self.projectile_pos, 2)
        pygame.draw.circle(
            screen, self.attacker.color,
            (int(self.projectile_pos.x), int(self.projectile_pos.y)), radius,
        )
