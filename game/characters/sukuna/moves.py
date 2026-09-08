"""Sukuna move list: Hachi, Kai, Kamino. The numbers/tags here drive the
generic combat pipeline (core/combat_resolution.py); the actual behavior
behind each tag lives in ability.py, and its animation in fx.py, next to
this file."""

from ...core.abilities import Ability


def make_sukuna_abilities():
    return {
        # no dash, no projectile — a single cut just appears on the target
        # (reuses "instant", same as Kai below, just one hit instead of
        # a flurry). dmg_mult 1.0 on ATK 9 (see CHARACTERS) means this hits
        # for exactly 9 — a very short 0.26s cooldown is what makes him
        # dangerous.
        "basic": Ability("Hachi", "basic", "instant", 1.4, 1.0, tag="dismantle"),
        "skills": [
            # no windup travel, no projectile — the cut just appears on the
            # target (see "instant" in core/motions.py / core/battle_loop.py).
            # Instead of dealing its own damage, using Kai procs the *basic
            # attack* itself 3-5 times at once (see sukuna_resolve_kai_flurry
            # in ability.py) — dmg_mult here is per-proc, matching Hachi's own 0.8.
            # ignore_clone=True: Kai resolves through SukunaPlugin.
            # resolve_special (see there), which always deals its damage
            # straight to battle.defender directly and never consults
            # redirect_target — leaving this redirect-eligible would desync
            # the visual strike position (moved to a decoy) from where the
            # damage actually lands.
            Ability("Kai", "skill", "instant", 5, 0.8, tag="kai_flurry", ignore_clone=True),
        ],
        # King of Curses' finisher: a devastating channeled strike that both
        # nukes and leaves the target bleeding out with healing crippled.
        # Cooldown shortened well below the other cast's 16s so it comes
        # back into play sooner between meter charges.
        # Uses "bolt" (not "cast") so it actually travels as a visible
        # projectile — see draw_fire_arrow / draw_projectile in
        # core/render.py — instead of resolving instantly in place like
        # Sukuna's other moves. ignore_clone=True — always lands on the real
        # target (see StatusLibraryMixin.taunt_redirect).
        "ultimate": Ability("Kamino", "ultimate", "homing_bolt", 11, 2.5, big=True, tag="kamino",
                            aoe_radius=110, ignore_clone=True),
    }
