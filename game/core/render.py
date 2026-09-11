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
    ARENA_RECT, AVATAR_R, BLACK, GOLD, HEIGHT, NAIL_SILVER, ORANGE, POISON_COLOR, RAIJU_CYAN,
    RED, SHIELD_COLOR, STUN_COLOR, WHITE, WIDTH,
)
from .effects import build_vignette, draw_shockwave, draw_status_rings, scale_sprite, tint_flash
from .motions import ease_out
from .status_library import RING_COLOR as STATUS_RING_COLOR


class RenderMixin:
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
        self.draw_zones(scene)
        self.draw_rings(scene, shake_x)
        self.draw_afterimages(scene, shake_x)
        self.draw_fighter(scene, self.f1, shake_x)
        self.draw_fighter(scene, self.f2, shake_x)
        for plugin in self.plugins:
            plugin.draw_fx(scene, shake_x)
        self.fx.draw(scene, bg_color=BLACK, offset=(shake_x, 0))
        self.draw_clone(scene)
        self.draw_projectile(scene)
        self.draw_floaters(scene)

        self.blit_zoomed_scene(screen, scene)
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

    def blit_zoomed_scene(self, screen, scene):
        """Composite the world layer onto `screen`, punched in by self.zoom
        around the arena's center — a no-op scale skips the resample."""
        if abs(self.zoom - 1.0) < 0.01:
            screen.blit(scene, (0, 0))
            return
        cx, cy = ARENA_RECT.center
        new_size = (max(1, round(WIDTH * self.zoom)), max(1, round(HEIGHT * self.zoom)))
        scaled = pygame.transform.smoothscale(scene, new_size)
        screen.blit(scaled, (cx - cx * self.zoom, cy - cy * self.zoom))

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

    def draw_afterimages(self, screen, shake_x):
        for ai in self.afterimages:
            img = ai["image"]
            img.set_alpha(max(0, int(ai["alpha"])))
            rect = img.get_rect(center=(int(ai["pos"].x + shake_x), int(ai["pos"].y)))
            screen.blit(img, rect)

    def hit_flash_sprite(self, img, f):
        """NORMAL -> WHITE -> NORMAL on a light/skill hit; NORMAL -> WHITE ->
        RED -> NORMAL on a heavy/ultimate hit (f.hit_flash_heavy), so bigger
        hits read as more punishing without a separate timer to manage."""
        ratio = f.hit_flash / f.hit_flash_max if f.hit_flash_max else 0.0
        if f.hit_flash_heavy:
            if ratio > 0.5:
                color, alpha = WHITE, 255 * ((ratio - 0.5) / 0.5)
            else:
                color, alpha = RED, 255 * (ratio / 0.5)
        else:
            color, alpha = WHITE, 255 * ratio
        return tint_flash(img, color, alpha)

    def draw_fighter(self, screen, f, shake_x):
        jitter = pygame.Vector2(
            random.uniform(-1, 1) * f.shake * 0.5, random.uniform(-1, 1) * f.shake * 0.5
        )
        x = f.pos.x + shake_x + jitter.x + f.visual_recoil.x
        y = f.pos.y + jitter.y + f.visual_recoil.y

        is_flicker_hidden = (
            self.mode == "attack" and self.motion == "flicker_slash" and f is self.attacker
            and self.current_phase in ("vanish", "reappear")
        )
        if self.mode == "attack" and self.motion == "spin" and f is self.attacker:
            for i in range(4):
                ang = f.spin_angle + i * math.pi / 2
                x2 = x + math.cos(ang) * (AVATAR_R + 10)
                y2 = y + math.sin(ang) * (AVATAR_R + 10)
                pygame.draw.line(screen, f.color, (x, y), (x2, y2), 2)

        # Everything drawn below the sprite itself — the outer color ring,
        # every status ring/pip, and the HP badge — fades in lockstep with
        # f.vanish_alpha too (battle_loop.py's update()), so Vanished (see
        # core/status_library.py) reads as the whole character genuinely
        # gone, not just its sprite. 1.0 the overwhelming rest of the time
        # (not vanished), so this is a no-op fade for every other fighter.
        alpha_mult = max(0.0, min(1.0, f.vanish_alpha / 255.0))

        def faded(color):
            return (color[0], color[1], color[2], round(255 * alpha_mult))

        ring_r = AVATAR_R + 6
        if (self.mode == "attack" and self.ability and self.ability.kind == "ultimate"
                and self.current_phase == "impact" and f is self.defender):
            ring_r += 8
            pygame.draw.circle(screen, faded(GOLD), (int(x), int(y)), ring_r, width=4)
        else:
            pygame.draw.circle(screen, faded(f.color), (int(x), int(y)), ring_r, width=3)

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
            img = scale_sprite(img, f.scale_x, f.scale_y)
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
        # visual feedback too.
        draw_status_rings(screen, pygame.Vector2(x, y), f.statuses, font=self.font_small, alpha_mult=alpha_mult)
        if f.key == "berserker" and "invulnerable" in f.statuses:
            pulse = 3 + 3 * math.sin(pygame.time.get_ticks() * 0.02)
            pygame.draw.circle(screen, faded(ORANGE), (int(x), int(y)), int(AVATAR_R + 8 + pulse), width=3)

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
        img = scale_sprite(c.image.copy(), c.scale_x, c.scale_y)
        rect = img.get_rect(center=(int(c.pos.x), int(c.pos.y)))
        screen.blit(img, rect)
        pygame.draw.circle(screen, c.color, (int(c.pos.x), int(c.pos.y)), AVATAR_R + 6, width=3)
        if "taunt" in c.statuses:
            pulse = 3 + 3 * math.sin(pygame.time.get_ticks() * 0.02)
            pygame.draw.circle(
                screen, STATUS_RING_COLOR["taunt"], (int(c.pos.x), int(c.pos.y)), int(AVATAR_R + 9 + pulse), width=2
            )
        # Same status-ring feedback a real fighter gets (see draw_fighter) —
        # a decoy can now carry poison/corruption/etc. from an enemy zone
        # tick or a redirected hit's own tag effect (see core/status_
        # library.py), so it reads that just as visibly.
        draw_status_rings(screen, c.pos, c.statuses, font=self.font_small, exclude=("taunt",))

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
