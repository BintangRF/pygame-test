"""Procedural placeholder sprite for Before-Hassasin — a plain black orb.
No before-Hassasin.png asset exists yet, so this draws a solid black circle
directly instead of loading a file (same fallback approach as
characters/sukuna/sprite.py, kept only until real art lands)."""

import pygame


def make_before_hassasin_sprite(size):
    """Solid black, with only a faint charcoal rim so the circle's own edge
    still reads against an equally dark arena floor/menu background."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    r = size * 0.46
    pygame.draw.circle(surf, (0, 0, 0), (c, c), r)
    pygame.draw.circle(surf, (40, 40, 44), (c, c), r, width=2)
    return surf
