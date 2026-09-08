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
`set_status(defender, "stunned", 1.5)` or `set_status(defender,
"vulnerability", 3, pct=0.3)` and gets correct, consistent behavior with
zero new plumbing — the duration and every kwarg (pct/dps/bonus/...) stays
that character's own call to override. A handful of effects (bleed, poison,
burn, frozen, asleep — see BASE_* constants below) do fall back to one
canonical base magnitude, expressed relative to the target's own max stat,
whenever a character omits the kwarg instead of computing its own; every
other status still has zero default and is purely whatever the caller
passes.

Every status this module gives shared meaning to (a character reaches for
`set_status(fighter, name, seconds, **kwargs)` with any name below and gets
correct, consistent behavior — the kwargs each name reads are noted inline;
`seconds`/duration is never one of them, that's plumbed generically by
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
                any damage, which also detonates a wake-up burst worth
                ASLEEP_WAKE_DAMAGE_PCT_MAX_HP of the target's max hp
                (see wake_from_sleep).
    curse     - disarmed + silenced + slowed bundled into one status
                ("pct" is the slow half); optional "dps" on top (Vampire's
                Blood Hex is the only source right now).

  DoT ("dps" tick, applied every frame by tick_library_effects; the ones
  marked optional can be applied purely for a debuff they carry with no
  actual damage tick):
    bleed       - "dps", flat, ignores armor entirely; defaults to
                  BLEED_BASE_DPS when omitted. Optional "move_bonus_dps"
                  (flat, also armor-ignoring) adds extra damage while the
                  target is moving during roam, defaulting to
                  BLEED_MOVE_BASE_PCT_MAX_HP of the target's max hp/sec.
    poison      - "dps", flat, ignores armor; defaults to POISON_BASE_DPS.
    burn        - "dps", flat, ignores armor; defaults to BURN_BASE_DPS.
    corruption  - "dps" optional, through armor normally. Also the generic
                  heal-reduction effect (see Debuffs below) — a character
                  can apply it purely for that "pct" and skip "dps"
                  entirely, same as curse's slow.
    frozen      - "dps" optional, through armor normally, layered on top of
                  its own Hard CC lock; defaults to FROZEN_BASE_PCT_MAX_HP
                  of the target's max hp/sec when omitted.

  Debuffs:
    armor_break  - "amount" flat armor points subtracted straight off the
                   target's armor stat (see effective_armor; folded into
                   the armor formula in apply_damage, not a multiplier).
    vulnerability      - "pct" of the target's own armor stat subtracted
                         off on top of armor_break (see effective_armor) —
                         no longer a direct damage-taken multiplier.
    attack_down        - "pct" less damage dealt (status_outgoing_multiplier).
    attack_speed_down  - "pct" slower attacks (status_attack_speed_multiplier).
    blind              - "chance" the holder's own swing just whiffs
                         (roll_blind_miss).
    cooldown_increase  - "pct" slower ability cooldowns
                         (status_cooldown_multiplier).
    corruption         - "pct" less healing received (heal_reduction_
                         multiplier/heal) — see DoT above for its other half.

  Buffs:
    regen             - "pct" of the target's max hp healed per second,
                        recomputed live off current max hp every tick
                        (tick_library_effects) — not a flat "hps".
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
             deliberately absent from CLEANSABLE. Guarantees an eligible
             attack aimed at its owner lands on the decoy instead (see
             taunt_redirect for exactly which attacks are eligible — gated
             by targeting type, not by ability.kind — AoE/homing-bolt/
             resolve_special-only attacks always land on the real target
             regardless). Vampire's Crimson Doppelganger is the only source
             right now; Phantom Lancer's illusion clones (see
             CharacterPlugin.basic_attack_decoys) get the same redirect, just
             as a weighted pool (see decoy_redirect_weight) alongside the
             real fighter rather than taunt's guaranteed 100%.
    vanished  - both-direction damage immunity while it lasts (is_vanished —
                checked in combat_resolution.do_damage/apply_damage): its
                holder can neither deal nor take damage, unlike invulnerable
                (incoming-only). Deliberately absent from every BLOCKS_*
                set — movement (and, unlike taunt, acting) isn't blocked at
                all, only damage. Also absent from CLEANSABLE, same
                reasoning as taunt: it's a brief self-only defensive window,
                not a debuff anyone would want stripped off a target.
                Phantom Lancer's Doppelganger is the only source right now.

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
_HOT_NAMES = ("regen",)
# "curse"/"corruption" tick through armor normally, same as any other hit,
# and carry no library default — their "dps" stays purely caller-supplied,
# see the class docstring above.
_ARMOR_GATED_DOT_NAMES = ("curse", "corruption")

