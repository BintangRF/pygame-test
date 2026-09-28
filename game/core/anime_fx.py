"""Anime/cartoon-style generic hit effects: thick shapes with dark outlines
and bright cores, rendered supersampled (drawn at SS x size, then
smoothscaled down) so the edges come out anti-aliased instead of pygame's
jagged raw polygons. Everything here returns plain surfaces or draws
straight onto a target; none of it reads battle state.

- build_impact_burst_frames: the glowing hit-flash flipbook a landed hit
  stamps on the defender (ImpactFXMixin.apply_impact), built from Kenney
  Particle Pack textures (CC0, assets/fx/kenney).
- build_ground_decal: crack/scorch/scratch ground marks (add_decal),
  drawn as glowing fissures so they read on the arena's black floor.
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
    light = _lighten(color, 0.5)
    # (flare scale, core scale, ring scale or None, ring alpha)
    timeline = [
        (1.0, 0.8, None, 0),
        (1.6, 1.0, 0.5, 220),
        (1.4, 0.8, 0.75, 170),
        (1.1, 0.55, 0.95, 110),
        (0.8, 0.3, 1.1, 60),
        (0.5, 0.0, 1.2, 20),
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
            _blit_center(surf, _texture("star_01", size * core_s * 0.9, (255, 255, 255)), c, add=True)
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

def _crack_branch(rng, start, angle, length, steps):
    """A jagged crack line: holds its overall heading but kinks sharply
    left/right on alternate segments (a zigzag, not a curving random walk),
    with uneven segment lengths."""
    pts = [pygame.Vector2(start)]
    side = rng.choice((-1, 1))
    weights = [rng.uniform(0.6, 1.4) for _ in range(steps)]
    total = sum(weights)
    for w in weights:
        a = angle + side * rng.uniform(0.25, 0.6)
        side = -side
        pts.append(pts[-1] + pygame.Vector2(math.cos(a), math.sin(a)) * (length * w / total))
    return pts


def _draw_fissure(big, pts, width, color, glow):
    """One glowing fissure: a wide soft glow, a dark outline, then a hot
    tapered core, so it reads as a lit crack on a black floor."""
    pygame.draw.polygon(big, (*glow, 60), _tapered_poly(pts, width * 2.4, width * 0.2))
    pygame.draw.polygon(big, (*OUTLINE, 255), _tapered_poly(pts, width + SS * 3, SS * 1.5))
    pygame.draw.polygon(big, (*color, 255), _tapered_poly(pts, width, 0))
    pygame.draw.polygon(big, (255, 250, 235, 255), _tapered_poly(pts, width * 0.35, 0))


def _draw_blade_cut(big, a, b, width, color, glow):
    """A straight fissure fat in the middle and pointed at both ends (a
    clean cut rather than a crack running out from a crater)."""
    mid = (a + b) / 2
    for end in (a, b):
        _draw_fissure(big, [mid, (mid + end) / 2, end], width, color, glow)


def _draw_rock(big, rng, p, r, stone=(128, 118, 110), stone_light=(196, 186, 174)):
    rock = [p + pygame.Vector2(math.cos(t), math.sin(t)) * r * rng.uniform(0.7, 1.1)
            for t in [rng.uniform(0, 0.4) + k * math.tau / 5 for k in range(5)]]
    pygame.draw.polygon(big, (*OUTLINE, 255), [p + (q - p) * 1.35 for q in rock])
    pygame.draw.polygon(big, (*stone, 255), rock)
    pygame.draw.polygon(big, (*stone_light, 255), [p + (q - p) * 0.55 + pygame.Vector2(-1, -1) * r * 0.25 for q in rock])


def _dir(angle):
    """Unit vector for a decal `angle` (degrees, counter-clockwise on screen
    like pygame.transform.rotate) — the attack's own heading."""
    return pygame.Vector2(1, 0).rotate(-angle)


