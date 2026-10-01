"""Soft additive light primitives shared by particles.py, effects.py and
render.py: cached radial glow sprites plus glowing strokes and rings, all
stacked with BLEND_RGBA_ADD so overlapping light brightens toward white
instead of flat opaque shapes painting over each other. Additive blending
adds RGB straight through (it ignores alpha), so every sprite here is
built premultiplied: its RGB already carries the falloff.

Nothing here reads battle state; it only draws.
"""

import pygame

#: Brightness steps a glow's intensity is quantized to, so the sprite
#: cache stays small while particles fade out smoothly enough.
LEVELS = 12
_DOT_CACHE = {}
_DOT_CACHE_MAX = 4000


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def lighten(color, t):
    return mix(color, (255, 255, 255), t)


def darken(color, t):
    return mix(color, (0, 0, 0), t)


def scale(color, k):
    return tuple(max(0, min(255, int(c * k))) for c in color[:3])


def _lit(color):
    """`color` with an alpha matching its brightness, for scratch surfaces
    added onto the scene: a dim halo pixel must stay mostly transparent,
    or it lands on an empty (transparent) patch of the scene as an opaque
    near-black pixel darker than the arena floor."""
    c = tuple(max(0, min(255, int(v))) for v in color[:3])
    return (*c, max(c))


def _quantize(color):
    return tuple(int(c) >> 3 << 3 for c in color[:3])


def glow_dot(radius, color, intensity=1.0):
    """A soft round glow `radius` px across its half-width, `color` at its
    center easing to nothing at the rim (quadratic falloff), premultiplied
    and scaled by `intensity` (0..1). Cached per (radius, color, level)."""
    r = max(1, int(round(radius)))
    level = max(0, min(LEVELS, int(round(intensity * LEVELS))))
    key = (r, _quantize(color), level)
    surf = _DOT_CACHE.get(key)
    if surf is not None:
        return surf
    if len(_DOT_CACHE) > _DOT_CACHE_MAX:
        _DOT_CACHE.clear()
    k = level / LEVELS
    base = _quantize(color)
    surf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
    c = (r + 1, r + 1)
    steps = max(3, r)
    for i in range(steps, 0, -1):
        f = (1 - (i - 1) / steps) ** 2 * k
        pygame.draw.circle(surf, _lit(scale(base, f)), c, r * i / steps)
    _DOT_CACHE[key] = surf
    return surf


def add_dot(screen, pos, radius, color, intensity=1.0):
    """Stack one glow_dot onto `screen` centered on `pos`."""
    if intensity <= 0 or radius < 0.5:
        return
    dot = glow_dot(radius, color, intensity)
    half = dot.get_width() / 2
    screen.blit(dot, (round(pos[0] - half), round(pos[1] - half)), special_flags=pygame.BLEND_RGBA_ADD)


def glow_polyline(screen, pts, color, width=3, intensity=1.0, closed=False):
    """A glowing stroke through `pts`: a wide dim halo, the colored body
    and a thin near-white core, built on a scratch surface and added onto
    `screen` so it reads as light rather than paint."""
    if len(pts) < 2 or intensity <= 0:
        return
    pad = int(width * 2.5) + 3
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    left, top = int(min(xs)) - pad, int(min(ys)) - pad
    w, h = int(max(xs)) - left + pad + 1, int(max(ys)) - top + pad + 1
    if w <= 0 or h <= 0 or w * h > 900 * 900:
        return
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    local = [(p[0] - left, p[1] - top) for p in pts]
    body = scale(color, intensity)
    for wmul, k, col in ((3.2, 0.22, body), (1.9, 0.5, body), (1.0, 1.0, body),
                         (0.45, 1.0, scale(lighten(color, 0.7), intensity))):
        lw = max(1, int(round(width * wmul)))
        c = _lit(scale(col, k))
        pygame.draw.lines(surf, c, closed, local, lw)
        if lw > 2:
            # round the joints so thick segments don't leave notches
            for p in local:
                pygame.draw.circle(surf, c, p, lw / 2)
    screen.blit(surf, (left, top), special_flags=pygame.BLEND_RGBA_ADD)


def glow_line(screen, a, b, color, width=3, intensity=1.0):
    glow_polyline(screen, [a, b], color, width, intensity)


def glow_ring(screen, pos, radius, color, width=3, intensity=1.0):
    """A glowing circle outline: soft halo, colored band and a bright
    anti-aliased core line, added onto `screen`."""
    if radius < 1.5 or intensity <= 0:
        return
    pad = int(width * 2.5) + 3
    half = int(radius) + pad
    surf = pygame.Surface((half * 2, half * 2), pygame.SRCALPHA)
    c = (half, half)
    body = scale(color, intensity)
    for wmul, k in ((3.2, 0.2), (1.9, 0.45), (1.0, 1.0)):
        lw = max(1, int(round(width * wmul)))
        pygame.draw.circle(surf, _lit(scale(body, k)), c, radius + lw / 2, width=lw)
    pygame.draw.aacircle(surf, _lit(scale(lighten(color, 0.7), intensity)), c, radius + width / 2,
                         width=max(1, int(width * 0.45)))
    screen.blit(surf, (round(pos[0]) - half, round(pos[1]) - half), special_flags=pygame.BLEND_RGBA_ADD)
