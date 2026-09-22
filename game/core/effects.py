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


def _draw_ring_style(screen, x, y, radius, color, style, width=2):
    """The status ring itself, in one of a few distinct outline treatments
    so e.g. a dashed ring never gets mistaken for a plain solid one even
    before its orbiting nodes are counted."""
    rect = pygame.Rect(x - radius, y - radius, radius * 2, radius * 2)
    if style == "solid":
        pygame.draw.circle(screen, color, (x, y), radius, width=width)
    elif style == "double":
        pygame.draw.circle(screen, color, (x, y), radius, width=1)
        pygame.draw.circle(screen, color, (x, y), max(1, radius - 4), width=1)
    elif style == "dashed":
        n = 10
        for k in range(n):
            a0 = 2 * math.pi * k / n
            a1 = a0 + (2 * math.pi / n) * 0.5
            pygame.draw.arc(screen, color, rect, a0, a1, width)
    elif style == "notched":
        n = 3
        for k in range(n):
            a0 = 2 * math.pi * k / n
            a1 = a0 + (2 * math.pi / n) * 0.75
            pygame.draw.arc(screen, color, rect, a0, a1, width)
    elif style == "spiked":
        pygame.draw.circle(screen, color, (x, y), radius, width=1)
        n = 8
        for k in range(n):
            ang = 2 * math.pi * k / n
            inner = (x + math.cos(ang) * radius, y + math.sin(ang) * radius)
            outer = (x + math.cos(ang) * (radius + 5), y + math.sin(ang) * (radius + 5))
            pygame.draw.line(screen, color, inner, outer, 2)


def draw_icon_glyph(screen, shape, center, r, color):
    """Public entry point to the small node-shape catalog above (see
    _draw_node_shape) for a caller that just wants one static glyph — e.g.
    hud.py's compact per-status/per-ability icons — without the full
    ring-plus-orbiting-dots treatment draw_status_rings puts around a
    fighter."""
    _draw_node_shape(screen, shape, center, r, color)


def _draw_status_icon(screen, x, y, radius, color, icon):
    """One status's full icon: its own ring style plus its own spinning set
    of orbiting nodes — see status_library.STATUS_ICON for where `icon`
    (shape/ring/dots/spin/speed) comes from and why it's guaranteed unique
    per status name."""
    _draw_ring_style(screen, x, y, radius, color, icon["ring"])
    base_angle = pygame.time.get_ticks() * icon["speed"] * icon["spin"]
    step = 2 * math.pi / icon["dots"]
    for i in range(icon["dots"]):
        ang = base_angle + i * step
        _draw_node_shape(screen, icon["shape"], (x + math.cos(ang) * radius, y + math.sin(ang) * radius), 3, color)


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
    """A quick radiating flash at the moment of impact — a dense ring of
    long and short rays around a bright flash core, for a punchier pop
    than a handful of plain spokes."""
    if fade <= 0:
        return
    pygame.draw.circle(screen, WHITE, (int(pos.x), int(pos.y)), max(1, int(size * 0.3 * fade)))
    for i in range(12):
        ang = i * (math.pi / 6) + random.uniform(-0.1, 0.1)
        length = size * fade * (1.0 if i % 2 == 0 else 0.55)
        x2 = pos.x + math.cos(ang) * length
        y2 = pos.y + math.sin(ang) * length
        width = 3 if i % 2 == 0 else 2
        pygame.draw.line(screen, color, pos, (x2, y2), width)


def draw_expanding_ring(screen, pos, radius, color, width=2):
    if radius > 1:
        pygame.draw.circle(screen, color, (int(pos.x), int(pos.y)), int(radius), width=width)
        inner = radius * 0.55
        if inner > 1:
            pygame.draw.circle(screen, WHITE, (int(pos.x), int(pos.y)), int(inner), width=max(1, width - 1))


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
    cut instead of a swung weapon prop."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    perp = pygame.Vector2(-d.y, d.x)
    p1 = center - perp * length / 2 - d * length * 0.2
    p2 = center + perp * length / 2 + d * length * 0.2
    glow_color = tuple(int(c * 0.5) for c in color)
    pygame.draw.line(screen, glow_color, p1, p2, width + 4)
    pygame.draw.line(screen, color, p1, p2, width)
    pygame.draw.line(screen, WHITE, p1, p2, max(1, width - 3))


