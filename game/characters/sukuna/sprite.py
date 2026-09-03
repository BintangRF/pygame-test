"""Procedural placeholder sprite for Sukuna — a cursed crimson battle orb.
No sukuna.png asset exists, so this draws the orb body, cursed markings and
face directly instead of loading a file."""

import math

import pygame

from ...core.constants import SUKUNA_PINK


def make_sukuna_sprite(size):
    """Deep crimson orb with cursed markings wrapping the shell, four sharp
    eyes, aggressive brows and a small sinister smile."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    r = size * 0.46

    # base orb: near-black rim, crimson body, brighter core for volume,
    # small highlight for the game's consistent top-left light direction
    pygame.draw.circle(surf, (35, 6, 10), (c, c), r)
    pygame.draw.circle(surf, (150, 24, 34), (c, c), r * 0.9)
    pygame.draw.circle(surf, (195, 55, 50), (c - r * 0.3, c - r * 0.32), r * 0.34)
    pygame.draw.circle(surf, SUKUNA_PINK, (c, c), r, width=3)

    # cursed markings wrapping the lower shell
    mark_color = (20, 4, 8)
    for side in (-1, 1):
        start = math.pi * 0.08 if side < 0 else math.pi * 0.58
        pygame.draw.arc(
            surf, mark_color,
            pygame.Rect(c - r * 0.95, c - r * 0.15, r * 1.9, r * 1.7),
            start, start + math.pi * 0.3, width=2,
        )
    for dx in (-0.3, 0.3):
        pygame.draw.line(
            surf, mark_color,
            (c + dx * size * 0.9, c + r * 0.15), (c + dx * size * 0.7, c + r * 0.45), width=2,
        )

    # aggressive brows
    brow_y = c - r * 0.32
    for dx in (-1, 1):
        pygame.draw.line(
            surf, (15, 3, 6),
            (c + dx * r * 0.44, brow_y - r * 0.05),
            (c + dx * r * 0.12, brow_y + r * 0.06),
            width=3,
        )

    # four sharp eyes, Sukuna's signature
    eye_color = (250, 150, 40)
    eye_r = max(2, size * 0.045)
    for dx in (-0.34, -0.12, 0.12, 0.34):
        ex, ey = c + dx * size, c - 0.08 * size
        pygame.draw.polygon(surf, eye_color, [
            (ex - eye_r * 1.5, ey), (ex, ey - eye_r * 0.85), (ex + eye_r * 1.5, ey), (ex, ey + eye_r * 0.85),
        ])
        pygame.draw.circle(surf, (30, 5, 5), (ex, ey), max(1, eye_r * 0.4))

    # small sinister smirk — asymmetric, corner pulled up, with a fang
    mouth_y = c + r * 0.36
    smirk = [
        (c - size * 0.15, mouth_y + size * 0.02),
        (c - size * 0.02, mouth_y + size * 0.045),
        (c + size * 0.05, mouth_y - size * 0.03),
        (c + size * 0.15, mouth_y - size * 0.07),
    ]
    pygame.draw.lines(surf, (15, 3, 6), False, smirk, width=3)
    fang = [
        (c - size * 0.05, mouth_y + size * 0.035),
        (c - size * 0.015, mouth_y + size * 0.035),
        (c - size * 0.032, mouth_y + size * 0.09),
    ]
    pygame.draw.polygon(surf, (245, 235, 225), fang)

    return surf
