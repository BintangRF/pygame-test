"""Anime/cartoon-style generic hit effects: thick shapes with dark outlines
and bright cores, rendered supersampled (drawn at SS x size, then
smoothscaled down) so the edges come out anti-aliased instead of pygame's
jagged raw polygons. Everything here returns plain surfaces or draws
straight onto a target; none of it reads battle state.

- build_impact_burst_frames: the glowing hit-flash flipbook a landed hit
  stamps on the defender (ImpactFXMixin.apply_impact), built from Kenney
  Particle Pack textures (CC0, assets/fx/kenney).
- build_scratch_decal: scratch ground marks (add_decal), drawn as glowing
  gouges so they read on the arena's black floor.
- dust_puff_sprite: a tinted Kenney smoke puff for fast-movement dust.
- build_smoke_ring_frames / build_muzzle_frames / draw_cast_circle /
  draw_twirl: more Kenney-textured flourishes (KO smoke ring, gun muzzle
  flash, an ultimate's casting circle, a spin attack's swirl).
- draw_speed_lines: the manga focus lines of the KO slow-motion beat.
"""

import math
import random

import pygame

from .asset_loading import load_sprite

#: Supersampling factor for every baked shape in this module.
SS = 3

OUTLINE = (22, 16, 20)


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _lighten(color, t):
    return _mix(color, (255, 255, 255), t)


def _darken(color, t):
    return _mix(color, (0, 0, 0), t)


def _downsample(big, size):
    return pygame.transform.smoothscale(big, size)


def _tapered_poly(points, width_start, width_end=0.0):
    """Outline polygon of a stroke along `points` whose width eases from
    width_start to width_end, for thick cartoon strokes that end in a point."""
    left, right = [], []
    n = len(points)
    for i, p in enumerate(points):
        if i == 0:
            d = points[1] - points[0]
        elif i == n - 1:
            d = points[-1] - points[-2]
        else:
            d = points[i + 1] - points[i - 1]
        if d.length_squared() == 0:
            d = pygame.Vector2(1, 0)
        perp = pygame.Vector2(-d.y, d.x).normalize()
        w = (width_start + (width_end - width_start) * (i / (n - 1))) / 2
        left.append(p + perp * w)
        right.append(p - perp * w)
    return left + right[::-1]


def _star_points(center, r_outer, r_inner, spikes, rng, rot=0.0, jitter=0.25):
    pts = []
    for i in range(spikes * 2):
        a = rot + math.tau * i / (spikes * 2)
        if i % 2 == 0:
            r = r_outer * rng.uniform(1 - jitter, 1.0)
        else:
            r = r_inner * rng.uniform(0.85, 1.1)
        pts.append(center + pygame.Vector2(math.cos(a), math.sin(a)) * r)
    return pts


# ---- textures (Kenney Particle Pack, CC0) ----------------------------------

#: Folder (under assets/) holding the Kenney Particle Pack textures this
#: module tints: white-on-transparent glows and smoke, CC0 licensed (see
#: License.txt there). Used for the hit burst and dust puffs, whose soft
#: glow/smoke reads better than a flat drawn shape; ground cracks stay
#: procedural since the pack has no crack art.
KENNEY_DIR = "fx/kenney"
_TEXTURE_CACHE = {}


def _texture(name, size, color, alpha=255):
    """A Kenney texture scaled to `size` px square and tinted `color` (the
    art is white, so a multiply tints it), alpha scaled by `alpha`/255."""
    key = (name, int(size), tuple(color[:3]), alpha)
    img = _TEXTURE_CACHE.get(key)
    if img is None:
        img = load_sprite(f"{KENNEY_DIR}/{name}.png", max(1, int(size))).copy()
        img.fill((*color[:3], alpha), special_flags=pygame.BLEND_RGBA_MULT)
        _TEXTURE_CACHE[key] = img
    return img


_GLOW_CACHE = {}
_GLOW_CACHE_MAX = 300