def draw_lightning(screen, start, end, color, segments=6, jitter=10, branches=2):
    """A flickering jagged bolt between two points, with a couple of short
    branching forks kicked off the main path for extra chaos — used for
    Heaven's Verdict, Chain Bolt, Static Field, and Thunder God's Descent."""
    diff = end - start
    perp = pygame.Vector2(-diff.y, diff.x).normalize() if diff.length_squared() > 0 else pygame.Vector2(0, 1)
    pts = [start]
    for i in range(1, segments):
        base = start.lerp(end, i / segments)
        pts.append(base + perp * random.uniform(-jitter, jitter))
    pts.append(end)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, color, pts[i], pts[i + 1], 6)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, color, pts[i], pts[i + 1], 3)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, WHITE, pts[i], pts[i + 1], 2)
    if len(pts) > 3 and branches > 0:
        for _ in range(branches):
            idx = random.randint(1, len(pts) - 2)
            fork_end = pts[idx] + perp * random.uniform(-1, 1) * jitter * 2.2 + diff.normalize() * jitter
            pygame.draw.line(screen, color, pts[idx], fork_end, 3)
            pygame.draw.line(screen, WHITE, pts[idx], fork_end, 1)


def draw_fan(screen, origin, base_angle, spread, reach, color, fill_alpha=90, segments=10):
    """A translucent fan/cone-shaped AoE wedge, like a hand fan opening from
    `origin` toward `base_angle`, spanning `spread` radians out to `reach`."""
    if reach < 2:
        return
    half = spread / 2
    pts = [pygame.Vector2(0, 0)]
    for i in range(segments + 1):
        a = base_angle - half + spread * (i / segments)
        pts.append(pygame.Vector2(math.cos(a), math.sin(a)) * reach)

    pad = 4
    min_x = min(p.x for p in pts) - pad
    max_x = max(p.x for p in pts) + pad
    min_y = min(p.y for p in pts) - pad
    max_y = max(p.y for p in pts) + pad
    w, h = max(1, int(max_x - min_x)), max(1, int(max_y - min_y))

    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    local_pts = [(p.x - min_x, p.y - min_y) for p in pts]
    pygame.draw.polygon(surf, (*color[:3], max(0, fill_alpha)), local_pts)
    pygame.draw.polygon(surf, (*color[:3], min(255, fill_alpha + 130)), local_pts, width=2)
    screen.blit(surf, (origin.x + min_x, origin.y + min_y))


def draw_slash_arc(screen, center, direction, radius=40, spread_deg=110, color=(255, 255, 255),
                    width=5, fade=1.0, segments=12):
    """A layered curved arc (outer/middle/bright core) sweeping around
    `center`, facing `direction` — the "real" slash arc from a weapon swing,
    distinct from the straight cut mark `draw_slash` draws."""
    if fade <= 0 or radius < 2:
        return
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    base_angle = math.atan2(d.y, d.x)
    half = math.radians(spread_deg) / 2
    r = radius * fade
    pts = []
    for i in range(segments + 1):
        a = base_angle - half + math.radians(spread_deg) * (i / segments)
        pts.append(center + pygame.Vector2(math.cos(a), math.sin(a)) * r)

    glow_w = max(1, int(width * 1.8))
    outer_w = max(1, int(width))
    mid_w = max(1, int(width * 0.6))
    core_w = max(1, int(width * 0.3))
    mid_color = tuple(min(255, int(c * 0.6 + 255 * 0.4)) for c in color)
    glow_color = tuple(int(c * 0.5) for c in color)

    for i in range(len(pts) - 1):
        pygame.draw.line(screen, glow_color, pts[i], pts[i + 1], glow_w)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, color, pts[i], pts[i + 1], outer_w)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, mid_color, pts[i], pts[i + 1], mid_w)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, (255, 255, 255), pts[i], pts[i + 1], core_w)
    pygame.draw.circle(screen, WHITE, (int(pts[0].x), int(pts[0].y)), max(2, core_w + 1))
    pygame.draw.circle(screen, WHITE, (int(pts[-1].x), int(pts[-1].y)), max(2, core_w + 1))


