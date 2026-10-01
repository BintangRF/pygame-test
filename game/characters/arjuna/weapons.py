"""Arjuna's own weapon props: the bow (rested idle, drawn back and released
for every arrow-motion ability) and the arrow it fires.

Both source images (bow.png, arrow.png) rest along a diagonal instead of the
tip-up orientation weapon_angle()/rotate_to_dir()'s own convention assumes
(see rotate_to_dir's docstring in core/effects.py) — pre-rotated at load time
here, the same fix Chaos Knight's mace.png and Legion Commander's own
scepter/arrow needed (see their own weapons.py). The two images do NOT sit at
exactly the same diagonal despite looking alike at a glance — a single
shared angle (225 degrees, picked by eye) left the bow under a degree off
but the arrow about 5 degrees off, just enough that a shot flying near-
horizontal or near-vertical visibly leaned off-axis instead of tracking
straight. Both now share the coarse 225 (which end is the head) and
load_weapon's upright() measures and rotates out each image's own leftover
lean (principal axis of the opaque pixels), so neither needs a hand-measured
angle."""

from ...core.asset_loading import load_weapon

BOW_TARGET_H = 150
# Bumped twice now (42 -> 66 -> this) — still unreadable in the real arena at
# normal viewing distance: arrow.png's own visible shaft only fills a
# fraction of its source canvas's height once rotated upright (see the
# module docstring above), and a thin fast-moving sliver is easy to
# miss even once its bounding box is "big enough" on paper. One fixed size
# for every ability (basic, skill, and Devadatta's own arrow in plugin.py) —
# never scaled down or up per ability.
ARROW_TARGET_H = 140
PRE_ROTATE = 225


def load_arjuna_weapons():
    return {
        "bow": load_weapon("arjuna/bow.png", BOW_TARGET_H, pre_rotate=PRE_ROTATE),
        "arrow": load_weapon("arjuna/arrow.png", ARROW_TARGET_H, pre_rotate=PRE_ROTATE),
    }
