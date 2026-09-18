"""Leonidas's spear prop — held by Leonidas himself and by every Spartan
conjured by This Is Sparta! (see plugin.py).

The source image rests along a diagonal (blade tip at the upper-right, grip/
tassel at the lower-left) instead of the tip-up orientation weapon_angle()/
rotate_to_dir()'s own convention assumes (see rotate_to_dir's docstring in
core/effects.py) — pre-rotated 45 degrees at load time here, the same fix
Legion Commander's scepter/arrow and Chaos Knight's mace needed (see their
own weapons.py), so the rest of this character's code can treat it as a
normal tip-up prop/projectile like everyone else's."""

import os

import pygame

from ...core.constants import ASSET_DIR

SPEAR_TARGET_H = 120


def load_leonidas_weapons():
    path = os.path.join(ASSET_DIR, "leonidas/spear.png")
    image = pygame.image.load(path).convert_alpha()
    image = pygame.transform.rotate(image, 45)  # see module docstring
    w, h = image.get_size()
    scale = SPEAR_TARGET_H / h
    spear = pygame.transform.smoothscale(image, (max(1, round(w * scale)), SPEAR_TARGET_H))
    return {"spear": spear}
