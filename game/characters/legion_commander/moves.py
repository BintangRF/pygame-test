"""Legion Commander move list: Scepter Strike, Overwhelming Odds, Press the
Attack, Moment of Courage, Duel. The numbers/tags here drive the generic
combat pipeline (core/combat_resolution.py); the actual behavior behind each
tag lives in plugin.py, next to this file.

Passive (Unyielding Resolve): while the opponent's hp is higher than Legion
Commander's own, she fights harder — a flat Attack Up + Armor Up buff kept
refreshed every frame (see LegionCommanderPlugin.ambient_tick), dropped the
instant the opponent's hp falls back to or below her own — not wired into
any one move here."""

from ...core.abilities import Ability


def make_legion_commander_abilities():
    return {
        "basic": Ability("Scepter Strike", "basic", "slash", 1.0, 1.0, melee_range=110),
        "skills": [
            # A radial flame-arrow barrage flying in from random points
            # around the whole arena (swarm_pattern="radial") at randomly
            # staggered times (swarm_timing="random") rather than one aimed
            # shot — resolves through the generic swarm engine (core/
            # battle_loop.py's spawn_swarm_projectiles/update_swarm_projectiles),
            # same as Vampire's own Bat Swarm (see
            # LegionCommanderPlugin.resolve_special). Every arrow that
            # actually connects also chips armor and leaves its target
            # burning (see LegionCommanderPlugin.on_damage_dealt).
            # ignore_clone=True, no aoe_radius: same reasoning as Bat Swarm —
            # this never consults redirect_target at all, and the barrage's
            # own projectiles already fly through the whole arena on their
            # own paths, so no separate guaranteed splash is needed either.
            Ability("Overwhelming Odds", "skill", "swarm", 3, 1, tag="overwhelming_odds",
                    ignore_clone=True, swarm_pattern="radial", swarm_timing="random",
                    swarm_count=20, swarm_speed=1050, swarm_size=46),
            # No damage of its own — cleanses every strippable debuff off
            # Legion Commander, tops her up with a quick heal, and sends her
            # into a short burst of move speed (see apply_tag_effects).
            Ability("Press the Attack", "skill", "cast", 7, 0.0, tag="press_the_attack",
                    ignore_clone=True, cast_target="self"),
            # No damage of its own — a short window of the generic
            # "lifesteal" status (100% of whatever damage actually lands
            # healed back, see core/status_library.py).
            Ability("Moment of Courage", "skill", "cast", 10, 0.0, tag="moment_of_courage",
                    ignore_clone=True, cast_target="self"),
        ],
        # Blinks Legion Commander to exactly her own basic attack's melee
        # range from the defender — the same teleport Chaos Knight's Reality
        # Rift uses (see LegionCommanderPlugin.strike_point_override) — and
        # always follows up with a guaranteed Scepter Strike (see
        # forced_ability). No damage of its own; the whole payoff is the
        # mutual root+silence lockdown, the self-only Reflect window while it
        # lasts, and the permanent Attack Up once it ends (see
        # apply_tag_effects/ambient_tick).
        "ultimate": Ability("Duel", "ultimate", "flicker_slash", 10, 0.0,
                             big=True, tag="duel", ignore_clone=True),
    }
