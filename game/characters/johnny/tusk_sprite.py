"""Tusk sprites for Johnny. If assets/johnny/tusk-<act>.png exists it is
used (see PNG_PATH / make_tusk_sprite); otherwise each Act falls back to a
procedural, original Stand-spirit design drawn here: pink spirit bodies with gold star marks and spiral motifs, one
silhouette per Act so each skill reads differently:

- Act 2: a small round spirit with big eyes, pointing its fingertip.
- Act 3: slimmer, crested, with a long coiled spirit tail.
- Act 4: a humanoid fighter with broad star-marked shoulders, a gold
  horseshoe crest and one fist thrown forward.

Every sprite faces right (flip it to face left) and is drawn supersampled
(SS x, then smoothscaled down) for clean edges, cached per (act, size).
"""

import math
import os

import pygame

from ...core.constants import ASSET_DIR

SS = 3
OUTLINE = (44, 20, 46)
PINK = (240, 168, 206)
PINK_DARK = (176, 96, 150)
LAVENDER = (196, 152, 226)
LAVENDER_DARK = (122, 84, 168)
CREAM = (255, 242, 232)
STAR_GOLD = (255, 214, 92)
EYE_DARK = (40, 24, 60)
EYE_GLOW = (140, 235, 255)

_CACHE = {}


def _p(S, u, v):
    return pygame.Vector2(u * S, v * S)


def _star(surf, center, r, color, outline=True, points=5, rot=-math.pi / 2):
    pts = []
    for i in range(points * 2):
        a = rot + math.pi * i / points
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(center + pygame.Vector2(math.cos(a), math.sin(a)) * rr)
    if outline:
        pygame.draw.polygon(surf, OUTLINE, [center + (q - center) * 1.35 for q in pts])
    pygame.draw.polygon(surf, color, pts)


def _blob(surf, rect, color, line=SS * 3):
    pygame.draw.ellipse(surf, OUTLINE, rect.inflate(line * 2, line * 2))
    pygame.draw.ellipse(surf, color, rect)


def _limb(surf, pts, w0, w1, color, line=SS * 3):
    """A tapered stroke along `pts` (width w0 -> w1), outlined."""
    left, right = [], []
    n = len(pts)
    for i, p in enumerate(pts):
        d = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)])
        if d.length_squared() == 0:
            d = pygame.Vector2(1, 0)
        perp = pygame.Vector2(-d.y, d.x).normalize()
        w = (w0 + (w1 - w0) * i / (n - 1)) / 2
        left.append(p + perp * w)
        right.append(p - perp * w)
    poly = left + right[::-1]
    pygame.draw.polygon(surf, OUTLINE, poly, width=line * 2)
    ends = ((pts[0], w0 / 2), (pts[-1], w1 / 2))
    for p, r in ends:
        pygame.draw.circle(surf, OUTLINE, p, r + line)
    pygame.draw.polygon(surf, color, poly)
    for p, r in ends:
        pygame.draw.circle(surf, color, p, r)


def _curl(S, start, length, turns, heading, shrink=1.0):
    """Points along a curling spirit tail: a spiral that tightens as it goes."""
    pts = []
    for i in range(14):
        t = i / 13
        a = heading + turns * math.tau * t
        r = length * (1 - 0.55 * t * shrink)
        pts.append(start + pygame.Vector2(math.cos(a), math.sin(a)) * r * t)
    return pts


def _spiral(surf, center, r, color, width):
    pts = []
    for i in range(40):
        t = i / 39
        a = t * math.tau * 1.6
        pts.append(center + pygame.Vector2(math.cos(a), math.sin(a)) * r * t)
    pygame.draw.lines(surf, color, False, pts, width)


def _eye(surf, center, w, h, look=0.25):
    rect = pygame.Rect(0, 0, w, h)
    rect.center = center
    pygame.draw.ellipse(surf, OUTLINE, rect.inflate(SS * 4, SS * 4))
    pygame.draw.ellipse(surf, CREAM, rect)
    pupil = pygame.Rect(0, 0, w * 0.55, h * 0.6)
    pupil.center = (center[0] + w * look, center[1] + h * 0.05)
    pygame.draw.ellipse(surf, EYE_DARK, pupil)
    pygame.draw.circle(surf, (255, 255, 255), (pupil.centerx - w * 0.08, pupil.centery - h * 0.12), max(2, w * 0.1))


