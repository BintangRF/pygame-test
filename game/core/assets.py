"""The character registry (CHARACTERS) that ties every fighter's stats,
sprite, move list, and CharacterPlugin together. Each character's own move
list, procedural sprite (if any), weapon props (if any), and plugin live in
characters/<name>/ next to that character's other code — this file only
holds the table that wires them together, so adding a new fighter never
needs edits outside characters/<name>/ + this dict. Generic loading
primitives live in core/asset_loading.py."""

import math
import random

import pygame

from ..characters.berserker.moves import make_berserker_abilities
from ..characters.berserker.plugin import BerserkerPlugin
from ..characters.johnny.moves import make_johnny_abilities
from ..characters.johnny.plugin import JohnnyPlugin
from ..characters.johnny.sprite import make_johnny_sprite
from ..characters.paladin.moves import make_paladin_abilities
from ..characters.paladin.plugin import PaladinPlugin
from ..characters.raiju.moves import make_raiju_abilities
from ..characters.raiju.plugin import RaijuPlugin
from ..characters.raiju.sprite import make_raiju_sprite
from ..characters.sukuna.moves import make_sukuna_abilities
from ..characters.sukuna.plugin import SukunaPlugin
from ..characters.sukuna.sprite import make_sukuna_sprite
from ..characters.vampire.moves import make_vampire_abilities
from ..characters.vampire.plugin import VampirePlugin
from .asset_loading import character_sprite
from .constants import ARENA_RECT, AVATAR_R, GOLD, JOHNNY_GREEN, ORANGE, RAIJU_CYAN, RED, SUKUNA_PINK
from .entities import Character

# Character registry — every selectable fighter, keyed by id. Drives both the
# character-select screen and make_character()/make_fighters() below, so
# adding a new fighter never needs edits outside characters/<name>/ + this dict.
CHARACTERS = {
    "paladin": {
        "label": "Paladin", "era": "Holy Order",
        "hp": 100, "atk": 15, "color": GOLD, "sprite": "paladin.png",
        "abilities": make_paladin_abilities, "plugin_cls": PaladinPlugin,
        "meter_max": 12, "meter_gain": 1, "meter_name": "ZEAL",
        "move_speed_mult": 1.4,
    },
    "vampire": {
        "label": "Vampire", "era": "Nightborn",
        "hp": 100, "atk": 13, "color": RED, "sprite": "vampire.png",
        "abilities": make_vampire_abilities, "plugin_cls": VampirePlugin,
        "meter_max": 20, "meter_gain": 5, "meter_name": "BLOOD",
        "move_speed_mult": 1.4,
    },
    "berserker": {
        "label": "Berserker", "era": "Frostreach Clans",
        "hp": 110, "atk": 18, "color": ORANGE, "sprite": "berserker.png",
        "abilities": make_berserker_abilities, "plugin_cls": BerserkerPlugin,
        "meter_max": 1, "meter_gain": 0, "meter_name": "RAGE",
        # hits harder, tankier, and faster afoot than the other two, to
        # offset its short reach — armor is on a 0-100 scale (30 = 30% less damage)
        "armor": 30, "move_speed_mult": 2.4,
    },
    "sukuna": {
        "label": "Sukuna", "era": "King of Curses",
        # no sukuna.png in assets/ — sprite_fn draws a placeholder instead of
        # a file (see characters/sukuna/sprite.py / character_sprite below)
        # low base ATK (basic hit lands for exactly 9) offset by very short
        # cooldowns on all three techniques — Sukuna wins by cutting fast
        # and often, not by hitting hard.
        "hp": 100, "atk": 9, "color": SUKUNA_PINK, "sprite": None, "sprite_fn": make_sukuna_sprite,
        "abilities": make_sukuna_abilities, "plugin_cls": SukunaPlugin,
        "meter_max": 6, "meter_gain": 1, "meter_name": "CURSE",
        "move_speed_mult": 1.4,
    },
    "raiju": {
        "label": "Raiju", "era": "Stormfang Clan",
        # no raiju.png in assets/ — sprite_fn draws a placeholder (see
        # characters/raiju/sprite.py), same approach as Sukuna above.
        # Lower HP than the others, offset by a very short basic-attack
        # cooldown and a skill (Blink Strike) that ignores melee range
        # entirely — Raiju wins by darting in, stacking Static, and cashing
        # it in, not by tanking hits.
        "hp": 115, "atk": 14, "color": RAIJU_CYAN, "sprite": None, "sprite_fn": make_raiju_sprite,
        "abilities": make_raiju_abilities, "plugin_cls": RaijuPlugin,
        "meter_max": 5, "meter_gain": 1, "meter_name": "STATIC",
        "move_speed_mult": 1.6,
    },
    "johnny": {
        "label": "Johnny Joestar", "era": "Steel Ball Run",
        # no johnny.png asset — sprite_fn draws a placeholder (see
        # characters/johnny/sprite.py), same approach as Sukuna/Raiju above.
        # A ranged skirmisher: every basic attack and skill spends one Nail
        # Bullet from a 20-shot pool (nail_bullets_max) that slowly reloads
        # on its own — see characters/johnny/plugin.py.
        "hp": 100, "atk": 9, "color": JOHNNY_GREEN, "sprite": None, "sprite_fn": make_johnny_sprite,
        "abilities": make_johnny_abilities, "plugin_cls": JohnnyPlugin,
        "meter_max": 3, "meter_gain": 1, "meter_name": "SPIN",
        "nail_bullets_max": 20,
        "move_speed_mult": 1.4,
    },
}


def spawn(f, x, y):
    f.pos = pygame.Vector2(x, y)
    angle = random.uniform(0, math.tau)
    speed = random.uniform(60, 100)
    f.vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
    return f


def start_all_on_cooldown(abilities):
    """Put every ability (basic, skills, ultimate) on its own full cooldown.
    Called right after a fighter is built so a match never opens with one
    side able to fire off a 260ms-cooldown basic (or any skill) before the
    other side has even had a chance to act — everyone starts even."""
    for ab in abilities["skills"] + [abilities["basic"], abilities["ultimate"]]:
        ab.timer = ab.cooldown_ms


def make_character(key):
    spec = CHARACTERS[key]
    abilities = spec["abilities"]()
    start_all_on_cooldown(abilities)
    c = Character(
        key, spec["label"], spec["era"], spec["hp"], spec["atk"], spec["color"],
        abilities=abilities,
        meter_max=spec["meter_max"], meter_gain=spec["meter_gain"], meter_name=spec["meter_name"],
        armor=spec.get("armor", 0.0), move_speed_mult=spec.get("move_speed_mult", 1.0),
        nail_bullets_max=spec.get("nail_bullets_max", 0),
    )
    c.image = character_sprite(spec, int(AVATAR_R * 2.4))
    return c


def make_fighters(key1=None, key2=None):
    """Build the two fighters for a match. The character-select flow always
    passes both keys explicitly; when either is omitted (e.g. calling this
    directly for a quick test), two distinct fighters are picked at random
    from CHARACTERS instead of defaulting to any specific pair — hardcoding
    two names here would go stale the moment the roster changes (see the
    module docstring: adding a fighter should never need edits outside
    characters/<name>/ + CHARACTERS)."""
    if key1 is None or key2 is None:
        key1, key2 = random.sample(list(CHARACTERS.keys()), 2)
    f1 = make_character(key1)
    f2 = make_character(key2)
    spawn(f1, ARENA_RECT.left + 80, ARENA_RECT.centery)
    spawn(f2, ARENA_RECT.right - 80, ARENA_RECT.centery)
    return f1, f2
