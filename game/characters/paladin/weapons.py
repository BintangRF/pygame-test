"""The Paladin's weapon props (see fx.py for how they're animated)."""

from ...core.asset_loading import load_weapon, load_weapon_or_fallback


def load_paladin_weapons():
    return {
        "sword": load_weapon("paladin/sword.png", 90),
        "sword_big": load_weapon("paladin/sword.png", 130),
        "spear": load_weapon("paladin/spear.png", 110),
        "warhammer": load_weapon("paladin/warhammer.png", 90),
        "shield": load_weapon_or_fallback("paladin/shield.png", "paladin/paladin.png", 60),
    }