# Canonical base magnitudes a character can skip computing itself by just
# omitting the kwarg (see the module docstring above) — never used when the
# caller passes its own dps/pct, so a kit like Sukuna/Johnny that wants
# bleed scaled off its own atk keeps doing exactly that. bleed/poison/burn
# are flat dps and (per this game's damage-type rules) always ignore armor;
# frozen instead scales with the target's own max hp, applied through armor
# like a normal hit since it's a Hard CC, not a pure damage-type DoT.
# Cut by another 25% (same pass as CHARACTERS' base ATK in core/assets.py)
# to slow matches down further.
BLEED_BASE_DPS = 0.375
BLEED_MOVE_BASE_PCT_MAX_HP = 0.0075
POISON_BASE_DPS = 0.75
BURN_BASE_DPS = 1.125
FROZEN_BASE_PCT_MAX_HP = 0.0075
_ARMOR_IGNORING_DOT_BASE_DPS = {"bleed": BLEED_BASE_DPS, "poison": POISON_BASE_DPS, "burn": BURN_BASE_DPS}

# Wake-up burst dealt by wake_from_sleep the instant an "asleep" target
# takes any damage, sized off its own max hp — through armor like a normal
# hit, unlike bleed/poison/burn above.
ASLEEP_WAKE_DAMAGE_PCT_MAX_HP = 0.075

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
    "vanished": (190, 215, 225),
}


# ---- one-shot / stateless helpers (no battle instance needed) ----------

