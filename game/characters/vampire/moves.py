"""Vampire move list: Shadow Spin, Blood Bolt, Blood Hex, Bat Swarm,
Blood Pool, Crimson Doppelganger, Eternal Night. The numbers/tags here
drive the generic combat pipeline (core/combat_resolution.py); the actual
behavior behind each tag lives in ability.py next to this file."""

from ...core.abilities import Ability


def make_vampire_abilities():
    return {
        "basic": Ability("Shadow Spin", "basic", "spin", 5450, 1.0),
        "skills": [
            Ability("Blood Bolt", "skill", "homing_bolt", 8500, 1.2, heal_ratio=0.35, tag="blood_bolt"),
            Ability("Blood Hex", "skill", "homing_bolt", 10500, 0.0, tag="curse"),
            Ability("Bat Swarm", "skill", "swarm", 12000, 1.2, tag="swarm"),
            Ability("Blood Pool", "skill", "cast", 8000, 0.0, tag="blood_pool"),
            Ability("Crimson Doppelganger", "skill", "cast", 10500, 0.0, tag="clone"),
        ],
        # meter_max raised from 20 (still 5/hit, now 6 hits instead of
        # 4) and cooldown nearly doubled, mirroring the Paladin's ultimate.
        "ultimate": Ability("Eternal Night", "ultimate", "cast", 16000, 0.0,
                             big=True, tag="eternal_night"),
    }