# The painted slash flipbook's own baked-in facing (assets/animation/slash/
# slash-1..4.png are drawn running top-left -> bottom-right) — draw_slash_fx
# rotates each frame by however far `direction` sits from this default.
_SLASH_FX_DEFAULT_DIR = pygame.Vector2(1, 1)


def draw_slash_fx(screen, center, direction, t, size=100, fade_start=0.75):
    """The painted 4-frame slash flipbook (assets/animation/slash/) swept
    across `center`, facing `direction` — a richer alternative to the
    vector-drawn draw_slash_arc/draw_slash for a fighter's own melee cut.
    `t` is the caller's own impact-phase progress (0..1, see
    battle.phase_t): picks which of the 4 frames is showing (so the cut
    reads as one continuous strike, not a static image held for the whole
    phase) and drives the fade-out over the final fade_start..1 stretch."""
    frames = load_animation_frames("animation/slash", "slash", 4, size)
    frame = frames[min(3, int(t * 4))]
    if direction.length_squared() != 0:
        default_angle = math.degrees(math.atan2(-_SLASH_FX_DEFAULT_DIR.y, _SLASH_FX_DEFAULT_DIR.x))
        angle = math.degrees(math.atan2(-direction.y, direction.x)) - default_angle
        frame = pygame.transform.rotate(frame, angle)
    if t > fade_start:
        frame = frame.copy()
        frame.set_alpha(int(255 * max(0.0, 1 - (t - fade_start) / (1 - fade_start))))
    screen.blit(frame, frame.get_rect(center=(round(center.x), round(center.y))))


def draw_hold_fx(screen, center, ratio, size=70):
    """The painted 7-frame charge-up flipbook (assets/animation/hold/
    hold-1..7.png are drawn escalating from a faint spark to a bright
    starburst) — picks the frame for `ratio` (0..1, how far a hold-and-
    release attack is charged) so the charge-up reads as one continuous
    buildup instead of a fixed vector ring/starburst repeating unchanged
    the whole time it's held. No rotation: unlike draw_slash_fx's cut mark,
    the flipbook's burst shape has no baked-in facing to correct for."""
    frames = load_animation_frames("animation/hold", "hold", 7, size)
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


def colorize_sprite(img, color):
    """Return a copy of `img` recolored to `color`, preserving its original
    per-pixel alpha and grayscale luminance (desaturate, then tint) — lets
    one painted asset (e.g. the cyan assets/animation/bolt/ flipbook) stand
    in for any ability's own signature color instead of needing separate
    art per color. Used by draw_bolt_fx; each (frame, color) pairing is
    computed once and cached there, not redone per draw call."""
    w, h = img.get_size()
    result = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(w):
        for y in range(h):
            r, g, b, a = img.get_at((x, y))
            if a == 0:
                continue
            lum = (r * 0.299 + g * 0.587 + b * 0.114) / 255
            result.set_at((x, y), (
                min(255, round(color[0] * lum)),
                min(255, round(color[1] * lum)),
                min(255, round(color[2] * lum)),
                a,
            ))
    return result


def draw_shockwave(screen, pos, radius, color, width=3, bg_color=(10, 10, 12), fade=1.0):
    """A single ring of an expanding shockwave, fading toward `bg_color` as
    it dies out — the caller (BattleAnimation.rings) owns the radius/fade
    timeline, this just draws one frame of it."""
    if radius <= 1 or fade <= 0:
        return
    blended = _lerp_color(bg_color, color, fade)
    pygame.draw.circle(screen, blended, (int(pos.x), int(pos.y)), int(radius), width=max(1, width))


