"""Reusable draw-time effect primitives shared across abilities: simple
shapes (a claw-cut, a lightning bolt, a fan-shaped AoE wedge), rotated-prop
blitting, a recolorable painted energy-bolt flipbook
(draw_bolt_fx, backed by colorize_sprite), and two "impact" effects — a
genuine curved slash arc (as opposed to the straight cut mark `draw_slash`)
and a fading expanding shockwave ring. None of these read or mutate battle
state; every caller passes in exactly the position/direction/color it wants
drawn.
"""

import math
import random

import pygame

from .asset_loading import load_animation_frames, load_sprite
from .glow import add_dot, glow_line, glow_polyline, glow_ring
from .glow import lighten as glow_lighten
from .glow import scale as glow_scale
from .constants import (
    AVATAR_R, NAIL_GLOW_BLUE, NAIL_SILVER, POISON_COLOR, RAIJU_CYAN, RED, SHIELD_COLOR, STUN_COLOR, WHITE,
)
from .status_library import RING_COLOR as STATUS_RING_COLOR
from .status_library import STATUS_ICON as STATUS_ICON

# Per-status icon rendering for every RING_COLOR fallback status (see
# status_library.STATUS_ICON for how each name gets its own unique
# (shape, ring) pair) — draw_status_rings below uses this to draw the ring
# in its own `ring` style and spin `dots` copies of its own `shape` around
# it, so two different statuses never come out looking like the same icon
# with only the color swapped.


def _draw_node_shape(screen, shape, center, r, color):
    """One orbiting accent node — the small `shape`-marked satellite that
    spins around a status ring (see the reference badge: a ring with a few
    orbiting nodes on it)."""
    cx, cy = center
    if shape == "circle":
        pygame.draw.circle(screen, color, (round(cx), round(cy)), r)
    elif shape == "diamond":
        pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
        pygame.draw.polygon(screen, color, pts)
    elif shape == "triangle":
        pts = [(cx, cy - r), (cx + r * 0.87, cy + r * 0.5), (cx - r * 0.87, cy + r * 0.5)]
        pygame.draw.polygon(screen, color, pts)
    elif shape == "square":
        pygame.draw.rect(screen, color, (round(cx - r), round(cy - r), r * 2, r * 2))
    elif shape == "cross":
        pygame.draw.line(screen, color, (cx - r, cy), (cx + r, cy), 2)
        pygame.draw.line(screen, color, (cx, cy - r), (cx, cy + r), 2)
    elif shape == "star":
        # A small 4-pointed sparkle: alternating outer/inner radius points.
        pts = []
        for k in range(8):
            ang = k * math.pi / 4
            rad = r if k % 2 == 0 else r * 0.4
            pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
        pygame.draw.polygon(screen, color, pts)
    elif shape == "hexagon":
        pts = [(cx + math.cos(k * math.pi / 3) * r, cy + math.sin(k * math.pi / 3) * r) for k in range(6)]
        pygame.draw.polygon(screen, color, pts)
    elif shape == "pentagon":
        pts = [
            (cx + math.cos(k * 2 * math.pi / 5 - math.pi / 2) * r, cy + math.sin(k * 2 * math.pi / 5 - math.pi / 2) * r)
            for k in range(5)
        ]
        pygame.draw.polygon(screen, color, pts)


def _draw_ring_style(screen, x, y, radius, color, style, width=2, rot=0.0):
    """The status ring itself, in one of a few distinct outline treatments
    so e.g. a dashed ring never gets mistaken for a plain solid one even
    before its orbiting nodes are counted. `rot` (radians) slowly turns the
    segmented styles (dashed/notched/spiked) so they read as alive."""
    rect = pygame.Rect(x - radius, y - radius, radius * 2, radius * 2)
    if style == "solid":
        pygame.draw.circle(screen, color, (x, y), radius, width=width)
    elif style == "double":
        pygame.draw.circle(screen, color, (x, y), radius, width=1)
        pygame.draw.circle(screen, color, (x, y), max(1, radius - 3), width=1)
    elif style == "dashed":
        n = 10
        for k in range(n):
            a0 = rot + 2 * math.pi * k / n
            pygame.draw.arc(screen, color, rect, a0, a0 + (2 * math.pi / n) * 0.55, width)
    elif style == "notched":
        n = 3
        for k in range(n):
            a0 = rot + 2 * math.pi * k / n
            pygame.draw.arc(screen, color, rect, a0, a0 + (2 * math.pi / n) * 0.75, width)
    elif style == "spiked":
        pygame.draw.circle(screen, color, (x, y), radius, width=1)
        n = 8
        for k in range(n):
            ang = rot + 2 * math.pi * k / n
            inner = (x + math.cos(ang) * radius, y + math.sin(ang) * radius)
            outer = (x + math.cos(ang) * (radius + 4), y + math.sin(ang) * (radius + 4))
            pygame.draw.line(screen, color, inner, outer, 2)


def draw_icon_glyph(screen, shape, center, r, color):
    """Public entry point to the small node-shape catalog above (see
    _draw_node_shape) for a caller that just wants one static glyph — e.g.
    hud.py's compact per-status/per-ability icons — without the full
    ring-plus-orbiting-dots treatment draw_status_rings puts around a
    fighter."""
    _draw_node_shape(screen, shape, center, r, color)


def _lerp_color(bg, color, ratio):
    ratio = max(0.0, min(1.0, ratio))
    return (
        int(bg[0] + (color[0] - bg[0]) * ratio),
        int(bg[1] + (color[1] - bg[1]) * ratio),
        int(bg[2] + (color[2] - bg[2]) * ratio),
    )