def draw_glow_texture(screen, name, center, size, color, fade=1.0, angle=0.0, stretch=None):
    """Add a tinted Kenney texture onto `screen` as light: `size` px square
    (rounded to 8 px for caching), brightness scaled by `fade` (0..1 — the
    art is premultiplied, so fading means darkening the tint), squashed by
    `stretch` (w, h multipliers) before rotating `angle` degrees. For
    one-off cinematic effects that grow/fade every frame."""
    if fade <= 0.02 or size < 2:
        return
    size = max(8, int(round(size / 8)) * 8)
    key = (name, size, tuple(color[:3]))
    img = _GLOW_CACHE.get(key)
    if img is None:
        if len(_GLOW_CACHE) > _GLOW_CACHE_MAX:
            _GLOW_CACHE.clear()
        img = load_sprite(f"{KENNEY_DIR}/{name}.png", size).copy()
        img.fill((*color[:3], 255), special_flags=pygame.BLEND_RGBA_MULT)
        _GLOW_CACHE[key] = img
    if fade < 1.0:
        f = int(255 * fade)
        img = img.copy()
        img.fill((f, f, f, 255), special_flags=pygame.BLEND_RGBA_MULT)
    if stretch is not None:
        img = pygame.transform.smoothscale(
            img, (max(1, int(size * stretch[0])), max(1, int(size * stretch[1]))))
    _blit_center(screen, img, center, angle=angle, add=True)


def _blit_center(dst, img, center, angle=0.0, add=False):
    """Blit `img` centered on `center`; `add` stacks it additively (colors
    and alpha summed) so layered glow brightens instead of just covering."""
    if angle:
        img = pygame.transform.rotate(img, angle)
    dst.blit(img, img.get_rect(center=(round(center[0]), round(center[1]))),
             special_flags=pygame.BLEND_RGBA_ADD if add else 0)


# ---- impact burst -----------------------------------------------------------

_BURST_CACHE = {}
#: Random shape variants kept per (size, color) so repeated hits don't all
#: stamp the identical flare.
BURST_VARIANTS = 4
BURST_FRAMES = 6
#: Some flare textures fill much more of their canvas than the thin star
#: flares do; scaled down so every character's flash reads the same size.
FLARE_SCALE = {"light_02": 0.6, "smoke_02": 0.8, "dirt_01": 0.8, "fire_01": 0.85, "twirl_02": 0.75}


def build_impact_burst_frames(color, size, variant=None, flare=None):
    """A BURST_FRAMES-long glowing hit flash, `size` px across at its peak,
    built from Kenney textures: a tinted flare (the attacker's own
    CharacterPlugin.BURST_TEXTURE, else a plain star; turned a little per
    variant) that pops and shrinks, a white-hot core, and a thin shock ring
    expanding and fading behind it. Cached per (size, color, variant,
    flare)."""
    color = tuple(color[:3])
    if variant is None:
        variant = random.randrange(BURST_VARIANTS)
    key = (int(size), color, variant, flare)
    frames = _BURST_CACHE.get(key)
    if frames is not None:
        return frames

    flare = flare or ("star_08", "star_06")[variant % 2]
    angle = variant * 22.5
    dim = int(size * 1.7)
    c = (dim / 2, dim / 2)
    light = _lighten(color, 0.25)
    # (flare scale, core scale, ring scale or None, ring alpha); the shock
    # ring starts outside the core and thins fast, so the flash reads as a
    # burst rather than a target
    timeline = [
        (1.0, 0.7, None, 0),
        (1.6, 0.85, 0.8, 170),
        (1.4, 0.6, 1.0, 120),
        (1.1, 0.4, 1.15, 70),
        (0.8, 0.2, 1.25, 35),
        (0.5, 0.0, 1.32, 12),
    ]
    frames = []
    for flare_s, core_s, ring_s, ring_a in timeline:
        surf = pygame.Surface((dim, dim), pygame.SRCALPHA)
        if ring_s is not None:
            _blit_center(surf, _texture("circle_02", size * ring_s * 1.1, light, ring_a), c)
        if core_s > 0:
            # soft colored halo behind the flare
            _blit_center(surf, _texture("star_01", size * core_s * 1.6, color, 170), c, add=True)
        # the flare stacked twice additively so its thin rays read bright; a
        # one-armed swirl texture goes on half a turn apart instead, so it
        # wraps all the way around
        spin = 180 if flare.startswith("twirl") else 0
        for k in range(2):
            _blit_center(surf, _texture(flare, size * flare_s * FLARE_SCALE.get(flare, 1.0), color), c,
                         angle + k * spin, add=True)
        if core_s > 0:
            _blit_center(surf, _texture("star_01", size * core_s * 0.75, _lighten(color, 0.8)), c, add=True)
        frames.append(surf)
    _BURST_CACHE[key] = frames
    return frames


