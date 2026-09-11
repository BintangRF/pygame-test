"""Raiju move list: Volt Fang, Chain Bolt, Static Field, Static Link,
Thunder God's Descent. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the actual behavior behind each tag
lives in plugin.py, next to this file.

Passive (Static): every landed hit from Raiju stacks Vulnerability on the
target (see RaijuPlugin.on_damage_dealt) — that's dispatched generically off
every ability's damage, not wired into any one move here.
"""

from ...core.abilities import Ability


def make_raiju_abilities():
    return {
        # A bolt of lightning that ricochets off the arena walls like a DVD
        # logo — but unlike Johnny's Tusk Act 3, it doesn't animate that
        # bounce path frame by frame at all: the whole wall-to-wall path
        # resolves in one shot (see "instant_ricochet" in core/motions.py
        # and RaijuPlugin.resolve_instant_ricochet), and it never stops
        # early just because it already touched the defender — the full
        # path always plays out to its last bounce, and every separate
        # bounce-leg that actually crosses a body (the real defender, or one
        # of their own clones/illusions) lands its own separate hit instead
        # of capping out at one (see RaijuPlugin.resolve_special).
        # ignore_clone=True: resolve_special already checks every clone
        # physically along the path itself — the generic single-decoy
        # taunt_redirect pre-pick would only fight that, and would desync
        # the visual path from where the damage actually lands (see
        # StatusLibraryMixin.taunt_redirect's own note on this exact case).
        # Raiju stands his ground the entire time (no moves_while_active):
        # up to 10 bounces, 15 once Static Link has been cast.
        "basic": Ability("Volt Fang", "basic", "instant_ricochet", 1.0, 0.8,
                          tag="volt_fang", ignore_clone=True),
        "skills": [
            # A homing bolt (ignore_clone=True — always finds the real
            # target): a brief stun on impact, then leaves the target
            # burning for 5s.
            Ability("Chain Bolt", "skill", "homing_bolt", 7.5, 1.0, tag="chain_bolt", ignore_clone=True),
            # No damage of its own; drops a field that periodically re-stuns
            # anyone standing in it (see RaijuPlugin.zone_tick's stun-pulse
            # tracking).
            Ability("Static Field", "skill", "cast", 8, 0.0, tag="static_field", ignore_clone=True,
                    cast_target="enemy"),
            # A permanent self-upgrade, not a repeatable cast — one_shot=True
            # means it only ever fires once, then Volt Fang's bounce budget
            # is raised for the rest of the match (see RaijuPlugin.
            # resolve_instant_ricochet).
            Ability("Static Link", "skill", "cast", 3, 0.0, tag="static_link",
                    one_shot=True, ignore_clone=True, cast_target="self"),
        ],
        # Calls down a single sky-splitting bolt: the longest stun and burn
        # in Raiju's kit.
        "ultimate": Ability("Thunder God's Descent", "ultimate", "sky_strike", 15, 1.5,
                             big=True, tag="thunder_descent", aoe_radius=120, ignore_clone=True),
    }