def rotate_to_dir(img, direction):
    """Rotate a weapon image (drawn tip-up) to point along `direction`."""
    if direction.length_squared() == 0:
        return img
    angle_deg = math.degrees(math.atan2(-direction.y, direction.x)) - 90
    return pygame.transform.rotate(img, angle_deg)


def weapon_angle(direction, extra_deg=0.0):
    """Angle (degrees) to face `direction`, plus an extra swing offset."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    base = math.degrees(math.atan2(-direction.y, direction.x)) - 90
    return base + extra_deg


def draw_rotated(screen, img, pos, angle_deg, alpha=255):
    rotated = pygame.transform.rotate(img, angle_deg)
    if alpha < 255:
        rotated = rotated.copy()
        rotated.set_alpha(alpha)
    screen.blit(rotated, rotated.get_rect(center=(pos.x, pos.y)))


def draw_starburst(screen, pos, color, size=18, fade=1.0):
    """A quick radiating flash at the moment of impact: a soft glow in
    `color`, eight tapered light rays (long and short alternating) and a
    white-hot core, all stacked additively so it reads as light."""
    if fade <= 0:
        return
    fade = min(1.0, fade)
    add_dot(screen, pos, size * 1.25, color, 0.5 * fade)
    reach = size * (0.65 + 0.35 * fade)
    dim = int(reach * 2) + 8
    surf = pygame.Surface((dim, dim), pygame.SRCALPHA)
    c = pygame.Vector2(dim / 2, dim / 2)
    rot = random.uniform(0, math.pi / 4)
    body = glow_scale(color, 0.85 * fade)
    core = glow_scale(glow_lighten(color, 0.7), fade)
    for i in range(8):
        a = rot + i * math.pi / 4
        long_ray = i % 2 == 0
        length = reach * (1.0 if long_ray else 0.5)
        d = pygame.Vector2(math.cos(a), math.sin(a))
        perp = pygame.Vector2(-d.y, d.x)
        w = max(1.5, size * 0.085) * (1.0 if long_ray else 0.7)
        pygame.draw.polygon(surf, (*body, max(body)), [c + perp * w, c + d * length, c - perp * w, c - d * w])
        pygame.draw.polygon(surf, (*core, max(core)), [c + perp * w * 0.4, c + d * length * 0.75, c - perp * w * 0.4])
    screen.blit(surf, (round(pos.x - dim / 2), round(pos.y - dim / 2)), special_flags=pygame.BLEND_RGBA_ADD)
    add_dot(screen, pos, size * 0.4, glow_lighten(color, 0.85), fade)


def draw_expanding_ring(screen, pos, radius, color, width=2, fade=1.0):
    """A glowing shock ring (see glow.glow_ring) with a faint inner echo
    ring, instead of two flat opaque outlines."""
    if radius > 1:
        glow_ring(screen, pos, radius, color, width=width, intensity=fade)
        if radius * 0.6 > 3:
            glow_ring(screen, pos, radius * 0.6, color, width=max(1, width - 1), intensity=0.35 * fade)


_BOLT_TINT_CACHE = {}


def _bolt_frames(pixel_size, color):
    """The painted 3-frame energy-bolt flipbook (assets/animation/bolt/
    bolt-1..3.png — a pulse that grows into a burst), recolored to `color`
    via colorize_sprite and cached per (pixel_size, color) so the same
    ability firing repeatedly doesn't re-tint from scratch every frame."""
    key = (pixel_size, color)
    frames = _BOLT_TINT_CACHE.get(key)
    if frames is None:
        base = load_animation_frames("animation/bolt", "bolt", 3, pixel_size)
        frames = tuple(colorize_sprite(f, color) for f in base)
        _BOLT_TINT_CACHE[key] = frames
    return frames


