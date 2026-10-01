"""Sans's sprite: just his head, assembled per frame from the cut-up sprite
sheet in assets/sans/parts/ — one face (grin, blink, wink, empty sockets,
glowing blue eye, ...) plus optional overlays (sweat). SansPlugin swaps
fighter.image for whichever face fits the current moment (see
SansPlugin._pose); every composite is cached, so a given face is only ever
built once per size/offset.

Faces are 32x30 pixel art, drawn at FACE_SCALE (nearest-neighbor, so they
stay crisp) and centered on the usual AVATAR_R * 2.4 square, leaving a few
pixels of headroom for the idle bob (`dy`)."""

import os

import pygame

from ...core.constants import ASSET_DIR, AVATAR_R

PARTS_DIR = os.path.join(ASSET_DIR, "sans", "parts")

NATIVE_SIZE = int(AVATAR_R * 2.4)
FACE_SCALE = 2

_PART_CACHE = {}
_POSE_CACHE = {}


def part(name):
    """One native-size part, e.g. part("face/face_00")."""
    img = _PART_CACHE.get(name)
    if img is None:
        img = pygame.image.load(os.path.join(PARTS_DIR, name + ".png")).convert_alpha()
        _PART_CACHE[name] = img
    return img


def compose(face, overlays=(), flip=False, dy=0, size=NATIVE_SIZE):
    """The full sprite for one moment. `face` is a face part ("face/face_00",
    "face_blue_eye/...", ...); `overlays` extra parts laid over it at the
    same origin (sweat); `flip` mirrors it to face left; `dy` nudges it up
    or down a few native pixels (the bob)."""
    key = (face, tuple(overlays), flip, dy, size)
    surf = _POSE_CACHE.get(key)
    if surf is not None:
        return surf

    head = part(face).copy()
    for name in overlays:
        head.blit(part(name), (0, 0))
    if flip:
        head = pygame.transform.flip(head, True, False)
    w, h = head.get_size()
    head = pygame.transform.scale(head, (w * FACE_SCALE, h * FACE_SCALE))

    canvas = pygame.Surface((NATIVE_SIZE, NATIVE_SIZE), pygame.SRCALPHA)
    canvas.blit(head, head.get_rect(center=(NATIVE_SIZE // 2, NATIVE_SIZE // 2 + dy)))
    if size != NATIVE_SIZE:
        canvas = pygame.transform.smoothscale(canvas, (size, size))
    _POSE_CACHE[key] = canvas
    return canvas


def make_sans_sprite(size):
    """The idle face: the usual grin."""
    return compose("face/face_00", size=size)
