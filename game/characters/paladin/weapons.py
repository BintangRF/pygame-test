"""The Paladin's weapon props (see fx.py for how they're animated)."""

from ...core.assets import load_weapon, load_weapon_or_fallback


def load_paladin_weapons():
    return {
        "sword": load_weapon("sword.png", 90),
        "sword_big": load_weapon("sword.png", 130),
        "spear": load_weapon("spear.png", 110),
        "warhammer": load_weapon("warhammer.png", 90),
        "shield": load_weapon_or_fallback("shield.png", "paladin.png", 60),
    }
