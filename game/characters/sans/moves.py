"""Sans move list: Bone Toss, Bone Wall, Blue Soul, Bone Cage, Gaster
Blaster, Shortcut, Power Nap, Bad Time. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the behavior behind each tag lives in
plugin.py next to this file.

Passives (see SansPlugin): Dodge — Sans slips out of the way of an incoming
attack the moment it starts, spending one STAMINA (3 max, slowly refilled) —
and Karmic Retribution — every hit Sans lands stacks KR on the target, an
armor-ignoring damage-over-time. His own hits are weak on purpose; KR is
where his damage comes from."""

from ...core.abilities import Ability


def make_sans_abilities():
    return {
        # A spinning bone lobbed at the target — weak, but every hit is +1 KR.
        "basic": Ability("Bone Toss", "basic", "bolt", 1.4, 1.0, tag="sans_bone"),
        "skills": [
            # A staggered row of bones sweeping straight across the arena —
            # each bone deals almost nothing and adds 1 KR, so how many land
            # (the target keeps roaming through it) decides the payoff.
            # ignore_clone=True: resolves through SansPlugin.resolve_special /
            # the generic swarm engine, never through redirect_target.
            Ability("Bone Wall", "skill", "swarm", 5, 2.0, tag="sans_bone_wall", ignore_clone=True,
                    swarm_pattern="linear", swarm_timing="staggered",
                    swarm_count=15, swarm_speed=520, swarm_size=34),
            # The target's soul turns blue: gravity slams it into the
            # nearest wall and stuns it.
            Ability("Blue Soul", "skill", "cast", 7, 1.4, tag="sans_blue", cast_target="enemy"),
            # A ring of bones rises around the target and snaps shut: rooted,
            # and its KR stacks stop decaying while it's caged.
            Ability("Bone Cage", "skill", "cast", 6, 1.0, tag="sans_cage", cast_target="enemy"),
            Ability("Gaster Blaster", "skill", "cast", 5, 1.8, tag="sans_blaster", cast_target="enemy"),
            # Teleport away and catch his breath: refills all STAMINA.
            Ability("Shortcut", "skill", "cast", 9, 0.0, tag="sans_shortcut", cast_target="self"),
            # Dozes on his feet: heals over time and refills STAMINA fast,
            # without ever dropping his guard (still acts and dodges).
            Ability("Power Nap", "skill", "cast", 11, 0.0, tag="sans_nap", cast_target="self"),
        ],
        # A ring of Gaster Blasters firing one after another on the target's
        # live position (see SansPlugin). Uses the
        # generic "whirl" motion only for its long planted phase; all of the
        # damage is SansPlugin.attack_frame's own beam checks.
        "ultimate": Ability("Bad Time", "ultimate", "whirl", 12, 0.0, big=True, tag="sans_bad_time",
                            ignore_clone=True, ignore_taunt=True),
    }