def _style_chop(big, rng, c, S, color, hot, angle):
    """Berserker: one brutal axe cleft across the swing, a deep wedge with
    short jagged cracks splitting off both lips and chunks thrown out."""
    d = _dir(angle).rotate(90)  # the axe bites across the swing direction
    perp = pygame.Vector2(-d.y, d.x)
    a, b = c - d * S * 0.9, c + d * S * 0.9
    _draw_blade_cut(big, a, b, S * 0.3, color, hot)
    for _ in range(rng.randint(6, 8)):
        t = rng.uniform(-0.7, 0.7)
        side = rng.choice((-1, 1))
        start = c + d * S * t + perp * side * S * 0.08
        ang = math.atan2(perp.y * side, perp.x * side) + rng.uniform(-0.5, 0.5)
        _draw_fissure(big, _crack_branch(rng, start, ang, S * rng.uniform(0.3, 0.55), 3), S * 0.07, color, hot)
    for _ in range(rng.randint(4, 6)):
        side = rng.choice((-1, 1))
        _draw_rock(big, rng, c + d * S * rng.uniform(-0.6, 0.6) + perp * side * S * rng.uniform(0.3, 0.55),
                   S * rng.uniform(0.06, 0.1))


def _style_holy(big, rng, c, S, color, hot, angle):
    """Paladin: a consecrated sigil, a glowing double ring with the ground
    split in a clean cross (plus shorter diagonals) and rune dots."""
    pygame.draw.circle(big, (*hot, 45), c, S * 0.95)
    for r, w in ((0.82, 0.05), (0.62, 0.025)):
        pygame.draw.circle(big, (*OUTLINE, 255), c, S * r, width=int(S * w) + SS * 3)
        pygame.draw.circle(big, (*color, 255), c, S * r, width=int(S * w))
        pygame.draw.circle(big, (255, 250, 235, 255), c, S * r, width=max(1, int(S * w * 0.35)))
    for k in range(8):
        a = math.tau * k / 8
        d = pygame.Vector2(math.cos(a), math.sin(a))
        length = 0.95 if k % 2 == 0 else 0.55
        _draw_fissure(big, [c, c + d * S * length * 0.5, c + d * S * length], S * (0.1 if k % 2 == 0 else 0.06),
                      color, hot)
    for k in range(12):
        a = math.tau * (k + 0.5) / 12
        p = c + pygame.Vector2(math.cos(a), math.sin(a)) * S * 0.72
        pygame.draw.circle(big, (*OUTLINE, 255), p, S * 0.035 + SS * 2)
        pygame.draw.circle(big, (*hot, 255), p, S * 0.035)
    pygame.draw.circle(big, (255, 250, 235, 255), c, S * 0.08)


def _style_pierce(big, rng, c, S, color, hot, angle):
    """Leonidas: a spear-point puncture, a small deep hole with dead
    straight splits (longest along the thrust) and the faint round
    imprint of a hoplite shield."""
    d = _dir(angle)
    for k in range(10):
        a0 = math.tau * k / 10
        arc = [c + pygame.Vector2(math.cos(a0 + t * 0.4), math.sin(a0 + t * 0.4)) * S * 0.8 for t in range(3)]
        pygame.draw.lines(big, (*color, 150), False, arc, int(S * 0.03))
    base = math.atan2(d.y, d.x)
    for k in range(6):
        a = base + math.tau * k / 6 + rng.uniform(-0.15, 0.15)
        along = abs(math.cos(a - base))
        length = S * (0.45 + 0.5 * along ** 2) * rng.uniform(0.85, 1.0)
        v = pygame.Vector2(math.cos(a), math.sin(a))
        _draw_fissure(big, [c + v * S * 0.12, c + v * length * 0.55, c + v * length], S * 0.09, color, hot)
    pygame.draw.circle(big, (*OUTLINE, 255), c, S * 0.17)
    pygame.draw.circle(big, (*_darken(color, 0.4), 255), c, S * 0.13)
    pygame.draw.circle(big, (*hot, 255), c, S * 0.06)


