"""Sukuna plugin: the Slaughter passive (stacking Attack Up off landed
hits — see the constants block below), Hachi's bleed application, Kai's
multi-hit flurry resolve (it doesn't deal its own damage — it procs Hachi's
basic-attack formula 3-5 times at once), Ten Shadows' random shadow summon,
Kamino's cursed detonation, and the bare-handed curse-slash animation for
the three melee techniques.

Ten Shadows (see SHADOWS below) is a fan-original move, not a literal port of
Megumi Fushiguro's own canon Ten Shadows Technique — Sukuna summons one of
ten shadows at random each cast, each with its own power, its own
on-hit effect, and (see the _move_* methods / CharacterPlugin.
clone_move_step) its own movement pattern, resolved through a single
CloneArmy (shadow_army, cap=TEN_SHADOWS_CAP — casting again while under cap
adds a second/third shadow instead of only ever replacing the last one; see
that constant's own comment) instead of Phantom Lancer's uniform
illusion-army model. Tiger Funeral is the one shadow that carries the
generic "taunt" status (see status_library.taunt_redirect, generalized to
also scan a defender's own clone_army() for it, not just Vampire's
singleton self.clone) — every other shadow is a plain, non-taunting
auto-attacker."""

import math
import random

import pygame

from ...core.clone_army import CloneArmy
from ...core.constants import (
    AVATAR_R, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GREEN, RED, SUKUNA_PINK, WHITE,
)
from ...core.effects import (
    draw_expanding_ring,
    draw_fire_arrow,
    draw_slash,
    draw_slash_arc,
    draw_slash_fx,
    draw_starburst,
)
from ...core.entities import bounce_move, set_status, squash
from ...core.particles import emit_dark, emit_explosion, emit_spark_burst
from ...core.plugin import CharacterPlugin
from ...core.status_library import apply_knockback, cleanse, heal
from .shadows_sprite import shadow_sprite

# Slaughter (passive): every landed hit from Sukuna's own basic/Kai/Kamino
# stacks a refreshing Attack Up on himself — the same "reward sustained
# pressure" shape Berserker's Fury, Raiju's Overcharge, and Johnny's Spin
# Charge already have (see their own plugins), which Sukuna previously
# lacked entirely: his damage used to be flat for the whole match while
# every one of those three snowballs. Refreshed (not permanent, unlike
# Fury) so it lapses on its own the moment he stops actually landing
# hits — same "use it or lose it" shape as Overcharge/Spin Charge. Doesn't
# apply to Kai's own per-proc damage (resolve_special deliberately skips
# status_outgoing_multiplier for its multi-hit flurry, same simplification
# Volt Fang/Bat Swarm accept), only to what lands after — Hachi and Kamino.
SLAUGHTER_MAX_STACKS = 10
SLAUGHTER_ATK_PCT_PER_STACK = 0.02
SLAUGHTER_DURATION_S = 3

# Kai: guaranteed 3 procs of the basic attack, then each hit past that
# (up to 5 total) independently rolls to proc as well.
KAI_BASE_HITS = 3
KAI_MAX_HITS = 5
KAI_EXTRA_HIT_CHANCE = 0.6

# Kai: bleed (DoT) + corruption (heal reduction) applied once the flurry lands
KAI_BLEED_DURATION_S = 5
KAI_CORRUPTION_DURATION_S = 5
KAI_CORRUPTION_PCT = 0.5

# Hachi (basic, tag "dismantle"): bleed (DoT) left by every basic hit
HACHI_BLEED_DURATION_S = 6

# Kamino (ultimate): bleed (DoT) + corruption (heal reduction) + burn (DoT)
KAMINO_BLEED_DURATION_S = 8
KAMINO_CORRUPTION_DURATION_S = 8
KAMINO_CORRUPTION_PCT = 0.7
KAMINO_BURN_DURATION_S = 8

# ---- Ten Shadows ------------------------------------------------------
# How long a summoned shadow sticks around before it despawns on its own
# (independent of it dying early to damage) — same duration Tiger Funeral's
# own "taunt" status is set for, so taunt never outlives the decoy carrying
# it.
TEN_SHADOWS_DURATION_S = 20

# How many shadows can be out at once — part of the buff pass alongside the
# ability's own shorter cooldown (see moves.py): Sukuna's kit was falling
# behind on raw stats, so instead of just inflating one number, Ten Shadows
# now builds toward an actual pack (recast while under cap adds another
# shadow instead of only ever replacing the last one; casting again once at
# cap still evicts the oldest, same as before this was raised off 1).
TEN_SHADOWS_CAP = 5

# SHADOWS: one entry rolled at random (weighted) each cast — stat_pct/hp_pct
# feed CloneArmy.spawn() same as Phantom Lancer's own army. attack_cooldown/
# attack_range are pinned onto each spawned clone individually (see
# CloneArmy.spawn's own attack_cooldown/attack_range kwargs) rather than
# shared on the army itself — necessary now that TEN_SHADOWS_CAP > 1 means a
# Toad and a Divine Dog can be out at the same time, each needing to keep
# its own attack pace instead of both reading one shared value. "move"
# picks this shadow's own entry in SukunaPlugin._move_fns (see
# clone_move_step) instead of the default DVD-bounce every other CloneArmy
# clone in this game still uses. attack_cooldown=None (Round Deer only)
# means it never attacks at all — see _summon_shadow, which pins its
# attack_cd at infinity instead of asking CloneArmy to treat "no cooldown"
# as "attacks every frame".
SHADOWS = [
    dict(key="divine_dog", label="Divine Dog", weight=14, stat_pct=0.35, hp_pct=0.12,
         attack_cooldown=0.6, attack_range=90, move="chase"),
    dict(key="nue", label="Nue", weight=14, stat_pct=0.45, hp_pct=0.12,
         attack_cooldown=0.8, attack_range=110, move="erratic"),
    dict(key="great_serpent", label="Great Serpent", weight=14, stat_pct=0.45, hp_pct=0.14,
         attack_cooldown=0.9, attack_range=100, move="slither"),
    dict(key="toad", label="Toad", weight=12, stat_pct=0.25, hp_pct=0.14,
         attack_cooldown=1.0, attack_range=130, move="hop"),
    # move="bounce_split": plain DVD-logo bounce, not orbit (see
    # _move_bounce_split) — every wall bounce multiplies it (RABBIT_SPLIT_
    # COOLDOWN_S/_split_rabbit) instead of buffing Sukuna, so it snowballs
    # into a pack given room under TEN_SHADOWS_CAP rather than sitting there
    # as one easily-ignored escort.
    dict(key="rabbit", label="Rabbit Escape", weight=12, stat_pct=0.4, hp_pct=0.14,
         attack_cooldown=1.1, attack_range=90, move="bounce_split"),
    # attack_range far beyond every other shadow's own melee-ish reach (was
    # 120) — its basic attack is now a water wave (see MAX_ELEPHANT_*/
    # clone_basic_attack_landed) that knocks the target back rather than a
    # bite/gore that needs to actually close distance, so its own slow
    # "trudge" movement (see _move_trudge) is no longer a liability.
    dict(key="max_elephant", label="Max Elephant", weight=10, stat_pct=0.75, hp_pct=0.22,
         attack_cooldown=1, attack_range=400, move="trudge"),
    dict(key="piercing_ox", label="Piercing Ox", weight=12, stat_pct=0.6, hp_pct=0.16,
         attack_cooldown=0.85, attack_range=110, move="pierce"),
    dict(key="round_deer", label="Round Deer", weight=8, stat_pct=0.0, hp_pct=0.16,
         attack_cooldown=None, attack_range=0, move="stationary"),
    dict(key="tiger_funeral", label="Tiger Funeral", weight=9, stat_pct=0.5, hp_pct=0.16,
         attack_cooldown=0.9, attack_range=100, move="guard"),
    # The rare "jackpot" pull (5/120 ≈ 4%) — biggest stats of the ten, and
    # the only one that also buffs Sukuna himself on summon (see
    # _summon_shadow: cleanse + a damage_reduction window), echoing
    # Mahoraga's own "adapts to anything" reputation. Its movement (see
    # _move_adaptive) literally cycles through several of the other
    # shadows' own movement patterns instead of having just one.
    # attack_cooldown brought back down to Divine Dog's own pace (was 1.7 —
    # at that pace Mahoraga's basic-attack-hits-per-second was only mid-pack
    # despite having the roster's biggest stat_pct/hp_pct, undercutting the
    # whole point of it being the rare pull).
    dict(key="mahoraga", label="Mahoraga", weight=5, stat_pct=1.5, hp_pct=0.6,
         attack_cooldown=0.3, attack_range=140, move="adaptive"),
]

