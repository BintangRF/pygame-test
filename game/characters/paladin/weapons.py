"""The Paladin's weapon props (see fx.py for how they're animated)."""

from ...core.asset_loading import load_weapon, load_weapon_or_fallback


def load_paladin_weapons():
    return {
        "sword": load_weapon("paladin/sword.png", 130),
        "sword_big": load_weapon("paladin/sword.png", 160),
        "spear": load_weapon("paladin/spear.png", 110),
        "warhammer": load_weapon("paladin/warhammer.png", 90),
        # shield.png is drawn hilt-up like sword.png (grip/guard at the top,
        # the shield disc filling the lower half) so it shares the sword's
        # own hold/rotate convention (see PaladinPlugin._draw_weapon_swap's
        # "shield" branch, which applies the same +180 correction as the
        # sword) instead of a plain flat heater-shield shape.
        "shield": load_weapon_or_fallback("paladin/shield.png", "paladin/paladin.png", 95),
    }
