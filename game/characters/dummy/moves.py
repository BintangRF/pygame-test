"""Dummy move list: a single harmless jab and an equally harmless ultimate.
Both deal zero damage regardless of dmg_mult since the dummy's own base atk
is 0 (see CHARACTERS["dummy"] in core/assets.py) — this is a stationary
punching bag for testing armor/health mechanics, not a real threat."""

from ...core.abilities import Ability


def make_dummy_abilities():
    return {
        "basic": Ability("Prod", "basic", "melee_dash", 1.0, 1.0, melee_range=100),
        "skills": [],
        "ultimate": Ability("Brace", "ultimate", "melee_dash", 12, 1.0, big=True),
    }