def draw_bolt_fx(screen, pos, direction, color, size=1.0):
    """The painted bolt flipbook (see _bolt_frames) in flight at `pos`,
    facing `direction` and recolored to `color` — the shared traveling-
    projectile visual for any "bolt"-style skill (Chaos Bolt, Spirit Lance,
    Blood Bolt, ...) that used to be its own bespoke tapered-comet polygon,
    so each keeps its own signature color on the same painted art instead of
    a flat vector shape. The art is drawn facing +x with its trail wisping
    back along -x, so no default-facing correction is needed (contrast
    draw_slash_fx's _SLASH_FX_DEFAULT_DIR).
    Frame picked off wall-clock time, not the caller's own attack-phase
    progress, so it keeps pulsing for as long as the bolt stays in flight."""
    pixel_size = max(8, round(40 * size))
    frames = _bolt_frames(pixel_size, tuple(color[:3]))
    frame = frames[(pygame.time.get_ticks() // 70) % len(frames)]
    if direction.length_squared() != 0:
        angle = math.degrees(math.atan2(-direction.y, direction.x))
        frame = pygame.transform.rotate(frame, angle)
    screen.blit(frame, frame.get_rect(center=(round(pos.x), round(pos.y))))


def draw_curse_orb(screen, pos, direction, color, size=1.0):
    """A pulsing dark-magic orb with orbiting motes and a wisp trail —
    Blood Hex's projectile. Deliberately not draw_lightning: Raiju's
    Chain Bolt already owns "jagged bolt," so Blood Hex needed its own
    silhouette instead of just a recolor of the same shape."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    perp = pygame.Vector2(-d.y, d.x)
    r = 9 * size
    t = pygame.time.get_ticks() * 0.006
    dim = tuple(int(c * 0.55) for c in color)

    for i in range(4):
        back = pos - d * (6 + i * 7) * size + perp * math.sin(t * 3 + i) * 4 * size
        wr = max(1, (4 - i) * 1.4 * size)
        pygame.draw.circle(screen, dim, (int(back.x), int(back.y)), int(wr))

    for i in range(3):
        ang = t * 2 + i * (math.tau / 3)
        mote = pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * r * 1.7
        pygame.draw.circle(screen, color, (int(mote.x), int(mote.y)), max(1, int(r * 0.3)))

    pygame.draw.circle(screen, dim, (int(pos.x), int(pos.y)), int(r * 1.6))
    pygame.draw.circle(screen, color, (int(pos.x), int(pos.y)), int(r))
    pygame.draw.circle(screen, WHITE, (int(pos.x), int(pos.y)), max(1, int(r * 0.35)))


_NAIL_BULLET_CACHE = {}


def _nail_bullet_image(diameter):
    """assets/johnny/nail-bullet.png, loaded once per size and cached — draw_nail
    below re-blits it every frame a nail is in flight."""
    img = _NAIL_BULLET_CACHE.get(diameter)
    if img is None:
        img = load_sprite("johnny/nail-bullet.png", diameter)
        _NAIL_BULLET_CACHE[diameter] = img
    return img


def draw_nail(screen, pos, direction, color, size=1.0):
    """One of Johnny's own fingernails, Stand-charged and fired as a bullet
    (see assets/johnny/nail-bullet.png) — a glow-orb oriented to face the way it's
    travelling (see rotate_to_dir), with a fading trail behind it colored
    per-ability (blue for a live shot, silver for Tusk Act 4's conjured
    nails — see NAIL_GLOW_BLUE/NAIL_SILVER). Used for the basic attack,
    Tusk Act 2, Tusk Act 3, and Tusk Act 4 alike (they differ in behavior,
    not in what the bullet looks like)."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    diameter = 38 * size

    for i in range(3):
        back = pos - d * (diameter * 0.55 + i * diameter * 0.4)
        wr = max(1, diameter * 0.22 * (1 - i * 0.25))
        pygame.draw.circle(screen, color, (int(back.x), int(back.y)), int(wr))

    img = rotate_to_dir(_nail_bullet_image(round(diameter)), d)
    screen.blit(img, img.get_rect(center=(pos.x, pos.y)))


def draw_slash(screen, center, direction, color, length=30, width=5):
    """A single bright claw-cut mark across `center`, angled by `direction`
    — for fighters (Sukuna, Raiju) who hit bare-handed and need an explicit
    cut instead of a swung weapon prop. Drawn as a glowing blade stroke
    tapering to points at both ends."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    perp = pygame.Vector2(-d.y, d.x)
    p1 = center - perp * length / 2 - d * length * 0.2
    p2 = center + perp * length / 2 + d * length * 0.2
    if (p2 - p1).length_squared() < 1:
        return
    along = (p2 - p1).normalize()
    side = pygame.Vector2(-along.y, along.x)
    w = width * 0.6
    add_dot(screen, center, length * 0.45, color, 0.35)
    glow_line(screen, p1, p2, color, width=max(1, int(width * 0.5)), intensity=0.8)
    blade = [p1, center + side * w, p2, center - side * w]
    pygame.draw.polygon(screen, glow_lighten(color, 0.55), blade)
    pygame.draw.aalines(screen, glow_lighten(color, 0.85), True, blade)


def draw_lightning(screen, start, end, color, segments=6, jitter=10, branches=2):
    """A flickering jagged bolt between two points, with a couple of short
    branching forks kicked off the main path for extra chaos — used for
    Heaven's Verdict, Chain Bolt, Static Field, and Thunder God's Descent.
    Drawn as a glowing stroke (wide soft halo, colored body, white core)."""
    diff = end - start
    perp = pygame.Vector2(-diff.y, diff.x).normalize() if diff.length_squared() > 0 else pygame.Vector2(0, 1)
    pts = [start]
    for i in range(1, segments):
        base = start.lerp(end, i / segments)
        pts.append(base + perp * random.uniform(-jitter, jitter))
    pts.append(end)
    glow_polyline(screen, pts, color, width=3)
    if len(pts) > 3 and branches > 0 and diff.length_squared() > 0:
        ahead = diff.normalize()
        for _ in range(branches):
            idx = random.randint(1, len(pts) - 2)
            mid = pts[idx] + perp * random.uniform(-1, 1) * jitter + ahead * jitter * 0.5
            fork_end = mid + perp * random.uniform(-1, 1) * jitter * 1.4 + ahead * jitter
            glow_polyline(screen, [pts[idx], mid, fork_end], color, width=2, intensity=0.75)


def draw_fan(screen, origin, base_angle, spread, reach, color, fill_alpha=90, segments=10):
    """A fan/cone-shaped AoE wedge, like a hand fan opening from `origin`
    toward `base_angle`, spanning `spread` radians out to `reach`: a
    translucent fill that brightens toward its rim, with a glowing leading
    edge, so the area reads clearly without a flat opaque slab over it."""
    if reach < 2:
        return
    half = spread / 2
    segments = max(segments, int(math.degrees(spread) / 6))

    def arc(r):
        return [pygame.Vector2(math.cos(base_angle - half + spread * (i / segments)),
                               math.sin(base_angle - half + spread * (i / segments))) * r
                for i in range(segments + 1)]

    rim = arc(reach)
    pts = [pygame.Vector2(0, 0)] + rim
    pad = 4
    min_x = min(p.x for p in pts) - pad
    min_y = min(p.y for p in pts) - pad
    w = max(1, int(max(p.x for p in pts) + pad - min_x))
    h = max(1, int(max(p.y for p in pts) + pad - min_y))
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    peak = max(0, min(255, fill_alpha)) * 0.75
    bands = 6
    for k in range(bands, 0, -1):
        frac = k / bands
        wedge = [(-min_x, -min_y)] + [(p.x - min_x, p.y - min_y) for p in arc(reach * frac)]
        pygame.draw.polygon(surf, (*color[:3], int(peak * (0.2 + 0.8 * frac ** 2))), wedge)
    for edge in (rim[0], rim[-1]):
        pygame.draw.aaline(surf, (*glow_lighten(color, 0.3), int(min(255, peak * 1.6))),
                           (-min_x, -min_y), (edge.x - min_x, edge.y - min_y))
    screen.blit(surf, (origin.x + min_x, origin.y + min_y))
    glow_polyline(screen, [origin + p for p in rim], color, width=3, intensity=min(1.0, fill_alpha / 90))


def draw_slash_arc(screen, center, direction, radius=40, spread_deg=110, color=(255, 255, 255),
                    width=5, fade=1.0, segments=12):
    """A curved glowing arc sweeping around `center`, facing `direction`,
    thick in the middle and tapering to points at both tips — the "real"
    slash arc from a weapon swing, distinct from the straight cut mark
    `draw_slash` draws."""
    if fade <= 0 or radius < 2:
        return
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    base_angle = math.atan2(d.y, d.x)
    half = math.radians(spread_deg) / 2
    r = radius * fade
    outer, inner = [], []
    for i in range(segments + 1):
        u = i / segments
        a = base_angle - half + math.radians(spread_deg) * u
        v = pygame.Vector2(math.cos(a), math.sin(a))
        thick = width * 1.2 * math.sin(math.pi * u)
        outer.append(center + v * (r + thick * 0.5))
        inner.append(center + v * (r - thick * 0.5))
    mid = [(o + q) / 2 for o, q in zip(outer, inner)]
    glow_polyline(screen, mid, color, width=max(1, int(width * 0.6)), intensity=0.8 * fade)
    blade = outer + inner[::-1]
    pygame.draw.polygon(screen, glow_lighten(color, 0.5), blade)
    pygame.draw.aalines(screen, glow_lighten(color, 0.85), True, blade)


# The painted slash flipbook's own baked-in facing (assets/animation/slash/
# slash-1..4.png are drawn running top-left -> bottom-right) — draw_slash_fx
# rotates each frame by however far `direction` sits from this default.
_SLASH_FX_DEFAULT_DIR = pygame.Vector2(1, 1)


def draw_slash_fx(screen, center, direction, t, size=100, fade_start=0.75, color=None):
    """The painted 4-frame slash flipbook (assets/animation/slash/) swept
    across `center`, facing `direction` — a richer alternative to the
    vector-drawn draw_slash_arc/draw_slash for a fighter's own melee cut.
    `t` is the caller's own impact-phase progress (0..1, see
    battle.phase_t): picks which of the 4 frames is showing (so the cut
    reads as one continuous strike, not a static image held for the whole
    phase) and drives the fade-out over the final fade_start..1 stretch.
    `color` recolors the art to the attacker's own signature color (see
    tinted_frames); None keeps the painted orange."""
    frames = tinted_frames(load_animation_frames("animation/slash", "slash", 4, size), color)
    frame = frames[min(3, int(t * 4))]
    if direction.length_squared() != 0:
        default_angle = math.degrees(math.atan2(-_SLASH_FX_DEFAULT_DIR.y, _SLASH_FX_DEFAULT_DIR.x))
        angle = math.degrees(math.atan2(-direction.y, direction.x)) - default_angle
        frame = pygame.transform.rotate(frame, angle)
    if t > fade_start:
        frame = frame.copy()
        frame.set_alpha(int(255 * max(0.0, 1 - (t - fade_start) / (1 - fade_start))))
    screen.blit(frame, frame.get_rect(center=(round(center.x), round(center.y))))


_CRESCENT_CACHE = {}

#: Crescent geometry shared by _crescent_image, draw_cleave_wave and
#: crescent_edge_point (so embers spawned on the blade line up with it):
#: arc radius and angular span, as fractions of the crescent's tip-to-tip
#: `size`.
CRESCENT_RADIUS = 0.5
CRESCENT_SPAN_DEG = 165


def _crescent_image(size, color):
    """One glowing half-moon blade (convex side facing +x, like ")"), baked
    onto a square surface centered on the crescent's own arc center so a
    rotate keeps that center fixed. `size` is the crescent's tip-to-tip
    height; cached per (size, color) since draw_cleave_wave rebuilds every
    frame."""
    key = (size, color)
    img = _CRESCENT_CACHE.get(key)
    if img is not None:
        return img
    radius = size * CRESCENT_RADIUS
    thick = size * 0.2
    span = math.radians(CRESCENT_SPAN_DEG)
    pad = int(thick * 0.5) + 6
    dim = int(radius * 2) + pad * 2
    c = pygame.Vector2(dim / 2, dim / 2)
    img = pygame.Surface((dim, dim), pygame.SRCALPHA)

    def crescent_pts(thickness, inset=0.0, segments=32):
        outer, inner = [], []
        for i in range(segments + 1):
            s = i / segments * 2 - 1  # -1..1 along the blade
            a = s * span / 2
            normal = pygame.Vector2(math.cos(a), math.sin(a))
            taper = math.cos(s * math.pi / 2) ** 0.8  # fat middle, sharp tips
            outer.append(normal * (radius - inset) + c)
            inner.append(normal * (radius - inset - thickness * taper) + c)
        return outer + inner[::-1]

    light = tuple(min(255, int(ch * 0.35 + 255 * 0.65)) for ch in color)
    pygame.draw.polygon(img, (*color, 45), crescent_pts(thick * 1.7, inset=-thick * 0.45))
    pygame.draw.polygon(img, (*color, 110), crescent_pts(thick * 1.2, inset=-thick * 0.15))
    pygame.draw.polygon(img, (*color, 245), crescent_pts(thick * 0.9))
    pygame.draw.polygon(img, (*light, 255), crescent_pts(thick * 0.35, inset=thick * 0.08))
    _CRESCENT_CACHE[key] = img
    return img


def crescent_edge_point(blade, direction, size, s):
    """A point on a crescent's outer edge whose blade midpoint sits at
    `blade` facing `direction` — `s` runs -1..1 tip to tip. For spawning
    particles along a draw_cleave_wave crescent."""
    d = direction.normalize()
    radius = size * CRESCENT_RADIUS
    arc_center = blade - d * radius
    return arc_center + d.rotate(s * CRESCENT_SPAN_DEG / 2) * radius


def cleave_wave_blade(origin, direction, t, size, travel, lag=0.0):
    """Where draw_cleave_wave's crescent (or one of its ghosts, `lag`
    behind) sits at progress `t`: (blade midpoint, crescent size), or None
    if that ghost hasn't launched yet. The lead crescent eases out `travel`
    pixels while swelling from 70% to full `size`."""
    tk = t - lag
    if tk < 0:
        return None
    ease = 1 - (1 - min(1.0, tk)) ** 2
    d = direction.normalize()
    return origin + d * (travel * ease), size * (0.7 + 0.3 * ease)


def draw_cleave_wave(screen, origin, direction, t, color=RAIJU_CYAN, size=90, travel=90,
                     ghosts=2, ghost_lag=0.16, fade_start=0.65):
    """A crescent shockwave pushed out from `origin` along `direction`,
    leaving shrinking, fading afterimages behind it — the cleave-style cut
    for a wide melee swing (Reckless Cleave), as opposed to the single
    painted cut draw_slash_fx stamps on the blade itself. `t` is the wave's
    own progress (0..1, see BattleAnimation.cleave_waves): the lead
    crescent follows cleave_wave_blade, each ghost replays that same path
    `ghost_lag` behind it, and everything fades over the final
    fade_start..1 stretch."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    angle = math.degrees(math.atan2(-d.y, d.x))
    fade = 1.0 if t <= fade_start else max(0.0, 1 - (t - fade_start) / (1 - fade_start))
    if fade <= 0:
        return

    # Oldest ghost first so the bright lead crescent paints over its trail.
    for k in range(ghosts, -1, -1):
        placed = cleave_wave_blade(origin, d, t, size, travel, lag=k * ghost_lag)
        if placed is None:
            continue
        blade, crescent_size = placed
        alpha = int(255 * fade * ((1 - k / (ghosts + 1)) * 0.5 if k else 1.0))
        if alpha <= 0:
            continue
        crescent_size = max(8, int(round(crescent_size * (1 - 0.1 * k) / 4)) * 4)  # quantized for the cache
        img = pygame.transform.rotate(_crescent_image(crescent_size, tuple(color[:3])), angle)
        img.set_alpha(alpha)
        # The image is centered on the arc's own center, which sits one
        # radius behind the blade.
        arc_center = blade - d * (crescent_size * CRESCENT_RADIUS)
        screen.blit(img, img.get_rect(center=(round(arc_center.x), round(arc_center.y))))


