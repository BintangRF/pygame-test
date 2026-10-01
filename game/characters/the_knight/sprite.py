"""The Knight's sprite: just his mask, cut from the portrait in
assets/the_knight/the_knight.png (assets/the_knight/parts/head.png). The
mask has no expressions to swap, so it moves instead — KnightPlugin._pose
picks a tilt, a stretch, a bob and a tint (a white Soul glow while
focusing, a black Shade silhouette while dashing) for every moment, and
compose() builds that variant once and caches it."""

import os

import pygame

from ...core.constants import ASSET_DIR, AVATAR_R

PARTS_DIR = os.path.join(ASSET_DIR, "the_knight", "parts")

NATIVE_SIZE = int(AVATAR_R * 2.4)
# The mask fills this share of the square, leaving room to tilt and stretch.
HEAD_FILL = 0.84

_PART_CACHE = {}
_POSE_CACHE = {}


def part(name):
    """One part at its native size, e.g. part("vengeful_spirit/vengeful_spirit_00")."""
    img = _PART_CACHE.get(name)
    if img is None:
        img = pygame.image.load(os.path.join(PARTS_DIR, name + ".png")).convert_alpha()
        _PART_CACHE[name] = img
    return img


def _tinted(img, tint, amount):
    """`img` pushed toward white ("soul") or flattened to black ("shade") by
    `amount` (0-1) — or tinted pink ("crystal") — keeping its own alpha."""
    out = img.copy()
    if tint in ("soul", "crystal"):
        base = (150, 170, 200) if tint == "soul" else (170, 40, 120)
        glow = pygame.Surface(out.get_size(), pygame.SRCALPHA)
        glow.fill((round(base[0] * amount), round(base[1] * amount), round(base[2] * amount), 0))
        out.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif tint == "shade":
        v = round(255 * (1 - 0.88 * amount))
        out.fill((v, v, min(255, v + 20), 255), special_flags=pygame.BLEND_RGBA_MULT)
    elif tint == "gray":
        out.fill((150, 150, 160, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def compose(angle=0, sx=1.0, sy=1.0, dy=0, flip=False, tint=None, amount=0.0, base="head",
            size=NATIVE_SIZE):
    """The mask for one moment: rotated `angle` degrees (counterclockwise),
    stretched by sx/sy, nudged `dy` px, mirrored when `flip`, tinted by
    `tint` ("soul"/"crystal"/"shade"/"gray") at `amount`. Callers pass
    coarse values (whole degrees, a few stretch/tint steps) so the cache
    stays small. `base` swaps the mask itself (his broken mask on defeat)."""
    key = (angle, sx, sy, dy, flip, tint, amount, base, size)
    surf = _POSE_CACHE.get(key)
    if surf is not None:
        return surf

    head = part(base)
    side = round(NATIVE_SIZE * HEAD_FILL)
    head = pygame.transform.smoothscale(head, (max(1, round(side * sx)), max(1, round(side * sy))))
    if flip:
        head = pygame.transform.flip(head, True, False)
    if tint is not None:
        head = _tinted(head, tint, amount)
    if angle:
        head = pygame.transform.rotate(head, angle)

    canvas = pygame.Surface((NATIVE_SIZE, NATIVE_SIZE), pygame.SRCALPHA)
    canvas.blit(head, head.get_rect(center=(NATIVE_SIZE // 2, NATIVE_SIZE // 2 + dy)))
    if size != NATIVE_SIZE:
        canvas = pygame.transform.smoothscale(canvas, (size, size))
    _POSE_CACHE[key] = canvas
    return canvas


def make_the_knight_sprite(size):
    """The resting mask, upright."""
    return compose(size=size)