def draw_status_rings(screen, pos, statuses, font=None, alpha_mult=1.0, exclude=(), radius=AVATAR_R):
    """Every status-effect ring a `statuses` dict can carry — shared between
    render.py's draw_fighter (a real fighter) and draw_clone (Vampire's own
    decoy)/core/clone_army.py's CloneArmy.draw (Phantom Lancer's illusions),
    so a clone that's now actually carrying poison/bleed/corruption/etc.
    (see core/status_library.py's generic pipeline and the redirected-hit/
    zone-tick fixes that let a clone receive them in the first place) reads
    that just as visibly as a real fighter would, instead of the effect
    being invisible on it. bleed/poison/static/spin_charge/rooted/stunned
    each get their own hand-tuned look (deliberately absent from
    status_library.RING_COLOR, see its own docstring note); everything else
    in RING_COLOR falls back to its own colored ring, drawn in its own ring
    style (solid/dashed/double/spiked/notched) plus its own rotating set of
    orbiting accent nodes in its own node shape (see
    status_library.STATUS_ICON for where each status's (shape, ring) pair
    comes from and why every one of them is unique) — no two statuses ever
    read as the same icon with only the color swapped.

    `radius` is the caller's own avatar circle for whoever `pos` belongs to
    — every offset below is relative to it, not a hardcoded AVATAR_R, so a
    dummy's much bigger sprite or a shrunk clone (Sukuna's Rabbit Escape,
    say) gets status rings sized to match its own actual circle instead of
    every fighter/clone sharing one fixed ring size regardless of how big it
    actually is on screen. Omitted, it defaults to the normal-fighter
    AVATAR_R, same as before this parameter existed.

    `font` is only used for the Static/Spin Charge stack-count pips (omit it
    to skip those pips, e.g. for a clone that has no such font handy);
    `exclude` skips specific names a caller already draws its own bespoke
    ring for (draw_clone's own pulsing "taunt" ring, say)."""
    x, y = int(pos.x), int(pos.y)

    def faded(color):
        return (color[0], color[1], color[2], round(255 * alpha_mult))

    if "shield" not in exclude and "shield" in statuses:
        pulse = 4 + 2 * math.sin(pygame.time.get_ticks() * 0.01)
        pygame.draw.circle(screen, faded(SHIELD_COLOR), (x, y), int(radius + 10 + pulse), width=2)
    if "bleed" not in exclude and "bleed" in statuses:
        pygame.draw.circle(screen, faded(RED), (x, y), radius + 2, width=2)
    if "poison" not in exclude and "poison" in statuses:
        pygame.draw.circle(screen, faded(POISON_COLOR), (x, y), radius + 2, width=2)
    if "static" not in exclude and "static" in statuses:
        stacks = statuses["static"].get("stacks", 0)
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.015)
        pygame.draw.circle(screen, faded(RAIJU_CYAN), (x, y), int(radius + 6 + pulse), width=2)
        if stacks > 0 and font is not None:
            pip_txt = font.render(str(stacks), True, RAIJU_CYAN)
            pip_txt.set_alpha(round(255 * alpha_mult))
            screen.blit(pip_txt, (x - pip_txt.get_width() / 2, y + radius + 6))
    if "spin_charge" not in exclude and "spin_charge" in statuses:
        stacks = statuses["spin_charge"].get("stacks", 0)
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.02)
        pygame.draw.circle(screen, faded(NAIL_GLOW_BLUE), (x, y), int(radius + 6 + pulse), width=2)
        if stacks > 0 and font is not None:
            pip_txt = font.render(str(stacks), True, NAIL_GLOW_BLUE)
            pip_txt.set_alpha(round(255 * alpha_mult))
            screen.blit(pip_txt, (x - pip_txt.get_width() / 2, y + radius + 6))
    if "rooted" not in exclude and "rooted" in statuses:
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.025)
        pygame.draw.circle(screen, faded(NAIL_SILVER), (x, y), int(radius + 8 + pulse), width=3)
        for ang in (0.6, 2.5, 4.4):
            pygame.draw.line(
                screen, faded(NAIL_SILVER),
                (x + math.cos(ang) * (radius + 2), y + math.sin(ang) * (radius + 2)),
                (x + math.cos(ang) * (radius + 16), y + math.sin(ang) * (radius + 16)), 2,
            )
    if "stunned" not in exclude and "stunned" in statuses:
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.03)
        pygame.draw.circle(screen, faded(STUN_COLOR), (x, y), int(radius + 6 + pulse), width=2)
    for name, color in STATUS_RING_COLOR.items():
        if name not in exclude and name in statuses:
            icon = STATUS_ICON.get(name)
            if icon is not None:
                _draw_status_icon(screen, x, y, radius + 5, faded(color), icon)
            else:
                pygame.draw.circle(screen, faded(color), (x, y), radius + 5, width=2)
