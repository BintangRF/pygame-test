"""Paladin move list: Lunge Strike, Judgment Mark, Divine Shield, Sacred
Ground, Heaven's Verdict. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the actual behavior behind each tag
lives in ability.py, and its animation in fx.py, next to this file."""

from ...core.abilities import Ability


def make_paladin_abilities():
    return {
        "basic": Ability("Lunge Strike", "basic", "melee_dash", 3000, 1.0, melee_range=120),
        # Every Paladin skill and the ultimate ignore_clone=True — a Divine
        # Shield/Sacred Ground cast has no defender to redirect anyway
        # (dmg_mult 0.0 already excludes those), but Judgment Mark and
        # Heaven's Verdict always land on the real fighter regardless of any
        # decoy in play (see StatusLibraryMixin.taunt_redirect).
        "skills": [
            Ability("Judgment Mark", "skill", "bolt", 8000, 0.4, tag="mark", ignore_clone=True),
            Ability("Divine Shield", "skill", "cast", 16000, 0.0, tag="shield", ignore_clone=True),
            Ability("Sacred Ground", "skill", "cast", 19000, 0.0, tag="sacred_ground", ignore_clone=True),
        ],
        # meter_max raised from 4 -> 6 and cooldown nearly doubled: the
        # ultimate now needs both more charge and a much longer wait.
        "ultimate": Ability("Heaven's Verdict", "ultimate", "melee_slam", 16000, 2.6,
                             big=True, tag="heavens_verdict", aoe_radius=130, ignore_clone=True),
    }
