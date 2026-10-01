"""The Legion Commander's weapon props: the scepter (rested idle, swung for
Scepter Strike, and swung again for Duel's guaranteed follow-up) and the
flame-arrow projectile Overwhelming Odds fires.

Both source images rest along a diagonal (head/tip at the upper-right,
handle/fletching at the lower-left) instead of the tip-up orientation
weapon_angle()/rotate_to_dir()'s own convention assumes (see rotate_to_dir's
docstring in core/effects.py) — pre-rotated 45 degrees at load time here,
the same fix Chaos Knight's mace.png needed (see
characters/chaos_knight/weapons.py), and load_weapon's upright() then
straightens whatever lean is left (the scepter's shaft sat ~10 degrees off
vertical after the 45 alone), so the rest of this character's code can treat
both as normal tip-up props/projectiles like everyone else's."""

from ...core.asset_loading import load_weapon

SCEPTER_TARGET_H = 100

# The Overwhelming Odds arrow sprite, loaded once per pixel size and cached
# — same pattern as Vampire's own _bat_sprite (characters/vampire/plugin.py).
# ARROW_SIZE_FALLBACK only matters if an ability somehow omits its own
# Ability.swarm_size (see abilities.py); Overwhelming Odds always sets one
# (see moves.py), so this is really just a safety net.
ARROW_SIZE_FALLBACK = 46
_ARROW_CACHE = {}


def load_legion_commander_weapons():
    scepter = load_weapon("legion_commander/legion-commander-scepter.png", SCEPTER_TARGET_H, pre_rotate=45)
    return {"scepter": scepter}


def flame_arrow_sprite(size=ARROW_SIZE_FALLBACK):
    img = _ARROW_CACHE.get(size)
    if img is None:
        img = load_weapon("legion_commander/legion-commander-arrow.png", size, pre_rotate=45)
        _ARROW_CACHE[size] = img
    return img