def draw_hold_fx(screen, center, ratio, size=70, color=None):
    """The painted 7-frame charge-up flipbook (assets/animation/hold/
    hold-1..7.png are drawn escalating from a faint spark to a bright
    starburst) — picks the frame for `ratio` (0..1, how far a hold-and-
    release attack is charged) so the charge-up reads as one continuous
    buildup instead of a fixed vector ring/starburst repeating unchanged
    the whole time it's held. No rotation: unlike draw_slash_fx's cut mark,
    the flipbook's burst shape has no baked-in facing to correct for.
    `color` recolors it like draw_slash_fx."""
    frames = tinted_frames(load_animation_frames("animation/hold", "hold", 7, size), color)
    frame = frames[min(6, int(ratio * 7))]
    screen.blit(frame, frame.get_rect(center=(round(center.x), round(center.y))))


def draw_impact_stamp(screen, pos, frames, t, fade_start=0.6):
    """One frame of a generic one-shot painted flourish — assets/animation/
    range/ (a single-frame flash marking where a projectile actually landed)
    or assets/animation/crit/ (a 3-frame escalating burst for a critical
    hit) — at `pos`, picked by progress `t` (0..1) through its own short
    lifetime and faded out over the final fade_start..1 stretch. Unlike
    draw_slash_fx/draw_hold_fx, `t` here tracks real elapsed time
    (BattleAnimation.impact_stamps/update_impact_stamps), not any one
    attack's own phase_t — a stamp is a standalone flourish, not tied to a
    specific character's own weapon animation."""
    frame = frames[min(len(frames) - 1, int(t * len(frames)))]
    if t > fade_start:
        frame = frame.copy()
        frame.set_alpha(int(255 * max(0.0, 1 - (t - fade_start) / (1 - fade_start))))
    screen.blit(frame, frame.get_rect(center=(round(pos.x), round(pos.y))))


