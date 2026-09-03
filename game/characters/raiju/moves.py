"""Raiju move list: Fang Flicker, Chain Bolt, Static Field, Blink Strike,
Thunder God's Descent. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the actual behavior behind each tag
lives in ability.py, and its animation in fx.py, next to this file."""

from ...core.abilities import Ability


def make_raiju_abilities():
    return {
        # a teleport-slash, not a dash: "melee_range" here is how far the
        # blink can reach, not how far Raiju has to run in.
        "basic": Ability("Fang Flicker", "basic", "flicker_slash", 480, 1.0,
                          tag="static_bite", melee_range=190),
        "skills": [
            # guarantees 2 stacks of Static per hit (vs 1 from the basic) —
            # the fast way to push a target to the discharge threshold.
            Ability("Chain Bolt", "skill", "bolt", 9500, 1.1, tag="chain_bolt"),
            # no damage of its own; drops a field that chips anyone standing
            # in it (and slows them, via the generic zone-slow in update_roam)
            # while charging Raiju's own meter faster.
            Ability("Static Field", "skill", "cast", 13500, 0.0, tag="static_field"),
            # a skill, so it ignores the basic's melee_range gate entirely —
            # a genuine gap-closer that rewards striking from far away.
            Ability("Blink Strike", "skill", "flicker_slash", 10500, 1.2, tag="blink_strike"),
        ],
        # consumes every Static stack on the target for bonus damage, then
        # calls down a single sky-splitting bolt — the payoff for a match
        # spent building charge with Fang Flicker / Chain Bolt.
        "ultimate": Ability("Thunder God's Descent", "ultimate", "sky_strike", 15000, 2.3,
                             big=True, tag="thunder_descent"),
    }
