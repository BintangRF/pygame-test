"""The Paladin's weapon props (see fx.py for how they're animated)."""

from ...core.asset_loading import load_weapon, load_weapon_or_fallback


def load_paladin_weapons():
    return {
        "sword": load_weapon("paladin/sword.png", 130),
        "sword_big": load_weapon("paladin/sword.png", 160),
        # spear.png rests along a diagonal (tip at the upper-right), so it's
        # pre-rotated 45 degrees to the tip-up convention here. The rotated
        # canvas is ~1.41x taller than the art's own, hence 155 keeps the
        # spear about as long on screen as the old diagonal 110 did.
        "spear": load_weapon("paladin/spear.png", 155, pre_rotate=45),
        "warhammer": load_weapon("paladin/warhammer.png", 90),
        # shield.png is drawn hilt-up like sword.png (grip/guard at the top,
        # the shield disc filling the lower half) so it shares the sword's
        # own hold/rotate convention (see PaladinPlugin._draw_weapon_swap's
        # "shield" branch, which applies the same +180 correction as the
        # sword) instead of a plain flat heater-shield shape.
        "shield": load_weapon_or_fallback("paladin/shield.png", "paladin/paladin.png", 95),
    }
