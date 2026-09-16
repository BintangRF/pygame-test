"""The Legion Commander's weapon props: the scepter (rested idle, swung for
Scepter Strike, and swung again for Duel's guaranteed follow-up) and the
flame-arrow projectile Overwhelming Odds fires.

Both source images rest along a diagonal (head/tip at the upper-right,
handle/fletching at the lower-left) instead of the tip-up orientation
weapon_angle()/rotate_to_dir()'s own convention assumes (see rotate_to_dir's
docstring in core/effects.py) — pre-rotated 45 degrees at load time here,
the same fix Chaos Knight's mace.png needed (see
characters/chaos_knight/weapons.py), so the rest of this character's code
can treat both as normal tip-up props/projectiles like everyone else's."""

import os

import pygame

from ...core.constants import ASSET_DIR

SCEPTER_TARGET_H = 100

# The Overwhelming Odds arrow sprite, loaded once per pixel size and cached
# — same pattern as Vampire's own _bat_sprite (characters/vampire/plugin.py).
# ARROW_SIZE_FALLBACK only matters if an ability somehow omits its own
# Ability.swarm_size (see abilities.py); Overwhelming Odds always sets one
# (see moves.py), so this is really just a safety net.
ARROW_SIZE_FALLBACK = 46
_ARROW_CACHE = {}


def load_legion_commander_weapons():
    path = os.path.join(ASSET_DIR, "legion-commander-scepter.png")
    image = pygame.image.load(path).convert_alpha()
    image = pygame.transform.rotate(image, 45)  # see module docstring
    w, h = image.get_size()
    scale = SCEPTER_TARGET_H / h
    scepter = pygame.transform.smoothscale(image, (max(1, round(w * scale)), SCEPTER_TARGET_H))
    return {"scepter": scepter}


def flame_arrow_sprite(size=ARROW_SIZE_FALLBACK):
    img = _ARROW_CACHE.get(size)
    if img is None:
        path = os.path.join(ASSET_DIR, "legion-commander-arrow.png")
        raw = pygame.image.load(path).convert_alpha()
        raw = pygame.transform.rotate(raw, 45)  # see module docstring
        w, h = raw.get_size()
        scale = size / h
        img = pygame.transform.smoothscale(raw, (max(1, round(w * scale)), size))
        _ARROW_CACHE[size] = img
    return img
