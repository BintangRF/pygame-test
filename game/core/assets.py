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

from ..characters.arjuna.moves import make_arjuna_abilities
from ..characters.arjuna.plugin import ArjunaPlugin
from ..characters.before_hassasin.moves import make_before_hassasin_abilities
from ..characters.before_hassasin.plugin import BeforeHassasinPlugin
from ..characters.before_hassasin.sprite import make_before_hassasin_sprite
from ..characters.berserker.moves import make_berserker_abilities
from ..characters.berserker.plugin import BerserkerPlugin
from ..characters.chaos_knight.moves import make_chaos_knight_abilities
from ..characters.chaos_knight.plugin import ChaosKnightPlugin
from ..characters.dummy.moves import make_dummy_abilities
from ..characters.dummy.plugin import DummyPlugin
from ..characters.johnny.moves import make_johnny_abilities
from ..characters.johnny.plugin import JohnnyPlugin
from ..characters.johnny.sprite import make_johnny_sprite
from ..characters.legion_commander.moves import make_legion_commander_abilities
from ..characters.legion_commander.plugin import LegionCommanderPlugin
from ..characters.leonidas.moves import make_leonidas_abilities
from ..characters.leonidas.plugin import LeonidasPlugin
from ..characters.paladin.moves import make_paladin_abilities
from ..characters.paladin.plugin import PaladinPlugin
from ..characters.phantom_lancer.moves import make_phantom_lancer_abilities
from ..characters.phantom_lancer.plugin import PhantomLancerPlugin
from ..characters.raiju.moves import make_raiju_abilities
from ..characters.raiju.plugin import RaijuPlugin
from ..characters.raiju.sprite import make_raiju_sprite
from ..characters.sukuna.moves import make_sukuna_abilities
from ..characters.sukuna.plugin import SukunaPlugin
from ..characters.sukuna.sprite import make_sukuna_sprite
from ..characters.vampire.moves import make_vampire_abilities
from ..characters.vampire.plugin import VampirePlugin
from .asset_loading import character_sprite
from .constants import (
    ARENA_RECT, ARJUNA_GOLD, AVATAR_R, CHAOS_EMBER, DUMMY_TAN, GOLD, HASSASIN_VIOLET, JOHNNY_GREEN, LEGION_CRIMSON,
    LEONIDAS_BRONZE, ORANGE, PHANTOM_BLUE, RAIJU_CYAN, RED, SUKUNA_PINK,
)
from .entities import Character

