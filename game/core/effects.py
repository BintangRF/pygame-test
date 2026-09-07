"""Reusable draw-time effect primitives shared across abilities: simple
shapes (a comet, a claw-cut, a lightning bolt, a fan-shaped AoE wedge, a
flaming arrow), rotated-prop blitting, and two "impact" effects — a genuine
curved slash arc (as opposed to the straight cut mark `draw_slash`) and a
fading expanding shockwave ring. None of these read or mutate battle state;
every caller passes in exactly the position/direction/color it wants drawn.
"""

import math
import random

import pygame

from .asset_loading import load_sprite
from .constants import AVATAR_R, NAIL_SILVER, POISON_COLOR, RAIJU_CYAN, RED, SHIELD_COLOR, STUN_COLOR, WHITE
from .status_library import RING_COLOR as STATUS_RING_COLOR


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


def draw_comet(screen, pos, direction, color, size=1.0):
    """A tapered comet shape with a bright head — used for Blood Bolt."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    perp = pygame.Vector2(-d.y, d.x)
    tip = pos + d * 10 * size
    back_l = pos - d * 16 * size + perp * 6 * size
    back_r = pos - d * 16 * size - perp * 6 * size
    pygame.draw.polygon(screen, color, [tip, back_l, back_r])
    pygame.draw.circle(screen, WHITE, (int(tip.x), int(tip.y)), max(1, int(4 * size)))


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


def draw_fire_arrow(screen, pos, direction, size=1.4):
    """A blazing arrow — Sukuna's Kamino ultimate: an actual arrow silhouette
    (fletched shaft behind a broad head) wrapped in layered flame and
    trailing guttering embers, so it reads clearly as fire in flight instead
    of a generic bolt/orb."""
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    d = direction.normalize()
    perp = pygame.Vector2(-d.y, d.x)

    for i in range(6):
        back = pos - d * (14 + i * 10) * size
        jitter = perp * random.uniform(-5, 5) * size + pygame.Vector2(0, random.uniform(-2, 2))
        r = max(1, (6 - i) * 1.6 * size)
        shade = (255, 210, 70) if i == 0 else ((255, 140, 30) if i < 3 else (200, 60, 20))
        p = back + jitter
        pygame.draw.circle(screen, shade, (int(p.x), int(p.y)), int(r))

    shaft_back = pos - d * 24 * size
    pygame.draw.line(screen, (50, 25, 12), pos - d * 4 * size, shaft_back, max(2, int(3 * size)))
    fl_tip = shaft_back - d * 8 * size
    pygame.draw.polygon(screen, (215, 50, 30), [
        shaft_back + perp * 6 * size, fl_tip, shaft_back - perp * 6 * size,
    ])

    tip = pos + d * 20 * size
    head_l = pos + perp * 7 * size - d * 2 * size
    head_r = pos - perp * 7 * size - d * 2 * size
    pygame.draw.polygon(screen, (255, 150, 40), [tip, head_l, head_r])
    pygame.draw.polygon(screen, (255, 235, 160), [
        pos + d * 12 * size, pos + perp * 2.5 * size, pos - perp * 2.5 * size,
    ])
    pygame.draw.circle(screen, (255, 255, 235), (int(tip.x), int(tip.y)), max(2, int(3 * size)))


_NAIL_BULLET_CACHE = {}


def _nail_bullet_image(diameter):
    """assets/nail-bullet.png, loaded once per size and cached — draw_nail
    below re-blits it every frame a nail is in flight."""
    img = _NAIL_BULLET_CACHE.get(diameter)
    if img is None:
        img = load_sprite("nail-bullet.png", diameter)
        _NAIL_BULLET_CACHE[diameter] = img
    return img


def draw_nail(screen, pos, direction, color, size=1.0):
    """One of Johnny's own fingernails, Stand-charged and fired as a bullet
    (see assets/nail-bullet.png) — a glow-orb oriented to face the way it's
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


def scale_sprite(img, scale_x, scale_y):
    """Return a squash/stretch-scaled copy of `img`, or `img` itself if the
    scale is close enough to 1.0 to skip the resample — cheap no-op for the
    common case where nothing is currently squashing."""
    if abs(scale_x - 1.0) < 0.01 and abs(scale_y - 1.0) < 0.01:
        return img
    w, h = img.get_size()
    new_size = (max(1, round(w * scale_x)), max(1, round(h * scale_y)))
    return pygame.transform.smoothscale(img, new_size)


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


