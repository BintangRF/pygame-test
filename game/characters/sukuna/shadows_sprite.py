"""Ten Shadows sprites — one per shadow, so Sukuna's summons read as ten
distinct creatures instead of ten faded copies of his own orb (see
CharacterPlugin.clone_army/CloneArmy.draw's own sprite_for hook, and
SukunaPlugin._shadow_sprite). Real art exists in assets/sukuna/ for all ten
shadows now (divine-dogs.png, great-serpent.png, mahoraga.png,
max-elephant.png, nue.png, piercing-ox.png, rabbit-escape.png,
round-deer.png, tiger-funeral.png, toad.png — see _ASSET_FILES) — shadow_sprite()
prefers that file whenever one exists for a given key. The procedural _make_*
functions below stay on as a fallback for any key with no asset (see
shadow_sprite) rather than being deleted now that every current shadow has
real art — a future shadow added without one still gets a placeholder
instead of a crash. Same drawing techniques (circles, polygons, arcs, lines
on an SRCALPHA surface) as characters/sukuna/sprite.py's own
make_sukuna_sprite; every procedural shadow shares the same dark
shadow-body base (_shadow_base) and an accent-colored rim as their "cast
from Sukuna's own shadow" family resemblance, then layers its own
silhouette on top."""

import math

import pygame

from ...core.asset_loading import load_sprite
from ...core.constants import GOLD, GRAY, GREEN, ORANGE, POISON_COLOR, RED, SUKUNA_PINK, WHITE

_CACHE = {}

# Real art in assets/sukuna/ for every shadow — see the module docstring. Square
# RGBA PNGs, loaded the same way core/assets.py loads any character's own
# sprite (load_sprite scales to (size, size)).
_ASSET_FILES = {
    "divine_dog": "sukuna/divine-dogs.png",
    "nue": "sukuna/nue.png",
    "great_serpent": "sukuna/great-serpent.png",
    "toad": "sukuna/toad.png",
    "rabbit": "sukuna/rabbit-escape.png",
    "max_elephant": "sukuna/max-elephant.png",
    "piercing_ox": "sukuna/piercing-ox.png",
    "round_deer": "sukuna/round-deer.png",
    "tiger_funeral": "sukuna/tiger-funeral.png",
    "mahoraga": "sukuna/mahoraga.png",
}


def shadow_sprite(key, size, width=None):
    """Cached per (key, size, width) — a shadow's sprite never changes once
    drawn, so there's no reason to reload/redraw it every summon, same
    reasoning as Vampire's own _bat_sprite cache in
    characters/vampire/plugin.py. `width`, when smaller than `size`,
    squashes the result horizontally after it's built (Rabbit Escape only —
    see SukunaPlugin._shadow_sprite/RABBIT_WIDTH_SCALE — a narrower body on
    top of RABBIT_SPRITE_SCALE's own overall shrink)."""
    width = size if width is None else width
    cache_key = (key, size, width)
    img = _CACHE.get(cache_key)
    if img is None:
        filename = _ASSET_FILES.get(key)
        if filename is not None:
            img = load_sprite(filename, size)
        else:
            maker = _MAKERS.get(key, _make_generic)
            img = maker(size)
        if width != size:
            img = pygame.transform.smoothscale(img, (width, size))
        _CACHE[cache_key] = img
    return img