# On-hit effects (see clone_basic_attack_landed) — each shadow's own flavor,
# deliberately not reusing bleed/corruption (Hachi/Kai/Kamino already own
# those) so Ten Shadows reads as its own thing rather than a fourth source
# of the same two statuses.
DIVINE_DOG_ARMOR_BREAK_S = 5
DIVINE_DOG_ARMOR_BREAK_AMOUNT = 3

NUE_SLOW_S = 5
NUE_SLOW_PCT = 0.35

SERPENT_POISON_S = 10  # dps kwarg omitted -> canonical POISON_BASE_DPS

TOAD_ROOT_S = 1.1
# Max Elephant's basic attack: a water wave (matches the flooded, aquatic
# art in assets/sukuna/max-elephant.png) that expands outward from the elephant's
# own position over MAX_ELEPHANT_PULSE_DURATION_S (see _tick_elephant_pulses/
# draw_fx) instead of an instant flat shove on landing — a slow-growing
# circular pulse that knocks back whatever its edge reaches (the real
# opponent, or one of their own decoys), each only once per pulse (see the
# "hit" set in _tick_elephant_pulses), rather than the armor_break every
# other heavy-hitter here already covers (Divine Dog, and Piercing Ox's own
# vulnerability is armor-adjacent too) — the one shadow in the whole kit
# with actual knockback, which is what makes it worth summoning over a
# second copy of something else now.
MAX_ELEPHANT_KNOCKBACK_DIST = 90
MAX_ELEPHANT_PULSE_DURATION_S = 1
MAX_ELEPHANT_PULSE_MAX_RADIUS = 340
MAX_ELEPHANT_WAVE_COLOR = (80, 170, 220)

OX_VULN_S = 3.0
OX_VULN_PCT = 0.25
# Mahoraga: unlike every other attacking shadow, it had no on-hit flavor of
# its own at all (its only payoff fired once, on summon) — "attack_down"
# instead of reusing Ox's own armor-shred vulnerability, so the rare pull
# actually cripples the opponent's own offense while it's out, not just a
# bigger basic-attack number.
MAHORAGA_ATK_DOWN_S = 3.0
MAHORAGA_ATK_DOWN_PCT = 0.2

# Round Deer never attacks (see _summon_shadow) — instead it passively heals
# Sukuna every frame it's alive (see _tick_round_deer_aura), banked and
# flushed as one floater every ROUND_DEER_FLOATER_INTERVAL seconds, same
# batching trick status_library._accrue_dot_floater uses for DoT ticks.
ROUND_DEER_HEAL_PCT_PER_S = 0.05
ROUND_DEER_FLOATER_INTERVAL = 0.5

# Rabbit Escape's real gimmick: no more move/attack-speed aura on Sukuna at
# all — instead every time it physically bounces off the arena wall (see
# _move_bounce_split/_split_rabbit) it multiplies, spawning a fresh rabbit
# right where it bounced. Gated by its own RABBIT_CAP (see
# _flush_rabbit_splits/_evict_oldest_rabbit) rather than the shared
# TEN_SHADOWS_CAP — a bounce past cap evicts only the oldest rabbit, never a
# Divine Dog or any other non-rabbit shadow sharing the same shadow_army, so
# the pack can genuinely fill up to RABBIT_CAP rabbits on top of whatever
# else is already out. Also gated by RABBIT_SPLIT_COOLDOWN_S per individual
# rabbit so one clone bouncing in a corner can't spawn a dozen copies in the
# same second. Rendered much smaller than every other shadow (see
# RABBIT_SPRITE_SCALE/_shadow_sprite) — a small, fast, multiplying nuisance
# rather than a single support unit.
RABBIT_SPLIT_COOLDOWN_S = 1.0
# Its own cap, separate from TEN_SHADOWS_CAP (see the comment above) — kept
# equal to it so a fully-grown rabbit pack tops out at the same size any
# other single-shadow-type stampede would, just without displacing the rest
# of the roster to get there.
RABBIT_CAP = 20
RABBIT_SPRITE_SCALE = 0.25
# Applied on top of RABBIT_SPRITE_SCALE, width only — a lean, narrow body
# instead of a small square blob (see _shadow_sprite).
RABBIT_WIDTH_SCALE = 0.25
# The ring CloneArmy.draw paints around every clone is a flat AVATAR_R + 6
# regardless of sprite size, so at RABBIT_SPRITE_SCALE's tiny body it read as
# an oversized hoop around a speck (see _ring_radius). Shrinks just that
# drawn ring for rabbits — cosmetic only, collision still uses the flat
# AVATAR_R every clone uses, untouched by this.
RABBIT_RING_SCALE = 0.25

# Mahoraga's own summon-payoff (on top of its bigger stats above): cleanses
# Sukuna and grants a flat damage_reduction window, echoing "adapts to
# anything" as a buff on the summoner rather than on the shadow itself.
MAHORAGA_SELF_BUFF_S = 6
MAHORAGA_DR_PCT = 0.5