def _act2(surf, S):
    # spirit tail first, so the body covers its root
    _limb(surf, _curl(S, _p(S, 0.48, 0.72), S * 0.42, 0.55, math.radians(120)), S * 0.2, S * 0.04, PINK)
    for u in (0.33, 0.62):
        _blob(surf, pygame.Rect(_p(S, u - 0.08, 0.14), (S * 0.16, S * 0.16)), PINK_DARK)
    _blob(surf, pygame.Rect(_p(S, 0.2, 0.2), (S * 0.6, S * 0.58)), PINK)
    # belly patch + spiral
    pygame.draw.ellipse(surf, CREAM, pygame.Rect(_p(S, 0.36, 0.5), (S * 0.3, S * 0.24)))
    _spiral(surf, _p(S, 0.51, 0.62), S * 0.09, PINK_DARK, SS * 2)
    _eye(surf, _p(S, 0.41, 0.4), S * 0.15, S * 0.2)
    _eye(surf, _p(S, 0.6, 0.4), S * 0.15, S * 0.2)
    _star(surf, _p(S, 0.5, 0.25), S * 0.06, STAR_GOLD)
    _star(surf, _p(S, 0.3, 0.52), S * 0.035, STAR_GOLD)
    # pointing arm, fingertip at (0.94, 0.47)
    _limb(surf, [_p(S, 0.7, 0.56), _p(S, 0.82, 0.5), _p(S, 0.93, 0.47)], S * 0.1, S * 0.05, PINK)


def _act3(surf, S):
    _limb(surf, _curl(S, _p(S, 0.5, 0.74), S * 0.5, 1.1, math.radians(100)), S * 0.17, S * 0.03, LAVENDER)
    # crest: three swept spikes
    for i, (u, h) in enumerate(((0.38, 0.16), (0.5, 0.06), (0.62, 0.16))):
        base_l, base_r = _p(S, u - 0.06, 0.3), _p(S, u + 0.06, 0.3)
        tip = _p(S, u + 0.05, h)
        pygame.draw.polygon(surf, OUTLINE, [base_l + (-SS * 3, SS), tip + (0, -SS * 3), base_r + (SS * 3, SS)])
        pygame.draw.polygon(surf, LAVENDER_DARK, [base_l, tip, base_r])
    _blob(surf, pygame.Rect(_p(S, 0.27, 0.22), (S * 0.46, S * 0.58)), LAVENDER)
    # arms swept back, one forward
    _limb(surf, [_p(S, 0.3, 0.5), _p(S, 0.18, 0.6), _p(S, 0.12, 0.66)], S * 0.08, S * 0.04, LAVENDER)
    _limb(surf, [_p(S, 0.68, 0.5), _p(S, 0.8, 0.46), _p(S, 0.92, 0.44)], S * 0.08, S * 0.04, LAVENDER)
    # narrow, determined eyes
    for u in (0.42, 0.59):
        rect = pygame.Rect(0, 0, S * 0.13, S * 0.07)
        rect.center = _p(S, u, 0.4)
        pygame.draw.ellipse(surf, OUTLINE, rect.inflate(SS * 4, SS * 4))
        pygame.draw.ellipse(surf, EYE_GLOW, rect)
    # star dots running down the body
    for u, v, r in ((0.5, 0.52, 0.04), (0.42, 0.63, 0.028), (0.58, 0.68, 0.028)):
        _star(surf, _p(S, u, v), S * r, STAR_GOLD)


