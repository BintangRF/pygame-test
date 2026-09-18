"""Generic sprite/weapon loading primitives — kept separate from
core/assets.py's CHARACTERS registry (which imports every character's own
plugin.py) so that a character's weapons.py can import these without
creating an import cycle back through the registry."""

import os

import pygame

from .constants import ASSET_DIR


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


def load_weapon(filename, target_h):
    """Load a weapon prop, scaling by height so its proportions stay intact."""
    path = os.path.join(ASSET_DIR, filename)
    image = pygame.image.load(path).convert_alpha()
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