# ---- movement tuning (see the _move_* methods / clone_move_step) --------
SHADOW_CHASE_SPEED = 130
SHADOW_ERRATIC_SPEED = (160, 240)
SHADOW_ERRATIC_INTERVAL = (0.35, 0.7)
SHADOW_SLITHER_AMPLITUDE = 40
SHADOW_SLITHER_FREQ = 3.2
SHADOW_HOP_REST_S = (0.5, 1.1)
SHADOW_HOP_TRAVEL_S = 0.22
SHADOW_HOP_DIST = 90
SHADOW_ORBIT_RADIUS = 70
SHADOW_ORBIT_SPEED = 2.2  # rad/s
SHADOW_TRUDGE_SPEED_MULT = 0.3
SHADOW_GUARD_OFFSET = 55
SHADOW_GUARD_SPEED = 160
# Piercing Ox: a heavy, dead-straight bull charge — by far the fastest
# speed any shadow moves at (every other SHADOW_*_SPEED above tops out around
# 240), so it actually reads as "hits like a freight train" rather than
# just roaming in a straight line. It charges until it slams into the
# arena edge, stops dead (no bounce, no wrap-through — see _move_pierce)
# for SHADOW_OX_PAUSE_S like a bull that overran its target, then picks a
# fresh direction and launches into another charge.
SHADOW_OX_CHARGE_SPEED = 1420
SHADOW_OX_PAUSE_S = 0.45
# How often Mahoraga's own movement "adapts" into the next pattern in
# ADAPT_ROTATION — deliberately excludes stationary/hop/pierce/guard so its
# own movement always reads as active and aggressive.
ADAPT_CYCLE_S = 3.0
ADAPT_ROTATION = ("chase", "orbit", "trudge", "erratic")

# How fast a wandering shadow's heading drifts toward the opponent (rad/s),
# layered on top of its own flavor pattern (erratic/slither/trudge/
# bounce_split) — without this, only Divine Dog (chase) and Piercing Ox
# (pierce, re-aimed each charge) ever reliably closed distance, so most of
# the pack just bounced/wiggled around the arena and rarely actually landed
# a hit. Kept low enough that the wiggle/erratic-jink flavor is still
# visible, not overridden into a straight chase.
SHADOW_HOMING_TURN_RATE = 2.0
# Toad's hop target is picked within this many radians of straight-at-the-
# opponent instead of a full 0-tau random spread, for the same reason.
SHADOW_HOP_AIM_SPREAD = math.radians(75)


class SukunaPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.kai_hits = KAI_BASE_HITS  # updated each time Kai resolves; read by draw_fx
        # Ten Shadows: cap=TEN_SHADOWS_CAP shadows can be out at once, each
        # spawned with its own attack_cooldown/attack_range (see
        # _summon_shadow/CloneArmy.spawn) — the attack_cooldown/attack_range
        # given here are just the fallback CloneArmy itself would use for a
        # clone spawned without either kwarg, never actually hit in practice
        # since every SHADOWS entry supplies both.
        self.shadow_army = CloneArmy(
            self, cap=TEN_SHADOWS_CAP, stat_pct=0.5, duration=TEN_SHADOWS_DURATION_S,
            can_attack=True, has_statuses=True,
            attack_cooldown=0.9, attack_range=110, attack_anim=0.22,
            clone_hp_pct=0.15,
        )
        # Dispatch table read by clone_move_step — one entry per SHADOWS
        # "move" key (see the _move_* methods below).
        self._move_fns = {
            "chase": self._move_chase,
            "erratic": self._move_erratic,
            "slither": self._move_slither,
            "hop": self._move_hop,
            "orbit": self._move_orbit,
            "trudge": self._move_trudge,
            "pierce": self._move_pierce,
            "stationary": self._move_stationary,
            "guard": self._move_guard,
            "adaptive": self._move_adaptive,
            "bounce_split": self._move_bounce_split,
        }
        self._deer_heal_accum = 0.0
        self._deer_floater_cd = ROUND_DEER_FLOATER_INTERVAL
        # Max Elephant's water-wave pulses currently expanding outward —
        # each a dict(pos, t, hit) ticked by _tick_elephant_pulses and drawn
        # by draw_fx; see clone_basic_attack_landed for where one gets
        # queued.
        self._elephant_pulses = []
        # Positions queued by _move_bounce_split for a fresh rabbit each —
        # flushed right after shadow_army.tick() finishes each frame (see
        # ambient_tick/_flush_rabbit_splits), never spawned from inside
        # clone_move_step itself: that runs from within CloneArmy.tick()'s
        # own `for clone in self.clones` loop, and spawn()'s eviction
        # (self.clones.pop(0)) mutating that same list mid-iteration would
        # silently skip or double-process clones for the rest of that pass.
        self._pending_rabbit_splits = []
        # Whichever shadow the last _roll_shadow() actually picked — excluded
        # from the very next roll (see _roll_shadow) so casting Ten Shadows
        # twice in a row can never summon the same shadow back-to-back. None
        # at the start of a match, when there's nothing yet to exclude.
        self._last_shadow_key = None

    def clone_army(self):
        """Read generically by combat_resolution.splash_aoe_to_clones (an
        enemy AoE landing on Sukuna also chips his own active shadow) and by
        status_library.taunt_redirect (Tiger Funeral's own "taunt" status
        — see the module docstring)."""
        return self.shadow_army

    def basic_attack_decoys(self):
        """Every living Ten Shadows shadow is now a candidate stand-in for a
        plain eligible attack aimed at Sukuna, not just Tiger Funeral's own
        guaranteed "taunt" redirect (checked first, still absolute — see
        status_library.taunt_redirect) — this is the same reach-gated pool
        Phantom Lancer's illusions already sit in (only whichever shadow is
        actually standing within decoy_redirect_reach() of Sukuna when the
        attack lands is eligible, per CloneArmy's own default
        dot_mirror_radius), so an opponent's basic attack or skill can land
        on one of these instead of Sukuna himself, and on_attack_redirected
        below already resolves that generically against whichever shadow
        actually got picked."""
        return self.shadow_army.redirect_pool()

    def extra_colliders(self):
        return self.shadow_army.extra_colliders()

    def _shadow_sprite(self, clone):
        """Passed to CloneArmy.draw as sprite_for — one of ten distinct
        procedural shadow sprites (see shadows_sprite.py) keyed off
        clone.shadow_key, instead of the default "faded copy of the owner's
        own sprite" every other CloneArmy in this game still uses. Sized to
        match Sukuna's own image so a shadow fills the same footprint any
        other clone/fighter does — except Rabbit, rendered at
        RABBIT_SPRITE_SCALE (and narrower still, RABBIT_WIDTH_SCALE, width
        only) instead: a small, lean, easy-to-miss nuisance rather than a
        full-size body, matching its "multiplies into a pack" identity (see
        _move_bounce_split). This only shrinks the drawn sprite — its
        hitbox/collision radius stays the same flat AVATAR_R every clone
        uses, same as any other shadow."""
        key = getattr(clone, "shadow_key", None)
        size = self.fighter.image.get_width()
        width = size
        if key == "rabbit":
            size = max(8, round(size * RABBIT_SPRITE_SCALE))
            width = max(6, round(size * RABBIT_WIDTH_SCALE))
        return shadow_sprite(key, size, width=width)

    def _ring_radius(self, clone):
        """Passed to CloneArmy.draw as ring_radius_for — shrinks just
        Rabbit's drawn ring (see RABBIT_RING_SCALE) to match its own tiny
        sprite instead of every other shadow's flat AVATAR_R + 6; purely
        cosmetic, same as _shadow_sprite's own shrink."""
        if getattr(clone, "shadow_key", None) == "rabbit":
            return max(6, round((AVATAR_R + 6) * RABBIT_RING_SCALE))
        return AVATAR_R + 6

    def resolve_special(self):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "kai_flurry"):
            return False
        attacker, defender, ability = battle.attacker, battle.defender, battle.ability
        hits = KAI_BASE_HITS
        while hits < KAI_MAX_HITS and random.random() < KAI_EXTRA_HIT_CHANCE:
            hits += 1
        self.kai_hits = hits

        total = 0
        for _ in range(hits):
            dmg = round(attacker.atk * ability.dmg_mult)
            actual = battle.deal_damage(attacker, defender, dmg)
            total += actual
            if actual > 0:
                self._stack_slaughter()
        battle.damage_applied = True

        # Status: bleed (DoT) + corruption (heal reduction) — dps kwarg
        # omitted so it falls back to the canonical BLEED_BASE_DPS flat rate
        # in status_library.py, same as every other bleed source now.
        set_status(defender, "bleed", KAI_BLEED_DURATION_S)
        set_status(defender, "corruption", KAI_CORRUPTION_DURATION_S, pct=KAI_CORRUPTION_PCT)
        defender.shake = 20
        battle.apply_impact(defender, ability)
        battle.floaters.append(
            [defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{total} x{hits}", SUKUNA_PINK]
        )
        battle.log = f"{attacker.name}'s Kai lands {hits} simultaneous cuts on {defender.name} for {total}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def on_damage_dealt(self, attacker, defender, actual):
        """Slaughter passive — see the constants block above. Covers Hachi
        and Kamino (both land through the generic do_damage() pipeline,
        which calls this); Kai's own flurry stacks it directly from
        resolve_special instead, since Kai bypasses this hook entirely."""
        if attacker is not self.fighter or defender is None or actual <= 0:
            return
        self._stack_slaughter()

    def _stack_slaughter(self):
        attacker = self.fighter
        cur = attacker.statuses.get("slaughter", {})
        stacks = min(SLAUGHTER_MAX_STACKS, cur.get("stacks", 0) + 1)
        set_status(attacker, "slaughter", SLAUGHTER_DURATION_S, stacks=stacks)
        set_status(attacker, "attack_up", SLAUGHTER_DURATION_S, pct=stacks * SLAUGHTER_ATK_PCT_PER_STACK)

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "dismantle":
            # Status: bleed (DoT) — same status name Kai/Kamino also use;
            # dps kwarg omitted so it falls back to the canonical
            # BLEED_BASE_DPS flat rate, same as every bleed source now.
            set_status(defender, "bleed", HACHI_BLEED_DURATION_S)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Sliced!", RED])
            battle.log = f"{attacker.name}'s Hachi leaves deep gashes on {defender.name}!"
        elif tag == "kamino":
            # Status: bleed (DoT) + corruption (heal reduction) + burn (DoT,
            # armor-ignoring, matches the fire visuals below) — bleed's and
            # burn's dps kwargs are both omitted, so both fall back to their
            # canonical flat rate (BLEED_BASE_DPS/BURN_BASE_DPS) in
            # status_library.py — same names as Kai above, see the overwrite
            # note there; whichever of Kai/Kamino lands last wins on both,
            # they don't stack
            set_status(defender, "bleed", KAMINO_BLEED_DURATION_S)
            set_status(defender, "corruption", KAMINO_CORRUPTION_DURATION_S, pct=KAMINO_CORRUPTION_PCT)
            set_status(defender, "burn", KAMINO_BURN_DURATION_S)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "KAMINO!", SUKUNA_PINK])
            battle.log = f"{attacker.name} unleashes the cursed technique Kamino on {defender.name}!"
            battle.flash_timer = max(battle.flash_timer, 0.5)
            battle.add_screen_shake(24, 0.32)
            battle.add_ring(defender.pos, 190, 0.6, (255, 150, 40), width=7)
            battle.add_ring(defender.pos, 170, 0.75, SUKUNA_PINK, width=5)
            emit_explosion(battle.fx, defender.pos, (255, 140, 40), count=46)
            emit_dark(battle.fx, defender.pos, count=34, radius=70)
        elif tag == "ten_shadows":
            self._summon_shadow()

    # ---- Ten Shadows: summon --------------------------------------------------
    def _roll_shadow(self):
        """Weighted-random pick among SHADOWS, excluding whichever one the
        previous roll landed on (self._last_shadow_key) — ten distinct
        shadows means casting Ten Shadows twice in a row should never
        summon the same one back-to-back, no matter how heavily that shadow
        is weighted. Only ever excludes the single immediately-preceding
        pick, not a lasting per-shadow lockout — the very next roll after
        that has all ten (including the one just excluded) back in play.
        The `or SHADOWS` fallback is unreachable with ten real entries here,
        but keeps this safe if the roster ever shrank to one."""
        candidates = [b for b in SHADOWS if b["key"] != self._last_shadow_key] or SHADOWS
        weights = [b["weight"] for b in candidates]
        profile = random.choices(candidates, weights=weights, k=1)[0]
        self._last_shadow_key = profile["key"]
        return profile

    def _summon_shadow(self):
        battle, attacker = self.battle, self.fighter
        profile = self._roll_shadow()
        cooldown = profile["attack_cooldown"]
        # attack_cooldown/attack_range are pinned onto this one clone (see
        # CloneArmy.spawn's own kwargs) rather than shared on the army —
        # with TEN_SHADOWS_CAP > 1, an earlier still-living shadow must keep
        # its own attack pace regardless of what this cast just rolled.
        # Round Deer passes None through (never attacks at all) rather than
        # some made-up finite number, then gets its attack_cd pinned at
        # infinity below instead of asking CloneArmy to treat "no cooldown"
        # as "attacks every frame".
        clone = self.shadow_army.spawn(
            stat_pct=profile["stat_pct"], hp_pct=profile["hp_pct"], duration=TEN_SHADOWS_DURATION_S,
            attack_cooldown=cooldown, attack_range=profile["attack_range"],
        )
        clone.shadow_key = profile["key"]
        clone.shadow_move = profile["move"]
        clone.name = f"{attacker.name}'s {profile['label']}"
        if cooldown is None:
            clone.attack_cd = float("inf")
        # Per-movement-pattern state (see the _move_* methods) — set
        # unconditionally on every spawn since it's cheap and each shadow
        # only ever reads the handful of fields its own movement uses.
        clone.dash_timer = 0.0
        clone.slither_phase = random.uniform(0, math.tau)
        clone.hop_state = "resting"
        clone.hop_timer = random.uniform(*SHADOW_HOP_REST_S)
        clone.orbit_angle = random.uniform(0, math.tau)
        guard_dir = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        if guard_dir.length_squared() == 0:
            guard_dir = pygame.Vector2(1, 0)
        clone.guard_offset = guard_dir.normalize() * SHADOW_GUARD_OFFSET
        clone.adapt_timer = ADAPT_CYCLE_S
        clone.adapt_index = 0
        clone.pierce_state = "charging"
        clone.pierce_timer = 0.0
        clone.split_cd = 0.0
        if profile["key"] == "tiger_funeral":
            # Status: taunt — lives on the clone, not on Sukuna himself (see
            # status_library.taunt_redirect's own CloneArmy scan).
            set_status(clone, "taunt", TEN_SHADOWS_DURATION_S)
        elif profile["key"] == "mahoraga":
            cleanse(attacker)
            set_status(attacker, "damage_reduction", MAHORAGA_SELF_BUFF_S, pct=MAHORAGA_DR_PCT)
        elif profile["key"] == "piercing_ox":
            # Launches straight into its first charge at full
            # SHADOW_OX_CHARGE_SPEED instead of CloneArmy.spawn's own weak
            # default spawn_speed (60-100) — a bull that ambles out at
            # walking pace before its first charge would undercut the
            # whole "hits like a freight train" point of this shadow. Aimed
            # at the opponent's current position (see
            # _ox_charge_direction) the instant it's summoned, not a
            # random heading.
            clone.vel = self._ox_charge_direction(clone) * SHADOW_OX_CHARGE_SPEED
        battle.floaters.append(
            [attacker.pos.x, attacker.pos.y - 60, -0.6, 255, f"{profile['label']}!", SUKUNA_PINK]
        )
        battle.log = f"{attacker.name} calls forth a shadow — {profile['label']}!"
        battle.add_ring(attacker.pos, 90, 0.5, SUKUNA_PINK, width=5)
        emit_dark(battle.fx, attacker.pos, count=30, radius=60)
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)

    def clone_basic_attack_landed(self, clone, target, actual, crit):
        """Each shadow's own on-hit flavor (see the SHADOWS table's own
        comment for why these don't reuse bleed/corruption) — Round Deer
        never reaches here at all (its attack_cd is pinned at infinity),
        Tiger Funeral's own payoff already happened on summon, and Rabbit's
        whole gimmick lives in its own movement instead (_move_bounce_split),
        so none of those three needs a branch here. Mahoraga gets both: its
        summon-time self-buff on Sukuna (see _summon_shadow) plus its own
        on-hit attack_down below, on every landed swing."""
        if actual <= 0:
            return
        key = getattr(clone, "shadow_key", None)
        if key == "divine_dog":
            set_status(target, "armor_break", DIVINE_DOG_ARMOR_BREAK_S, amount=DIVINE_DOG_ARMOR_BREAK_AMOUNT)
        elif key == "nue":
            set_status(target, "slowed", NUE_SLOW_S, pct=NUE_SLOW_PCT)
        elif key == "great_serpent":
            set_status(target, "poison", SERPENT_POISON_S)
        elif key == "toad":
            set_status(target, "rooted", TOAD_ROOT_S)
        elif key == "max_elephant":
            # A water wave centered on the elephant itself, not a stat debuff
            # (see MAX_ELEPHANT_* above) — queues a pulse instead of shoving
            # `target` directly; _tick_elephant_pulses grows it outward
            # frame by frame and applies the actual knockback once it
            # reaches something.
            self._elephant_pulses.append(
                {"pos": pygame.Vector2(clone.pos), "t": 0.0, "hit": set()}
            )
            emit_spark_burst(self.battle.fx, clone.pos, MAX_ELEPHANT_WAVE_COLOR, count=16)
        elif key == "piercing_ox":
            set_status(target, "vulnerability", OX_VULN_S, pct=OX_VULN_PCT)
        elif key == "mahoraga":
            set_status(target, "attack_down", MAHORAGA_ATK_DOWN_S, pct=MAHORAGA_ATK_DOWN_PCT)

    def on_attack_redirected(self):
        """An eligible attack aimed at Sukuna got forced onto one of his own
        shadows instead — either Tiger Funeral's guaranteed "taunt" (see
        status_library.taunt_redirect) or, now that basic_attack_decoys()
        offers up the whole army, any other shadow picked at plain equal
        odds. Resolve the hit against whichever one it was via CloneArmy.
        damage_clone, same treatment Phantom Lancer's own illusions get for
        a redirected hit (see PhantomLancerPlugin.on_attack_redirected)."""
        battle = self.battle
        clone = battle.redirect_target
        if clone is None or clone not in self.shadow_army.clones:
            return False
        attacker, ability = battle.attacker, battle.ability
        dmg = round(attacker.atk * ability.dmg_mult)
        dmg = round(dmg * battle.status_outgoing_multiplier(attacker))
        actual = self.shadow_army.damage_clone(clone, dmg, ability=ability, knock_dir=battle.atk_dir)
        battle.damage_applied = True
        battle.log = f"{attacker.name}'s {ability.name} tears into {clone.name}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def ambient_tick(self, dt):
        self.shadow_army.tick(dt)
        self._flush_rabbit_splits()
        self._tick_round_deer_aura(dt)
        self._tick_elephant_pulses(dt)

    def _tick_elephant_pulses(self, dt):
        """Grows each queued Max Elephant pulse's radius from 0 up to
        MAX_ELEPHANT_PULSE_MAX_RADIUS over MAX_ELEPHANT_PULSE_DURATION_S,
        knocking back the real opponent and/or any of their own decoys the
        instant the growing edge reaches them — each target only once per
        pulse (the "hit" set), so a target standing still just inside the
        blast doesn't get shoved again every subsequent frame. A pulse is
        dropped once its duration elapses, same expiry style CloneArmy.tick
        uses for clones."""
        battle = self.battle
        opponent = battle.f2 if battle.f1 is self.fighter else battle.f1
        enemy_plugin = battle.plugin_for(opponent)
        enemy_army = enemy_plugin.clone_army() if enemy_plugin is not None else None

        alive = []
        for pulse in self._elephant_pulses:
            pulse["t"] += dt
            radius = MAX_ELEPHANT_PULSE_MAX_RADIUS * min(1.0, pulse["t"] / MAX_ELEPHANT_PULSE_DURATION_S)
            if opponent.is_alive() and opponent not in pulse["hit"]:
                if (opponent.pos - pulse["pos"]).length() <= radius:
                    apply_knockback(opponent, pulse["pos"], MAX_ELEPHANT_KNOCKBACK_DIST)
                    pulse["hit"].add(opponent)
            if enemy_army is not None:
                for decoy in enemy_army.clones:
                    if decoy in pulse["hit"]:
                        continue
                    if (decoy.pos - pulse["pos"]).length() <= radius:
                        apply_knockback(decoy, pulse["pos"], MAX_ELEPHANT_KNOCKBACK_DIST)
                        pulse["hit"].add(decoy)
            if pulse["t"] < MAX_ELEPHANT_PULSE_DURATION_S:
                alive.append(pulse)
        self._elephant_pulses = alive

    def _evict_oldest_rabbit(self):
        """Removes the oldest live rabbit from shadow_army.clones — used by
        _flush_rabbit_splits instead of letting CloneArmy.spawn's own
        generic cap eviction (oldest clone overall, any type) run, which
        would let a rabbit split evict a Divine Dog or any other non-rabbit
        shadow. No-op if no rabbit is currently out (shouldn't happen —
        called only once rabbit_count already hit RABBIT_CAP)."""
        for i, c in enumerate(self.shadow_army.clones):
            if getattr(c, "shadow_key", None) == "rabbit":
                self.shadow_army.clones.pop(i)
                return

    def _flush_rabbit_splits(self):
        """Spawns whatever _move_bounce_split queued this frame — deferred
        out of that method (called from inside shadow_army.tick()'s own
        `for clone in self.clones` loop) to here, right after that loop has
        already finished and reassigned self.clones, so any eviction below
        never mutates the list mid-iteration. No-op most frames (empty
        queue).

        Gated by RABBIT_CAP, not shadow_army's own shared TEN_SHADOWS_CAP —
        once RABBIT_CAP rabbits are already out, evicts the oldest rabbit
        ourselves (_evict_oldest_rabbit) and passes CloneArmy.spawn an
        explicit `cap` big enough that its own generic eviction never fires,
        so a rabbit split can never evict a non-rabbit shadow."""
        if not self._pending_rabbit_splits:
            return
        profile = next(b for b in SHADOWS if b["key"] == "rabbit")
        for pos in self._pending_rabbit_splits:
            rabbit_count = sum(1 for c in self.shadow_army.clones if getattr(c, "shadow_key", None) == "rabbit")
            if rabbit_count >= RABBIT_CAP:
                self._evict_oldest_rabbit()
            child = self.shadow_army.spawn(
                near=pos, cap=len(self.shadow_army.clones) + 1,
                stat_pct=profile["stat_pct"], hp_pct=profile["hp_pct"],
                duration=TEN_SHADOWS_DURATION_S,
                attack_cooldown=profile["attack_cooldown"], attack_range=profile["attack_range"],
            )
            child.shadow_key = "rabbit"
            child.shadow_move = "bounce_split"
            child.name = f"{self.fighter.name}'s {profile['label']}"
            child.split_cd = RABBIT_SPLIT_COOLDOWN_S
            self.battle.add_ring(child.pos, 30, 0.3, WHITE, width=3)
            emit_dark(self.battle.fx, child.pos, count=10, radius=18)
        self._pending_rabbit_splits = []

    def _tick_round_deer_aura(self, dt):
        """Scales with however many Round Deer happen to be out at once —
        TEN_SHADOWS_CAP > 1 means rolling a second (or third) one while an
        earlier one is still alive is a real possibility, and a second deer
        standing right there doing nothing would be a strange non-buff."""
        deer_count = sum(1 for c in self.shadow_army.clones if getattr(c, "shadow_key", None) == "round_deer")
        if deer_count == 0:
            self._deer_heal_accum = 0.0
            self._deer_floater_cd = ROUND_DEER_FLOATER_INTERVAL
            return
        self._deer_heal_accum += heal(self.fighter, ROUND_DEER_HEAL_PCT_PER_S * deer_count, dt)
        self._deer_floater_cd -= dt
        if self._deer_floater_cd <= 0:
            amount = round(self._deer_heal_accum)
            if amount > 0:
                self.battle.floaters.append(
                    [self.fighter.pos.x, self.fighter.pos.y - 40, -0.5, 200, f"+{amount}", GREEN]
                )
            self._deer_heal_accum = 0.0
            self._deer_floater_cd += ROUND_DEER_FLOATER_INTERVAL

    # ---- Ten Shadows: per-shadow movement (see clone_move_step) ----------------
    def clone_move_step(self, clone, dt, speed_mult):
        fn = self._move_fns.get(getattr(clone, "shadow_move", None), bounce_move)
        fn(clone, dt, speed_mult)

    @staticmethod
    def _clamp_pos(pos):
        pos.x = max(BOUND_LEFT, min(BOUND_RIGHT, pos.x))
        pos.y = max(BOUND_TOP, min(BOUND_BOTTOM, pos.y))

    def _steer_toward_opponent(self, vel, pos, dt, turn_rate):
        """Rotate `vel` up to turn_rate rad/s toward the live opponent,
        keeping its own speed — used by the wandering movement patterns
        (erratic/slither/trudge/bounce_split) so their own bounce/wiggle
        still generally advances on the fight instead of drifting away from
        it for its whole lifespan. No-op (returns vel unchanged) with no
        live opponent or no velocity to steer."""
        if vel.length_squared() == 0:
            return vel
        battle = self.battle
        opponent = battle.f2 if battle.f1 is self.fighter else battle.f1
        if not opponent.is_alive():
            return vel
        target_dir = opponent.pos - pos
        if target_dir.length_squared() == 0:
            return vel
        cur_angle = math.atan2(vel.y, vel.x)
        target_angle = math.atan2(target_dir.y, target_dir.x)
        diff = (target_angle - cur_angle + math.pi) % math.tau - math.pi
        diff = max(-turn_rate * dt, min(turn_rate * dt, diff))
        new_angle = cur_angle + diff
        speed = vel.length()
        return pygame.Vector2(math.cos(new_angle), math.sin(new_angle)) * speed

    def _move_stationary(self, clone, dt, speed_mult):
        """Round Deer: plants itself at its summon spot and never moves —
        its whole kit is the passive heal aura in _tick_round_deer_aura."""
        clone.vel = pygame.Vector2()

    def _move_chase(self, clone, dt, speed_mult):
        """Divine Dog: relentlessly beelines the opponent instead of idly
        roaming — a hunting dog closing distance, not bouncing past it."""
        battle = self.battle
        opponent = battle.f2 if battle.f1 is self.fighter else battle.f1
        if opponent.is_alive():
            direction = opponent.pos - clone.pos
            if direction.length_squared() > 4:
                clone.vel = direction.normalize() * SHADOW_CHASE_SPEED
        clone.pos += clone.vel * dt * speed_mult
        self._clamp_pos(clone.pos)

    def _move_erratic(self, clone, dt, speed_mult):
        """Nue: still bounces off the arena walls like any roamer, but also
        jinks into a fresh random direction every fraction of a second —
        a darting, hard-to-pin-down flight instead of a steady heading."""
        clone.dash_timer -= dt
        if clone.dash_timer <= 0:
            angle = random.uniform(0, math.tau)
            speed = random.uniform(*SHADOW_ERRATIC_SPEED)
            clone.vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
            clone.dash_timer = random.uniform(*SHADOW_ERRATIC_INTERVAL)
        clone.vel = self._steer_toward_opponent(clone.vel, clone.pos, dt, SHADOW_HOMING_TURN_RATE)
        bounce_move(clone, dt, speed_mult)

    def _move_slither(self, clone, dt, speed_mult):
        """Great Serpent: the usual bounce path, plus a perpendicular sine
        wiggle layered on top — a wavy, slithering trail instead of a
        straight one."""
        clone.vel = self._steer_toward_opponent(clone.vel, clone.pos, dt, SHADOW_HOMING_TURN_RATE)
        bounce_move(clone, dt, speed_mult)
        clone.slither_phase += dt * SHADOW_SLITHER_FREQ
        if clone.vel.length_squared() > 0:
            perp = pygame.Vector2(-clone.vel.y, clone.vel.x).normalize()
            clone.pos += perp * math.sin(clone.slither_phase) * SHADOW_SLITHER_AMPLITUDE * dt
            self._clamp_pos(clone.pos)

    def _move_hop(self, clone, dt, speed_mult):
        """Toad: sits still for a beat, then hops to a nearby random spot
        over a short arc-less lerp, then rests again — a hopping toad, not
        a continuous roamer."""
        if clone.hop_state == "resting":
            clone.vel = pygame.Vector2()
            clone.hop_timer -= dt
            if clone.hop_timer <= 0:
                battle = self.battle
                opponent = battle.f2 if battle.f1 is self.fighter else battle.f1
                if opponent.is_alive() and (opponent.pos - clone.pos).length_squared() > 4:
                    aim = math.atan2(opponent.pos.y - clone.pos.y, opponent.pos.x - clone.pos.x)
                    angle = aim + random.uniform(-SHADOW_HOP_AIM_SPREAD, SHADOW_HOP_AIM_SPREAD)
                else:
                    angle = random.uniform(0, math.tau)
                target = clone.pos + pygame.Vector2(math.cos(angle), math.sin(angle)) * SHADOW_HOP_DIST
                self._clamp_pos(target)
                clone.hop_from = pygame.Vector2(clone.pos)
                clone.hop_to = target
                clone.hop_t = 0.0
                clone.hop_state = "hopping"
        else:
            clone.hop_t += dt
            t = min(1.0, clone.hop_t / SHADOW_HOP_TRAVEL_S)
            clone.pos = clone.hop_from.lerp(clone.hop_to, t)
            if t >= 1.0:
                clone.hop_state = "resting"
                clone.hop_timer = random.uniform(*SHADOW_HOP_REST_S)

    def _move_orbit(self, clone, dt, speed_mult):
        """Circles its own owner at a fixed radius instead of roaming the
        arena — no longer Rabbit Escape's own movement (see
        _move_bounce_split for that), kept on purely as one of the patterns
        Mahoraga's own _move_adaptive cycles through (see ADAPT_ROTATION)."""
        clone.orbit_angle += SHADOW_ORBIT_SPEED * dt * speed_mult
        center = pygame.Vector2(self.fighter.pos)
        offset = pygame.Vector2(math.cos(clone.orbit_angle), math.sin(clone.orbit_angle)) * SHADOW_ORBIT_RADIUS
        clone.pos = center + offset
        self._clamp_pos(clone.pos)
        clone.vel = pygame.Vector2(-math.sin(clone.orbit_angle), math.cos(clone.orbit_angle))

    def _move_bounce_split(self, clone, dt, speed_mult):
        """Rabbit Escape: a plain DVD-logo bounce (same reflect-and-squash
        physics bounce_move gives every real fighter), except every actual
        wall bounce also tries to split (see _maybe_split_rabbit) —
        reimplements the bounce math inline (instead of calling bounce_move)
        purely to know exactly when a bounce happened, the one thing
        bounce_move doesn't report back to its caller. Colliding into a
        fighter or another roaming body splits it the same way, just via
        on_collision instead of this method — see that hook."""
        clone.split_cd = max(0.0, getattr(clone, "split_cd", 0.0) - dt)
        clone.vel = self._steer_toward_opponent(clone.vel, clone.pos, dt, SHADOW_HOMING_TURN_RATE)
        clone.pos += clone.vel * dt * speed_mult
        bounced = False
        if clone.pos.x < BOUND_LEFT:
            clone.pos.x = BOUND_LEFT
            clone.vel.x *= -1
            squash(clone, "x")
            bounced = True
        elif clone.pos.x > BOUND_RIGHT:
            clone.pos.x = BOUND_RIGHT
            clone.vel.x *= -1
            squash(clone, "x")
            bounced = True
        if clone.pos.y < BOUND_TOP:
            clone.pos.y = BOUND_TOP
            clone.vel.y *= -1
            squash(clone, "y")
            bounced = True
        elif clone.pos.y > BOUND_BOTTOM:
            clone.pos.y = BOUND_BOTTOM
            clone.vel.y *= -1
            squash(clone, "y")
            bounced = True
        if bounced:
            self._maybe_split_rabbit(clone)

    def _maybe_split_rabbit(self, clone):
        """Queues a fresh rabbit at `clone`'s current spot (flushed by
        _flush_rabbit_splits) once its own RABBIT_SPLIT_COOLDOWN_S has
        elapsed — shared by every way a rabbit can bounce: off a wall (see
        _move_bounce_split) or into a fighter/other roaming body (see
        on_collision, driven by battle_loop.resolve_collisions). No-op for
        anything that isn't an on-cooldown rabbit."""
        if getattr(clone, "shadow_key", None) != "rabbit":
            return
        if getattr(clone, "split_cd", 0.0) > 0:
            return
        clone.split_cd = RABBIT_SPLIT_COOLDOWN_S
        self._pending_rabbit_splits.append(pygame.Vector2(clone.pos))

    def on_collision(self, a, b):
        """Rabbit Escape's split isn't just a wall-bounce gimmick — bumping
        into a fighter, the opponent's own clone, or another shadow splits
        it too (see _maybe_split_rabbit). Every plugin gets every collision
        (see CharacterPlugin.on_collision), so this only acts when one side
        is actually one of this plugin's own shadow clones."""
        for obj in (a, b):
            if obj in self.shadow_army.clones:
                self._maybe_split_rabbit(obj)

    def _move_trudge(self, clone, dt, speed_mult):
        """Max Elephant: the usual bounce path, just heavily slowed down —
        a lumbering, heavy-footed gait instead of darting around."""
        clone.vel = self._steer_toward_opponent(clone.vel, clone.pos, dt, SHADOW_HOMING_TURN_RATE)
        bounce_move(clone, dt, speed_mult * SHADOW_TRUDGE_SPEED_MULT)

    def _ox_charge_direction(self, clone):
        """Piercing Ox locks onto the opponent's CURRENT position the
        instant a charge launches, then commits to that straight line for
        the whole charge — no re-aiming mid-run (that's Divine Dog's own
        _move_chase job) — a real bull charge, not a homing shot. Falls
        back to its current heading, or a random one as a last resort, if
        there's no live opponent to aim at."""
        battle = self.battle
        opponent = battle.f2 if battle.f1 is self.fighter else battle.f1
        if opponent.is_alive():
            direction = opponent.pos - clone.pos
            if direction.length_squared() > 1:
                return direction.normalize()
        if clone.vel.length_squared() > 0:
            return clone.vel.normalize()
        angle = random.uniform(0, math.tau)
        return pygame.Vector2(math.cos(angle), math.sin(angle))

    def _move_pierce(self, clone, dt, speed_mult):
        """Piercing Ox: a heavy, dead-straight bull charge — never the
        DVD-logo bounce every other roamer here uses, and (unlike this
        move's own earlier "tunnel through the wall" version) no longer
        wraps around either. It just charges in a straight line at
        SHADOW_OX_CHARGE_SPEED, aimed at the opponent's position the instant
        the charge starts (see _ox_charge_direction) but never adjusting
        mid-charge, until it slams into the arena edge, stops dead there
        (squash + a small shake/puff, so hitting the wall reads as real
        mass colliding with something, not a quiet teleport) for
        SHADOW_OX_PAUSE_S, then re-aims and launches into another charge —
        repeating stop/charge/stop instead of one continuous path."""
        if clone.pierce_state == "resting":
            clone.vel = pygame.Vector2()
            clone.pierce_timer -= dt
            if clone.pierce_timer <= 0:
                clone.vel = self._ox_charge_direction(clone) * SHADOW_OX_CHARGE_SPEED
                clone.pierce_state = "charging"
            return

        clone.pos += clone.vel * dt * speed_mult
        axis = None
        if clone.pos.x < BOUND_LEFT:
            clone.pos.x = BOUND_LEFT
            axis = "x"
        elif clone.pos.x > BOUND_RIGHT:
            clone.pos.x = BOUND_RIGHT
            axis = "x"
        if clone.pos.y < BOUND_TOP:
            clone.pos.y = BOUND_TOP
            axis = "y"
        elif clone.pos.y > BOUND_BOTTOM:
            clone.pos.y = BOUND_BOTTOM
            axis = "y"
        if axis is not None:
            squash(clone, axis)
            clone.vel = pygame.Vector2()
            clone.pierce_state = "resting"
            clone.pierce_timer = SHADOW_OX_PAUSE_S
            self.battle.add_screen_shake(6, 0.12)
            emit_dark(self.battle.fx, clone.pos, count=10, radius=22)

    def _move_guard(self, clone, dt, speed_mult):
        """Tiger Funeral: stays close to Sukuna at a fixed offset, trailing
        him like a bodyguard, instead of roaming off on its own — its
        actual bait/taunt effect doesn't need proximity to work, but a
        decoy standing where it's meant to be baiting reads better than one
        that's wandered across the map."""
        target = pygame.Vector2(self.fighter.pos) + clone.guard_offset
        to_target = target - clone.pos
        dist = to_target.length()
        if dist > 2:
            step = min(dist, SHADOW_GUARD_SPEED * dt * speed_mult)
            clone.pos += to_target.normalize() * step
            clone.vel = to_target.normalize() * SHADOW_GUARD_SPEED
        self._clamp_pos(clone.pos)

    def _move_adaptive(self, clone, dt, speed_mult):
        """Mahoraga: cycles through several of the other shadows' own
        movement patterns instead of having just one of its own — "adapts"
        its movement the same way the real Mahoraga adapts to anything."""
        clone.adapt_timer -= dt
        if clone.adapt_timer <= 0:
            clone.adapt_index = (clone.adapt_index + 1) % len(ADAPT_ROTATION)
            clone.adapt_timer = ADAPT_CYCLE_S
            self.battle.add_ring(clone.pos, 40, 0.3, WHITE, width=3)
        self._move_fns[ADAPT_ROTATION[clone.adapt_index]](clone, dt, speed_mult)

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_dark(self.battle.fx, pos, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos and battle.ability.name == "Kamino"):
            return False
        draw_fire_arrow(screen, battle.projectile_pos, battle.atk_dir, size=1.5)
        return True

    def draw_fx(self, screen, shake_x):
        """Hachi and Kai land as bare-handed curse-slashes with no travel
        time (a single cut for Hachi, a fanned-out flurry of 3-5 for Kai),
        Kamino is the exception — a fireball gathers in Sukuna's palm
        (windup), a blazing arrow flies across the arena (draw_projectile
        above), then it explodes into a burst of curse-slashes on impact —
        and Ten Shadows summons a shadow that lingers on screen long
        after the cast itself ends, so its own draw (shadow_army.draw) runs
        unconditionally below, unlike every other branch here which only
        ever draws while Sukuna is mid-attack."""
        battle, s = self.battle, self.fighter
        self.shadow_army.draw(
            screen, shake_x, sprite_alpha=225, ring_color=SUKUNA_PINK, sprite_for=self._shadow_sprite,
            ring_radius_for=self._ring_radius,
        )
        # Max Elephant's water-wave pulses (see _tick_elephant_pulses) drawn
        # unconditionally, same as shadow_army.draw above — a pulse keeps
        # growing well past the single frame the landed hit happened on.
        for pulse in self._elephant_pulses:
            radius = MAX_ELEPHANT_PULSE_MAX_RADIUS * min(1.0, pulse["t"] / MAX_ELEPHANT_PULSE_DURATION_S)
            pos = pulse["pos"] + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, pos, radius, MAX_ELEPHANT_WAVE_COLOR, width=5)
        if not (battle.mode == "attack" and battle.attacker is s):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t

        if name == "Hachi" and phase == "impact":
            # no dash — the single cut appears directly on the target, same
            # as Kai below, just one slash instead of a fanned-out flurry
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            draw_slash_fx(screen, center, battle.atk_dir, t, size=95)
            draw_starburst(screen, center, WHITE, size=28, fade=1 - t)

        elif name == "Kai" and phase == "impact":
            # no travel, no projectile — `hits` cuts appear on the target
            # all at once, fanned out around the attack direction
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            hits = self.kai_hits
            spread_deg = 26
            draw_slash_arc(screen, center, battle.atk_dir, radius=54, spread_deg=160,
                            color=SUKUNA_PINK, width=8, fade=1 - t)
            for i in range(hits):
                ang_deg = (i - (hits - 1) / 2) * spread_deg + random.uniform(-6, 6)
                d = battle.atk_dir.rotate(ang_deg)
                draw_slash(screen, center, d, SUKUNA_PINK, length=50, width=6)
            draw_starburst(screen, center, WHITE, size=36, fade=1 - t)
            draw_expanding_ring(screen, center, 55 * t, SUKUNA_PINK, width=4)

        elif name == "Kamino" and phase == "windup":
            # a fireball gathers in Sukuna's palm before the arrow is loosed
            # — clear windup so the shot reads as fire from the first frame
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            for _ in range(6):
                jitter = pygame.Vector2(random.uniform(-11, 11), random.uniform(-11, 11)) * t
                pygame.draw.circle(
                    screen, (255, 150, 40),
                    (int((origin + jitter).x), int((origin + jitter).y)), int(6 + 12 * t),
                )
            pygame.draw.circle(screen, (255, 230, 140), (int(origin.x), int(origin.y)), max(2, int(5 + 8 * t)))
            draw_starburst(screen, origin, (255, 200, 90), size=18 + 26 * t, fade=t)

        elif name == "Kamino" and phase == "impact":
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, center, 95 * t, (255, 150, 40), width=7)
            draw_expanding_ring(screen, center, 65 * t, (255, 210, 110), width=4)
            draw_starburst(screen, center, (255, 210, 110), size=50, fade=1 - t)
            for i in range(6):
                ang = i * (math.pi / 3) + t * 2
                d = pygame.Vector2(math.cos(ang), math.sin(ang))
                draw_slash(screen, center, d, SUKUNA_PINK, length=56, width=7)
                draw_slash_arc(screen, center, d, radius=40, spread_deg=80,
                                color=SUKUNA_PINK, width=5, fade=1 - t * 0.6)
            draw_expanding_ring(screen, center, 70 * t, SUKUNA_PINK, width=4)

        elif name == "Ten Shadows" and phase in ("windup", "channel"):
            # a shadow circle gathers under Sukuna's own feet through the
            # whole windup/channel — the actual shadow only appears once
            # apply_tag_effects (RESOLVE_PHASE for "cast" is "release")
            # spawns it, drawn unconditionally by shadow_army.draw above.
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, origin, 20 + 30 * t, SUKUNA_PINK, width=3)

        elif name == "Ten Shadows" and phase == "release":
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            draw_starburst(screen, origin, SUKUNA_PINK, size=40, fade=1 - t)
            draw_expanding_ring(screen, origin, 90 * t, SUKUNA_PINK, width=5)
