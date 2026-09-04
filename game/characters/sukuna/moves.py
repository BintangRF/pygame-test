"""Sukuna move list: Hachi, Kai, Kamino. The numbers/tags here drive the
generic combat pipeline (core/combat_resolution.py); the actual behavior
behind each tag lives in ability.py, and its animation in fx.py, next to
this file."""

from ...core.abilities import Ability


def make_sukuna_abilities():
    return {
        # no dash, no projectile — a single cut just appears on the target
        # (reuses "instant_cut", same as Kai below, just one hit instead of
        # a flurry). dmg_mult 1.0 on ATK 9 (see CHARACTERS) means this hits
        # for exactly 9 — a very short 260ms cooldown is what makes him
        # dangerous.
        "basic": Ability("Hachi", "basic", "instant_cut", 760, 1.0, tag="dismantle"),
        "skills": [
            # no windup travel, no projectile — the cut just appears on the
            # target (see "instant_cut" in core/motions.py / core/battle_loop.py).
            # Instead of dealing its own damage, using Kai procs the *basic
            # attack* itself 3-5 times at once (see sukuna_resolve_kai_flurry
            # in ability.py) — dmg_mult here is per-proc, matching Hachi's own 0.8.
            Ability("Kai", "skill", "instant_cut", 4000, 0.8, tag="kai_flurry"),
        ],
        # King of Curses' finisher: a devastating channeled strike that both
        # nukes and leaves the target bleeding out with healing crippled.
        # Cooldown shortened well below the other cast's 16s so it comes
        # back into play sooner between meter charges.
        # Uses "bolt" (not "cast") so it actually travels as a visible
        # projectile — see draw_fire_arrow / draw_projectile in
        # core/render.py — instead of resolving instantly in place like
        # Sukuna's other moves.
        "ultimate": Ability("Kamino", "ultimate", "bolt", 11000, 2.5, big=True, tag="kamino"),
    }
