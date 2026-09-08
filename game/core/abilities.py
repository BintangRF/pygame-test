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
                 ignore_clone=False):
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
        # If set, this ability is flavored as an area attack (Bat Swarm, an
        # ultimate's blast radius, ...) rather than a pure single-target hit
        # — mechanically it still only ever lands on the one chosen defender
        # (this engine has no multi-target resolution), but a character
        # whose own kit spawns extra bodies on the field (Phantom Lancer's
        # illusion clones) can read this to also deal the same damage to
        # anything of its own caught within this radius of wherever the hit
        # actually landed — see PhantomLancerPlugin's on_damage_dealt in
        # characters/phantom_lancer/plugin.py. Two different shapes, sharing
        # this same field for "how far":
        #   aoe_cone_deg unset  -> a blast radius centered on the defender's
        #                          own impact point (Bat Swarm, Kamino,
        #                          Heaven's Verdict, Thunder God's Descent —
        #                          all detonate AT the target, so that's the
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
        # Whether StatusLibraryMixin.taunt_redirect is even allowed to pick
        # a decoy for this ability at all — False (the default) means an
        # eligible decoy pool can still make this ability land on a clone
        # instead of the real defender; True means it always lands on the
        # real defender regardless of any decoy in play. A per-ability call
        # (see each character's own moves.py for which), not derived from
        # motion/kind/aoe automatically — a homing/guaranteed-hit shot and a
        # blast that already reaches clones through splash_aoe_to_clones are
        # the usual reasons a character sets this, but it's each ability's
        # own explicit choice, not an engine-wide rule.
        self.ignore_clone = ignore_clone
