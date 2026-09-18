"""Arjuna's own weapon props: the bow (rested idle, drawn back and released
for every arrow-motion ability) and the arrow it fires.

Both source images (bow.png, arrow.png) rest along a diagonal instead of the
tip-up orientation weapon_angle()/rotate_to_dir()'s own convention assumes
(see rotate_to_dir's docstring in core/effects.py) — pre-rotated at load time
here, the same fix Chaos Knight's mace.png and Legion Commander's own
scepter/arrow needed (see their own weapons.py). The two images do NOT sit at
exactly the same diagonal despite looking alike at a glance — a single
shared angle (225 degrees, picked by eye) left the bow under a degree off
but the arrow about 5 degrees off, just enough that a shot flying near-
horizontal or near-vertical visibly leaned off-axis instead of tracking
straight. ARROW_PRE_ROTATE/BOW_PRE_ROTATE below were each measured directly
off their own image (principal axis of the opaque pixels, head end picked by
which side is darker) rather than eyeballed, and land within ~0.1 degree of
true vertical."""

import os

import pygame

from ...core.constants import ASSET_DIR

BOW_TARGET_H = 150
# Bumped twice now (42 -> 66 -> this) — still unreadable in the real arena at
# normal viewing distance: arrow.png's own visible shaft only fills a
# fraction of its source canvas's height once rotated upright (see the
# ARROW_PRE_ROTATE comment above), and a thin fast-moving sliver is easy to
# miss even once its bounding box is "big enough" on paper. One fixed size
# for every ability (basic, skill, and Devadatta's own arrow in plugin.py) —
# never scaled down or up per ability.
ARROW_TARGET_H = 140
ARROW_PRE_ROTATE = 230.25
BOW_PRE_ROTATE = 224.0


def _load(filename, target_h, pre_rotate):
    path = os.path.join(ASSET_DIR, filename)
    image = pygame.image.load(path).convert_alpha()
    image = pygame.transform.rotate(image, pre_rotate)
    w, h = image.get_size()
    scale = target_h / h
    return pygame.transform.smoothscale(image, (max(1, round(w * scale)), target_h))


def load_arjuna_weapons():
    return {
        "bow": _load("arjuna/bow.png", BOW_TARGET_H, BOW_PRE_ROTATE),
        "arrow": _load("arjuna/arrow.png", ARROW_TARGET_H, ARROW_PRE_ROTATE),
    }
