"""Vampire move list: Shadow Spin, Blood Bolt, Blood Hex, Bat Swarm,
Blood Pool, Crimson Doppelganger, Eternal Night. The numbers/tags here
drive the generic combat pipeline (core/combat_resolution.py); the actual
behavior behind each tag lives in ability.py next to this file.

Passive (Blood Hunger): the generic "lifesteal" status (100% of whatever
damage actually lands, see core/status_library.py) kept refreshed on the
Vampire every frame, so every basic attack and skill always heals it,
topped up once its own hp drops below a threshold, which also layers on a
flat "damage_reduction" while it stays that low (see VampirePlugin.
ambient_tick/heal_bonus) — not wired into any one move here."""

from ...core.abilities import Ability


def make_vampire_abilities():
    return {
        "basic": Ability("Shadow Spin", "basic", "spin", 2.0, 1.0),
        "skills": [
            # Blood Bolt/Blood Hex: ignore_clone=True — a genuine homing
            # shot that keeps re-aiming at the defender's own live position
            # every frame, so it always lands on the real Vampire's target
            # regardless of any decoy in play (see StatusLibraryMixin.
            # taunt_redirect).
            Ability("Blood Bolt", "skill", "homing_bolt", 3, 1.6, tag="blood_bolt",
                    ignore_clone=True),
            Ability("Blood Hex", "skill", "homing_bolt", 10.5, 0.0, tag="curse", ignore_clone=True),
            # ignore_clone=True for a different reason than the two above:
            # Bat Swarm resolves through VampirePlugin.resolve_special (see
            # there), which hands off to the generic swarm engine (core/
            # battle_loop.py's spawn_swarm_projectiles/update_swarm_projectiles)
            # instead of do_damage()'s single-target formula, and never
            # consults redirect_target at all — leaving this redirect-eligible
            # would let taunt_redirect silently pick a decoy this ability then
            # just ignores. No aoe_radius either: unlike a single-impact-point
            # blast (Kamino, Heaven's Verdict, ...), the barrage's own
            # projectiles already fly through the whole arena on their own
            # paths and can incidentally catch one of the defender's own
            # illusions directly (see _swarm_enemy_bodies in
            # battle_loop.py) — no separate guaranteed splash needed.
            # swarm_pattern="radial": bats launch from every edge of the
            # arena at once, aimed at random points across the whole map —
            # a real bat swarm closing in from every side and genuinely
            # not targeted at anyone in particular, not a guaranteed strike.
            # swarm_timing="random": each bat gets its own random delay
            # instead of arriving in a neat wave, so the barrage reads as
            # chaotic rather than choreographed.
            # swarm_count/swarm_speed/swarm_size are Vampire's own tuning
            # (count/speed read by the generic engine, size by
            # VampirePlugin.draw_projectile) — a denser, slower, bigger-bat
            # swarm than the engine's own SWARM_PROJECTILE_COUNT/SPEED
            # defaults, since a Vampire's own Bat Swarm should read as a
            # heavy, looming cloud rather than a quick spray.
            Ability("Bat Swarm", "skill", "swarm", 2, 1, tag="swarm", ignore_clone=True,
                    swarm_pattern="radial", swarm_timing="random",
                    swarm_count=20, swarm_speed=1000, swarm_size=100),
            Ability("Blood Pool", "skill", "cast", 4, 0.0, tag="blood_pool", cast_target="self"),
            Ability("Crimson Doppelganger", "skill", "cast", 6, 0.0, tag="clone", cast_target="self"),
        ],
        # meter_max raised from 20 (still 5/hit, now 6 hits instead of
        # 4) and cooldown nearly doubled, mirroring the Paladin's ultimate.
        "ultimate": Ability("Eternal Night", "ultimate", "cast", 10, 0.0,
                             big=True, tag="eternal_night", cast_target="self"),
    }
