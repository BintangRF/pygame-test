"""Leonidas move list: Spear Thrust, Javelin Charge, Shield Slam, War Cry,
This Is Sparta! The numbers/tags here drive the generic combat pipeline
(core/combat_resolution.py); the actual behavior behind each tag lives in
plugin.py, next to this file.

Passive (Spartan Fury): landing a hit or taking one charges a bespoke gauge
(separate from the generic meter_max/meter_gain ultimate-charge above) that,
once full, unloads a temporary Armor Up + Attack Up + Cleanse + extended
basic-attack range, and turns Spear Thrust's plain double-slash into a
hold-and-release thrust whose damage grows the longer it's held ready before
an enemy actually walks into its range (see LeonidasPlugin.ambient_tick/
cooldown_bonus/outgoing_damage) — not wired into any one move here."""

from ...core.abilities import Ability


def make_leonidas_abilities():
    return {
        # A stationary double-thrust (see "slash" in core/motions.py), same
        # shape Berserker's Reckless Cleave/Phantom Lancer's Spear Slash use
        # — no dash-in, Leonidas just plants and stabs twice. While Spartan
        # Fury is up this becomes a hold-and-release thrust instead (see
        # LeonidasPlugin's own ambient_tick/outgoing_damage/draw_fx).
        "basic": Ability("Spear Thrust", "basic", "slash", 1.0, 1.0, melee_range=115),
        "skills": [
            # A dead-straight bull-charge through the defender and on to the
            # arena edge (see "charge" in core/motions.py) — no melee_range
            # gate, this is Leonidas's own gap closer. While This Is Sparta!'s
            # own Spartan formation is out, every Spartan mirrors this same
            # charge at the same instant, each along its own formation
            # direction (see LeonidasPlugin.apply_tag_effects/_legion_charge).
            Ability("Javelin Charge", "skill", "charge", 6, 1.3, tag="javelin_charge"),
            # A shield-first dash that shatters the target's guard and drops
            # them stunned (see LeonidasPlugin.apply_tag_effects). No
            # melee_range — a skill's own melee_range is never actually read
            # anywhere (combat_resolution.choose_ability only ever gates a
            # BASIC that way), so this is a gap-closer, not a close-range-only
            # follow-up.
            Ability("Shield Slam", "skill", "melee_dash", 8, 1.0, tag="shield_slam"),
            # No damage of its own — drops a warcry field at the target's own
            # position that saps move speed and attack while anyone but
            # Leonidas stands in it (see LeonidasPlugin.zone_tick).
            Ability("War Cry", "skill", "cast", 9, 0.0, tag="war_cry", ignore_clone=True, cast_target="enemy"),
        ],
        # No damage of its own — conjures a formation (linear or circle,
        # picked at random each cast) of Spartan illusions around Leonidas
        # (see LeonidasPlugin._summon_phalanx), each holding its own slot and
        # its own outward facing.
        "ultimate": Ability("This Is Sparta!", "ultimate", "cast", 11, 0.0,
                             big=True, tag="phalanx_call", ignore_clone=True, cast_target="self"),
    }
