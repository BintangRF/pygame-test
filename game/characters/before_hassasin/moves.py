"""Before-Hassasin move list: Twin Fangs, Death Scent, Trace of Death,
Zabaniya. The numbers/tags here drive the generic combat pipeline
(core/combat_resolution.py); the actual behavior behind each tag lives in
plugin.py, next to this file.

Passive (built into Twin Fangs, not a separate ability slot): the basic
attack has no melee_range gate at all (always usable at any distance) — its
own plugin flips `motion` between "instant" (a bare-blade slash, when
already within BH_MELEE_RANGE of the target) and "swarm" (3 knives thrown in
3 genuinely different directions, not all converging on the target — see
swarm_pattern="fan" below and BeforeHassasinPlugin.resolve_special) every
frame, based on the live distance to the defender, right before it's
actually cast — see BeforeHassasinPlugin.forced_ability/
_refresh_basic_motion. The motion set here is just its starting value; both
modes deal Twin Fangs' own full dmg_mult on whatever they actually connect
with, they only differ in animation/spread. moves_while_active=True on top
of that — same as Johnny's Nail Bullet — so Before-Hassasin never freezes
in place for either mode, always kept DVD-bounce roaming through its own
windup/impact/settle."""

from ...core.abilities import Ability


def make_before_hassasin_abilities():
    return {
        # swarm_* only ever matters once `motion` actually flips to "swarm"
        # (see the module docstring) — a melee-range Twin Fangs never reads
        # them at all. 3 knives, thrown at once, fanned across 50 degrees —
        # tighter than the engine's own SWARM_FAN_DEG_DEFAULT spread would
        # read as "aimed", wider reads as "sprayed"; a bit faster than a
        # Bat Swarm bolt (SWARM_PROJECTILE_SPEED) since this is a basic
        # attack's own short cooldown, not a barrage ultimate.
        "basic": Ability("Twin Fangs", "basic", "instant", 0.5, 1.0, tag="twin_fangs",
                          moves_while_active=True, swarm_pattern="fan", swarm_timing="simultaneous",
                          swarm_count=3, swarm_speed=1050, swarm_fan_deg=50),
        "skills": [
            # Pure utility (dmg_mult 0) — drops a lingering cloud of smoke
            # centered on the opponent's own position (cast_target="enemy",
            # same shape as Raiju's Static Field: a Zone dropped directly
            # under the target rather than a projectile that flies there,
            # see BeforeHassasinPlugin.apply_tag_effects/zone_tick) that
            # disarms+silences+weakens (Vulnerability, less effective armor)
            # anyone standing in it, refreshed continuously while they stay
            # inside and left to lapse within a fraction of a second of
            # stepping clear — then BH blinks in right beside them.
            # ignore_clone=True (same reasoning as Raiju's Chain Bolt/
            # Vampire's Blood Hex): the cloud always centers on the real
            # opponent, never a decoy.
            Ability("Death Scent", "skill", "cast", 7, 0.0, tag="death_scent", ignore_clone=True,
                    cast_target="enemy"),
            # No damage, no fixed effect — one of 3 random payoffs each cast
            # (see BeforeHassasinPlugin.apply_tag_effects): a stat buff, a
            # primed crit+bleed on the next Twin Fangs, or an instant
            # poison+blind hex thrown on the opponent instead.
            Ability("Trace of Death", "skill", "cast", 7, 0.0, tag="trace_of_death", cast_target="self"),
        ],
        # Plunges the arena into darkness for its duration: the opponent is
        # blinded, and Twin Fangs itself turns into a guaranteed, arena-wide
        # hit that also reaches every one of the opponent's own clones/
        # illusions at once (see BeforeHassasinPlugin.apply_tag_effects/
        # on_status_expire).
        "ultimate": Ability("Zabaniya", "ultimate", "cast", 10, 0.0, big=True, tag="death_ultimate",
                             cast_target="self"),
    }
