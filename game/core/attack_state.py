"""One fighter's own in-flight ability: everything combat_resolution.py and
battle_loop.py track about a single cast from try_start_attack() through
finish_attack() — who's involved, which motion/phase it's in, and all the
per-motion bookkeeping (projectile flight, ricochet bounces, swarm
projectiles) a specific ability kind needs along the way.

BattleAnimation used to hold exactly one of these inline as ~30 separate
scalar attributes, since only one attack could ever be in flight for the
whole match at a time. Now each fighter can have its own AttackState live
in BattleAnimation.attacks at once (see battle.py) — this class is just
that same bag of fields pulled out so there can be more than one.
"""

import pygame

# Every field name BattleAnimation exposes as a property delegating to
# whichever AttackState is currently bound (see battle.py's _current) —
# kept as one list so both sides (the property generation and this
# class's defaults) stay in sync.
ATTACK_STATE_FIELDS = [
    "attacker", "defender", "ability", "motion",
    "seq", "seq_index", "phase_elapsed", "current_phase", "phase_t",
    "damage_applied", "_miss", "crit",
    "attacker_start", "defender_start", "strike_point", "atk_dir",
    "projectile_pos", "projectile_origin", "projectile_travel",
    "ricochet_pos", "ricochet_vel", "ricochet_bounces", "ricochet_max_bounces",
    "instant_ricochet_resolved", "projectile_hit_confirmed",
    "attack_target_clone", "redirect_target",
    "swarm_projectiles", "swarm_hit_count", "swarm_dmg_total", "swarm_finalized",
]


class AttackState:
    def __init__(self, attacker, defender, ability):
        self.attacker = attacker
        self.defender = defender
        self.ability = ability
        self.motion = None

        self.seq = None
        self.seq_index = 0
        self.phase_elapsed = 0
        self.current_phase = None
        self.phase_t = 0.0
        self.damage_applied = False
        self._miss = False
        # Set True the instant this attack's own damage roll lands as a
        # critical hit (see combat_resolution._strike_defender's generic
        # crit roll, and any character's own bespoke crit passive that flags
        # this itself instead — Chaos Knight's Chaos Strike, Johnny's Tusk
        # Act 2, Before-Hassasin's Lethal Mark) — read by apply_impact
        # (core/impact_fx.py) for the distinct "critical" tier and by
        # draw_fx/render.py wherever a crit should look different from an
        # ordinary hit of the same ability.
        self.crit = False

        self.attacker_start = None
        self.defender_start = None
        self.strike_point = None
        self.atk_dir = pygame.Vector2(1, 0)

        self.projectile_pos = None
        # Dodgeable-bolt flight state (Nail Bullet — see is_dodgeable in
        # core/motions.py): where the nail was actually fired from and how
        # long it's been flying, so it can keep sailing past defender_start
        # instead of stopping there.
        self.projectile_origin = None
        self.projectile_travel = 0.0
        # Tusk Act 3's ricocheting nail (see "ricochet" in core/motions.py
        # and ricochet_step in core/battle_loop.py): its own live position,
        # velocity, and how many walls it's bounced off so far.
        self.ricochet_pos = None
        self.ricochet_vel = None
        self.ricochet_bounces = 0
        self.ricochet_max_bounces = 0
        # Raiju's Volt Fang (see "instant_ricochet" in core/motions.py):
        # whether this attack's whole bounce path has already been resolved
        # in one shot yet.
        self.instant_ricochet_resolved = False
        # True the instant a dodgeable shot's actual flown position ever
        # comes within CHARACTER_HITBOX_R of the defender's *live* position —
        # do_damage() reads this instead of guessing from a single distance
        # snapshot.
        self.projectile_hit_confirmed = False
        self.attack_target_clone = False
        # Whichever decoy taunt_redirect actually picked for this attack
        # (Vampire's clone, one of Phantom Lancer's illusions), or None.
        self.redirect_target = None

        # Any Ability.tag == "swarm" (Vampire's Bat Swarm today, reusable by
        # any future character's own multi-projectile ability): the live
        # list of in-flight swarm projectiles plus the running hit/damage
        # tally for the current barrage, and whether finalize_swarm has
        # already run for it.
        self.swarm_projectiles = []
        self.swarm_hit_count = 0
        self.swarm_dmg_total = 0
        self.swarm_finalized = False