def build_vignette(width, height, band=70, max_alpha=90):
    """A static darkened-edge frame — nested rect outlines fading from
    `max_alpha` at the border to fully transparent `band` pixels in. Built
    once and cached by the caller (draw() only needs to blit it per frame)."""
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    for i in range(band):
        alpha = int(max_alpha * (1 - i / band) ** 2)
        if alpha <= 0:
            continue
        pygame.draw.rect(surf, (0, 0, 0, alpha), (i, i, width - i * 2, height - i * 2), width=1)
    return surf


def tint_flash(img, color, alpha):
    """Return a copy of `img` additively tinted toward `color` by `alpha`
    (0-255) — the classic damage-flash trick: BLEND_RGB_ADD only brightens
    existing pixels and leaves the alpha channel untouched, so a sprite's
    silhouette and transparency survive the flash intact."""
    if alpha <= 0:
        return img
    flashed = img.copy()
    amount = tuple(int(c * (alpha / 255)) for c in color)
    flashed.fill(amount, special_flags=pygame.BLEND_RGB_ADD)
    return flashed


def blend_flash(img, color, alpha):
    """Return a copy of `img` mixed toward `color` by `alpha` (0-255),
    alpha channel untouched: a true blend rather than tint_flash's add, so
    an already-bright sprite takes on the flash color instead of blowing
    out to flat white."""
    if alpha <= 0:
        return img
    k = max(0.0, min(1.0, alpha / 255))
    flashed = img.copy()
    keep = int(255 * (1 - k))
    flashed.fill((keep, keep, keep), special_flags=pygame.BLEND_RGB_MULT)
    flashed.fill(tuple(int(c * k) for c in color[:3]), special_flags=pygame.BLEND_RGB_ADD)
    return flashed


