"""Sukuna move list: Hachi, Kai, Ten Shadows, Kamino. The numbers/tags here drive the
generic combat pipeline (core/combat_resolution.py); the actual behavior
behind each tag lives in ability.py, and its animation in fx.py, next to
this file."""

from ...core.abilities import Ability


def make_sukuna_abilities():
    return {
        # no dash, no projectile — a single cut just appears on the target
        # (reuses "instant", same as Kai below, just one hit instead of
        # a flurry). Cooldown cut to 0.5s (was 1, same as everyone else's
        # basic, which never actually delivered on the "cuts fast and
        # often" identity CHARACTERS' own sukuna comment describes) — this
        # is what a below-average ATK stat is supposed to be traded for,
        # and it's also what feeds SukunaPlugin's Slaughter passive
        # (stacking Attack Up off landed hits — see plugin.py) enough hits
        # to actually ramp up during a fight instead of sitting flat.
        "basic": Ability("Hachi", "basic", "instant", 0.5, 0.6, tag="dismantle"),
        "skills": [
            # no windup travel, no projectile — the cut just appears on the
            # target (see "instant" in core/motions.py / core/battle_loop.py).
            # Instead of dealing its own damage, using Kai procs the *basic
            # attack* itself 3-5 times at once (see sukuna_resolve_kai_flurry
            # in ability.py) — dmg_mult here is per-proc, matching Hachi's own 0.8.
            # ignore_clone=True: Kai resolves through SukunaPlugin.
            # resolve_special (see there), which always deals its damage
            # straight to battle.defender directly and never consults
            # redirect_target — leaving this redirect-eligible would desync
            # the visual strike position (moved to a decoy) from where the
            # damage actually lands. ignore_taunt=True on top of that for the
            # same reason, specifically covering a taunting decoy (Vampire's
            # Crimson Doppelganger) too — plain ignore_clone no longer blocks
            # that source on its own (see taunt_redirect), but Kai's own
            # draw_fx still keys its cuts off battle.defender_start, so it
            # needs the same exclusion.
            Ability("Kai", "skill", "instant", 5, 0.9, tag="kai_flurry", ignore_clone=True, ignore_taunt=True),
            # Ten Shadows: a self-cast summon (cast_target="self", same
            # shape as Vampire's Blood Pool/Crimson Doppelganger) that
            # conjures one of ten shadows at random, each with its own
            # power, on-hit effect, and movement pattern — see SukunaPlugin's
            # SHADOWS table, apply_tag_effects, and the _move_* methods.
            # Resolved entirely through this plugin's own CloneArmy
            # (SukunaPlugin.shadow_army, cap > 1 — see its own comment for
            # why — so recasting stacks a second/third shadow instead of only
            # ever replacing the last one). Cooldown cut hard (was 13, then
            # 10) as part of an overall buff pass: Sukuna's low base ATK (see
            # CHARACTERS) was leaving him weak, and a shadow pack that can
            # actually stack is the fix, not just a bigger number on one
            # stat. dmg_mult 0.0 like every other pure-utility self-cast in
            # this game — no ignore_clone needed either, since
            # taunt_redirect's own dmg_mult<=0 check already skips it
            # regardless.
            Ability("Ten Shadows", "skill", "cast", 8, 0.0, tag="ten_shadows", cast_target="self"),
        ],
        # King of Curses' finisher: a devastating channeled strike that both
        # nukes and leaves the target bleeding out with healing crippled.
        # Cooldown shortened well below the other cast's 16s so it comes
        # back into play sooner between meter charges.
        # Uses "bolt" (not "cast") so it actually travels as a visible
        # projectile — see draw_fire_arrow / draw_projectile in
        # core/render.py — instead of resolving instantly in place like
        # Sukuna's other moves. No ignore_clone: aoe_radius alone already
        # means this blast damages every body inside it rather than picking
        # one to land on (see StatusLibraryMixin.taunt_redirect).
        "ultimate": Ability("Kamino", "ultimate", "homing_bolt", 10, 3, big=True, tag="kamino",
                            aoe_radius=110),
    }