def heal(target, pct, dt=1.0):
    """The generic external-heal funnel (regen ticks, zone heals, a future
    plain Heal skill) — respects the target's own Corruption debuff the
    same way outgoing lifesteal/heal_ratio already does in
    combat_resolution.py. Returns the actual amount restored.

    `pct` is always a fraction of the target's own max hp, recomputed live
    off current max hp rather than a flat number — every heal in this game
    is defined relative to max hp, same as regen/lifesteal elsewhere in
    this module. `dt` (seconds) scales it down to a per-tick slice for a
    heal-over-time caller; leave it at the default 1.0 for an instant heal
    worth the full `pct` of max hp.

    Deliberately doesn't round the resulting amount before applying it:
    callers ticking a small per-frame slice (pct * dt) end up with a
    fraction well under 1 — rounding that away every frame would silently
    heal nothing at all no matter how many frames it ran for, since hp is
    tracked as a float and accumulates the same way DoT ticks do below."""
    if pct <= 0:
        return 0
    amount = pct * target.max_hp * dt
    corruption = target.statuses.get("corruption")
    mult = max(0.0, 1 - corruption["pct"]) if corruption else 1.0
    amount *= mult
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
# reaches for entities.set_status(target, "stunned", seconds) directly with
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

    def is_vanished(self, f):
        """Phantom Lancer's Doppelganger: both-direction damage immunity —
        see the "vanished" entry in the module docstring above."""
        return bool(f.statuses.get("vanished"))

    def taunt_redirect(self, attacker, defender, ability):
        """Whether this attack actually lands on `defender` itself or gets
        forced onto a decoy standing in for them instead. Gated purely by
        each ability's own explicit `ignore_clone` flag (see abilities.py) —
        basic/skill/ultimate (`ability.kind`) and motion both play no part
        in this anymore, so a bolt/ricochet *skill* (Judgment Mark, Tusk Act
        3) is just as eligible as a basic attack of the same kind, and a
        homing/AoE ability is excluded only because that specific ability's
        own moves.py sets ignore_clone=True, not from an engine-wide rule
        keyed off its motion.

        Excluded entirely (always lands on the real `defender`, decoys
        ignored) when `ability.ignore_clone` is set — see each character's
        own moves.py for which and why (a genuine homing shot that can't be
        fooled by a decoy, a blast that already reaches clones through the
        separate splash_aoe_to_clones path, an ability resolved outside the
        normal do_damage() pipeline via resolve_special() that would
        desync the visual strike position from where the damage actually
        lands, ...) — or when there's no damage at all (dmg_mult <= 0, no
        point luring a decoy away from a heal/utility move).

        Everything else is eligible, from two independent sources checked
        in order:
          1. A decoy actively taunting on `defender`'s behalf — its "taunt"
             status, see the Clone docstring in entities.py — is a
             guaranteed 100% redirect while it's up. Vampire's Crimson
             Doppelganger is the only source right now (see spawn_clone/
             apply_tag_effects in characters/vampire/plugin.py).
          2. `defender`'s own plugin offering up a pool of decoys via
             basic_attack_decoys() (Phantom Lancer's illusion clones) —
             unlike a taunting decoy, these are only an alternative
             alongside the real `defender` itself, weighted by that
             plugin's own decoy_redirect_weight() (1 = plain equal-odds), so
             having clones out doesn't guarantee any single attack actually
             lands on one.

        Returns the decoy actually chosen, or None (attack lands on
        `defender` normally)."""
        if ability.dmg_mult <= 0 or ability.ignore_clone:
            return None
        clone = self.clone
        if clone is not None and clone.owner is defender and "taunt" in clone.statuses:
            return clone
        defender_plugin = self.plugin_for(defender)
        decoys = defender_plugin.basic_attack_decoys() if defender_plugin is not None else []
        if decoys:
            weight = max(1, defender_plugin.decoy_redirect_weight())
            pick = random.choice([None, *(decoys * weight)])
            if pick is not None:
                return pick
        return None

    def wake_from_sleep(self, target):
        """Sleep breaks the instant its target takes any damage, and that
        break itself detonates a wake-up burst worth
        ASLEEP_WAKE_DAMAGE_PCT_MAX_HP of the target's max hp (through armor
        like a normal hit) — popping the status first so this burst's own
        call into apply_damage can't recurse back into here."""
        if target.statuses.pop("asleep", None) is None:
            return
        bonus = round(ASLEEP_WAKE_DAMAGE_PCT_MAX_HP * target.max_hp)
        if bonus <= 0:
            return
        actual = self.apply_damage(target, bonus)
        if actual > 0:
            self.floaters.append(
                [target.pos.x, target.pos.y - 60, -0.5, 255, f"-{actual} Wake", RING_COLOR.get("asleep", GRAY)]
            )

    def roll_blind_miss(self, attacker):
        """True if `attacker`'s own Blind status makes this swing whiff —
        the chance is whatever that character's plugin set it to, rolled
        fresh each attack."""
        blind = attacker.statuses.get("blind")
        return bool(blind) and random.random() < blind["chance"]

    # ---- damage-pipeline read-throughs (combat_resolution.py) ---------------
    def effective_armor(self, target):
        """`target`'s armor stat after Armor Break's flat "amount" and
        Vulnerability's "pct" of that same base armor stat are both
        subtracted off it (never below 0) — the single read-through
        apply_damage's armor-mitigation formula uses, so a target can be
        worn down by either or both debuffs at once."""
        armor = target.armor
        armor_break = target.statuses.get("armor_break")
        if armor_break:
            armor -= armor_break["amount"]
        vuln = target.statuses.get("vulnerability")
        if vuln:
            armor -= target.armor * vuln["pct"]
        return max(0.0, armor)

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

    def forced_flee_step(self, f, dt):
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
        f.pos += direction * speed * dt * f.move_speed_mult
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
        """Defender-side damage-taken multiplier: Damage Reduction's
        decrease. Vulnerability and Armor Break are both handled separately
        in apply_damage (see effective_armor) — they feed the
        armor-mitigation formula, not a flat multiplier on top of it."""
        mult = 1.0
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
    def tick_library_effects(self, f, dt):
        if self.is_invulnerable(f) or self.is_vanished(f):
            return
        # bleed/poison/burn: flat dps, always ignoring armor — the caller's
        # own "dps" wins when given (Sukuna/Johnny scale bleed off their own
        # atk this way), otherwise falls back to the canonical base rate.
        for name, base_dps in _ARMOR_IGNORING_DOT_BASE_DPS.items():
            dot = f.statuses.get(name)
            if dot:
                dps = dot.get("dps", base_dps)
                if dps:
                    self.apply_damage(f, dps * dt, ignore_armor=True)
        bleed = f.statuses.get("bleed")
        if bleed and self.mode == "roam" and f.vel.length_squared() > 0:
            move_bonus = bleed.get("move_bonus_dps")
            if move_bonus is None:
                move_bonus = BLEED_MOVE_BASE_PCT_MAX_HP * f.max_hp
            if move_bonus:
                self.apply_damage(f, move_bonus * dt, ignore_armor=True)
        # frozen: through armor like a normal hit, "dps" optional, falling
        # back to a base rate off the target's own max hp when omitted.
        frozen = f.statuses.get("frozen")
        if frozen:
            dps = frozen.get("dps")
            if dps is None:
                dps = FROZEN_BASE_PCT_MAX_HP * f.max_hp
            if dps:
                self.apply_damage(f, dps * dt)
        # curse/corruption: through armor, "dps" optional, no library
        # default — see the class docstring above.
        for name in _ARMOR_GATED_DOT_NAMES:
            dot = f.statuses.get(name)
            if dot and dot.get("dps", 0):
                self.apply_damage(f, dot["dps"] * dt)
        for name in _HOT_NAMES:
            hot = f.statuses.get(name)
            if hot:
                heal(f, hot["pct"], dt)
