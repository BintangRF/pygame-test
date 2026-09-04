"""Reusable status-effect library, layered on top of the timed-status
plumbing in entities.set_status()/status_effects.py's tick_statuses. That
plumbing only gives every status a shared timer and an expiry hook and
leaves *what a status actually does* to be reinvented per character (see
how Paladin's shield-absorb and Vampire's disarm+silence+slow lockdown each
used to live only in that one character's own plugin, invisible to anyone
else's statuses) —
this module is the opposite: one canonical implementation of a full
MOBA-style effect taxonomy that the shared pipeline (combat_resolution.py,
battle_loop.py) already reads generically, so any character reaches for
`set_status(defender, "stunned", 1500)` or `set_status(defender,
"vulnerability", 3000, pct=0.3)` and gets correct, consistent behavior with
zero new plumbing — the duration and every kwarg (pct/dps/bonus/...) stays
that character's own call, never a default owned by this module.

Every status this module gives shared meaning to (a character reaches for
`set_status(fighter, name, ms, **kwargs)` with any name below and gets
correct, consistent behavior — the kwargs each name reads are noted inline;
`ms`/duration is never one of them, that's plumbed generically by
entities.set_status()/status_effects.py already):

  Hard CC (gated generically by can_move/can_basic_attack/can_use_skill/
  can_act below — see BLOCKS_MOVE/BLOCKS_BASIC/BLOCKS_SKILL/BLOCKS_ACT;
  knockback/pull are instant shoves, not timed statuses, see
  apply_knockback/apply_pull instead):
    stunned   - full lock: no move, no basic attack, no skill.
    frozen    - same full lock as stunned, plus an optional "dps" tick.
    rooted    - blocks movement only; can still attack/use skills.
    silenced  - blocks skills/ultimate only.
    disarmed  - blocks basic attacks only.
    slowed    - "pct" move-speed penalty, no action lock at all.
    feared    - full basic/skill lock, and forces movement away from
                whoever applied it instead of normal roaming (see
                forced_flee_step).
    asleep    - full lock; breaks instantly the moment the target takes
                any damage (see wake_from_sleep).
    curse     - disarmed + silenced + slowed bundled into one status
                ("pct" is the slow half); optional "dps" on top (Vampire's
                Blood Hex is the only source right now).

  DoT ("dps" tick, applied every frame by tick_library_effects; the ones
  marked optional can be applied purely for a debuff they carry with no
  actual damage tick):
    bleed       - "dps"; optional "move_bonus_dps" adds extra damage while
                  the target is moving during roam.
    poison      - "dps".
    burn        - "dps".
    corruption  - "dps" optional. Also the generic heal-reduction effect
                  (see Debuffs below) — a character can apply it purely for
                  that "pct" and skip "dps" entirely, same as curse's slow.
    frozen      - "dps" optional, layered on top of its own Hard CC lock.

  Debuffs:
    armor_break  - "pct" less armor mitigation (folded into the armor
                   formula in apply_damage, not a flat multiplier).
    vulnerability      - "pct" more damage taken (status_damage_multiplier).
    attack_down        - "pct" less damage dealt (status_outgoing_multiplier).
    attack_speed_down  - "pct" slower attacks (status_attack_speed_multiplier).
    blind              - "chance" the holder's own swing just whiffs
                         (roll_blind_miss).
    cooldown_increase  - "pct" slower ability cooldowns
                         (status_cooldown_multiplier).
    corruption         - "pct" less healing received (heal_reduction_
                         multiplier/heal) — see DoT above for its other half.

  Buffs:
    regen             - "hps" healed every frame (tick_library_effects).
    shield            - "absorb": a flat barrier that eats incoming damage
                        before hp does, sized however big each character's
                        own kit needs it (see apply_shield_absorb). Purely a
                        barrier — pair it with damage_reduction below if a
                        kit also wants an upfront % mitigation.
    damage_reduction  - "pct" flat less damage taken (status_damage_
                        multiplier) — the generic "% mitigation" buff, kept
                        separate from shield's own barrier so the two can be
                        used independently or together.
    attack_up         - "pct" more damage dealt.
    attack_speed_up   - "pct" faster attacks.
    move_speed_up     - "pct" faster movement.
    lifesteal         - "pct" of damage dealt returned as healing
                        (lifesteal_pct).
    invulnerable      - immune to all damage (is_invulnerable) — also
                        suppresses every DoT/HoT tick for its holder.
    reflect           - "pct" of damage taken bounced back at the attacker
                        (apply_status_reflect).
    (heal and cleanse below are one-shot actions, not statuses themselves.)

  Special:
    taunt  - lives on a decoy (the Clone), never on a fighter, so it's
             deliberately absent from CLEANSABLE. Forces an attack aimed at
             its owner onto the decoy instead (see taunt_redirect).
             Vampire's Crimson Doppelganger is the only source right now.

  Not a status at all — already generic elsewhere, so neither needed a new
  entry here: Execute (combat_resolution.do_damage, any ultimate vs <30%
  hp) and Zone (Zone/zone_tick).

A character can still layer its own extra flavor on top of any of these via
its own plugin hooks (Paladin's Holy Nova retaliation on on_shield_broken,
say) — the generic behavior below is what runs by default, not instead of.
"""