# Character registry — every selectable fighter, keyed by id. Drives both the
# character-select screen and make_character()/make_fighters() below, so
# adding a new fighter never needs edits outside characters/<name>/ + this dict.
CHARACTERS = {
    "paladin": {
        "label": "Paladin", "era": "Holy Order",
        # base ATK halved and +15 armor vs. the original balance, across
        # every fighter, to slow matches down (fewer one-sided burst kills).
        # Further cut by another 25% across every fighter's base ATK, then rounded.
        "hp": 115, "atk": 8, "color": GOLD, "sprite": "paladin/paladin.png",
        "abilities": make_paladin_abilities, "plugin_cls": PaladinPlugin,
        "meter_max": 10, "meter_gain": 1, "meter_name": "ZEAL",
        "armor": 17, "move_speed_mult": 1.6,
    },
    "vampire": {
        "label": "Vampire", "era": "Nightborn",
        "hp": 200, "atk": 8, "color": RED, "sprite": "vampire/vampire.png",
        "abilities": make_vampire_abilities, "plugin_cls": VampirePlugin,
        "meter_max": 6, "meter_gain": 1, "meter_name": "BLOOD",
        "armor": 0, "move_speed_mult": 3,
    },
    "berserker": {
        "label": "Berserker", "era": "Frostreach Clans",
        "hp": 130, "atk": 7, "color": ORANGE, "sprite": "berserker/berserker.png",
        "abilities": make_berserker_abilities, "plugin_cls": BerserkerPlugin,
        "meter_max": 1, "meter_gain": 0, "meter_name": "RAGE",
        # hits harder, tankier, and faster afoot than the other two, to
        # offset its short reach — armor is on a 0-100 scale (30 = 30% less damage)
        "armor": 15, "move_speed_mult": 1.8,
    },
    "sukuna": {
        "label": "Sukuna", "era": "King of Curses",
        # no sukuna.png in assets/ — sprite_fn draws a placeholder instead of
        # a file (see characters/sukuna/sprite.py / character_sprite below)
        # low base ATK offset by very short cooldowns on all three
        # techniques — Sukuna wins by cutting fast and often, not by hitting hard.
        "hp": 90, "atk": 4, "color": SUKUNA_PINK, "sprite": "sukuna/sukuna.png",
        "abilities": make_sukuna_abilities, "plugin_cls": SukunaPlugin,
        "meter_max": 9, "meter_gain": 1, "meter_name": "CURSE",
        "armor": 18, "move_speed_mult": 2,
    },
    "raiju": {
        "label": "Raiju", "era": "Stormfang Clan",
        # no raiju.png in assets/ — sprite_fn draws a placeholder (see
        # characters/raiju/sprite.py), same approach as Sukuna above.
        # Lower HP than the others, offset by a ranged, wall-bouncing basic
        # (Volt Fang — see characters/raiju/moves.py) that never needs to
        # close distance at all, and a passive (Static) that stacks
        # Vulnerability on anything it hits while also charging Overcharge's
        # Attack Speed Up on Raiju himself — he wins by chipping away from
        # range while snowballing his own swing speed as the fight goes on.
        "hp": 135, "atk": 7, "color": RAIJU_CYAN, "sprite": "raiju/raiju.png",
        "abilities": make_raiju_abilities, "plugin_cls": RaijuPlugin,
        "meter_max": 5, "meter_gain": 1, "meter_name": "STATIC",
        "armor": 20, "move_speed_mult": 1.6,
    },
    "johnny": {
        "label": "Johnny Joestar", "era": "Steel Ball Run",
        # no johnny.png asset — sprite_fn draws a placeholder (see
        # characters/johnny/sprite.py), same approach as Sukuna/Raiju above.
        # A ranged skirmisher: every basic attack and skill spends one Nail
        # Bullet from a 20-shot pool (nail_bullets_max) that slowly reloads
        # on its own, and a passive (Spin Charge) that stacks Attack Up off
        # his own landed hits, lapsing if he stops connecting — see
        # characters/johnny/plugin.py.
        "hp": 105, "atk": 6, "color": JOHNNY_GREEN, "sprite": "johnny/johnny.png",
        "abilities": make_johnny_abilities, "plugin_cls": JohnnyPlugin,
        "meter_max": 3, "meter_gain": 1, "meter_name": "SPIN",
        "armor": 15,
        "nail_bullets_max": 20,
        "move_speed_mult": 1.4,
    },
    "phantom_lancer": {
        "label": "Phantom Lancer", "era": "Phantom Legion",
        # Modest ATK of its own — the Juxtapose passive's illusory clones
        # (see characters/phantom_lancer/plugin.py) are where its real
        # damage comes from, chipping in extra hits alongside its own.
        "hp": 110, "atk": 6, "color": PHANTOM_BLUE, "sprite": "phantom_lancer/phantom-lancer.png",
        "abilities": make_phantom_lancer_abilities, "plugin_cls": PhantomLancerPlugin,
        "meter_max": 6, "meter_gain": 1, "meter_name": "ILLUSION",
        "armor": 15, "move_speed_mult": 2,
    },
    "chaos_knight": {
        "label": "Chaos Knight", "era": "Chaotic Rift",
        # Moderate ATK on its own — Chaos Strike's flat chance for a Mace
        # Slash to crit and fully lifesteal (see
        # characters/chaos_knight/plugin.py) and the Phantasm ultimate's
        # full-atk illusion are where its extra damage comes from.
        "hp": 100, "atk": 5, "color": CHAOS_EMBER, "sprite": "chaos_knight/chaos-knight.png",
        "abilities": make_chaos_knight_abilities, "plugin_cls": ChaosKnightPlugin,
        "meter_max": 5, "meter_gain": 1, "meter_name": "CHAOS",
        "armor": 15, "move_speed_mult": 1.8,
    },
    "before_hassasin": {
        "label": "Before-Hassasin", "era": "Silent Order",
        # no before-Hassasin.png in assets/ — sprite_fn draws a placeholder
        # instead of a file (see characters/before_hassasin/sprite.py /
        # character_sprite below), same approach Sukuna/Raiju/Johnny
        # originally used. Slightly below-average HP — Twin Fangs' own
        # dual-range passive, Death Scent's hard lockdown, and Trace of
        # Death's random burst/utility do the rest of the work (see
        # characters/before_hassasin/plugin.py).
        "hp": 80, "atk": 10, "color": HASSASIN_VIOLET, "sprite": "before-Hassasin.png",
        "sprite_fn": make_before_hassasin_sprite,
        "abilities": make_before_hassasin_abilities, "plugin_cls": BeforeHassasinPlugin,
        "meter_max": 8, "meter_gain": 1, "meter_name": "DEATH",
        "armor": 10, "move_speed_mult": 2.5,
    },
    "legion_commander": {
        "label": "Legion Commander", "era": "Iron Legion",
        # A bruiser whose own kit does most of the swinging: Unyielding
        # Resolve (see characters/legion_commander/plugin.py) only kicks in
        # while behind on hp, and Duel's permanent Attack Up only pays off
        # once she's actually landed it — moderate hp/armor/atk on their own.
        "hp": 110, "atk": 8, "color": LEGION_CRIMSON, "sprite": "legion_commander/legion-commander.png",
        "abilities": make_legion_commander_abilities, "plugin_cls": LegionCommanderPlugin,
        "meter_max": 6, "meter_gain": 1, "meter_name": "VALOR",
        "armor": 15, "move_speed_mult": 1.7,
    },
    "arjuna": {
        "label": "Arjuna", "era": "Kurukshetra",
        # A pure ranged glass cannon — no melee_range at all on Gandiva —
        # offset by low hp/armor: Savyasachi's stacking Attack Speed Up and
        # its empowered payoff shot (see characters/arjuna/plugin.py) is
        # where the sustained damage comes from, not raw base ATK.
        "hp": 95, "atk": 8, "color": ARJUNA_GOLD, "sprite": "arjuna/arjuna.png",
        "abilities": make_arjuna_abilities, "plugin_cls": ArjunaPlugin,
        "meter_max": 6, "meter_gain": 1, "meter_name": "FOCUS",
        "armor": 15, "move_speed_mult": 2,
    },
    "leonidas": {
        "label": "Leonidas", "era": "300",
        # A bruiser whose own passive (Spartan Fury — see
        # characters/leonidas/plugin.py) rewards both giving and taking hits
        # with a temporary buff window, and whose ultimate calls in a
        # formation of Spartan illusions that charge in lockstep with his
        # own Javelin Charge — moderate hp/atk/armor on their own.
        "hp": 115, "atk": 6, "color": LEONIDAS_BRONZE, "sprite": "leonidas/leonidas.png",
        "abilities": make_leonidas_abilities, "plugin_cls": LeonidasPlugin,
        "meter_max": 6, "meter_gain": 1, "meter_name": "VALOR",
        "armor": 16, "move_speed_mult": 1.7,
    },
    "dummy": {
        "label": "Dummy", "era": "Practice Yard",
        # A pure punching bag for testing armor/health tuning in isolation:
        # huge hp, zero atk (every hit it lands deals 0 damage), and just 1
        # armor of its own, with no passive at all (see
        # characters/dummy/plugin.py — every hook stays default).
        "hp": 9999, "atk": 0, "color": DUMMY_TAN, "sprite": "dummy/dummy.png",
        "abilities": make_dummy_abilities, "plugin_cls": DummyPlugin,
        "meter_max": 10, "meter_gain": 1, "meter_name": "BRACE",
        "armor": 0, "move_speed_mult": 1.0,
    },
}