# ---- other texture effects --------------------------------------------------

_STAMP_CACHE = {}


def build_smoke_ring_frames(size, color=(200, 186, 164)):
    """A 6-frame ring of smoke (Kenney smoke_10) blowing outward from a
    point and thinning out, `size` px across at its widest — the KO beat's
    ground shockwave."""
    key = ("smoke_ring", int(size), tuple(color))
    frames = _STAMP_CACHE.get(key)
    if frames is None:
        dim = int(size * 1.1)
        frames = []
        for k in range(6):
            t = k / 5
            surf = pygame.Surface((dim, dim), pygame.SRCALPHA)
            _blit_center(surf, _texture("smoke_10", size * (0.45 + 0.55 * t), color, int(255 * (1 - t * 0.6))),
                         (dim / 2, dim / 2), angle=k * 9)
            frames.append(surf)
        _STAMP_CACHE[key] = frames
    return frames


def build_muzzle_frames(color, size, heading_deg):
    """A 3-frame muzzle flash (Kenney muzzle_02, drawn pointing up) turned
    to fire along `heading_deg` (screen degrees, counter-clockwise), flaring
    then shrinking. Quantized to 10 degrees for the cache."""
    heading = int(round(heading_deg / 10.0)) * 10
    key = ("muzzle", tuple(color[:3]), int(size), heading)
    frames = _STAMP_CACHE.get(key)
    if frames is None:
        dim = int(size * 2.4)
        d = pygame.Vector2(1, 0).rotate(-heading)
        frames = []
        for scale in (0.8, 1.0, 0.55):
            surf = pygame.Surface((dim, dim), pygame.SRCALPHA)
            # the flame's base sits at the muzzle (surface center) and it
            # licks forward along the heading; the art only fills the middle
            # of its texture, hence the 2x
            center = pygame.Vector2(dim / 2, dim / 2) + d * size * scale * 0.4
            _blit_center(surf, _texture("muzzle_02", size * scale * 2, color), center, angle=heading - 90, add=True)
            _blit_center(surf, _texture("star_01", size * scale * 0.5, (255, 255, 255)), (dim / 2, dim / 2), add=True)
            frames.append(surf)
        _STAMP_CACHE[key] = frames
    return frames


def draw_cast_circle(screen, pos, color, size, spin, alpha=255):
    """A rotating magic circle on the ground under a caster (Kenney magic_03
    turning one way, the magic_02 rune ring the other), `spin` in degrees."""
    alpha = max(0, min(255, int(alpha)))
    if alpha <= 0:
        return
    _blit_center(screen, _texture("magic_02", size * 1.15, _lighten(color, 0.3), alpha), pos, angle=-spin * 0.6)
    _blit_center(screen, _texture("magic_03", size, color, alpha), pos, angle=spin)


def draw_twirl(screen, pos, color, size, spin, alpha=255):
    """A pair of spinning swirl streaks (Kenney twirl_02) around `pos`, for a
    spin attack."""
    tex = _texture("twirl_02", size, color, max(0, min(255, int(alpha))))
    _blit_center(screen, tex, pos, angle=spin)
    _blit_center(screen, tex, pos, angle=spin + 180)


# ---- ground decals ----------------------------------------------------------

def _draw_fissure(big, pts, width, color, glow):
    """One glowing gouge: a wide soft glow, a dark outline, then a hot
    tapered core, so it reads on a black floor."""
    pygame.draw.polygon(big, (*glow, 60), _tapered_poly(pts, width * 2.4, width * 0.2))
    pygame.draw.polygon(big, (*OUTLINE, 255), _tapered_poly(pts, width + SS * 3, SS * 1.5))
    pygame.draw.polygon(big, (*color, 255), _tapered_poly(pts, width, 0))
    pygame.draw.polygon(big, (255, 250, 235, 255), _tapered_poly(pts, width * 0.35, 0))


