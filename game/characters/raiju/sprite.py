"""Procedural placeholder sprite for Raiju — an electric beast battle orb.
No raiju.png asset exists, so this draws the orb body, a lightning-bolt
marking and face directly instead of loading a file."""

import pygame

from ...core.constants import RAIJU_CYAN


def make_raiju_sprite(size):
    """Deep-blue orb with a single bold lightning-bolt marking down the
    shell and sharp glowing eyes above it — kept inside a clean circular
    silhouette, and simple enough to still read at 32-48px."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    r = size * 0.46

    # base orb: dark navy rim, electric blue body, bright core for volume
    pygame.draw.circle(surf, (10, 16, 34), (c, c), r)
    pygame.draw.circle(surf, (28, 60, 130), (c, c), r * 0.9)
    pygame.draw.circle(surf, (70, 130, 210), (c - r * 0.32, c - r * 0.4), r * 0.24)
    pygame.draw.circle(surf, RAIJU_CYAN, (c, c), r, width=3)

    # sharp glowing eyes, set high so the bolt marking has the lower shell to itself
    eye_r = max(2, size * 0.055)
    for dx in (-0.3, 0.3):
        ex, ey = c + dx * size, c - 0.24 * size
        pygame.draw.polygon(surf, RAIJU_CYAN, [
            (ex - eye_r * 1.5, ey + eye_r * 0.3), (ex, ey - eye_r), (ex + eye_r * 1.5, ey + eye_r * 0.3),
            (ex, ey + eye_r * 0.6),
        ])
        pygame.draw.circle(surf, (240, 255, 255), (ex, ey), max(1, eye_r * 0.35))

    # one bold lightning-bolt marking, the character's single readable identity mark
    scale = r * 0.62
    ox, oy = c, c + r * 0.12
    bolt = [
        (ox + 0.08 * scale, oy - 0.83 * scale),
        (ox - 0.75 * scale, oy + 0.17 * scale),
        (ox + 0.0 * scale, oy + 0.17 * scale),
        (ox - 0.08 * scale, oy + 0.83 * scale),
        (ox + 0.75 * scale, oy - 0.17 * scale),
        (ox + 0.0 * scale, oy - 0.17 * scale),
    ]
    pygame.draw.polygon(surf, (235, 250, 255), bolt)
    pygame.draw.polygon(surf, RAIJU_CYAN, bolt, width=2)

    return surf