def _lightning_branch(big, rng, start, angle, length, width, depth, color, hot):
    pts = [pygame.Vector2(start)]
    steps = 7
    for _ in range(steps):
        a = angle + rng.uniform(-0.8, 0.8)
        pts.append(pts[-1] + pygame.Vector2(math.cos(a), math.sin(a)) * length / steps)
    _draw_fissure(big, pts, width, color, hot)
    if depth > 0:
        for i in rng.sample(range(2, steps), 2):
            _lightning_branch(big, rng, pts[i], angle + rng.choice((-1, 1)) * rng.uniform(0.5, 1.0),
                              length * 0.45, width * 0.6, depth - 1, color, hot)


def _style_lightning(big, rng, c, S, color, hot, angle):
    """Raiju: a Lichtenberg burn, forked electric branches crawling out
    from a scorched strike point."""
    for i in range(4, 0, -1):
        pygame.draw.circle(big, (*color, 30), c, S * 0.12 * i)
    for k in range(5):
        a = math.tau * k / 5 + rng.uniform(-0.3, 0.3)
        _lightning_branch(big, rng, c, a, S * rng.uniform(0.7, 0.95), S * 0.07, 2, color, hot)
    pygame.draw.circle(big, (*OUTLINE, 255), c, S * 0.12)
    pygame.draw.circle(big, (255, 250, 235, 255), c, S * 0.08)


def _style_dismantle(big, rng, c, S, color, hot, angle):
    """Sukuna: no crater at all, just clean invisible-blade cuts slicing
    straight through the floor at every angle, crossing in a hash."""
    base = rng.uniform(0, math.pi)
    count = rng.randint(5, 7)
    for k in range(count):
        a = base + math.pi * k / count + rng.uniform(-0.12, 0.12)
        v = pygame.Vector2(math.cos(a), math.sin(a))
        off = pygame.Vector2(-v.y, v.x) * S * rng.uniform(-0.3, 0.3)
        half = S * rng.uniform(0.7, 1.0)
        _draw_blade_cut(big, c + off - v * half, c + off + v * half, S * 0.055, color, hot)


def _style_blood(big, rng, c, S, color, hot, angle):
    """Vampire: the crack floods with blood, a glossy splatter pool with
    drips thrown out around it and thin cracks under the rim."""
    blood = _mix(color, (150, 10, 25), 0.5)
    for _ in range(4):
        a = rng.uniform(0, math.tau)
        _draw_fissure(big, _crack_branch(rng, c, a, S * rng.uniform(0.6, 0.9), 3), S * 0.05, blood, _lighten(blood, 0.3))
    lobes = [(c, S * 0.36)]
    for _ in range(7):
        a = rng.uniform(0, math.tau)
        lobes.append((c + pygame.Vector2(math.cos(a), math.sin(a)) * S * rng.uniform(0.15, 0.35), S * rng.uniform(0.14, 0.24)))
    for p, r in lobes:
        pygame.draw.circle(big, (*OUTLINE, 255), p, r + SS * 3)
    for p, r in lobes:
        pygame.draw.circle(big, (*blood, 255), p, r)
    for p, r in lobes[:3]:
        pygame.draw.circle(big, (*_lighten(blood, 0.55), 255), p + pygame.Vector2(-r * 0.3, -r * 0.35), r * 0.25)
    for _ in range(10):
        a = rng.uniform(0, math.tau)
        v = pygame.Vector2(math.cos(a), math.sin(a))
        p = c + v * S * rng.uniform(0.55, 0.9)
        r = S * rng.uniform(0.03, 0.06)
        pygame.draw.polygon(big, (*blood, 255), _tapered_poly([p - v * r * 3, p], 0, r * 2))
        pygame.draw.circle(big, (*OUTLINE, 255), p, r + SS * 2)
        pygame.draw.circle(big, (*blood, 255), p, r)


