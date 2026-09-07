"""Phantom Lancer move list: Spear Slash, Spirit Lance, Doppelganger,
Phantom Rush, Juxtapose. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the actual behavior behind each tag
lives in plugin.py next to this file.

Every landed hit from Spear Slash or Spirit Lance triggers the Juxtapose
passive (see PhantomLancerPlugin.on_damage_dealt) — Doppelganger, Phantom
Rush, and the Juxtapose ultimate are all pure-utility (dmg_mult 0.0) and
never spawn a clone themselves this way, only through the ultimate's own
direct spawn_clone() calls."""

from ...core.abilities import Ability


def make_phantom_lancer_abilities():
    return {
        "basic": Ability("Spear Slash", "basic", "slash", 850, 0.7, melee_range=80),
        "skills": [
            # A genuine homing shot (see "homing_bolt" in core/motions.py) —
            # always finds its living target regardless of drift.
            Ability("Spirit Lance", "skill", "homing_bolt", 3200, 0.2, tag="spirit_lance"),
            # No damage of its own — a brief both-direction damage immunity
            # window (the "vanished" status; see core/status_library.py)
            # while Phantom Lancer keeps drifting on its current heading.
            Ability("Doppelganger", "skill", "instant", 6000, 0.0, tag="doppelganger"),
            # No damage — a short, sharp move-speed burst (the generic
            # "move_speed_up" status).
            Ability("Phantom Rush", "skill", "cast", 4000, 0.0, tag="phantom_rush"),
        ],
        # No damage of its own — upgrades the Juxtapose passive's own cap/
        # stats/duration for a while, and immediately conjures two clones at
        # the boosted stats as its own payoff.
        "ultimate": Ability("Juxtapose", "ultimate", "cast", 12000, 0.0, big=True, tag="juxtapose"),
    }
