"""Shared constants: window size, colors, and the arena's bounce bounds."""

import os

import pygame

# HEIGHT grown from the original 560 to make room in the status panels
# (hud.py) for armor + full move-stat + buff/debuff readouts below the arena
# without crowding the battle log line. Grown again by the same amount the
# arena grew when it was squared up (ARENA_RECT below), so everything below
# the arena keeps its original spacing, just shifted down.
WIDTH, HEIGHT = 420, 780
FPS = 60

BLACK = (10, 10, 12)
WHITE = (240, 240, 240)
GOLD = (240, 200, 60)
RED = (220, 60, 60)
GRAY = (110, 110, 110)
GREEN = (80, 200, 120)
ORANGE = (225, 140, 50)
SUKUNA_PINK = (230, 70, 150)
RAIJU_CYAN = (90, 220, 240)
JOHNNY_GREEN = (110, 175, 90)
NAIL_SILVER = (205, 205, 215)
# Johnny's Nail Bullet is one of his own fingernails, Stand-charged and
# glowing — not a literal steel nail (see draw_nail in core/effects.py).
NAIL_GLOW_BLUE = (80, 220, 255)
# His beanie/durag and its gold horseshoe charm (characters/johnny/sprite.py).
JOHNNY_BEANIE_BLUE = (120, 175, 215)
JOHNNY_BEANIE_BLUE_DARK = (65, 105, 150)
PHANTOM_BLUE = (140, 205, 235)
METER_COLOR = (150, 90, 220)
SHIELD_COLOR = (120, 190, 255)
CURSE_COLOR = (150, 50, 180)
POISON_COLOR = (140, 200, 60)
STUN_COLOR = (250, 220, 80)

# constants.py lives at game/core/constants.py, three levels under the
# project root (game/core/ -> game/ -> project root), where assets/ lives.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSET_DIR = os.path.join(PROJECT_DIR, "assets")

# Square arena: same width and height (WIDTH - 40) instead of a wide
# rectangle, so movement/bounce feel consistent on both axes.
ARENA_RECT = pygame.Rect(20, 110, WIDTH - 40, WIDTH - 40)
AVATAR_R = 30
# A fighter's sprite is drawn at AVATAR_R * 2.4 across (see character_sprite
# in core/assets.py), i.e. a visual radius of AVATAR_R * 1.2 — this is that
# same radius, used as the hit-box for projectile-vs-character collision
# checks so "the nail visibly touched them" and "it counted as a hit" agree.
CHARACTER_HITBOX_R = AVATAR_R * 1.2
BOUND_LEFT = ARENA_RECT.left + AVATAR_R
BOUND_RIGHT = ARENA_RECT.right - AVATAR_R
BOUND_TOP = ARENA_RECT.top + AVATAR_R
BOUND_BOTTOM = ARENA_RECT.bottom - AVATAR_R

# A clone/decoy is a flimsy illusion, not a scaled-down copy of whichever
# fighter it stands in for — flat regardless of that fighter's own max_hp/
# armor. Shared by Vampire's Crimson Doppelganger (entities.Clone) and
# Phantom Lancer's illusion army (core/clone_army.CloneUnit) so both take
# zone/status-library damage (Blood Pool poison, an enemy zone's chip
# damage, a mirrored DoT, ...) exactly like a real fighter would, instead
# of being invisible to the generic damage pipeline.
CLONE_BASE_HP = 5
CLONE_BASE_ARMOR = 0.0