def _style_tusk(big, rng, c, S, color, hot, angle):
    """Johnny: a Tusk drill hole, a bored-out pit ringed by short curved
    blades all curling the same way like a spinning drill bit, with broken
    swirl arcs around it so the mark itself reads as rotation."""
    pygame.draw.circle(big, (*color, 16), c, S * 0.9)
    turn = rng.choice((-1, 1))  # which way this hole spins
    # broken swirl arcs, all running the same way as the blades; a small
    # per-nail hole keeps just the outer one so it doesn't turn to mush
    small = S < 30 * SS
    for r, gap in ((0.82, 0.9),) if small else ((0.82, 0.9), (0.6, 1.3)):
        a0 = rng.uniform(0, math.tau)
        for k in range(3):
            base = a0 + math.tau * k / 3
            arc = [c + pygame.Vector2(math.cos(base + turn * t * 0.1), math.sin(base + turn * t * 0.1)) * S * r
                   for t in range(int((math.tau / 3 - gap) / 0.1))]
            if len(arc) > 2:
                _draw_fissure(big, arc[::-1], S * 0.045, color, hot)
    blades = 4 if small else 6
    start = rng.uniform(0, math.tau)
    for k in range(blades):
        a = start + math.tau * k / blades
        pts = []
        for i in range(8):
            t = i / 7
            ang = a + turn * t * 0.95
            pts.append(c + pygame.Vector2(math.cos(ang), math.sin(ang)) * S * (0.22 + 0.5 * t))
        _draw_fissure(big, pts, S * 0.13, color, hot)
    pygame.draw.circle(big, (*OUTLINE, 255), c, S * 0.26)
    pygame.draw.circle(big, (*color, 255), c, S * 0.22)
    pygame.draw.circle(big, (6, 8, 14, 255), c, S * 0.17)
    # a light catch on the pit's upper-left lip
    pygame.draw.arc(big, (255, 250, 235, 255), pygame.Rect(c.x - S * 0.2, c.y - S * 0.2, S * 0.4, S * 0.4),
                    math.radians(100), math.radians(170), max(1, int(S * 0.035)))


def _style_starfall(big, rng, c, S, color, hot, angle):
    """Arjuna: a divine shot from the sky, a round crater ringed by broken
    shock circles with straight rays bursting through them."""
    for r in (0.5, 0.78):
        k = 0
        while k < 360:
            span = rng.uniform(35, 70)
            arc = [c + pygame.Vector2(math.cos(math.radians(k + t)), math.sin(math.radians(k + t))) * S * r
                   for t in range(0, int(span), 6)]
            if len(arc) > 2:
                _draw_fissure(big, arc, S * 0.05, color, hot)
            k += span + rng.uniform(12, 30)
    for k in range(8):
        a = math.tau * k / 8 + rng.uniform(-0.1, 0.1)
        v = pygame.Vector2(math.cos(a), math.sin(a))
        _draw_fissure(big, [c + v * S * 0.2, c + v * S * 0.6, c + v * S * rng.uniform(0.85, 1.0)], S * 0.07, color, hot)
    pygame.draw.circle(big, (*OUTLINE, 255), c, S * 0.24)
    pygame.draw.circle(big, (128, 118, 110, 255), c, S * 0.2)
    pygame.draw.circle(big, (*hot, 255), c, S * 0.1)