import random

import pygame

from .constants import (
    BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, CURSE_COLOR, GRAY, GREEN, ORANGE, POISON_COLOR, RED, WHITE,
)
# ---- action gating -----------------------------------------------------

# Which statuses block which kind of action — checked generically instead of
# a hand-rolled f.statuses.get(name) at every call site. "rooted" only ever
# blocks movement (per Root's own definition: still able to fight back),
# which is why it's absent from every BLOCKS_* set below except MOVE.
BLOCKS_MOVE = {"stunned", "frozen", "rooted", "asleep"}
# "curse" bundles disarm + silence (see status_move_speed_multiplier below
# for its slow half) into one status, so it belongs in both sets — Vampire's
# Blood Hex is its only source right now.
BLOCKS_BASIC = {"stunned", "frozen", "disarmed", "curse", "asleep", "feared"}
BLOCKS_SKILL = {"stunned", "frozen", "silenced", "curse", "asleep", "feared"}
# The fast-path "nothing at all is possible" gate for start_attack — a
# perf-only shortcut (choose_ability's own per-candidate gating below would
# reach the same empty-candidates result on its own for disarm/silence
# alone), so it only needs to list the *fully* incapacitating statuses.
BLOCKS_ACT = {"stunned", "frozen", "asleep", "feared"}

# Every status Cleanse can strip. A character's own bespoke debuff (Raiju's
# "static") is deliberately not covered here — only this generic table's own
# effects are.
CLEANSABLE = {
    "stunned", "frozen", "rooted", "silenced", "disarmed", "slowed",
    "feared", "asleep",
    "burn", "poison", "bleed", "curse", "corruption",
    "armor_break", "vulnerability", "attack_down",
    "attack_speed_down", "blind", "cooldown_increase",
}
# "taunt" is deliberately not in here — it lives on a decoy (the Clone),
# not a fighter, so there's nothing for a normal Cleanse to strip.

# Damage/heal-over-time ticked by tick_library_effects.
_DOT_NAMES = ("bleed", "poison", "burn", "curse", "corruption", "frozen")
_HOT_NAMES = ("regen",)

