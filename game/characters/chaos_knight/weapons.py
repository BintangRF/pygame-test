"""The Chaos Knight's weapon prop (see plugin.py for how it's animated).

mace.png's own source art rests along a diagonal (handle at the lower-left,
head at the upper-right) instead of the tip-up orientation every other
weapon sprite/weapon_angle()'s own convention assumes (see rotate_to_dir's
docstring in core/effects.py) — pre-rotated 45 degrees at load time here,
the same fix Vampire's bats.png needed (see _bat_sprite in
characters/vampire/plugin.py), so the rest of this character's code can
treat it as a normal tip-up prop like every other weapon."""

import os

import pygame

from ...core.constants import ASSET_DIR

MACE_TARGET_H = 95


def load_chaos_knight_weapons():
    path = os.path.join(ASSET_DIR, "mace.png")
    image = pygame.image.load(path).convert_alpha()
    image = pygame.transform.rotate(image, 45)  # see module docstring
    w, h = image.get_size()
    scale = MACE_TARGET_H / h
    image = pygame.transform.smoothscale(image, (max(1, round(w * scale)), MACE_TARGET_H))
    return {"mace": image}