def _style_rift(big, rng, c, S, color, hot, angle):
    """Chaos Knight: reality tears instead of cracking, jagged shards of
    void opening in the floor with burning edges and loose fragments."""
    count = rng.randint(3, 4)
    start = rng.uniform(0, math.tau)
    for i in range(count):
        a = start + math.tau * i / count + rng.uniform(-0.3, 0.3)
        center = c + pygame.Vector2(math.cos(a), math.sin(a)) * S * rng.uniform(0.3, 0.45)
        length, width = S * rng.uniform(0.45, 0.7), S * rng.uniform(0.1, 0.16)
        v = pygame.Vector2(math.cos(a + 1.2), math.sin(a + 1.2))
        perp = pygame.Vector2(-v.y, v.x)
        shard = [center - v * length, center + perp * width * rng.uniform(0.6, 1.0) - v * length * 0.2,
                 center + perp * width * rng.uniform(0.3, 0.6) + v * length * 0.3, center + v * length,
                 center - perp * width * rng.uniform(0.6, 1.0) + v * length * 0.15,
                 center - perp * width * rng.uniform(0.3, 0.6) - v * length * 0.4]
        pygame.draw.polygon(big, (*hot, 60), [center + (p - center) * 1.5 for p in shard])
        pygame.draw.polygon(big, (*color, 255), [center + (p - center) * 1.22 for p in shard])
        pygame.draw.polygon(big, (*OUTLINE, 255), [center + (p - center) * 1.08 for p in shard])
        pygame.draw.polygon(big, (*_darken(color, 0.72), 255), shard)
        # a thin bright seam down the tear's middle, like light leaking through
        pygame.draw.polygon(big, (*hot, 255), _tapered_poly([center - v * length * 0.8, center, center + v * length * 0.8],
                                                            width * 0.35, 0))
    for _ in range(7):
        a = rng.uniform(0, math.tau)
        p = c + pygame.Vector2(math.cos(a), math.sin(a)) * S * rng.uniform(0.6, 0.95)
        r = S * rng.uniform(0.03, 0.06)
        tri = [p + pygame.Vector2(math.cos(rng.uniform(0, math.tau)), math.sin(rng.uniform(0, math.tau))) * r * 1.6
               for _ in range(3)]
        pygame.draw.polygon(big, (*color, 255), [p + (q - p) * 1.4 for q in tri])
        pygame.draw.polygon(big, (8, 4, 14, 255), tri)


def _style_phantom(big, rng, c, S, color, hot, angle):
    """Phantom Lancer: lance-straight rents in a tight fan along the
    thrust, each shadowed by a faint offset echo like his illusions."""
    d = _dir(angle)
    base = math.atan2(d.y, d.x)
    echo = pygame.Surface(big.get_size(), pygame.SRCALPHA)
    for k in (-2, -1, 0, 1, 2):
        a = base + k * 0.24
        v = pygame.Vector2(math.cos(a), math.sin(a))
        start, end = c - d * S * 0.55, c - d * S * 0.55 + v * S * (1.5 - abs(k) * 0.22)
        off = pygame.Vector2(-v.y, v.x) * S * 0.1
        _draw_fissure(echo, [start + off, (start + end) / 2 + off, end + off], S * 0.1, color, hot)
        _draw_fissure(big, [start, (start + end) / 2, end], S * 0.1, color, hot)
    echo.set_alpha(90)
    big.blit(echo, (0, 0))
    pygame.draw.circle(big, (*OUTLINE, 255), c - d * S * 0.55, S * 0.11)
    pygame.draw.circle(big, (*hot, 255), c - d * S * 0.55, S * 0.06)


def _style_ripple(big, rng, c, S, color, hot, angle):
    """Legion Commander: a war-drum stomp, the ground buckling in
    concentric broken rings joined by short radial splits."""
    for r in (0.35, 0.6, 0.88):
        k = rng.uniform(0, 40)
        while k < 360:
            span = rng.uniform(50, 90)
            arc = []
            for t in range(0, int(span), 5):
                a = math.radians(k + t)
                arc.append(c + pygame.Vector2(math.cos(a), math.sin(a)) * S * r * rng.uniform(0.96, 1.04))
            if len(arc) > 2:
                _draw_fissure(big, arc, S * (0.075 - r * 0.03), color, hot)
            k += span + rng.uniform(15, 35)
    for k in range(7):
        a = math.tau * k / 7 + rng.uniform(-0.2, 0.2)
        v = pygame.Vector2(math.cos(a), math.sin(a))
        r0 = rng.choice((0.2, 0.45, 0.7))
        _draw_fissure(big, [c + v * S * r0, c + v * S * (r0 + 0.2)], S * 0.05, color, hot)
    pygame.draw.circle(big, (*OUTLINE, 255), c, S * 0.16)
    pygame.draw.circle(big, (*_darken(color, 0.3), 255), c, S * 0.12)


