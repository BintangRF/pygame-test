"""Pac-Man's sprites, cut from the arcade sheet in assets/pacman/image.png
(assets/pacman/parts/, background keyed out): Pac-Man's own mouth frames
for each direction, his death animation, the giant intermission Pac-Man
(Super Pac-Man), the four ghosts in every direction, the frightened ghost,
the ghosts' eyes, Blinky's torn / patched / naked intermission frames, the
eight bonus fruits and the score numbers. All of it is
16-bit-era pixel art on 32 px cells, drawn at a whole-number scale
(nearest-neighbour) so it stays crisp, and cached per frame/scale/facing.
Only the pellets have no sprite in the sheet — PacmanPlugin draws those as
plain dots."""

import os

import pygame

from ...core.constants import ASSET_DIR, AVATAR_R

PARTS_DIR = os.path.join(ASSET_DIR, "pacman", "parts")
NATIVE_SIZE = int(AVATAR_R * 2.4)
PIXEL_SCALE = 2
CELL = 32

_PART_CACHE = {}
_CACHE = {}


def part(name):
    img = _PART_CACHE.get(name)
    if img is None:
        img = pygame.image.load(os.path.join(PARTS_DIR, name + ".png")).convert_alpha()
        _PART_CACHE[name] = img
    return img


def scaled(name, scale=PIXEL_SCALE):
    """A part blown up `scale` times, always nearest-neighbour so the
    pixel art stays crisp (a fractional scale just doubles some pixels)."""
    key = ("scaled", name, scale)
    img = _CACHE.get(key)
    if img is None:
        src = part(name)
        w, h = src.get_size()
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        img = pygame.transform.scale(src, size)
        _CACHE[key] = img
    return img


def direction_name(v):
    """"right"/"left"/"up"/"down" for whichever axis dominates `v`."""
    if v.length_squared() == 0:
        return "right"
    if abs(v.x) >= abs(v.y):
        return "right" if v.x >= 0 else "left"
    return "down" if v.y > 0 else "up"


def _on_canvas(img, canvas_size):
    canvas = pygame.Surface((canvas_size, canvas_size), pygame.SRCALPHA)
    canvas.blit(img, img.get_rect(center=(canvas_size // 2, canvas_size // 2)))
    return canvas


def pac(direction, mouth, scale=1.0, size=NATIVE_SIZE):
    """Pac-Man facing `direction`, `mouth` "open"/"half"/"closed", drawn
    `scale` times his normal size on a size x size square (bigger squares
    for scale > 1, so nothing is cropped)."""
    key = ("pac", direction, mouth, scale, size)
    surf = _CACHE.get(key)
    if surf is None:
        name = "pac/pac_closed" if mouth == "closed" else f"pac/pac_{direction}_{mouth}"
        px = PIXEL_SCALE * size / NATIVE_SIZE * scale
        img = scaled(name, px)
        surf = _on_canvas(img, max(size, round(size * scale)))
        _CACHE[key] = surf
    return surf


def big_pac(direction, mouth, scale=1.0):
    """The giant intermission Pac-Man (Super Pac-Man) — the sheet only has
    him facing right, so the other facings are rotated/mirrored from it."""
    key = ("big", direction, mouth, scale)
    surf = _CACHE.get(key)
    if surf is None:
        img = scaled(f"big/big_{mouth}", scale)
        if direction == "left":
            img = pygame.transform.flip(img, True, False)
        elif direction == "up":
            img = pygame.transform.rotate(img, 90)
        elif direction == "down":
            img = pygame.transform.rotate(img, -90)
        surf = img
        _CACHE[key] = surf
    return surf


def death(frame, size=NATIVE_SIZE):
    """Death animation frame 0-9, or "spark" for the final pop."""
    name = "death/death_spark" if frame == "spark" else f"death/death_{frame:02d}"
    key = ("death", name, size)
    surf = _CACHE.get(key)
    if surf is None:
        surf = _on_canvas(scaled(name, PIXEL_SCALE * size / NATIVE_SIZE), size)
        _CACHE[key] = surf
    return surf


def ghost(name, direction, frame, scale=1.5):
    return scaled(f"ghost/{name}_{direction}_{frame % 2}", scale)


def fright(white, frame, scale=1.0):
    return scaled(f"ghost/fright_{'white' if white else 'blue'}_{frame % 2}", scale)


def eyes(direction, scale=1.5):
    return scaled(f"ghost/eyes_{direction}", scale)


def intermission(name, scale=1.5):
    """An intermission piece: "nail", "torn_piece", "blinky_torn_0/1",
    "blinky_patched_0/1", "blinky_naked_0/1"."""
    return scaled(f"intermission/{name}", scale)


def fruit(name, scale=1.0):
    return scaled(f"fruit/{name}", scale)


def score(value, scale=1.0):
    return scaled(f"score/score_{value}", scale)


def make_pacman_sprite(size):
    """The resting sprite: mouth half open, facing right."""
    return pac("right", "half", size=size)
