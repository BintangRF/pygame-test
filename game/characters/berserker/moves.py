"""Berserker move list: Reckless Cleave, Axe Throw, Whirling Axes, Berserker Rage. The
numbers/tags here drive the generic combat pipeline
(core/combat_resolution.py); the actual behavior behind each tag lives in
ability.py, and its animation in fx.py, next to this file."""

from ...core.abilities import Ability


def make_berserker_abilities():
    return {
        # quicker attack speed than the other fighters' basics (0.55s vs
        # 0.9s) but a much shorter reach (110 vs 170) — has to get in close.
        # Uses "slash" motion, not "melee_dash": a stationary double rake
        # with the axe instead of a dash-in strike like the others.
        # No aoe_radius here — Reckless Cleave only gains its splash once
        # Rage's own timed window ends (see BerserkerPlugin.on_status_expire).
        "basic": Ability("Reckless Cleave", "basic", "slash", 1, 1, melee_range=100),
        "skills": [
            # A fan/cone (see draw_fan/_draw_axe_fan in plugin.py), not a
            # blast centered on the target — aoe_cone_deg says so. aoe_radius
            # is a genuine fixed reach here (unlike a plain blast, where it's
            # already naturally centered on wherever the hit landed): the
            # fan's real size can't depend on how far the one resolved
            # target happened to be standing, or it'd be a different size
            # every cast — same fixed area always, whether that hits 0 or 5
            # clones this time. 540 comfortably clears the arena's own
            # corner-to-corner diagonal (~537, see ARENA_RECT in
            # core/constants.py) so the fan's outer edge always reaches the
            # map's own walls, at any angle, no matter where on the field
            # the Berserker throws from. No ignore_clone needed (and none
            # wanted): declaring an area at all is already what makes this
            # hit every body inside it — the real fighter and each of their
            # illusions alike, none of them standing in for the others (see
            # StatusLibraryMixin.taunt_redirect / combat_resolution.
            # do_damage).
            Ability("Axe Throw", "skill", "bolt", 3, 0.6, tag="axe_throw", aoe_cone_deg=64, aoe_radius=540),
            # Axes orbit the Berserker on an ever-widening ring (see
            # _draw_whirling_axes in plugin.py) out to aoe_radius, hitting
            # each enemy body once the moment the ring reaches it (see
            # BerserkerPlugin.attack_frame), centered on the Berserker, not
            # the defender. Every cast cleanses the Berserker first, the
            # instant it starts (so a Blind can't make the spin whiff).
            # moves_while_active: the Berserker keeps roaming while the axes
            # spin, and the ring (drawn and hit-checked at the Berserker's
            # live position) travels with it.
            Ability("Whirling Axes", "skill", "whirl", 5, 0.6, tag="whirling_axes",
                    aoe_radius=140, moves_while_active=True),
        ],
        # no meter gate at all — this ultimate is desperation, not a builder.
        # It only becomes available once HP drops below 30%, and it's a
        # one-shot: no cooldown, it simply can never fire a second time
        # (whether it goes off proactively here or via the death-save last
        # stand in ability.py — see berserker_death_save's used-flag check).
        "ultimate": Ability("Berserker Rage", "ultimate", "cast", 0, 0.0,
                             big=True, tag="berserker_rage", hp_threshold=0.5,
                             one_shot=True, cast_target="self"),
    }
