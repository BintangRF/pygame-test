"""Paladin move list: Lunge Strike, Judgment Mark, Divine Shield, Sacred
Ground, Heaven's Verdict. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the actual behavior behind each tag
lives in ability.py, and its animation in fx.py, next to this file."""

from ...core.abilities import Ability


def make_paladin_abilities():
    return {
        "basic": Ability("Lunge Strike", "basic", "melee_dash", 5000, 1.0, melee_range=120),
        "skills": [
            Ability("Judgment Mark", "skill", "bolt", 8000, 0.4, tag="mark"),
            Ability("Divine Shield", "skill", "cast", 10000, 0.0, tag="shield"),
            Ability("Sacred Ground", "skill", "cast", 12000, 0.0, tag="sacred_ground"),
        ],
        # meter_max raised from 4 -> 6 and cooldown nearly doubled: the
        # ultimate now needs both more charge and a much longer wait.
        "ultimate": Ability("Heaven's Verdict", "ultimate", "melee_slam", 16000, 2.6,
                             big=True, tag="heavens_verdict"),
    }