def draw_shockwave(screen, pos, radius, color, width=3, bg_color=(10, 10, 12), fade=1.0):
    """A single ring of an expanding shockwave, fading toward `bg_color` as
    it dies out — the caller (BattleAnimation.rings) owns the radius/fade
    timeline, this just draws one frame of it."""
    if radius <= 1 or fade <= 0:
        return
    blended = _lerp_color(bg_color, color, fade)
    pygame.draw.circle(screen, blended, (int(pos.x), int(pos.y)), int(radius), width=max(1, width))


def draw_status_rings(screen, pos, statuses, font=None, alpha_mult=1.0, exclude=()):
    """Every status-effect ring a `statuses` dict can carry — shared between
    render.py's draw_fighter (a real fighter) and draw_clone (Vampire's own
    decoy)/core/clone_army.py's CloneArmy.draw (Phantom Lancer's illusions),
    so a clone that's now actually carrying poison/bleed/corruption/etc.
    (see core/status_library.py's generic pipeline and the redirected-hit/
    zone-tick fixes that let a clone receive them in the first place) reads
    that just as visibly as a real fighter would, instead of the effect
    being invisible on it. bleed/poison/static/rooted/stunned each get their
    own hand-tuned look (deliberately absent from status_library.RING_COLOR,
    see its own docstring note); everything else in RING_COLOR falls back to
    a single plain ring. `font` is only used for the Static stack-count pip
    (omit it to skip that pip, e.g. for a clone that has no such font handy);
    `exclude` skips specific names a caller already draws its own bespoke
    ring for (draw_clone's own pulsing "taunt" ring, say)."""
    x, y = int(pos.x), int(pos.y)

    def faded(color):
        return (color[0], color[1], color[2], round(255 * alpha_mult))

    if "shield" not in exclude and "shield" in statuses:
        pulse = 4 + 2 * math.sin(pygame.time.get_ticks() * 0.01)
        pygame.draw.circle(screen, faded(SHIELD_COLOR), (x, y), int(AVATAR_R + 10 + pulse), width=2)
    if "bleed" not in exclude and "bleed" in statuses:
        pygame.draw.circle(screen, faded(RED), (x, y), AVATAR_R + 2, width=2)
    if "poison" not in exclude and "poison" in statuses:
        pygame.draw.circle(screen, faded(POISON_COLOR), (x, y), AVATAR_R + 2, width=2)
    if "static" not in exclude and "static" in statuses:
        stacks = statuses["static"].get("stacks", 0)
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.015)
        pygame.draw.circle(screen, faded(RAIJU_CYAN), (x, y), int(AVATAR_R + 6 + pulse), width=2)
        if stacks > 0 and font is not None:
            pip_txt = font.render(str(stacks), True, RAIJU_CYAN)
            pip_txt.set_alpha(round(255 * alpha_mult))
            screen.blit(pip_txt, (x - pip_txt.get_width() / 2, y + AVATAR_R + 6))
    if "rooted" not in exclude and "rooted" in statuses:
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.025)
        pygame.draw.circle(screen, faded(NAIL_SILVER), (x, y), int(AVATAR_R + 8 + pulse), width=3)
        for ang in (0.6, 2.5, 4.4):
            pygame.draw.line(
                screen, faded(NAIL_SILVER),
                (x + math.cos(ang) * (AVATAR_R + 2), y + math.sin(ang) * (AVATAR_R + 2)),
                (x + math.cos(ang) * (AVATAR_R + 16), y + math.sin(ang) * (AVATAR_R + 16)), 2,
            )
    if "stunned" not in exclude and "stunned" in statuses:
        pulse = 2 + 2 * math.sin(pygame.time.get_ticks() * 0.03)
        pygame.draw.circle(screen, faded(STUN_COLOR), (x, y), int(AVATAR_R + 6 + pulse), width=2)
    for name, color in STATUS_RING_COLOR.items():
        if name not in exclude and name in statuses:
            pygame.draw.circle(screen, faded(color), (x, y), AVATAR_R + 5, width=2)