def _shadow_base(size, accent):
    """Every shadow's shared shell: a dark shadow-body with a brighter core
    for volume (same top-left light convention as make_sukuna_sprite) and
    an accent-colored rim instead of Sukuna's own SUKUNA_PINK one — Round
    Deer's own healer-green rim, say — so a shadow's own color story is
    readable even before its silhouette registers."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    r = size * 0.44
    pygame.draw.circle(surf, (14, 10, 16), (c, c), r)
    pygame.draw.circle(surf, (36, 26, 38), (c - r * 0.28, c - r * 0.3), r * 0.42)
    pygame.draw.circle(surf, accent, (c, c), r, width=3)
    return surf, c, r


def _eyes(surf, c, r, color, dx=0.16, dy=-0.06, eye_r_scale=0.09):
    eye_r = max(1.5, r * eye_r_scale)
    for sign in (-1, 1):
        pygame.draw.circle(surf, color, (c + sign * dx * r, c + dy * r), eye_r)


def _make_divine_dog(size):
    """Two pricked ears, a snarling snout with a fang, glowing eyes."""
    surf, c, r = _shadow_base(size, SUKUNA_PINK)
    for sign in (-1, 1):
        pygame.draw.polygon(surf, (14, 10, 16), [
            (c + sign * r * 0.55, c - r * 0.55), (c + sign * r * 0.85, c - r * 1.05), (c + sign * r * 0.25, c - r * 0.7),
        ])
    pygame.draw.polygon(surf, (10, 7, 11), [
        (c - r * 0.3, c + r * 0.3), (c + r * 0.3, c + r * 0.3), (c, c + r * 0.75),
    ])
    pygame.draw.polygon(surf, WHITE, [
        (c - r * 0.08, c + r * 0.35), (c + r * 0.08, c + r * 0.35), (c, c + r * 0.55),
    ])
    _eyes(surf, c, r, ORANGE)
    return surf


def _make_nue(size):
    """A sharp pale beak, swept-back wing flares, and a bright lightning-bolt
    streak — flighty and electric."""
    surf, c, r = _shadow_base(size, (120, 200, 255))
    for sign in (-1, 1):
        pygame.draw.polygon(surf, (60, 90, 130), [
            (c + sign * r * 0.35, c - r * 0.1), (c + sign * r * 1.0, c - r * 0.35), (c + sign * r * 0.75, c + r * 0.15),
            (c + sign * r * 0.3, c + r * 0.15),
        ])
    pygame.draw.polygon(surf, (240, 225, 180), [
        (c, c + r * 0.15), (c - r * 0.18, c - r * 0.15), (c + r * 0.18, c - r * 0.15),
    ])
    bolt = [
        (c - r * 0.15, c - r * 0.55), (c + r * 0.1, c - r * 0.15), (c - r * 0.05, c - r * 0.15),
        (c + r * 0.2, c + r * 0.4),
    ]
    pygame.draw.lines(surf, (210, 240, 255), False, bolt, width=max(2, int(size * 0.045)))
    _eyes(surf, c, r, (255, 255, 210), dy=-0.3, eye_r_scale=0.1)
    return surf


def _make_great_serpent(size):
    """A coiled S-shape with a pale venomous underbelly and slit eyes."""
    surf, c, r = _shadow_base(size, POISON_COLOR)
    coil = []
    for i in range(24):
        t = i / 23
        y = c - r * 0.75 + t * r * 1.5
        x = c + math.sin(t * math.tau * 1.3) * r * 0.4
        coil.append((x, y))
    pygame.draw.lines(surf, POISON_COLOR, False, coil, width=int(max(3, size * 0.09)))
    pygame.draw.lines(surf, (60, 90, 30), False, coil, width=max(1, int(size * 0.03)))
    head = coil[0]
    for sign in (-1, 1):
        pygame.draw.ellipse(surf, (230, 220, 60), (head[0] - 3 + sign * 2, head[1] - 4, 3, 5))
    return surf


def _make_toad(size):
    """A wide, flattened body, bulging top eyes, and warty spots — all in a
    swamp green bright enough to actually read against the dark shadow
    base, instead of the muddy same-as-background tones a real toad's
    skin would suggest."""
    surf, c, r = _shadow_base(size, GREEN)
    pygame.draw.ellipse(surf, (30, 60, 40), (c - r * 0.95, c - r * 0.25, r * 1.9, r * 1.0))
    for sign in (-1, 1):
        pygame.draw.circle(surf, GREEN, (c + sign * r * 0.32, c - r * 0.55), r * 0.24)
        pygame.draw.circle(surf, (20, 15, 10), (c + sign * r * 0.32, c - r * 0.55), r * 0.1)
    for dx, dy in ((-0.5, 0.15), (0.5, 0.1), (0.18, 0.35), (-0.18, 0.35)):
        pygame.draw.circle(surf, (150, 220, 140), (c + dx * r, c + dy * r), max(1.5, r * 0.07))
    pygame.draw.arc(
        surf, (20, 40, 25), (c - r * 0.5, c + r * 0.05, r, r * 0.5), math.pi * 0.1, math.pi * 0.9,
        width=max(2, int(size * 0.035)),
    )
    return surf


def _make_rabbit(size):
    """Two tall ears, a small nose, and a soft pale fur tuft."""
    surf, c, r = _shadow_base(size, WHITE)
    for sign in (-1, 1):
        pygame.draw.ellipse(surf, (14, 10, 16), (c + sign * r * 0.35 - r * 0.14, c - r * 1.25, r * 0.28, r * 0.95))
        pygame.draw.ellipse(surf, (230, 190, 200), (c + sign * r * 0.35 - r * 0.07, c - r * 1.1, r * 0.14, r * 0.65))
    pygame.draw.circle(surf, (240, 230, 235), (c, c + r * 0.2), r * 0.16)
    pygame.draw.circle(surf, (230, 140, 150), (c, c + r * 0.12), r * 0.06)
    for sign in (-1, 1):
        for k in range(2):
            pygame.draw.line(surf, WHITE, (c, c + r * 0.15), (c + sign * r * 0.6, c + r * (0.05 + k * 0.12)), width=1)
    _eyes(surf, c, r, (200, 60, 70), dy=-0.05)
    return surf


def _make_max_elephant(size):
    """Big floppy ears, a curling trunk, and small pale tusks — the heavy,
    tanky one. Ears/trunk are a mid gray, bright enough to actually
    silhouette against the dark shadow-body instead of blending into it."""
    surf, c, r = _shadow_base(size, GRAY)
    ear_color = (100, 96, 108)
    for sign in (-1, 1):
        pygame.draw.ellipse(surf, ear_color, (c + sign * r * 0.55 - r * 0.4, c - r * 0.35, r * 0.8, r * 0.95))
        pygame.draw.ellipse(
            surf, (60, 56, 66), (c + sign * r * 0.55 - r * 0.4, c - r * 0.35, r * 0.8, r * 0.95), width=2,
        )
    trunk = [(c, c + r * 0.15), (c - r * 0.05, c + r * 0.55), (c + r * 0.2, c + r * 0.75), (c + r * 0.05, c + r * 0.9)]
    pygame.draw.lines(surf, (90, 86, 96), False, trunk, width=int(max(3, size * 0.1)))
    for sign in (-1, 1):
        pygame.draw.line(
            surf, (235, 230, 220), (c + sign * r * 0.12, c + r * 0.35), (c + sign * r * 0.3, c + r * 0.55), width=3,
        )
    _eyes(surf, c, r, (230, 190, 120), dx=0.2, dy=-0.05, eye_r_scale=0.07)
    return surf


def _make_piercing_ox(size):
    """Curved bronze horns and a nose ring — built to charge in a straight
    line."""
    surf, c, r = _shadow_base(size, (200, 150, 80))
    horn_color = (200, 150, 80)
    horn_width = int(max(2, size * 0.06))
    # Left horn: an arc swept from the top of its own bounding box down to
    # the outer side, so it curves outward-and-up; the right horn is the
    # exact mirror, its own bounding box shifted to the other side instead
    # of reusing one rect with a sign flip (an ellipse arc doesn't mirror
    # cleanly under a coordinate negation the way a point does).
    left_rect = (c - r * 0.95, c - r * 1.1, r * 0.9, r * 0.85)
    right_rect = (c + r * 0.05, c - r * 1.1, r * 0.9, r * 0.85)
    pygame.draw.arc(surf, horn_color, left_rect, math.pi * 0.05, math.pi * 0.75, width=horn_width)
    pygame.draw.arc(surf, horn_color, right_rect, math.pi * 0.25, math.pi * 0.95, width=horn_width)
    pygame.draw.circle(surf, (14, 10, 16), (c, c + r * 0.35), r * 0.18)
    pygame.draw.circle(surf, (210, 190, 160), (c, c + r * 0.35), r * 0.12, width=2)
    _eyes(surf, c, r, RED, dy=-0.15)
    return surf


def _make_round_deer(size):
    """Branching antlers and gentle eyes, ringed in healer green instead of
    Sukuna's usual pink — the one shadow that never fights. Antlers/eyes are
    a pale bone color so they read clearly against the dark shadow-body,
    instead of the too-dark brown that used to all but disappear on it."""
    surf, c, r = _shadow_base(size, GREEN)
    antler_color = (215, 195, 150)
    for sign in (-1, 1):
        base = (c + sign * r * 0.18, c - r * 0.55)
        mid = (c + sign * r * 0.35, c - r * 1.0)
        tip_a = (c + sign * r * 0.15, c - r * 1.25)
        tip_b = (c + sign * r * 0.55, c - r * 1.2)
        pygame.draw.lines(surf, antler_color, False, [base, mid, tip_a], width=max(2, int(size * 0.03)))
        pygame.draw.lines(surf, antler_color, False, [mid, tip_b], width=max(2, int(size * 0.03)))
    _eyes(surf, c, r, (150, 115, 75), eye_r_scale=0.1)
    pygame.draw.circle(surf, (*GREEN, 110), (int(c), int(c)), int(r * 1.05), width=3)
    return surf


def _make_tiger_funeral(size):
    """Diagonal tiger stripes and fierce eyes — the decoy/bait shadow.
    Stripes are drawn in the bright orange accent itself (a real tiger's
    dark stripes would vanish into this game's already-dark shadow-body),
    so the pattern actually reads instead of disappearing into the shell."""
    stripe_color = (230, 140, 40)
    surf, c, r = _shadow_base(size, stripe_color)
    for sign in (-1, 1):
        pygame.draw.polygon(surf, (14, 10, 16), [
            (c + sign * r * 0.5, c - r * 0.5), (c + sign * r * 0.8, c - r * 0.95), (c + sign * r * 0.2, c - r * 0.65),
        ])
        pygame.draw.polygon(surf, stripe_color, [
            (c + sign * r * 0.5, c - r * 0.5), (c + sign * r * 0.8, c - r * 0.95), (c + sign * r * 0.2, c - r * 0.65),
        ], width=1)
    for i in range(4):
        offset = -r * 0.5 + i * r * 0.35
        pygame.draw.line(
            surf, stripe_color, (c - r * 0.5, c + offset), (c + r * 0.15, c + offset + r * 0.35),
            width=max(2, int(size * 0.035)),
        )
    _eyes(surf, c, r, GOLD, dy=-0.02, eye_r_scale=0.1)
    return surf


def _make_mahoraga(size):
    """The rare jackpot pull: a horned, masked face with a concentric
    "wheel" motif on its brow — bigger, gaudier, unmistakably a cut above
    the other nine."""
    surf, c, r = _shadow_base(size, GOLD)
    for sign in (-1, 1):
        horn = [
            (c + sign * r * 0.3, c - r * 0.5), (c + sign * r * 0.75, c - r * 0.85), (c + sign * r * 0.9, c - r * 1.3),
            (c + sign * r * 0.55, c - r * 0.95), (c + sign * r * 0.15, c - r * 0.65),
        ]
        pygame.draw.polygon(surf, (200, 160, 60), horn)
        pygame.draw.polygon(surf, (120, 90, 30), horn, width=1)
    for radius_pct in (0.5, 0.32, 0.14):
        pygame.draw.circle(surf, GOLD, (c, c - r * 0.05), r * radius_pct, width=2)
    pygame.draw.circle(surf, RED, (c, c - r * 0.05), r * 0.08)
    pygame.draw.rect(surf, (14, 10, 16), (c - r * 0.55, c + r * 0.25, r * 1.1, r * 0.35), border_radius=3)
    return surf


def _make_generic(size):
    """Fallback for any key with no dedicated maker — shouldn't come up in
    practice since every SHADOWS entry has one, but keeps shadow_sprite() safe
    either way."""
    surf, c, r = _shadow_base(size, SUKUNA_PINK)
    _eyes(surf, c, r, ORANGE)
    return surf


_MAKERS = {
    "divine_dog": _make_divine_dog,
    "nue": _make_nue,
    "great_serpent": _make_great_serpent,
    "toad": _make_toad,
    "rabbit": _make_rabbit,
    "max_elephant": _make_max_elephant,
    "piercing_ox": _make_piercing_ox,
    "round_deer": _make_round_deer,
    "tiger_funeral": _make_tiger_funeral,
    "mahoraga": _make_mahoraga,
}