def spawn(f, x, y):
    f.pos = pygame.Vector2(x, y)
    angle = random.uniform(0, math.tau)
    speed = random.uniform(60, 100)
    f.vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
    f.base_speed = speed
    return f


def start_all_on_cooldown(abilities):
    """Put every ability (basic, skills, ultimate) on its own full cooldown.
    Called right after a fighter is built so a match never opens with one
    side able to fire off a 260ms-cooldown basic (or any skill) before the
    other side has even had a chance to act — everyone starts even."""
    for ab in abilities["skills"] + [abilities["basic"], abilities["ultimate"]]:
        ab.timer = ab.cooldown


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
    sprite_size = int(AVATAR_R * 4.8) if key == "dummy" else int(AVATAR_R * 2.4)
    c.image = character_sprite(spec, sprite_size)
    c.hitbox_r = sprite_hitbox_r(c.image)
    return c


# Pixels at or above this alpha count as "part of the character" when
# measuring its visible width — low enough to keep soft anti-aliased edges,
# high enough to skip faint glow/shadow halos around the silhouette.
HITBOX_MIN_ALPHA = 64


def sprite_hitbox_r(image):
    """Collision/bounce radius (see Character.hitbox_r) matching how wide
    this fighter's own sprite actually looks: half the width of its
    non-transparent pixels, not of the whole square canvas. Every sprite is
    drawn into the same square, but each silhouette fills a different share
    of it (a slim lancer vs a broad shield-bearer, or the Dummy's 2x canvas),
    so a flat radius per canvas size would make some fighters collide with
    empty air and others overlap visibly before bumping."""
    width = image.get_bounding_rect(min_alpha=HITBOX_MIN_ALPHA).width
    return width / 2 if width > 0 else image.get_width() / 2


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