# Generic status-ring color for render.py's fallback loop — only statuses
# without their own bespoke draw already in render.py need an entry (shield,
# bleed, poison, static, rooted, stunned keep their existing hand-tuned look
# and are left out on purpose; invulnerable keeps its plain entry here even
# though Berserker's plugin layers its own extra orange ring on top while
# raging; taunt keeps its plain entry too even though draw_clone in
# render.py layers its own pulsing ring on top).
RING_COLOR = {
    "frozen": (130, 210, 255),
    "silenced": (170, 130, 220),
    "disarmed": (190, 140, 70),
    "slowed": (110, 150, 190),
    "feared": (110, 40, 130),
    "taunt": (220, 90, 60),
    "asleep": (90, 90, 170),
    "burn": (240, 110, 40),
    "curse": CURSE_COLOR,
    "corruption": (110, 160, 80),
    "armor_break": (140, 140, 140),
    "vulnerability": RED,
    "attack_down": (90, 120, 180),
    "attack_speed_down": (80, 150, 150),
    "blind": (60, 60, 60),
    "cooldown_increase": (130, 90, 180),
    "regen": GREEN,
    "damage_reduction": (90, 140, 210),
    "attack_up": ORANGE,
    "attack_speed_up": (230, 220, 90),
    "move_speed_up": (90, 220, 210),
    "lifesteal": (150, 30, 50),
    "invulnerable": WHITE,
    "reflect": (200, 200, 210),
}


# ---- one-shot / stateless helpers (no battle instance needed) ----------

def heal(target, amount):
    """The generic external-heal funnel (regen ticks, a future plain Heal
    skill) — respects the target's own Corruption debuff the same way
    outgoing lifesteal/heal_ratio already does in combat_resolution.py.
    Returns the actual amount restored."""
    if amount <= 0:
        return 0
    corruption = target.statuses.get("corruption")
    mult = 1 - corruption["pct"] if corruption else 1.0
    amount = round(amount * mult)
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    return target.hp - before


def cleanse(target, names=None):
    """Strip hard-CC/DoT/negative-stat debuffs from `target` (the Cleanse
    buff). Pass `names` to restrict it to just those; omitted, it clears
    every cleansable status currently on `target` (see CLEANSABLE)."""
    pool = CLEANSABLE if names is None else set(names) & CLEANSABLE
    for name in list(target.statuses.keys()):
        if name in pool:
            del target.statuses[name]


def _clamp_to_bounds(target):
    target.pos.x = max(BOUND_LEFT, min(BOUND_RIGHT, target.pos.x))
    target.pos.y = max(BOUND_TOP, min(BOUND_BOTTOM, target.pos.y))


def apply_knockback(target, source_pos, distance):
    """Instant shove of `target` directly away from `source_pos` by
    `distance` px, clamped to the arena bounds — a one-shot position nudge,
    not a timed status, so any plugin can just call this from its own
    apply_tag_effects."""
    direction = target.pos - source_pos
    if direction.length_squared() == 0:
        direction = pygame.Vector2(1, 0)
    target.pos += direction.normalize() * distance
    _clamp_to_bounds(target)


def apply_pull(target, dest_pos, distance):
    """Instant pull of `target` toward `dest_pos` by up to `distance` px
    (never overshooting past it), clamped to the arena bounds."""
    direction = dest_pos - target.pos
    dist_to_dest = direction.length()
    if dist_to_dest == 0:
        return
    target.pos += direction.normalize() * min(distance, dist_to_dest)
    _clamp_to_bounds(target)


# No apply_stun()/apply_corruption()-style wrappers here on purpose — how
# long a status lasts and how strong it is (ms, pct, dps, ...) is each
# character's own call, decided in that character's own plugin. A plugin
# reaches for entities.set_status(target, "stunned", ms) directly with
# whatever numbers it wants; this module only defines what a status *does*
# once applied (the gating/multiplier/tick behavior below), never what
# duration or magnitude any character should use.


# ---- battle-state mixin --------------------------------------------------

