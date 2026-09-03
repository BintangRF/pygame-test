"""Berserker move list: Reckless Cleave, Axe Throw, Berserker Rage. The
numbers/tags here drive the generic combat pipeline
(core/combat_resolution.py); the actual behavior behind each tag lives in
ability.py, and its animation in fx.py, next to this file."""

from ...core.abilities import Ability


def make_berserker_abilities():
    return {
        # quicker attack speed than the other fighters' basics (550ms vs
        # 900ms) but a much shorter reach (110 vs 170) — has to get in close.
        # Uses "claw" motion, not "melee_dash": a stationary double rake
        # with the axe instead of a dash-in strike like the others.
        "basic": Ability("Reckless Cleave", "basic", "claw", 900, 1.0, melee_range=110),
        "skills": [
            Ability("Axe Throw", "skill", "bolt", 9500, 0.9, tag="axe_throw"),
        ],
        # no meter gate at all — this ultimate is desperation, not a builder.
        # It only becomes available once HP drops below 30%, and it's a
        # one-shot: no cooldown, it simply can never fire a second time
        # (whether it goes off proactively here or via the death-save last
        # stand in ability.py — see berserker_death_save's used-flag check).
        "ultimate": Ability("Berserker Rage", "ultimate", "cast", 0, 0.0,
                             big=True, tag="berserker_rage", hp_threshold=0.3,
                             one_shot=True),
    }
