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
# Per-character signature colors picked off each fighter's own emblem art
# (assets/<name>/<name>.png), used for the ring around the avatar and every
# generic hit effect (burst, shock ring, ground mark, sparks, afterimage).
# Paladin: the warm holy light of his gold-trimmed shield and warhammer.
PALADIN_HOLY = (255, 215, 125)
# Vampire: the deep blood-red of vampire.png's orb.
VAMPIRE_CRIMSON = (220, 30, 50)
# Berserker: the blood-red runes hammered into berserker.png's iron shield.
BERSERKER_RED = (225, 60, 40)
# Sukuna's cursed crimson: the blood-red seal lines of sukuna.png, not a
# candy pink, so his cuts and cursed energy read as the same color as him.
SUKUNA_CRIMSON = (215, 35, 60)
RAIJU_CYAN = (90, 220, 240)
# The gold rim and horseshoe of johnny.png's navy emblem.
JOHNNY_GOLD = (235, 190, 95)
NAIL_SILVER = (205, 205, 215)
# Johnny's Nail Bullet is one of his own fingernails, Stand-charged and
# glowing — not a literal steel nail (see draw_nail in core/effects.py).
NAIL_GLOW_BLUE = (80, 220, 255)
# His beanie/durag and its gold horseshoe charm (characters/johnny/sprite.py).
JOHNNY_BEANIE_BLUE = (120, 175, 215)
JOHNNY_BEANIE_BLUE_DARK = (65, 105, 150)
# The saturated azure of phantom-lancer.png's glowing sigil and lance.
PHANTOM_BLUE = (70, 185, 255)
# Chaos Knight's ember-red-orange — distinct from Berserker's lighter ORANGE
# and Vampire's RED, closer to the fiery black-iron look of chaos-knight.png.
CHAOS_EMBER = (245, 105, 30)
METER_COLOR = (150, 90, 220)
SHIELD_COLOR = (120, 190, 255)
CURSE_COLOR = (150, 50, 180)
POISON_COLOR = (140, 200, 60)
STUN_COLOR = (250, 220, 80)
# The generic critical-hit accent (combat_resolution.py's own crit roll, plus
# any character's bespoke crit passive that flags battle.crit — Chaos
# Knight's Chaos Strike, Johnny's Tusk Act 2, Before-Hassasin's Lethal Mark):
# floater text, the impact ring, and the hit-flash tint (see hit_flash_sprite
# in render.py) all use this instead of the attacker's own color, so a crit
# always reads as "this specific hit", not just a bigger number in the same
# color as every other hit.
CRIT_COLOR = (255, 100, 20)
# Before-Hassasin's shadow-assassin violet — distinct from Vampire's RED and
# Sukuna's SUKUNA_CRIMSON, closer to a bruised night-purple.
HASSASIN_VIOLET = (140, 85, 205)
# Accent used for Trace of Death's Lethal Mark buff ring — a hotter,
# brighter pink-red than HASSASIN_VIOLET so a primed crit reads distinctly
# from the character's own base color.
LETHAL_MARK_COLOR = (230, 60, 110)
# Legion Commander's own deep war-banner crimson — distinct from Vampire's
# brighter RED and Chaos Knight's orange-leaning CHAOS_EMBER, closer to the
# oxblood-and-gold look of legion-commander.png/legion-commander-scepter.png.
LEGION_CRIMSON = (205, 40, 48)
# Arjuna's divine-astra violet: the indigo orb and white wind of
# arjuna.png, so his arrows and their blasts glow the color of his emblem.
ARJUNA_ASTRA = (175, 150, 255)
# The one accent color reserved for anything tracing back to his father
# Indra (Aindrastra's bolt, the stun ring it leaves) — kept a cool electric
# blue so it never gets mistaken for Raiju's own cyan-leaning RAIJU_CYAN.
INDRA_SPARK = (140, 200, 255)
# Leonidas's own dulled bronze-cuirass accent — distinct from every existing
# red/gold (RED, LEGION_CRIMSON, GOLD, ARJUNA_ASTRA, CHAOS_EMBER), closer to
# tarnished bronze armor than any of those brighter reds/golds.
LEONIDAS_BRONZE = (230, 165, 60)
# Sans's blue hoodie — darker and more violet-leaning than Phantom Lancer's
# azure PHANTOM_BLUE or Raiju's cyan.
SANS_BLUE = (70, 120, 235)
# Karmic Retribution's magenta, the color Undertale paints KR damage in.
SANS_KARMA = (225, 60, 200)
# The Knight's pale Soul glow — the white-blue light of Hollow Knight's
# Soul vessel, cooler than the plain WHITE used for generic floaters.
KNIGHT_SOUL = (205, 220, 250)
# Pac-Man's arcade yellow — a purer, brighter yellow than GOLD or
# LEONIDAS_BRONZE, so his ring never reads as either of theirs.
PACMAN_YELLOW = (255, 225, 0)
# Kings's emerald: the gem set in his crown-mask (assets/kings/parts/masks/
# king.png) - greener than Raiju's cyan, deeper than the GREEN heal floaters.
KINGS_EMERALD = (35, 200, 150)
# The Dummy's own burlap-sack tan — a dull, inert neutral distinct from every
# other fighter's accent color, fitting a practice target rather than a combatant.
DUMMY_TAN = (196, 160, 110)

# constants.py lives at game/core/constants.py, three levels under the
# project root (game/core/ -> game/ -> project root), where assets/ lives.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSET_DIR = os.path.join(PROJECT_DIR, "assets")

# Square arena: same width and height (WIDTH - 40) instead of a wide
# rectangle, so movement/bounce feel consistent on both axes.
ARENA_RECT = pygame.Rect(20, 110, WIDTH - 40, WIDTH - 40)
AVATAR_R = 30
# A fighter's sprite is drawn at AVATAR_R * 2.4 across by default (see
# character_sprite in core/assets.py), i.e. a visual radius of AVATAR_R *
# 1.2 — this is that same radius, used as the *default* hit-box for
# projectile-vs-character collision checks and for wall/body bounce margins,
# so "the nail visibly touched them" and "it counted as a hit" agree. Every
# real fighter gets its own Character.hitbox_r instead (set in
# make_character by sprite_hitbox_r, from the visible width of that
# fighter's own sprite), so each hitbox/bounce point matches its own
# silhouette instead of this flat default. Every collision check that
# targets a specific fighter's body should read that fighter's own
# hitbox_r (falling back to this constant for non-Character bodies, e.g.
# Vampire's Clone) rather than this constant directly.
CHARACTER_HITBOX_R = AVATAR_R * 1.2
BOUND_LEFT = ARENA_RECT.left + AVATAR_R
BOUND_RIGHT = ARENA_RECT.right - AVATAR_R
BOUND_TOP = ARENA_RECT.top + AVATAR_R
BOUND_BOTTOM = ARENA_RECT.bottom - AVATAR_R

# A clone/decoy's armor — flat regardless of whichever fighter it stands in
# for. Its hp is no longer this kind of flat constant (see each character's
# own clone_hp_pct of its owner's own max_hp instead — entities.Clone/
# core/clone_army.CloneArmy), only armor stays a shared flat default.
CLONE_BASE_ARMOR = 0.0
