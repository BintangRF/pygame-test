"""Before-Hassasin's weapon prop: the throwing dagger Twin Fangs' ranged
mode hurls (see plugin.py's _draw_one_knife).

dagger.png's own source art stands straight up but tip-DOWN (pommel at the
top), on a mostly empty 600x600 canvas - cropped to its opaque pixels and
flipped 180 degrees at load time here (upright() then straightens whatever
lean is left), so the rest of this character's code can treat it as a
normal tip-up prop like every other weapon (see rotate_to_dir's docstring in
core/effects.py)."""

import os

import pygame

from ...core.asset_loading import upright
from ...core.constants import ASSET_DIR

DAGGER_TARGET_H = 48


def load_before_hassasin_weapons():
    path = os.path.join(ASSET_DIR, "before_hassasin/dagger.png")
    image = pygame.image.load(path).convert_alpha()
    image = image.subsurface(image.get_bounding_rect()).copy()
    image = upright(image, 180)  # see module docstring
    w, h = image.get_size()
    scale = DAGGER_TARGET_H / h
    image = pygame.transform.smoothscale(image, (max(1, round(w * scale)), DAGGER_TARGET_H))
    return {"dagger": image}