def colorize_sprite(img, color):
    """Return a copy of painted effect art `img` recolored to `color` with a
    gradient map: its midtones take `color` and its brightest pixels stay
    white-hot, alpha untouched — so one painted asset (the cyan bolt, the
    orange slash/crit/hold flipbooks) can glow in any fighter's own color
    and still keep a bright core. Built from whole-surface blend ops, not a
    per-pixel loop, so it is cheap enough to do on first use."""
    gray = pygame.transform.grayscale(img)
    result = gray.copy()
    result.fill((*color[:3], 255), special_flags=pygame.BLEND_RGBA_MULT)
    boost = result.copy()
    boost.fill((140, 140, 140, 255), special_flags=pygame.BLEND_RGBA_MULT)
    result.blit(boost, (0, 0), special_flags=pygame.BLEND_RGB_ADD)  # color x ~1.55
    hot = gray.copy()
    hot.fill((190, 190, 190, 0), special_flags=pygame.BLEND_RGB_SUB)
    for _ in range(2):  # (gray - 190) x 4: only the very core reaches white
        hot.blit(hot, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    result.blit(hot, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    return result


_TINTED_FRAMES_CACHE = {}


def tinted_frames(frames, color):
    """`frames` (a cached flipbook list) run through colorize_sprite for
    `color`, cached per (flipbook, color); None returns them untouched."""
    if color is None:
        return frames
    key = (id(frames), tuple(color[:3]))
    tinted = _TINTED_FRAMES_CACHE.get(key)
    if tinted is None:
        tinted = [colorize_sprite(f, tuple(color[:3])) for f in frames]
        _TINTED_FRAMES_CACHE[key] = tinted
    return tinted


def draw_shockwave(screen, pos, radius, color, width=3, bg_color=(10, 10, 12), fade=1.0):
    """A single glowing ring of an expanding shockwave, dimming as it dies
    out — the caller (BattleAnimation.rings) owns the radius/fade
    timeline, this just draws one frame of it. `bg_color` is kept for
    callers; additive light fades to the floor on its own."""
    if radius <= 1 or fade <= 0:
        return
    glow_ring(screen, pos, radius, color, width=max(1, width), intensity=fade)


# How each status shows on the fighter itself. Only a few "state" statuses
# earn a full ring, capped at _MAX_AURAS so a stacked buff bundle (Berserker
# Rage's five statuses, say) never turns into a pile of circles. Hard CC
# gets its own classic cue (stars over the head, Zs, nails at the feet),
# DoTs are particles, and every plain stat modifier is a small pip in an
# arc under the avatar.
#
# _AURA_ICON is in priority order: when more than _MAX_AURAS are active the
# first ones win and the rest drop down to pips.
_AURA_ICON = {
    "invulnerable": {"ring": "solid", "shape": "star", "dots": 2, "spin": 1, "speed": 0.0020},
    "shield": {"ring": "double", "shape": "hexagon", "dots": 3, "spin": 1, "speed": 0.0012},
    "frozen": {"ring": "spiked", "shape": "diamond", "dots": 0, "spin": 1, "speed": 0.0},
    "reflect": {"ring": "dashed", "shape": "square", "dots": 2, "spin": -1, "speed": 0.0015},
    "death_ultimate": {"ring": "notched", "shape": "triangle", "dots": 3, "spin": -1, "speed": 0.0018},
    "bh_lethal_mark": {"ring": "notched", "shape": "cross", "dots": 0, "spin": 1, "speed": 0.0},
}
_MAX_AURAS = 2
_PARTICLE_COLOR = {"bleed": RED, "poison": POISON_COLOR, "burn": STATUS_RING_COLOR["burn"]}
_CC_COLOR = {"stunned": STUN_COLOR, "asleep": STATUS_RING_COLOR["asleep"], "rooted": NAIL_SILVER}
# Pip-only statuses with no RING_COLOR entry (see status_library's note).
_PIP_EXTRA = {"static": (RAIJU_CYAN, "diamond"), "spin_charge": (NAIL_GLOW_BLUE, "triangle")}
# Buff pips sort ahead of debuff pips so the two groups read apart.
_BUFFS = frozenset({
    "regen", "damage_reduction", "attack_up", "attack_speed_up", "move_speed_up", "lifesteal",
    "invulnerable", "reflect", "vanished", "armor_up", "shield", "spin_charge", "death_ultimate",
})

# (id(statuses), name) -> get_ticks() when that status first showed, so a
# fresh one pops in instead of just blinking on. Keyed by the dict's id
# since draw_status_rings has no other per-owner state to hang it on.
_RING_BORN = {}
_RING_POP_MS = 260


def _brighten(color, amt):
    return _lerp_color(color, WHITE, amt)


def _draw_z(surf, cx, cy, s, color):
    pygame.draw.lines(surf, color, False, [(cx - s, cy - s), (cx + s, cy - s), (cx - s, cy + s), (cx + s, cy + s)], 2)


def draw_status_rings(screen, pos, statuses, font=None, alpha_mult=1.0, exclude=(), radius=AVATAR_R):
    """Every status effect a `statuses` dict can carry, drawn on the fighter
    — shared between render.py's draw_fighter (a real fighter) and
    draw_clone (Vampire's decoy)/core/clone_army.py's CloneArmy.draw
    (Phantom Lancer's illusions), so a clone carrying poison/bleed/etc.
    reads it just as visibly as a real fighter would.

    Four treatments, so a heavily buffed fighter stays readable instead of
    wearing one ring per status (see _AURA_ICON's note above):
      - aura: a glowing ring in its own style, at most _MAX_AURAS of them;
      - CC: stunned stars over the head, asleep Zs, rooted nails at the feet;
      - DoT: bleed drips, poison bubbles, burn embers;
      - pip: a small badge per remaining status in an arc under the avatar,
        its glyph from status_library.STATUS_ICON (unique per status), or
        its stack count for Static/Spin Charge when `font` is given.
    Everything pops in briefly on first appearance. Drawn on a small alpha
    overlay so glow and `alpha_mult` (Vanished fade) are real translucency.

    `radius` is the caller's own avatar circle, so a dummy's bigger sprite
    or a shrunk clone gets everything sized to match. `exclude` skips names
    a caller already draws its own bespoke look for (draw_clone's pulsing
    "taunt" ring, say)."""
    owner = id(statuses)
    for key in [k for k in _RING_BORN if k[0] == owner and k[1] not in statuses]:
        del _RING_BORN[key]
    if alpha_mult <= 0:
        return

    active = [n for n in statuses if n not in exclude]
    if not active:
        return
    auras = [n for n in _AURA_ICON if n in active][:_MAX_AURAS]
    handled = set(auras) | set(_PARTICLE_COLOR) | set(_CC_COLOR)
    pip_pool = [n for n in (*_PIP_EXTRA, *STATUS_RING_COLOR) if n in active and n not in handled]
    pips = sorted(pip_pool, key=lambda n: n not in _BUFFS)
    drawn = auras + pips + [n for n in active if n in _PARTICLE_COLOR or n in _CC_COLOR]
    if not drawn:
        return

    now = pygame.time.get_ticks()
    x, y = int(pos.x), int(pos.y)
    scale = max(0.7, min(1.4, radius / AVATAR_R))
    half = int(radius + 56 * scale)
    surf = pygame.Surface((half * 2, half * 2), pygame.SRCALPHA)
    c0 = (half, half)

    def rgba(color, a):
        return (color[0], color[1], color[2], max(0, min(255, round(a * alpha_mult))))

    def pop(name):
        born = _RING_BORN.setdefault((owner, name), now)
        p = min(1.0, (now - born) / _RING_POP_MS)
        return p, 1 - (1 - p) ** 3

    # ---- DoT particles (behind everything else) ----
    for n_i, name in enumerate(n for n in active if n in _PARTICLE_COLOR):
        color = _PARTICLE_COLOR[name]
        _, ease = pop(name)
        count = 5
        for i in range(count):
            seed = i * 2.399 + n_i * 1.7
            t = (now * 0.0011 + i / count + n_i * 0.37) % 1.0
            px = half + math.cos(seed) * radius * 0.85
            if name == "bleed":  # drips falling off the body
                py = half + math.sin(seed) * radius * 0.4 + t * t * radius * 0.9
                pygame.draw.circle(surf, rgba(color, 230 * (1 - t) * ease), (px, py), 3 * scale)
            elif name == "poison":  # bubbles rising with a wobble
                px += math.sin(now * 0.006 + seed) * 3
                py = half + radius * 0.5 - t * radius * 1.3
                pygame.draw.circle(surf, rgba(_brighten(color, 0.3), 220 * (1 - t) * ease), (px, py), (2.5 + 2.5 * t) * scale, 2)
            else:  # burn embers rising and shrinking
                px += math.sin(now * 0.004 + seed * 3) * 4
                py = half + radius * 0.6 - t * radius * 1.5
                ember = _lerp_color(color, (255, 230, 120), 1 - t)
                pygame.draw.circle(surf, rgba(ember, 240 * (1 - t) * ease), (px, py), (1.5 + 3 * (1 - t)) * scale)

    # ---- auras: glow pass, then core pass ----
    aura_layers = []
    for k, name in enumerate(auras):
        p, ease = pop(name)
        color = SHIELD_COLOR if name == "shield" else STATUS_RING_COLOR.get(name, WHITE)
        breath = 0.5 + 0.5 * math.sin(now * 0.004 + k * 1.3)
        r = (radius + 10 + 7 * k) * (1 + 0.4 * (1 - ease)) + breath
        aura_layers.append((name, color, r, p, ease, breath))
    for name, color, r, p, ease, breath in aura_layers:
        pygame.draw.circle(surf, rgba(color, (30 + 30 * breath) * ease), c0, r + 3, width=6)
        if p < 1.0:
            pygame.draw.circle(surf, rgba(_brighten(color, 0.6), 200 * (1 - p)), c0, r + 14 * p, width=2)
    for name, color, r, p, ease, breath in aura_layers:
        icon = _AURA_ICON[name]
        core = rgba(_brighten(color, 0.15 * breath), (180 + 75 * breath) * ease)
        _draw_ring_style(surf, half, half, r, core, icon["ring"], width=2, rot=now * 0.0006 * icon["spin"])
        if icon["dots"]:
            base_angle = now * icon["speed"] * icon["spin"]
            for i in range(icon["dots"]):
                ang = base_angle + i * 2 * math.pi / icon["dots"]
                c = (half + math.cos(ang) * r, half + math.sin(ang) * r)
                pygame.draw.circle(surf, rgba(color, 80 * ease), c, 5)
                _draw_node_shape(surf, icon["shape"], c, 3, rgba(_brighten(color, 0.4), 255 * ease))

    # ---- hard CC cues ----
    if "stunned" in active:
        _, ease = pop("stunned")
        hy = half - radius * 1.05
        for i in range(3):
            ang = now * 0.006 + i * 2 * math.pi / 3
            front = math.sin(ang) > 0
            sx = half + math.cos(ang) * radius * 0.65
            sy = hy + math.sin(ang) * radius * 0.2
            col = _brighten(STUN_COLOR, 0.45 if front else 0.0)
            _draw_node_shape(surf, "star", (sx, sy), (5 if front else 3.5) * scale * ease, rgba(col, 255 if front else 170))
    if "asleep" in active:
        _, ease = pop("asleep")
        col = _brighten(_CC_COLOR["asleep"], 0.5)
        for i in range(3):
            t = (now * 0.0007 + i / 3) % 1.0
            zx = half + radius * 0.45 + t * 12 * scale + math.sin(t * 6) * 2
            zy = half - radius * 0.8 - t * 22 * scale
            _draw_z(surf, zx, zy, (2 + 3 * t) * scale, rgba(col, 255 * math.sin(t * math.pi) * ease))
    if "rooted" in active:
        _, ease = pop("rooted")
        col = rgba(_CC_COLOR["rooted"], 240 * ease)
        for k in range(5):
            ang = math.pi / 2 + (k - 2) * 0.32
            inner = radius - 2
            outer = radius + (6 + (4 if k % 2 == 0 else 0)) * scale * ease
            base = (half + math.cos(ang) * inner, half + math.sin(ang) * inner)
            tip = (half + math.cos(ang) * outer, half + math.sin(ang) * outer)
            pygame.draw.line(surf, col, base, tip, 3)

    # ---- pips: arc under the avatar, second arc if it overflows ----
    per_arc = 7
    for idx, name in enumerate(pips):
        row, col_i = divmod(idx, per_arc)
        n_row = min(per_arc, len(pips) - row * per_arc)
        pr = radius + (16 + 17 * row) * scale
        ang = math.pi / 2 + (col_i - (n_row - 1) / 2) * (17 * scale / pr)
        cx, cy = half + math.cos(ang) * pr, half + math.sin(ang) * pr
        p, ease = pop(name)
        if name in _PIP_EXTRA:
            color, shape = _PIP_EXTRA[name]
        else:
            color, shape = STATUS_RING_COLOR[name], STATUS_ICON.get(name, {}).get("shape", "circle")
        pr_r = 7.5 * scale * (0.5 + 0.5 * ease)
        pygame.draw.circle(surf, rgba((16, 18, 26), 225 * ease), (cx, cy), pr_r)
        pygame.draw.circle(surf, rgba(color, 255 * ease), (cx, cy), pr_r, width=2 if name in _BUFFS else 1)
        if p < 1.0:
            pygame.draw.circle(surf, rgba(_brighten(color, 0.6), 200 * (1 - p)), (cx, cy), pr_r + 8 * p, width=2)
        stacks = statuses[name].get("stacks", 0) if isinstance(statuses[name], dict) else 0
        if stacks > 0 and font is not None:
            txt = font.render(str(stacks), True, _brighten(color, 0.3))
            txt.set_alpha(round(255 * alpha_mult * ease))
            surf.blit(txt, (cx - txt.get_width() / 2, cy - txt.get_height() / 2))
        else:
            _draw_node_shape(surf, shape, (cx, cy), 3.5 * scale * ease, rgba(_brighten(color, 0.35), 255 * ease))

    screen.blit(surf, (x - half, y - half))