def _style_shadow(big, rng, c, S, color, hot, angle):
    """Before Hassasin: an assassin's mark, two long crossed knife slits
    over a spreading stain of shadow, with a few stray nicks."""
    for i in range(6, 0, -1):
        pygame.draw.circle(big, (*color, 34), c + pygame.Vector2(rng.uniform(-1, 1), rng.uniform(-1, 1)) * S * 0.08,
                           S * 0.14 * i)
    base = rng.uniform(0, math.pi)
    for a in (base, base + math.pi / 2 + rng.uniform(-0.3, 0.3)):
        v = pygame.Vector2(math.cos(a), math.sin(a))
        _draw_blade_cut(big, c - v * S * 0.95, c + v * S * 0.95, S * 0.06, color, hot)
    for _ in range(4):
        a = rng.uniform(0, math.tau)
        v = pygame.Vector2(math.cos(a), math.sin(a))
        p = c + pygame.Vector2(math.cos(a + 1), math.sin(a + 1)) * S * rng.uniform(0.4, 0.7)
        _draw_blade_cut(big, p - v * S * 0.15, p + v * S * 0.15, S * 0.035, color, hot)


#: Character-flavored crack styles for build_ground_decal, picked by each
#: CharacterPlugin's own GROUND_DECAL (see ImpactFXMixin.apply_impact).
#: Each draws onto the supersampled canvas `big` around its center `c`,
#: with `S` the decal radius in supersampled px and `angle` the attack
#: heading in degrees.
DECAL_STYLES = {
    "chop": _style_chop,
    "holy": _style_holy,
    "pierce": _style_pierce,
    "lightning": _style_lightning,
    "dismantle": _style_dismantle,
    "blood": _style_blood,
    "tusk": _style_tusk,
    "starfall": _style_starfall,
    "rift": _style_rift,
    "phantom": _style_phantom,
    "ripple": _style_ripple,
    "shadow": _style_shadow,
}