class StatusLibraryMixin:
    # ---- flat immunity/evasion flags (combat_resolution.py) ------------------
    def is_invulnerable(self, f):
        return bool(f.statuses.get("invulnerable"))

    def is_untargetable(self, f):
        return bool(f.statuses.get("untargetable"))

    def taunt_redirect(self, attacker, defender, ability):
        """If `defender` has a decoy actively taunting on their behalf —
        its "taunt" status, see the Clone docstring in entities.py — this
        attack gets forced onto that decoy instead, as long as it would
        actually deal damage (no point luring away a heal/utility skill).
        Returns the decoy, or None. Vampire's Crimson Doppelganger is the
        only source of this right now (see spawn_clone/apply_tag_effects
        in characters/vampire/plugin.py); any future decoy just needs to
        set its own Clone-like object's "taunt" status the same way."""
        clone = self.clone
        if clone is not None and clone.owner is defender and ability.dmg_mult > 0 and "taunt" in clone.statuses:
            return clone
        return None

    def wake_from_sleep(self, target):
        """Sleep breaks the instant its target takes any damage."""
        target.statuses.pop("asleep", None)

    def roll_blind_miss(self, attacker):
        """True if `attacker`'s own Blind status makes this swing whiff —
        the chance is whatever that character's plugin set it to, rolled
        fresh each attack."""
        blind = attacker.statuses.get("blind")
        return bool(blind) and random.random() < blind["chance"]

    # ---- damage-pipeline read-throughs (combat_resolution.py) ---------------
    def armor_break_multiplier(self, target):
        armor_break = target.statuses.get("armor_break")
        return max(0.0, 1 - armor_break["pct"]) if armor_break else 1.0

    def heal_reduction_multiplier(self, target):
        """Healing penalty from `target`'s own Corruption debuff — the one
        generic anti-heal effect (no separate "anti_heal" status anymore;
        every kit that wants to reduce a target's healing reaches for
        Corruption, dps optional, same as Curse's slow)."""
        corruption = target.statuses.get("corruption")
        return 1 - corruption["pct"] if corruption else 1.0

    def lifesteal_pct(self, attacker):
        ls = attacker.statuses.get("lifesteal")
        return ls["pct"] if ls else 0.0

    # ---- action gates (combat_resolution.choose_ability/start_attack,
    # battle_loop.roam_step) -------------------------------------------------
    def can_act(self, f):
        return not (f.statuses.keys() & BLOCKS_ACT)

    def can_move(self, f):
        return not (f.statuses.keys() & BLOCKS_MOVE)

    def can_basic_attack(self, f):
        return not (f.statuses.keys() & BLOCKS_BASIC)

    def can_use_skill(self, f):
        return not (f.statuses.keys() & BLOCKS_SKILL)

    can_use_ultimate = can_use_skill

    def is_stunned(self, f):
        """Stunned is the generic "can't act at all" effect: blocks both
        starting a new attack (combat_resolution.start_attack) and roam
        movement (battle_loop.roam_step) — unlike "rooted", which only
        pins movement and still lets its target fight back."""
        return bool(f.statuses.get("stunned"))

    def forced_flee_step(self, f, dt_ms):
        """Fear's own movement: if `f` is feared, it isn't frozen in place,
        it's forced to keep moving directly away from whoever feared it
        (falls back to its current heading if that source is no longer
        around), instead of battle_loop.roam_step's usual DVD-logo bounce.
        Returns True once it has moved `f` this way, False if `f` isn't
        feared at all (roam_step falls through to its normal movement)."""
        feared = f.statuses.get("feared")
        if not feared:
            return False
        source = feared.get("source")
        direction = (f.pos - source) if source is not None else pygame.Vector2(f.vel)
        if direction.length_squared() == 0:
            direction = pygame.Vector2(1, 0)
        direction = direction.normalize()
        speed = f.vel.length() or 120
        f.pos += direction * speed * (dt_ms / 1000) * f.move_speed_mult
        _clamp_to_bounds(f)
        return True

    # ---- speed / cooldown multipliers (battle_loop.py, combat_resolution.py) ---
    def status_move_speed_multiplier(self, f):
        mult = 1.0
        slow = f.statuses.get("slowed")
        if slow:
            mult *= max(0.0, 1 - slow["pct"])
        curse = f.statuses.get("curse")
        if curse:
            mult *= max(0.0, 1 - curse.get("pct", 0))
        boost = f.statuses.get("move_speed_up")
        if boost:
            mult *= 1 + boost["pct"]
        return mult

    def status_attack_speed_multiplier(self, f):
        mult = 1.0
        down = f.statuses.get("attack_speed_down")
        if down:
            mult *= max(0.0, 1 - down["pct"])
        up = f.statuses.get("attack_speed_up")
        if up:
            mult *= 1 + up["pct"]
        return mult

    def status_cooldown_multiplier(self, f):
        inc = f.statuses.get("cooldown_increase")
        return 1 + inc["pct"] if inc else 1.0

    # ---- damage pipeline (combat_resolution.py) ------------------------------
    def status_outgoing_multiplier(self, attacker):
        """Attacker-side damage-dealt multiplier: Attack Up/Down."""
        mult = 1.0
        up = attacker.statuses.get("attack_up")
        if up:
            mult *= 1 + up["pct"]
        down = attacker.statuses.get("attack_down")
        if down:
            mult *= max(0.0, 1 - down["pct"])
        return mult

    def status_damage_multiplier(self, defender):
        """Defender-side damage-taken multiplier: Vulnerability's increase,
        Damage Reduction's decrease. Armor Break is handled separately in
        apply_damage (it feeds the armor-mitigation formula, not a flat
        multiplier on top of it)."""
        mult = 1.0
        vuln = defender.statuses.get("vulnerability")
        if vuln:
            mult *= 1 + vuln["pct"]
        dr = defender.statuses.get("damage_reduction")
        if dr:
            mult *= max(0.0, 1 - dr["pct"])
        return mult

    def apply_shield_absorb(self, defender, dmg):
        """Generic Shield: a flat barrier ("absorb") that eats whatever
        damage lands on `defender` before hp does — the same math Paladin's
        Divine Shield used to hand-roll for itself alone (see
        characters/paladin/plugin.py's on_shield_broken for the retaliation
        it now layers on top via the generic break notification below).
        Shield is barrier-only by design; a kit that also wants a flat %
        mitigation pairs it with the separate "damage_reduction" status
        instead of this status growing its own reduction field again."""
        sh = defender.statuses.get("shield")
        if not sh:
            return dmg
        absorb = sh.get("absorb", 0)
        if absorb > 0:
            absorbed = min(absorb, dmg)
            sh["absorb"] = absorb - absorbed
            dmg -= absorbed
            if absorbed > 0:
                self.floaters.append(
                    [defender.pos.x, defender.pos.y - 68, -0.5, 255, "Absorbed", RING_COLOR.get("shield", GRAY)]
                )
            if sh["absorb"] <= 0:
                data = defender.statuses.pop("shield")
                for plugin in self.plugins:
                    plugin.on_shield_broken(defender, self.attacker, data)
        return dmg

    def apply_status_reflect(self, attacker, defender, actual):
        reflect = defender.statuses.get("reflect")
        if reflect and actual > 0 and attacker.is_alive():
            amt = round(actual * reflect["pct"])
            if amt > 0:
                reflected = self.apply_damage(attacker, amt)
                self.floaters.append(
                    [attacker.pos.x, attacker.pos.y - 55, -0.5, 255, f"-{reflected} Reflect", WHITE]
                )

    # ---- per-frame tick (battle_loop.py) -------------------------------------
    def tick_library_effects(self, f, dt_ms):
        if self.is_invulnerable(f):
            return
        for name in _DOT_NAMES:
            dot = f.statuses.get(name)
            # "curse" doubles as a pure-CC status (disarm+silence+slow, no
            # dps) and "corruption" doubles as the generic heal-reduction
            # debuff (see heal_reduction_multiplier/heal) — unlike every
            # other name here, their dps is optional.
            if dot and dot.get("dps", 0):
                self.apply_damage(f, dot["dps"] * dt_ms / 1000)
        bleed = f.statuses.get("bleed")
        if bleed and bleed.get("move_bonus_dps") and self.mode == "roam" and f.vel.length_squared() > 0:
            self.apply_damage(f, bleed["move_bonus_dps"] * dt_ms / 1000)
        for name in _HOT_NAMES:
            hot = f.statuses.get(name)
            if hot:
                heal(f, hot["hps"] * dt_ms / 1000)
