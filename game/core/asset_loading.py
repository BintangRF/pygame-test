"""Generic sprite/weapon loading primitives — kept separate from
core/assets.py's CHARACTERS registry (which imports every character's own
plugin.py) so that a character's weapons.py can import these without
creating an import cycle back through the registry."""

import math
import os

import pygame

from .constants import ASSET_DIR

# Weapon/projectile art is expected tip-up (see rotate_to_dir's docstring in
# core/effects.py), but source PNGs are rarely drawn exactly vertical — a
# shaft a few degrees off reads as visibly crooked once it flies dead
# horizontal or vertical. upright() measures the art's own long axis and
# rotates the leftover lean out, so no character needs a hand-measured angle
# like 230.25. Leans bigger than MAX_AUTO_STRAIGHTEN_DEG are a wrong coarse
# orientation (art drawn diagonal or tip-down), not a slight tilt — those are
# the caller's to fix via pre_rotate, never guessed here.
MAX_AUTO_STRAIGHTEN_DEG = 20
# Below this length:width ratio the art has no clear long axis (a shield, an
# orb, a bat's spread wings) and its measured "axis" is noise.
MIN_STRAIGHTEN_ELONGATION = 2.5
# The axis is measured on the opaque-pixel mask shrunk to this many pixels
# on its longer side — plenty for sub-degree accuracy, cheap in pure Python.
_AXIS_MEASURE_SIZE = 160
_ALPHA_THRESHOLD = 40


def axis_lean(image):
    """Degrees to pass to pygame.transform.rotate (counterclockwise-positive)
    that would bring `image`'s long axis to true vertical, taken from the
    second moments of its opaque pixels. None when the art has no clear long
    axis (see MIN_STRAIGHTEN_ELONGATION)."""
    mask = pygame.mask.from_surface(image, _ALPHA_THRESHOLD)
    w, h = mask.get_size()
    k = _AXIS_MEASURE_SIZE / max(w, h)
    if k < 1:
        mask = mask.scale((max(1, round(w * k)), max(1, round(h * k))))
        w, h = mask.get_size()
    n = sx = sy = sxx = syy = sxy = 0
    for y in range(h):
        for x in range(w):
            if mask.get_at((x, y)):
                n += 1
                sx += x
                sy += y
                sxx += x * x
                syy += y * y
                sxy += x * y
    if n < 2:
        return None
    cx, cy = sx / n, sy / n
    mu20 = sxx / n - cx * cx
    mu02 = syy / n - cy * cy
    mu11 = sxy / n - cx * cy
    spread = math.hypot(mu20 - mu02, 2 * mu11)
    major = (mu20 + mu02 + spread) / 2
    minor = (mu20 + mu02 - spread) / 2
    if minor <= 0 or math.sqrt(major / minor) < MIN_STRAIGHTEN_ELONGATION:
        return None
    # Long axis angle in screen coords (y down), then the rotation that
    # stands it up, folded into [-90, 90).
    theta = math.degrees(0.5 * math.atan2(2 * mu11, mu20 - mu02))
    return (theta + 180) % 180 - 90


def upright(image, pre_rotate=0.0):
    """Rotate `image` by the caller's coarse `pre_rotate` (which end is the
    tip: 45 for art resting diagonally tip at the upper-right, 180 for art
    drawn tip-down, ...), then by whatever small lean axis_lean() still
    measures, in a single rotation so the art is only resampled once."""
    turned = pygame.transform.rotate(image, pre_rotate) if pre_rotate else image
    lean = axis_lean(turned)
    if lean is None or abs(lean) > MAX_AUTO_STRAIGHTEN_DEG or abs(lean) < 0.1:
        return turned
    return pygame.transform.rotate(image, pre_rotate + lean)


def load_sprite(filename, size):
    path = os.path.join(ASSET_DIR, filename)
    image = pygame.image.load(path).convert_alpha()
    return pygame.transform.smoothscale(image, (size, size))


def character_sprite(spec, size):
    """Load a character's sprite: from its PNG file, or via its procedural
    sprite_fn for fighters (currently Sukuna, Raiju, and Johnny) that don't
    have one."""
    sprite_fn = spec.get("sprite_fn")
    if sprite_fn is not None:
        return sprite_fn(size)
    return load_sprite(spec["sprite"], size)


def load_weapon(filename, target_h, pre_rotate=0.0):
    """Load a weapon/projectile prop standing straight tip-up (see upright()),
    scaling by height so its proportions stay intact."""
    path = os.path.join(ASSET_DIR, filename)
    image = upright(pygame.image.load(path).convert_alpha(), pre_rotate)
    w, h = image.get_size()
    scale = target_h / h
    return pygame.transform.smoothscale(image, (max(1, round(w * scale)), target_h))


def load_weapon_or_fallback(filename, fallback_filename, target_h):
    """Like load_weapon, but falls back to another file if `filename` is missing
    (used so a dedicated shield.png can be dropped in later without code changes)."""
    path = os.path.join(ASSET_DIR, filename)
    if not os.path.exists(path):
        filename = fallback_filename
    return load_weapon(filename, target_h)


_ANIMATION_FRAME_CACHE = {}


def load_animation_frames(dirname, prefix, count, size):
    """Load a numbered flipbook (assets/<dirname>/<prefix>-1.png ..
    <prefix>-<count>.png), each scaled to `size` across — cached per
    (dirname, prefix, count, size) so a caller that plays the same flipbook
    every frame (e.g. draw_slash_fx in effects.py) doesn't reload/rescale
    from disk each time."""
    key = (dirname, prefix, count, size)
    frames = _ANIMATION_FRAME_CACHE.get(key)
    if frames is None:
        frames = [load_sprite(f"{dirname}/{prefix}-{i}.png", size) for i in range(1, count + 1)]
        _ANIMATION_FRAME_CACHE[key] = frames
    return frames
