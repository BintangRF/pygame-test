"""Chaos Knight move list: Mace Slash, Chaos Bolt, Reality Rift, Phantasm.
The numbers/tags here drive the generic combat pipeline
(core/combat_resolution.py); the actual behavior behind each tag lives in
plugin.py, next to this file.

Passive (Chaos Strike): every Mace Slash has a flat chance to land as a
critical hit and lifesteal off the damage it dealt — dispatched generically
off the basic attack's own outgoing_damage/on_damage_dealt hooks (see
ChaosKnightPlugin), not wired into any one move here."""

from ...core.abilities import Ability


def make_chaos_knight_abilities():
    return {
        "basic": Ability("Mace Slash", "basic", "slash", 1.0, 1.0, melee_range=100, tag="mace_slash"),
        "skills": [
            # A homing bolt (ignore_clone=True — always finds the real
            # target, same reasoning as Raiju's Chain Bolt/Vampire's Blood
            # Bolt): stuns on impact for a random duration between 0.5s and
            # 1.5s (see ChaosKnightPlugin.apply_tag_effects).
            Ability("Chaos Bolt", "skill", "homing_bolt", 5, 1.0, tag="chaos_bolt", ignore_clone=True),
            # No damage of its own (dmg_mult 0) — blinks Chaos Knight to
            # exactly its own basic attack's melee range from the defender
            # (see ChaosKnightPlugin.strike_point_override, using "flicker_slash"'s
            # genuine teleport — see core/motions.py) and roots them for the
            # brief instant of the teleport.
            Ability("Reality Rift", "skill", "flicker_slash", 5, 0.0, tag="reality_rift"),
        ],
        # Summons a full-power illusion that fights and casts alongside
        # Chaos Knight for the rest of its duration (see
        # ChaosKnightPlugin.apply_tag_effects / core/clone_army.py).
        "ultimate": Ability("Phantasm", "ultimate", "cast", 7, 0.0, big=True, tag="phantasm",
                             cast_target="self"),
    }