def build_scratch_decal(color, size, seed, angle=0.0):
    """A scratch mark baked once onto its own surface (centered), for
    ImpactFXMixin.add_decal: three glowing gouges tapered at both ends,
    running along `angle` degrees. `seed` keeps its random shape stable
    for its whole lifetime. (Ground cracks/craters are deliberately not
    part of this game's look — only scratches.)"""
    rng = random.Random(seed)
    color = tuple(color[:3])
    dim = int(size * 2.4) + 8
    big_dim = dim * SS
    c = pygame.Vector2(big_dim / 2, big_dim / 2)
    S = size * SS
    big = pygame.Surface((big_dim, big_dim), pygame.SRCALPHA)
    hot = _lighten(color, 0.45)
    d = pygame.Vector2(1, 0).rotate(-angle)
    perp = pygame.Vector2(-d.y, d.x)
    for i in range(3):
        off = perp * (i - 1) * S * 0.3 + d * rng.uniform(-0.1, 0.1) * S
        half = S * rng.uniform(0.75, 0.95) * (0.85 if i != 1 else 1.0)
        a, b = c + off - d * half, c + off + d * half
        mid = (a + b) / 2 + perp * rng.uniform(-0.06, 0.06) * S
        w = S * 0.11
        for pts in ([mid, (mid + a) / 2, a], [mid, (mid + b) / 2, b]):
            _draw_fissure(big, pts, w, color, hot)
    return _downsample(big, (dim, dim))


# ---- dust puff --------------------------------------------------------------

DUST_FILL = (215, 198, 172)
#: The smoke art only fills the middle of its texture, so it's scaled up
#: by this much for the visible cloud to match a puff's nominal size.
DUST_TEXTURE_SCALE = 1.9
#: Kenney smoke textures, one per dust puff variant (add_dust_puff picks
#: variant 0..5).
DUST_TEXTURES = ("smoke_03", "smoke_04", "smoke_05", "smoke_06", "smoke_07", "smoke_08")


def dust_puff_sprite(size, variant):
    """A soft dusty smoke puff (a Kenney smoke texture tinted dust-brown),
    `size` px across. Cached by _texture per (size, variant)."""
    img = _texture(DUST_TEXTURES[variant % len(DUST_TEXTURES)], size * DUST_TEXTURE_SCALE, DUST_FILL)
    # the smoke art's own alpha peaks around half, so double it up
    key = ("dust2x", int(size), variant)
    doubled = _TEXTURE_CACHE.get(key)
    if doubled is None:
        doubled = img.copy()
        doubled.blit(img, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        _TEXTURE_CACHE[key] = doubled
    return doubled


def draw_dust_puff(screen, pos, size, t, variant):
    """One dust puff at progress `t` (0..1): pops up to full size fast,
    then keeps swelling slowly while it fades out."""
    grow = 0.5 + 0.5 * min(1.0, t / 0.25) + 0.3 * t
    s = max(4, int(round(size * grow / 2)) * 2)
    img = dust_puff_sprite(s, variant)
    if t > 0.35:
        img = img.copy()
        img.set_alpha(int(255 * max(0.0, 1 - (t - 0.35) / 0.65)))
    screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))


# ---- KO beat ----------------------------------------------------------------

def draw_speed_lines(screen, center, rect, seed, alpha=170, count=64, clear_radius=90):
    """Manga focus lines: thin tapered wedges from beyond `rect`'s edges
    converging on `center`, stopping short of a clear circle around it.
    Re-seed every couple of frames for the flickering hand-drawn look."""
    rng = random.Random(seed)
    overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    far = math.hypot(rect.width, rect.height)
    for i in range(count):
        a = math.tau * (i + rng.uniform(-0.4, 0.4)) / count
        d = pygame.Vector2(math.cos(a), math.sin(a))
        perp = pygame.Vector2(-d.y, d.x)
        inner = clear_radius * rng.uniform(1.0, 1.9)
        w = rng.uniform(3, 11)
        tip = center + d * inner
        base = center + d * far
        shade = 255 if rng.random() < 0.7 else 30
        pygame.draw.polygon(overlay, (shade, shade, shade, alpha), [tip, base + perp * w, base - perp * w])
    screen.blit(overlay, (0, 0))
