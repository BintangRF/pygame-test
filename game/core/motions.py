"""
Movement/animation definitions shared by all abilities.

Each motion is a list of (phase_name, duration_ms) — e.g. windup, strike,
impact, return — that the battle state machine steps through. Several
abilities can reuse the same motion (e.g. every ranged skill uses "bolt")
while still doing different damage/effects, since the effect resolves
separately at RESOLVE_PHASE.
"""

MOTIONS = {
    "melee_dash": [("windup", 80), ("strike", 100), ("impact", 110), ("return", 120)],
    "melee_slam": [("windup", 180), ("arc", 380), ("impact", 300), ("return", 320)],
    "spin": [("windup", 120), ("spin_travel", 420), ("impact", 250), ("return", 280)],
    "bolt": [("windup", 150), ("fire", 320), ("impact", 200), ("settle", 180)],
    "cast": [("windup", 200), ("channel", 400), ("release", 250)],
    "swarm": [("scatter", 300), ("reposition", 250), ("strike", 200)],
    # Berserker's basic: a stationary double claw-rake with the axe (no
    # dash-in like the other basics) — two crossing slashes, then reset.
    "slash": [("windup", 90), ("slash1", 80), ("slash2", 90), ("return", 110)],
    # Sukuna's Kai: no travel time and no projectile — the attacker barely
    # moves, and the cut(s) just appear directly on the target at "impact"
    # (see draw_sukuna_effects), instead of a bolt flying across the arena.
    "instant_cut": [("windup", 100), ("impact", 150), ("settle", 150)],
    # Raiju's basic/Blink Strike: the attacker vanishes in a spark of static,
    # reappears already inside striking range of the target, cuts, then
    # flickers back — a teleport-slash instead of a dash-in or stationary hit.
    "flicker_slash": [("vanish", 90), ("reappear", 90), ("strike", 100), ("return", 140)],
    # Thunder God's Descent: a long ritual channel (Raiju calls the storm)
    # before a single sky-splitting bolt slams down on the target.
    "sky_strike": [("windup", 220), ("channel", 380), ("impact", 280), ("settle", 200)],
    # Johnny's Tusk Act 2: unlike "bolt" (which flies to the defender's
    # position at the moment the attack started and can't correct), the nail
    # keeps re-aiming at the defender's *current* position every frame during
    # "chase" — a genuine homing shot instead of a fixed-line one.
    "homing_bolt": [("windup", 140), ("chase", 380), ("impact", 200), ("settle", 160)],
    # Tusk Act 3: no more dash-in or teleport — the nail launches from
    # Johnny (who just keeps roaming, moves_while_active) and ricochets off
    # the arena walls like a DVD logo, hunting for a hit, for as long as
    # "flight" lasts (see RICOCHET_MAX_BOUNCES/RICOCHET_SPEED and
    # ricochet_step in battle_loop.py). 2200ms is generous enough to almost
    # always fit in its full bounce budget before "settle" cuts it off.
    "ricochet": [("windup", 150), ("flight", 2200), ("settle", 200)],
}

# phase at which an ability's damage/effect actually resolves, per motion
RESOLVE_PHASE = {
    "melee_dash": "impact", "melee_slam": "impact", "spin": "impact", "bolt": "impact",
    "cast": "release", "swarm": "strike", "slash": "slash2", "instant_cut": "impact",
    "flicker_slash": "strike", "sky_strike": "impact",
    "homing_bolt": "impact", "ricochet": "settle",
}

# Ability tags whose projectile flies to a fixed point (or, for Tusk Act 3,
# bounces around the arena) instead of homing in on the defender's live
# position — the only ones where the defender actually drifting (or just not
# being where the nail ends up bouncing) can make it whiff. Everything not
# listed here is guaranteed to connect once it resolves: melee/instant
# attacks land wherever the attacker is standing, homing_bolt (Tusk Act 2 and
# Tusk Act 4) re-aims at the defender's *current* spot every frame.
DODGEABLE_TAGS = {"nail_bullet", "tusk_act3"}


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
