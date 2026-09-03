"""Procedural placeholder sprite for Johnny Joestar — a stylish precision
battle orb. No johnny.png asset exists, so this draws a wide-brimmed riding
hat over a navy orb with a spiral "Spin" motif and a nail crossed at the
brow instead of loading a file."""

import pygame

from ...core.constants import GOLD, JOHNNY_GREEN, NAIL_SILVER


def make_johnny_sprite(size):
    """Navy/royal-blue orb (not a literal face) with a hat, spiral marking
    and calm spiral eyes — clean and controlled next to Sukuna/Raiju."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    r = size * 0.44

    # base orb: dark navy rim, royal blue body, bright core for volume
    pygame.draw.circle(surf, (10, 14, 26), (c, c + size * 0.03), r)
    pygame.draw.circle(surf, (30, 48, 95), (c, c + size * 0.03), r * 0.9)
    pygame.draw.circle(surf, (70, 95, 165), (c - r * 0.42, c + r * 0.08), r * 0.2)
    pygame.draw.circle(surf, (225, 230, 235), (c, c + size * 0.03), r, width=2)
    pygame.draw.circle(surf, GOLD, (c, c + size * 0.03), r * 0.98, width=1)

    # spiral "Spin" motif on the lower shell
    spiral_c = (c, c + r * 0.42)
    for i, ring_r in enumerate((r * 0.34, r * 0.22, r * 0.1)):
        pygame.draw.circle(surf, (200, 210, 225), spiral_c, ring_r, width=1)

    # hat, bouncing slightly independently on top of the orb
    brim_rect = pygame.Rect(0, 0, size * 1.0, size * 0.3)
    brim_rect.center = (c, c - r * 0.65)
    pygame.draw.ellipse(surf, JOHNNY_GREEN, brim_rect)
    pygame.draw.ellipse(surf, (40, 60, 35), brim_rect, width=2)
    crown_rect = pygame.Rect(0, 0, size * 0.48, size * 0.32)
    crown_rect.center = (c, c - r * 0.95)
    pygame.draw.ellipse(surf, JOHNNY_GREEN, crown_rect)
    pygame.draw.ellipse(surf, (40, 60, 35), crown_rect, width=2)

    # calm spiral eyes
    eye_r = max(3, size * 0.07)
    for dx in (-0.24, 0.24):
        ex, ey = c + dx * size, c - 0.02 * size
        for i, ring_r in enumerate((eye_r, eye_r * 0.6, eye_r * 0.25)):
            shade = (240, 245, 250) if i == 0 else ((30, 45, 80) if i == 1 else (240, 245, 250))
            pygame.draw.circle(surf, shade, (ex, ey), max(1, ring_r))

    # a nail crossed at the brow, his Stand's calling card
    nail_len = size * 0.3
    nx, ny = c, c - r * 0.12
    pygame.draw.line(surf, NAIL_SILVER, (nx - nail_len / 2, ny), (nx + nail_len / 2, ny), 3)
    pygame.draw.circle(surf, NAIL_SILVER, (nx - nail_len / 2, ny), 3)

    # small confident mouth
    m = size * 0.11
    pygame.draw.arc(
        surf, (225, 230, 235),
        pygame.Rect(c - m, c + r * 0.32, m * 2, m * 1.4),
        3.4, 6.0, width=2,
    )
    return surf