def build_ground_decal(kind, color, size, seed, angle=0.0):
    """A ground mark baked once onto its own surface (centered), for
    ImpactFXMixin.add_decal, in the anime style: "crack" (a stone crater
    with glowing tapered fissures and rock chunks), "scorch" (a glowing
    burn ring with ember flecks), "scratch" (three glowing tapered gouges
    along `angle` degrees), or any character style in DECAL_STYLES.
    `seed` keeps each decal's random shape stable for its whole
    lifetime."""
    rng = random.Random(seed)
    color = tuple(color[:3])
    dim = int(size * 2.4) + 8
    big_dim = dim * SS
    c = pygame.Vector2(big_dim / 2, big_dim / 2)
    S = size * SS
    big = pygame.Surface((big_dim, big_dim), pygame.SRCALPHA)
    hot = _lighten(color, 0.45)
    stone = (128, 118, 110)
    stone_light = (196, 186, 174)

    if kind in DECAL_STYLES:
        DECAL_STYLES[kind](big, rng, c, S, color, hot, angle)
    elif kind == "scratch":
        d = pygame.Vector2(1, 0).rotate(-angle)
        perp = pygame.Vector2(-d.y, d.x)
        for i in range(3):
            off = perp * (i - 1) * S * 0.3 + d * rng.uniform(-0.1, 0.1) * S
            half = S * rng.uniform(0.75, 0.95) * (0.85 if i != 1 else 1.0)
            a, b = c + off - d * half, c + off + d * half
            mid = (a + b) / 2 + perp * rng.uniform(-0.06, 0.06) * S
            # tapered at both ends: build as two halves meeting fat in the middle
            w = S * 0.11
            for pts in ([mid, (mid + a) / 2, a], [mid, (mid + b) / 2, b]):
                _draw_fissure(big, pts, w, color, hot)
    elif kind == "scorch":
        for i in range(5, 0, -1):
            pygame.draw.circle(big, (*color, 22), c, S * (0.5 + 0.1 * i))
        ring = []
        for i in range(28):
            a = math.tau * i / 28
            r = S * rng.uniform(0.52, 0.62)
            ring.append(c + pygame.Vector2(math.cos(a), math.sin(a)) * r)
        pygame.draw.polygon(big, (*OUTLINE, 255), ring)
        pygame.draw.polygon(big, (*color, 255), ring, width=int(S * 0.08))
        pygame.draw.polygon(big, (*hot, 255), ring, width=int(S * 0.03))
        inner = [c + (p - c) * 0.78 for p in ring]
        pygame.draw.polygon(big, (30, 24, 24, 255), inner)
        for _ in range(4):
            a = rng.uniform(0, math.tau)
            pts = _crack_branch(rng, c + pygame.Vector2(math.cos(a), math.sin(a)) * S * 0.1, a, S * 0.35, 3)
            _draw_fissure(big, pts, S * 0.06, color, hot)
        for _ in range(12):
            a = rng.uniform(0, math.tau)
            p = c + pygame.Vector2(math.cos(a), math.sin(a)) * S * rng.uniform(0.65, 1.0)
            r = S * rng.uniform(0.025, 0.05)
            pygame.draw.circle(big, (*OUTLINE, 255), p, r + SS * 2)
            pygame.draw.circle(big, (*hot, 255), p, r)
    else:  # crack
        crater = []
        for i in range(14):
            a = math.tau * i / 14
            r = S * 0.34 * rng.uniform(0.8, 1.15)
            crater.append(c + pygame.Vector2(math.cos(a), math.sin(a)) * r)
        rim = [c + (p - c) * 1.22 for p in crater]
        pygame.draw.polygon(big, (*OUTLINE, 255), [c + (p - c) * 1.3 for p in crater])
        pygame.draw.polygon(big, (*stone, 255), rim)
        # light catches the rim's upper-left edge
        pygame.draw.polygon(big, (*stone_light, 255), [c + (p - c) * 1.22 + pygame.Vector2(-SS, -SS) * 2 for p in crater[7:12]] + [c], 0)
        pygame.draw.polygon(big, (*stone, 255), [c + (p - c) * 1.05 for p in crater])
        pygame.draw.polygon(big, (*OUTLINE, 255), crater)
        pygame.draw.polygon(big, (*_darken(color, 0.55), 255), [c + (p - c) * 0.8 for p in crater])
        pygame.draw.circle(big, (*color, 255), c, S * 0.1)
        pygame.draw.circle(big, (*hot, 255), c, S * 0.05)
        count = rng.randint(7, 9)
        for i in range(count):
            a = math.tau * i / count + rng.uniform(-0.25, 0.25)
            start = c + pygame.Vector2(math.cos(a), math.sin(a)) * S * 0.32
            length = S * rng.uniform(0.4, 0.9)
            pts = _crack_branch(rng, start, a, length, rng.randint(3, 5))
            _draw_fissure(big, pts, S * rng.uniform(0.08, 0.12), color, hot)
            if length > S * 0.6 and rng.random() < 0.7:
                j = rng.randint(1, len(pts) - 2)
                fork = _crack_branch(rng, pts[j], a + rng.choice((-1, 1)) * rng.uniform(0.5, 0.9), S * 0.28, 2)
                _draw_fissure(big, fork, S * 0.05, color, hot)
        for _ in range(rng.randint(5, 8)):
            a = rng.uniform(0, math.tau)
            p = c + pygame.Vector2(math.cos(a), math.sin(a)) * S * rng.uniform(0.45, 0.8)
            r = S * rng.uniform(0.05, 0.09)
            rock = [p + pygame.Vector2(math.cos(t), math.sin(t)) * r * rng.uniform(0.7, 1.1)
                    for t in [rng.uniform(0, 0.4) + k * math.tau / 5 for k in range(5)]]
            pygame.draw.polygon(big, (*OUTLINE, 255), [p + (q - p) * 1.35 for q in rock])
            pygame.draw.polygon(big, (*stone, 255), rock)
            pygame.draw.polygon(big, (*stone_light, 255), [p + (q - p) * 0.55 + pygame.Vector2(-1, -1) * r * 0.25 for q in rock])
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
