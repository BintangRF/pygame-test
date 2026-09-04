"""Johnny Joestar's move list: Nail Bullet, Tusk Act 2, Tusk Act 3, Tusk
Act 4. The numbers/tags here drive the generic combat pipeline
(core/combat_resolution.py); the actual behavior behind each tag lives in
ability.py, and its animation in fx.py, next to this file.

Every move here (basic and skills alike) draws from the same 20-shot Nail
Bullet pool — see johnny_ammo_ready/johnny_consume_nail_bullet in
ability.py, and Character.nail_bullets in core/entities.py. Only the
ultimate is exempt.
"""

from ...core.abilities import Ability


def make_johnny_abilities():
    return {
        # A straight, non-homing shot: "bolt" flies to wherever the defender
        # was standing when the attack started and never corrects course —
        # contrast with Tusk Act 2's "homing_bolt" below, which keeps
        # re-aiming every frame. It's also the one attack Johnny doesn't
        # need to plant himself for, so he keeps doing his normal linear
        # DVD-bounce roam the whole time instead of freezing (moves_while_active).
        "basic": Ability("Nail Bullet", "basic", "bolt", 200, 1, tag="nail_bullet",
                          moves_while_active=True),
        "skills": [
            # A genuine homing shot (see "homing_bolt" in core/motions.py):
            # always lands as a critical hit and leaves the target bleeding
            # (see johnny_critical_bonus / the "bleed" status applied in
            # johnny_apply_tag_effects below).
            Ability("Tusk Act 2", "skill", "homing_bolt", 2300, 0.9, tag="tusk_act2"),
            # A ricocheting shot: the nail bounces off the arena walls like a
            # DVD logo (see "ricochet" in core/motions.py) hunting for a hit
            # instead of flying a single fixed line — no more dash-in either,
            # Johnny just keeps roaming while it's out (moves_while_active).
            Ability("Tusk Act 3", "skill", "ricochet", 4500, 1.0, tag="tusk_act3",
                    moves_while_active=True),
        ],
        # Steel Ball Run's finisher: an unavoidable nail that pins the
        # target in place (the "rooted" status, checked generically in
        # core/battle_loop.py's update_roam) for 4 full seconds.
        "ultimate": Ability("Tusk Act 4", "ultimate", "homing_bolt", 8000, 1.7, big=True, tag="tusk_act4"),
    }
