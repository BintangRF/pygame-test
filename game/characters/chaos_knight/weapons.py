"""The Chaos Knight's weapon prop (see plugin.py for how it's animated).

mace.png's own source art rests along a diagonal (handle at the lower-left,
head at the upper-right) instead of the tip-up orientation every other
weapon sprite/weapon_angle()'s own convention assumes (see rotate_to_dir's
docstring in core/effects.py) — pre-rotated 45 degrees at load time here
(load_weapon's upright() then straightens whatever lean is left), so the
rest of this character's code can treat it as a normal tip-up prop like
every other weapon."""

from ...core.asset_loading import load_weapon

MACE_TARGET_H = 95


def load_chaos_knight_weapons():
    return {"mace": load_weapon("chaos_knight/mace.png", MACE_TARGET_H, pre_rotate=45)}