def _act4(surf, S):
    # tapering spirit lower body
    _limb(surf, [_p(S, 0.5, 0.6), _p(S, 0.47, 0.8), _p(S, 0.4, 0.96)], S * 0.26, S * 0.04, PINK_DARK)
    # back arm, fist low
    _limb(surf, [_p(S, 0.26, 0.4), _p(S, 0.18, 0.52), _p(S, 0.2, 0.62)], S * 0.11, S * 0.09, PINK)
    _blob(surf, pygame.Rect(_p(S, 0.13, 0.58), (S * 0.13, S * 0.12)), CREAM)
    # torso: broad shoulders tapering to the waist
    torso = [_p(S, 0.22, 0.36), _p(S, 0.78, 0.36), _p(S, 0.63, 0.66), _p(S, 0.37, 0.66)]
    c = sum(torso, pygame.Vector2()) / 4
    pygame.draw.polygon(surf, OUTLINE, [c + (q - c) * 1.08 for q in torso])
    pygame.draw.polygon(surf, PINK, torso)
    # chest plate seam + star
    pygame.draw.line(surf, PINK_DARK, _p(S, 0.5, 0.42), _p(S, 0.5, 0.64), SS * 2)
    _star(surf, _p(S, 0.5, 0.48), S * 0.075, STAR_GOLD)
    # shoulder pads, each with a star
    for u in (0.24, 0.76):
        _blob(surf, pygame.Rect(_p(S, u - 0.09, 0.3), (S * 0.18, S * 0.16)), PINK_DARK)
        _star(surf, _p(S, u, 0.38), S * 0.04, STAR_GOLD)
    # forward punching arm, fist out at (0.93, 0.44)
    _limb(surf, [_p(S, 0.74, 0.4), _p(S, 0.84, 0.43), _p(S, 0.9, 0.44)], S * 0.12, S * 0.1, PINK)
    _blob(surf, pygame.Rect(_p(S, 0.86, 0.38), (S * 0.13, S * 0.13)), CREAM)
    # head
    _blob(surf, pygame.Rect(_p(S, 0.39, 0.1), (S * 0.22, S * 0.24)), PINK)
    # gold horseshoe crest over the brow
    crest = pygame.Rect(_p(S, 0.4, 0.04), (S * 0.2, S * 0.18))
    pygame.draw.arc(surf, OUTLINE, crest.inflate(SS * 4, SS * 4), math.radians(10), math.radians(170), SS * 7)
    pygame.draw.arc(surf, STAR_GOLD, crest, math.radians(14), math.radians(166), SS * 4)
    # glowing eye slits
    for u in (0.46, 0.55):
        rect = pygame.Rect(0, 0, S * 0.07, S * 0.03)
        rect.center = _p(S, u, 0.23)
        pygame.draw.ellipse(surf, EYE_GLOW, rect)


_DRAWERS = {2: _act2, 3: _act3, 4: _act4}

#: Where each Act's fingertip/fist sits in its own procedural sprite (0..1,
#: facing right) — the plugin anchors the spinning nail / punch FX here.
TIP = {2: (0.94, 0.47), 3: (0.93, 0.44), 4: (0.95, 0.44)}

#: Optional art per Act (transparent PNGs under assets/). When the file
#: exists it replaces the procedural sprite above, scaled so its height is
#: the requested size (the art is portrait, not square).
PNG_PATH = {act: f"johnny/tusk-{act}.png" for act in (1, 2, 3, 4)}
#: Fingertip/claw/fist anchor in each PNG (0..1 of its own width/height,
#: as drawn — i.e. facing right): Act 2's right cannon arm, Act 3's right
#: claw, Act 4's right hand.
PNG_TIP = {1: (0.5, 0.6), 2: (0.95, 0.6), 3: (0.93, 0.6), 4: (0.9, 0.44)}

_PNG_CACHE = {}


def _load_png(act):
    """The Act's source PNG (unscaled), or None if it isn't there."""
    if act not in _PNG_CACHE:
        rel = PNG_PATH.get(act)
        path = os.path.join(ASSET_DIR, rel) if rel else None
        _PNG_CACHE[act] = pygame.image.load(path).convert_alpha() if path and os.path.exists(path) else None
    return _PNG_CACHE[act]


def make_tusk_sprite(act, size):
    key = (act, int(size))
    img = _CACHE.get(key)
    if img is None:
        src = _load_png(act)
        if src is not None:
            w, h = src.get_size()
            img = pygame.transform.smoothscale(src, (max(1, round(w * size / h)), int(size)))
        else:
            S = int(size) * SS
            big = pygame.Surface((S, S), pygame.SRCALPHA)
            # Act 1 has no procedural design of its own; it borrows Act 2's.
            _DRAWERS.get(act, _act2)(big, S)
            img = pygame.transform.smoothscale(big, (int(size), int(size)))
        _CACHE[key] = img
    return img


def tusk_tip_offset(act, size):
    """Offset from the sprite's center to its fingertip/fist, facing right —
    from PNG_TIP when the Act's PNG is in use, else from TIP."""
    img = make_tusk_sprite(act, size)
    w, h = img.get_size()
    u, v = PNG_TIP[act] if uses_png(act) else TIP.get(act, TIP[2])
    return pygame.Vector2((u - 0.5) * w, (v - 0.5) * h)


def uses_png(act):
    """Whether this Act is drawn from its PNG art (front-facing, so the
    plugin never mirrors it) rather than the procedural side-on sprite."""
    return _load_png(act) is not None
