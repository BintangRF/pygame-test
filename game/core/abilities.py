"""The `Ability` data bundle shared by every character's move list.

Each Ability says what motion animation it plays, how much it costs in
cooldown, how much damage/heal it does, and a `tag` used by the battle
state machine to run its special effect (mark, shield, curse, etc). The
move lists themselves — one function per character, e.g.
make_paladin_abilities() — live next to that character's other code in
characters/<name>/moves.py, not here.
"""


class Ability:
    def __init__(self, name, kind, motion, cooldown_ms, dmg_mult,
                 heal_ratio=0.0, big=False, tag=None, melee_range=None, hp_threshold=None,
                 one_shot=False, moves_while_active=False):
        self.name = name
        self.kind = kind  # "basic" | "skill" | "ultimate"
        self.motion = motion
        self.cooldown_ms = cooldown_ms
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
        self.timer = 0  # ms remaining until ready again
        # if set, this ability can only ever fire once per match — no
        # cooldown-based re-trigger; see `used` below
        self.one_shot = one_shot
        self.used = False
