"""The `Ability` data bundle shared by every character's move list.

Each Ability says what motion animation it plays, how much it costs in
cooldown, how much damage/heal it does, and a `tag` used by the battle
state machine to run its special effect (mark, shield, curse, etc). The
move lists themselves — one function per character, e.g.
make_paladin_abilities() — live next to that character's other code in
characters/<name>/moves.py, not here.
"""


class Ability:
    def __init__(self, name, kind, motion, cooldown, dmg_mult,
                 heal_ratio=0.0, big=False, tag=None, melee_range=None, hp_threshold=None,
                 one_shot=False, moves_while_active=False, aoe_radius=None, aoe_cone_deg=None,
                 ignore_clone=False, ignore_taunt=False, swarm_pattern=None, swarm_timing=None,
                 swarm_count=None, swarm_speed=None, swarm_size=None):
        self.name = name
        self.kind = kind  # "basic" | "skill" | "ultimate"
        self.motion = motion
        self.cooldown = cooldown
        self.dmg_mult = dmg_mult
        self.heal_ratio = heal_ratio
        self.big = big
        self.tag = tag
        self.melee_range = melee_range  # if set, only usable within this distance
        # Every ability's user falls into one of two camps while it plays
        # out: planted in place for its dash/arc/lean animation (the
        # default — every melee/cast/teleport move in the game), or, if
        # this is set, just left to keep doing the same plain linear
        # DVD-logo bounce roam as always (see roam_step in
        # battle_loop.py) — currently only Johnny's Nail Bullet, since a
        # ranged shot has no dash-in or stance to commit to. Independent of
        # is_dodgeable (motions.py), which is about whether the *target*
        # can be missed, not whether the *user* keeps moving.
        self.moves_while_active = moves_while_active
        # if set, this ultimate charges by HP condition (owner's hp/max_hp
        # below this ratio) instead of the usual meter-fill gate
        self.hp_threshold = hp_threshold
        self.timer = 0  # seconds remaining until ready again
        # if set, this ability can only ever fire once per match — no
        # cooldown-based re-trigger; see `used` below
        self.one_shot = one_shot
        self.used = False
        # If set, this ability is flavored as an area attack (an ultimate's
        # blast radius, ...) rather than a pure single-target hit —
        # mechanically it still only ever lands on the one chosen defender
        # (this engine has no multi-target resolution), but a character
        # whose own kit spawns extra bodies on the field (Phantom Lancer's
        # illusion clones) can read this to also deal the same damage to
        # anything of its own caught within this radius of wherever the hit
        # actually landed — see PhantomLancerPlugin's on_damage_dealt in
        # characters/phantom_lancer/plugin.py. Not used by Bat Swarm (tag ==
        # "swarm") — that ability's own projectiles already fly through the
        # whole arena on their own paths (see spawn_swarm_projectiles/
        # update_swarm_projectiles in core/battle_loop.py) and can
        # incidentally catch a clone directly, so it needs no separate
        # guaranteed splash centered on one impact point. Two different
        # shapes, sharing this same field for "how far":
        #   aoe_cone_deg unset  -> a blast radius centered on the defender's
        #                          own impact point (Kamino, Heaven's
        #                          Verdict, Thunder God's Descent — all
        #                          detonate AT the target, so that's the
        #                          right origin).
        #   aoe_cone_deg set    -> aoe_radius is instead the reach of a cone
        #                          swept from the ATTACKER's own position
        #                          along its cast direction (Axe Throw's fan
        #                          — see draw_fan/_draw_axe_fan in
        #                          characters/berserker/plugin.py; the fan
        #                          originates at the attacker, not the
        #                          target, so centering a blast on the
        #                          defender instead would put the whole
        #                          shape in the wrong place).
        self.aoe_radius = aoe_radius
        self.aoe_cone_deg = aoe_cone_deg
        # Whether StatusLibraryMixin.taunt_redirect is allowed to pick a
        # decoy from the defender's own weighted illusion pool
        # (basic_attack_decoys(), e.g. Phantom Lancer's clones) for this
        # ability — False (the default) means an eligible pool can still
        # make this ability land on one of those instead of the real
        # defender; True excludes that pool entirely, always landing on the
        # real defender. A per-ability call (see each character's own
        # moves.py for which), not derived from motion/kind/aoe
        # automatically — a homing/guaranteed-hit shot and a blast that
        # already reaches clones through splash_aoe_to_clones are the usual
        # reasons a character sets this, but it's each ability's own
        # explicit choice, not an engine-wide rule. Does NOT exclude an
        # actively taunting decoy (Vampire's Crimson Doppelganger) — that's
        # a guaranteed 100% redirect regardless of this flag, since the
        # defender is genuinely fooled rather than the attack just happening
        # to have several equally-valid bodies to pick from; see
        # taunt_redirect's own docstring.
        self.ignore_clone = ignore_clone
        # A narrower, separate exclusion that blocks even a taunting decoy:
        # only for an ability whose own resolve_special() bypasses
        # redirect_target entirely (always deals damage straight to the real
        # battle.defender) while its draw_fx still keys its visual strike
        # position off battle.defender_start (Kai's fanned cuts — see
        # SukunaPlugin.draw_fx/resolve_special) — letting taunt move
        # defender_start to a decoy there would show the cuts landing on the
        # decoy while the damage still actually lands on the real target.
        # Every other resolve_special ability either doesn't read
        # defender_start for its own visual at all (Volt Fang) or has no way
        # to ever face its own owner's taunting decoy (Bat Swarm), so this
        # should stay unused outside that one specific shape.
        self.ignore_taunt = ignore_taunt
        # Only meaningful for an Ability.tag == "swarm" (see
        # spawn_swarm_projectiles in core/battle_loop.py): how the barrage's
        # individual projectiles are launched and timed, so a single generic
        # engine can drive any future swarm-flavored ability instead of
        # hand-rolling one per character.
        #   swarm_pattern: "radial" (default) launches each projectile from a
        #     random point around every edge of the arena, converging back
        #     toward the defender — "coming from every side of the map".
        #     "linear" instead lines every projectile up off one straight
        #     edge and sends them all the same direction (self.atk_dir),
        #     like a single volley sweeping across the map.
        #   swarm_timing: "simultaneous" (default) launches every projectile
        #     at once; "staggered" spaces them evenly across the barrage so
        #     they arrive in an orderly wave; "random" gives each an
        #     independent random delay, arriving in no particular order.
        #   swarm_count/swarm_speed: how many projectiles the barrage
        #     launches and how fast each one flies (px/s) — None falls back
        #     to BattleLoopMixin's own SWARM_PROJECTILE_COUNT/
        #     SWARM_PROJECTILE_SPEED, but any character can override either
        #     per ability (a denser/slower swarm reads very differently from
        #     a sparse/fast one) instead of every swarm-tagged ability being
        #     forced to share one engine-wide feel.
        #   swarm_size: the on-screen diameter (px) of one projectile — pure
        #     presentation, read by whichever plugin actually draws it (e.g.
        #     VampirePlugin.draw_projectile's BAT_SPRITE_SIZE fallback), not
        #     by the engine itself.
        self.swarm_pattern = swarm_pattern
        self.swarm_timing = swarm_timing
        self.swarm_count = swarm_count
        self.swarm_speed = swarm_speed
        self.swarm_size = swarm_size
