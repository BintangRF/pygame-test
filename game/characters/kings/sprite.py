"""Kings's sprites, all cut from the two sheets in assets/kings/:

  - his head: one of four masks from kings.png (assets/kings/parts/masks/):
    "king" (the gold crown-mask with the emerald, his resting face), "cast"
    (the red masquerade, worn while he plays a hand), "reversed" (the violet
    crescent, flashed whenever fate turns against him) and "ultimate" (the
    horned blue mask of the Three Card Spread). KingsPlugin._pose picks the
    mask, tilt and bob for every moment; compose() builds it once and caches.
  - the 21 Major Arcana, 0 The Fool to XX Judgement, from cards.png
    (assets/kings/parts/cards/), in that sheet's own numbering (it has The
    World as XVII and no Star). A card not yet turned up is its own art
    darkened, not a separate card back."""

import os

import pygame

from ...core.constants import ASSET_DIR, AVATAR_R

PARTS_DIR = os.path.join(ASSET_DIR, "kings", "parts")

NATIVE_SIZE = int(AVATAR_R * 2.4)
# Every mask is fitted to this share of the square's width.
MASK_FILL = 0.9
HIDDEN_SHADE = (60, 45, 80, 255)

_PART_CACHE = {}
_POSE_CACHE = {}
_CARD_CACHE = {}


def part(name):
    """One part at its native size, e.g. part("masks/king"), part("cards/tower")."""
    img = _PART_CACHE.get(name)
    if img is None:
        img = pygame.image.load(os.path.join(PARTS_DIR, name + ".png")).convert_alpha()
        _PART_CACHE[name] = img
    return img


def card_image(card, w, h, hidden=False):
    """One card's art at w x h, upside down while it's reversed, darkened
    while `hidden` (dealt but not yet turned up)."""
    key = (card.name, w, h, hidden, card.reversed)
    img = _CARD_CACHE.get(key)
    if img is None:
        img = pygame.transform.smoothscale(part(f"cards/{card.name}"), (w, h))
        if hidden:
            img.fill(HIDDEN_SHADE, special_flags=pygame.BLEND_RGBA_MULT)
        elif card.reversed:
            img = pygame.transform.rotate(img, 180)
        _CARD_CACHE[key] = img
    return img


def compose(mask="king", angle=0, dy=0, flip=False, gray=False, size=NATIVE_SIZE):
    """The head for one moment: `mask` ("king"/"cast"/"reversed"/"ultimate")
    fitted to the square, rotated `angle` degrees, nudged `dy` px, mirrored
    when `flip`, washed out when `gray` (defeat). Callers pass coarse values
    so the cache stays small."""
    key = (mask, angle, dy, flip, gray, size)
    surf = _POSE_CACHE.get(key)
    if surf is not None:
        return surf

    head = part(f"masks/{mask}")
    w, h = head.get_size()
    tw = round(NATIVE_SIZE * MASK_FILL)
    head = pygame.transform.smoothscale(head, (tw, max(1, round(h * tw / w))))
    if flip:
        head = pygame.transform.flip(head, True, False)
    if gray:
        head = head.copy()
        head.fill((120, 120, 130, 255), special_flags=pygame.BLEND_RGBA_MULT)
    if angle:
        head = pygame.transform.rotate(head, angle)

    canvas = pygame.Surface((NATIVE_SIZE, NATIVE_SIZE), pygame.SRCALPHA)
    canvas.blit(head, head.get_rect(center=(NATIVE_SIZE // 2, NATIVE_SIZE // 2 + dy)))
    if size != NATIVE_SIZE:
        canvas = pygame.transform.smoothscale(canvas, (size, size))
    _POSE_CACHE[key] = canvas
    return canvas


def make_kings_sprite(size):
    """The resting crown-mask."""
    return compose(size=size)
