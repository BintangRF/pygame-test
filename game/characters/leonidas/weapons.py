"""Leonidas's spear prop — held by Leonidas himself and by every Spartan
conjured by This Is Sparta! (see plugin.py).

The source image rests along a diagonal (blade tip at the upper-right, grip/
tassel at the lower-left) instead of the tip-up orientation weapon_angle()/
rotate_to_dir()'s own convention assumes (see rotate_to_dir's docstring in
core/effects.py) — pre-rotated 45 degrees at load time here (load_weapon's
upright() then straightens whatever lean is left), the same fix Legion
Commander's scepter/arrow and Chaos Knight's mace needed (see their own
weapons.py), so the rest of this character's code can treat it as a normal
tip-up prop/projectile like everyone else's."""

from ...core.asset_loading import load_weapon

SPEAR_TARGET_H = 120


def load_leonidas_weapons():
    return {"spear": load_weapon("leonidas/spear.png", SPEAR_TARGET_H, pre_rotate=45)}
