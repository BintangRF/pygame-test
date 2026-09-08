"""
Movement/animation definitions shared by all abilities.

Each motion is a list of (phase_name, duration_s) — e.g. windup, strike,
impact, return — that the battle state machine steps through. Several
abilities can reuse the same motion (e.g. every ranged skill uses "bolt")
while still doing different damage/effects, since the effect resolves
separately at RESOLVE_PHASE.
"""

MOTIONS = {
    "melee_dash": [("windup", 0.08), ("strike", 0.1), ("impact", 0.11), ("return", 0.12)],
    "melee_slam": [("windup", 0.18), ("arc", 0.38), ("impact", 0.3), ("return", 0.32)],
    "spin": [("windup", 0.12), ("spin_travel", 0.42), ("impact", 0.25), ("return", 0.28)],
    "bolt": [("windup", 0.15), ("fire", 0.32), ("impact", 0.2), ("settle", 0.18)],
    "cast": [("windup", 0.2), ("channel", 0.4), ("release", 0.25)],
    "swarm": [("scatter", 0.3), ("reposition", 0.25), ("strike", 0.2)],
    # Berserker's basic: a stationary double claw-rake with the axe (no
    # dash-in like the other basics) — two crossing slashes, then reset.
    "slash": [("windup", 0.09), ("slash1", 0.08), ("slash2", 0.09), ("return", 0.11)],
    # Sukuna's Kai: no travel time and no projectile — the attacker barely
    # moves, and the cut(s) just appear directly on the target at "impact"
    # (see draw_sukuna_effects), instead of a bolt flying across the arena.
    "instant": [("windup", 0.1), ("impact", 0.15), ("settle", 0.15)],
    # Raiju's basic/Blink Strike: the attacker vanishes in a spark of static,
    # reappears already inside striking range of the target, cuts, then
    # flickers back — a teleport-slash instead of a dash-in or stationary hit.
    "flicker_slash": [("vanish", 0.09), ("reappear", 0.09), ("strike", 0.1), ("return", 0.14)],
    # Thunder God's Descent: a long ritual channel (Raiju calls the storm)
    # before a single sky-splitting bolt slams down on the target.
    "sky_strike": [("windup", 0.22), ("channel", 0.38), ("impact", 0.28), ("settle", 0.2)],
    # Johnny's Tusk Act 2: unlike "bolt" (which flies to the defender's
    # position at the moment the attack started and can't correct), the nail
    # keeps re-aiming at the defender's *current* position every frame during
    # "chase" — a genuine homing shot instead of a fixed-line one.
    "homing_bolt": [("windup", 0.14), ("chase", 0.38), ("impact", 0.2), ("settle", 0.16)],
    # Tusk Act 3: no more dash-in or teleport — the nail launches from
    # Johnny (who just keeps roaming, moves_while_active) and ricochets off
    # the arena walls like a DVD logo, hunting for a hit, for as long as
    # "flight" lasts (see RICOCHET_MAX_BOUNCES/RICOCHET_SPEED and
    # ricochet_step in battle_loop.py). 2.2s is generous enough to almost
    # always fit in its full bounce budget before "settle" cuts it off.
    "ricochet": [("windup", 0.15), ("flight", 2.2), ("settle", 0.2)],
    # Raiju's Volt Fang: unlike "ricochet" above, this never animates its
    # bounce path frame by frame at all — the attacker doesn't even move
    # (no moves_while_active; see core/plugin.py's resolve_instant_ricochet)
    # — the whole wall-to-wall path resolves in one shot the instant
    # "impact" begins, then just holds on screen through "settle" before
    # vanishing.
    "instant_ricochet": [("windup", 0.15), ("impact", 0.25), ("settle", 0.2)],
}

# phase at which an ability's damage/effect actually resolves, per motion
RESOLVE_PHASE = {
    "melee_dash": "impact", "melee_slam": "impact", "spin": "impact", "bolt": "impact",
    "cast": "release", "swarm": "strike", "slash": "slash2", "instant": "impact",
    "flicker_slash": "strike", "sky_strike": "impact",
    "homing_bolt": "impact", "ricochet": "settle", "instant_ricochet": "impact",
}

# Ability tags whose projectile flies to a fixed point (or, for Tusk Act 3,
# bounces around the arena over its whole flight; Raiju's Volt Fang instead
# resolves its bounce path in one shot — see "instant_ricochet" above)
# instead of homing in on the defender's live position — the only ones where
# the defender actually drifting (or just not being where the shot ends up
# bouncing) can make it whiff. Everything not listed here is guaranteed to
# connect once it resolves: melee/instant attacks land wherever the attacker
# is standing, homing_bolt (Tusk Act 2 and Tusk Act 4, Raiju's Chain Bolt)
# re-aims at the defender's *current* spot every frame.
DODGEABLE_TAGS = {"nail_bullet", "tusk_act3", "volt_fang"}


def is_dodgeable(ability):
    """Whether `ability`'s projectile is the fixed-point kind that can be
    outrun — see DODGEABLE_TAGS. Used by battle_loop.py to decide whether the
    defender keeps moving during the attack, and by combat_resolution.py's
    do_damage() to check whether they actually did."""
    return ability.tag in DODGEABLE_TAGS


def ease_out(t):
    return 1 - (1 - t) ** 2


def ease_in(t):
    return t * t


def ease_in_out(t):
    return t * t * (3 - 2 * t)


def ease_back(t, overshoot=1.7):
    return 1 + overshoot * (t - 1) ** 3 + overshoot * (t - 1) ** 2
