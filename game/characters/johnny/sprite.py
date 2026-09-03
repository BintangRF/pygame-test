"""Procedural placeholder sprite for Johnny Joestar — a stylish precision
battle orb. No johnny.png asset exists, so this draws a fitted blue beanie
banded by a gold horseshoe charm over a navy orb with a spiral "Spin" motif,
instead of loading a file."""

import math

import pygame

from ...core.constants import GOLD, JOHNNY_BEANIE_BLUE, JOHNNY_BEANIE_BLUE_DARK


def make_johnny_sprite(size):
    """Navy/royal-blue orb (not a literal face) with a beanie, spiral
    marking and calm spiral eyes — clean and controlled next to
    Sukuna/Raiju."""
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

    # fitted beanie — a snug dome over the crown (not a brimmed riding hat),
    # with a subtle cuffed fold at the brow and a gold horseshoe charm
    # centered on it, Steel Ball Run's silhouette.
    dome_rect = pygame.Rect(0, 0, r * 2.06, r * 1.15)
    dome_rect.center = (c, c - r * 0.68)
    pygame.draw.ellipse(surf, JOHNNY_BEANIE_BLUE, dome_rect)
    pygame.draw.ellipse(surf, JOHNNY_BEANIE_BLUE_DARK, dome_rect, width=2)

    fold_rect = dome_rect.inflate(-r * 0.16, -r * 0.14)
    pygame.draw.arc(surf, JOHNNY_BEANIE_BLUE_DARK, fold_rect, math.radians(200), math.radians(340), width=2)

    # the horseshoe: an open-bottomed gold arc on the brow, two small
    # rivets ("nail holes") near its ends
    hs_c = pygame.Vector2(c, c - r * 0.4)
    hs_r = r * 0.18
    hs_rect = pygame.Rect(0, 0, hs_r * 2, hs_r * 2)
    hs_rect.center = hs_c
    hs_width = max(2, round(size * 0.06))
    pygame.draw.arc(surf, (150, 115, 25), hs_rect, math.radians(338), math.radians(562), width=hs_width + 2)
    pygame.draw.arc(surf, GOLD, hs_rect, math.radians(340), math.radians(560), width=hs_width)
    for ang_deg in (345, 555):
        rivet = hs_c + pygame.Vector2(math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))) * hs_r
        pygame.draw.circle(surf, (150, 115, 25), rivet, max(1, hs_width * 0.4))

    # calm spiral eyes
    eye_r = max(3, size * 0.07)
    for dx in (-0.24, 0.24):
        ex, ey = c + dx * size, c - 0.02 * size
        for i, ring_r in enumerate((eye_r, eye_r * 0.6, eye_r * 0.25)):
            shade = (240, 245, 250) if i == 0 else ((30, 45, 80) if i == 1 else (240, 245, 250))
            pygame.draw.circle(surf, shade, (ex, ey), max(1, ring_r))

    # small confident mouth
    m = size * 0.11
    pygame.draw.arc(
        surf, (225, 230, 235),
        pygame.Rect(c - m, c + r * 0.32, m * 2, m * 1.4),
        3.4, 6.0, width=2,
    )
    return surf
