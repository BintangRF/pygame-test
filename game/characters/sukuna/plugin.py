"""Sukuna plugin: the Slaughter passive (stacking Attack Up off landed
hits — see the constants block below), Hachi's bleed application, Kai's
multi-hit flurry resolve (it doesn't deal its own damage — it procs Hachi's
basic-attack formula 3-5 times at once), Ten Shadows' random shadow summon,
Kamino's cursed detonation, and the bare-handed curse-slash animation for
the three melee techniques.

Ten Shadows (see SHADOWS below) is a fan-original move, not a literal port of
Megumi Fushiguro's own canon Ten Shadows Technique — Sukuna summons one of
nine shadows at random each cast, each with its own power, its own
on-hit effect, and (see the _move_* methods / CharacterPlugin.
clone_move_step) its own movement pattern, resolved through a single
CloneArmy (shadow_army, cap=TEN_SHADOWS_CAP — casting again while under cap
adds a second/third shadow instead of only ever replacing the last one; see
that constant's own comment) instead of Phantom Lancer's uniform
illusion-army model. Tiger Funeral is the one shadow that carries the
generic "taunt" status (see status_library.taunt_redirect, generalized to
also scan a defender's own clone_army() for it, not just Vampire's
singleton self.clone) — every other shadow is a plain, non-taunting
auto-attacker.

Mahoraga is the tenth, and it isn't part of that random pool at all any
more — see the "Ten Shadows: Mahoraga rework" constants block and
_sukuna_critical/_big_mahoraga/_summon_big_mahoraga/_tick_big_mahoraga.
Above MAHORAGA_HP_THRESHOLD_PCT of Sukuna's own hp it can't be summoned at
all; at/under it, it's the ONLY thing Ten Shadows can summon, replacing
(killing outright) whatever's already out instead of joining it. It has no
duration of its own at all (unlike every other shadow's TEN_SHADOWS_
DURATION_S) — once out, it stays out regardless of what Sukuna's own hp
does afterward, and Ten Shadows can't summon anything else at all (not
even a fresh Mahoraga) until it actually dies to damage. And unlike every
other shadow, it's a once-per-match summon: the instant it dies,
_mahoraga_spent latches True for good (see _tick_big_mahoraga) and only
the random nine-shadow pool ever opens back up after that, no matter how
low Sukuna's own hp drops again later in the same match. It's chanted in
first — Sukuna speaks Mahoraga's own
norito (MAHORAGA_CHANT_LINE_1/2) through the cast's windup/channel, drawn
by _draw_mahoraga_chant — then comes out far bigger and stronger than any
of the other nine (BIG_MAHORAGA_HP_PCT/ATK_PCT, rendered at roughly the
training dummy's own oversized footprint), guaranteed-taunting so it
answers every eligible hit aimed at Sukuna while it's out, always shedding
every cleansable debuff the instant it lands (_tick_big_mahoraga), and
growing a permanent Attack Up stack every time it actually takes a hit —
"adapts to anything" as a mechanic, not just a reputation. Sukuna himself
is silenced + disarmed the whole time (MAHORAGA_SUKUNA_LOCK_S) — Mahoraga
fights in his place, not alongside him."""

import math
import random

import pygame

from ...core.asset_loading import load_sprite
from ...core.clone_army import CloneArmy
from ...core.constants import (
    AVATAR_R, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GOLD, GREEN, RED, SUKUNA_PINK, WHITE,
)
from ...core.effects import (
    draw_expanding_ring,
    draw_slash,
    draw_slash_arc,
    draw_slash_fx,
    draw_starburst,
)
from ...core.entities import bounce_move, set_status
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

# The painted fireball projectile (assets/sukuna/kamino.png), loaded once per
# pixel size and cached, same pattern as _bat_sprite in vampire/plugin.py.
# Drawn tip pointing up-and-right at roughly 45 degrees — _KAMINO_FX_DEFAULT_DIR
# below is that baked-in facing, so draw_projectile can rotate it by however
# far atk_dir sits from it, same correction draw_slash_fx applies for its own
# painted flipbook's default facing.
KAMINO_SPRITE_SIZE = 130
_KAMINO_SPRITE_CACHE = {}
_KAMINO_FX_DEFAULT_DIR = pygame.Vector2(1, -1)


def _kamino_sprite(size):
    img = _KAMINO_SPRITE_CACHE.get(size)
    if img is None:
        img = load_sprite("sukuna/kamino.png", size)
        _KAMINO_SPRITE_CACHE[size] = img
    return img


# The real norito chanted right before Mahoraga is called (see
# _draw_mahoraga_chant/_sukuna_critical) — battle_animation.py's own
# font_big/font_mid/font_small are all plain Consolas, which has no CJK
# glyphs at all, so this needs its own font found via match_font instead
# (Windows ships MS Gothic/Yu Gothic, most Linux desktops ship a Noto CJK
# family) rather than reusing those.
_CHANT_FONT_CACHE = {}


def _chant_font(size):
    font = _CHANT_FONT_CACHE.get(size)
    if font is None:
        path = pygame.font.match_font(
            "msgothic,yugothic,meiryo,notosanscjkjp,notosanscjk,arialunicodems"
        )
        font = pygame.font.Font(path, size) if path else pygame.font.SysFont(None, size)
        _CHANT_FONT_CACHE[size] = font
    return font

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
    # Mahoraga USED to sit here as the rare "jackpot" weighted pull — it no
    # longer does. See the "Ten Shadows: Mahoraga rework" block below:
    # above MAHORAGA_HP_THRESHOLD_PCT of Sukuna's own hp it can't be
    # summoned at all, and at/under that threshold it's the ONLY thing Ten
    # Shadows can summon (see apply_tag_effects/_sukuna_critical), so it has
    # no weight to roll here any more.
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
# its own at all — "attack_down" instead of reusing Ox's own armor-shred
# vulnerability, so it actually cripples the opponent's own offense while
# it's out, not just a bigger basic-attack number. Still applies to the new
# threshold-gated Mahoraga below (see clone_basic_attack_landed), on top of
# its own on-hit adaptation (MAHORAGA_ADAPT_*).
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

# ---- Ten Shadows: Mahoraga rework ---------------------------------------
# Mahoraga no longer sits in the SHADOWS weighted-random table at all (see
# that table's own comment) — it's Sukuna's own emergency answer once he's
# genuinely hurt, not a lucky pull: sealed away entirely above this hp
# threshold, and the ONLY thing Ten Shadows can summon at/under it (see
# apply_tag_effects/_sukuna_critical/_summon_big_mahoraga) — but only once
# per match; once it dies, _mahoraga_spent keeps it sealed away for good
# regardless of hp (see _tick_big_mahoraga).
MAHORAGA_HP_THRESHOLD_PCT = 0.5

# hp_pct/stat_pct both read off Sukuna's own CURRENT max_hp/atk at summon
# time, same as every other shadow (see CloneArmy.spawn) — bigger numbers
# than any of the other nine get, but deliberately reined in from this
# rework's first pass (was 0.5/1.5, attacking every 0.3s — the single
# fastest attacker in the whole roster) once a taunting, no-duration,
# always-cleansed, on-hit-growing tank at those numbers turned out to make
# Sukuna dominate a match outright rather than just answer one. Armor is
# spelled out here even though it's already CloneArmy's own default
# (CLONE_BASE_ARMOR == 0.0), so a future change to that shared default can
# never accidentally hand Mahoraga armor it was never supposed to have.
BIG_MAHORAGA_HP_PCT = 3.0
BIG_MAHORAGA_ATK_PCT = 6.5
BIG_MAHORAGA_ARMOR = 0.0
# Unlike TEN_SHADOWS_DURATION_S (the ordinary pack's own despawn timer),
# Mahoraga has no clock at all — CloneUnit.time_left is pinned at infinity
# (see _summon_big_mahoraga) so CloneArmy.tick's own `time_left -= dt`
# expiry can never fire for it; the only way it ever leaves the field is
# dying to actual damage (hp <= 0, same as any other clone). And for as
# long as it's alive, Ten Shadows can't summon anything else at all — not
# just "can't duplicate" (see apply_tag_effects/_big_mahoraga) — only once
# it's dead does the random nine-shadow pool open back up.
#
# attack_cooldown slowed to Toad's own pace (the slowest of the random
# nine) rather than Divine Dog's — an indestructible taunting tank that
# also outpaced every other attacker in the game was the single biggest
# contributor to Mahoraga snowballing a match, well before its on-hit
# Attack Up (MAHORAGA_ADAPT_*) even entered into it.
BIG_MAHORAGA_ATTACK_COOLDOWN = 1.0
BIG_MAHORAGA_ATTACK_RANGE = 180
# Move speed: rescaled onto its own spawned velocity right after CloneArmy.
# spawn hands it back (see _summon_big_mahoraga), instead of the shared
# shadow_army's own spawn_speed default (60-100, same slow idle-roam range
# every other shadow gets) — a wheel deity chasing an already-desperate
# Sukuna needs to actually be able to close distance on its own plain
# bounce (see clone.shadow_move = "bounce"), not roam at the same pace as
# a stationary Round Deer. Faster than every other shadow's own top speed
# (SHADOW_ERRATIC_SPEED tops out at 240) short of Piercing Ox's dedicated
# charge burst.
BIG_MAHORAGA_MOVE_SPEED = 1060

# Sukuna himself: silenced + disarmed for as long as Mahoraga is out (see
# _tick_big_mahoraga) — the wheel fights in his place, not alongside him,
# so he can't throw a basic attack or cast anything of his own while it's
# up. A short rolling window refreshed every ambient_tick rather than tied
# to Mahoraga's own infinite time_left: pinning it to that would leave
# Sukuna locked out of his own kit forever even after Mahoraga actually
# dies, since nothing would ever be left to clear it once the refresh
# stops — this way it just lapses on its own within a second of that.
MAHORAGA_SUKUNA_LOCK_S = 1.0

# Rendered at roughly the training dummy's own oversized footprint (see
# core/assets.py: sprite_size = AVATAR_R * 4.8 for "dummy" vs AVATAR_R * 2.4
# for every other fighter/shadow — exactly double) instead of the flat
# fighter-sized sprite every other shadow uses (see _shadow_sprite) — a
# wheel deity should visibly dwarf the rest of the pack it just replaced.
BIG_MAHORAGA_SPRITE_SCALE = 2.0

# On-hit "adaptation": every landed hit against Mahoraga (an actual hp drop
# since the previous ambient_tick, not just existing damage-over-time —
# see _tick_big_mahoraga) stacks a permanent Attack Up on itself instead of
# just chipping its hp down like any other shadow would — echoing the real
# Mahoraga's "adapts to any technique" reputation by growing more dangerous
# the longer a fight against it drags on, not just tankier. Both the
# per-stack amount and the cap were cut from this rework's first pass
# (0.05/20, +100% at the cap) alongside BIG_MAHORAGA_ATK_PCT above — a
# slower snowball on top of a lower starting number, not just one or the
# other.
MAHORAGA_ADAPT_ATK_PCT_PER_HIT = 0.06
MAHORAGA_ADAPT_MAX_STACKS = 15

# The real norito chanted right before Mahoraga answers the summon (see
# _draw_mahoraga_chant) — windup speaks the first line, channel the second.
MAHORAGA_CHANT_LINE_1 = "布瑠部由良由良"
MAHORAGA_CHANT_LINE_2 = "八握剣異戒神将魔虚羅"

# ---- movement tuning (see the _move_* methods / clone_move_step) --------
SHADOW_CHASE_SPEED = 130
SHADOW_ERRATIC_SPEED = (160, 240)
SHADOW_ERRATIC_INTERVAL = (0.35, 0.7)
SHADOW_SLITHER_AMPLITUDE = 40
SHADOW_SLITHER_FREQ = 3.2
SHADOW_HOP_REST_S = (0.5, 1.1)
SHADOW_HOP_TRAVEL_S = 0.22
SHADOW_HOP_DIST = 90
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
        # "move" key (see the _move_* methods below), plus "bounce" for
        # Mahoraga (see _summon_big_mahoraga) — the exact same plain
        # bounce_move every real fighter's own roam already uses, no
        # steering/flavor of its own layered on top the way every other
        # shadow's own movement gets (Mahoraga moves like a real fighter,
        # not like the rest of the pack).
        self._move_fns = {
            "chase": self._move_chase,
            "erratic": self._move_erratic,
            "slither": self._move_slither,
            "hop": self._move_hop,
            "trudge": self._move_trudge,
            "pierce": self._move_pierce,
            "stationary": self._move_stationary,
            "guard": self._move_guard,
            "bounce": bounce_move,
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
        # Mahoraga: a once-per-match answer, not a repeatable one — see
        # _tick_big_mahoraga (which flips _mahoraga_spent the first frame it
        # notices the clone it was watching is gone) and _sukuna_critical's
        # own callers, all of which gate on this too. _mahoraga_alive_last_tick
        # is just the bookkeeping that death-detection needs: whether the
        # clone _tick_big_mahoraga saw last frame is still the one it sees now.
        self._mahoraga_alive_last_tick = False
        self._mahoraga_spent = False

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
        _move_bounce_split). Mahoraga (see BIG_MAHORAGA_SPRITE_SCALE) is the
        opposite — rendered roughly the training dummy's own oversized
        footprint, dwarfing the pack it replaced instead of blending into
        it. This only resizes the drawn sprite — its hitbox/collision
        radius stays the same flat AVATAR_R every clone uses, same as any
        other shadow."""
        key = getattr(clone, "shadow_key", None)
        size = self.fighter.image.get_width()
        width = size
        if key == "rabbit":
            size = max(8, round(size * RABBIT_SPRITE_SCALE))
            width = max(6, round(size * RABBIT_WIDTH_SCALE))
        elif key == "mahoraga":
            size = round(size * BIG_MAHORAGA_SPRITE_SCALE)
            width = size
        return shadow_sprite(key, size, width=width)

    def _ring_radius(self, clone):
        """Passed to CloneArmy.draw as ring_radius_for — shrinks Rabbit's
        drawn ring (see RABBIT_RING_SCALE) and grows Mahoraga's own (see
        BIG_MAHORAGA_SPRITE_SCALE) to match each one's own resized sprite,
        instead of every other shadow's flat AVATAR_R + 6; purely cosmetic,
        same as _shadow_sprite's own resize."""
        key = getattr(clone, "shadow_key", None)
        if key == "rabbit":
            return max(6, round((AVATAR_R + 6) * RABBIT_RING_SCALE))
        if key == "mahoraga":
            return round((AVATAR_R + 6) * BIG_MAHORAGA_SPRITE_SCALE)
        return AVATAR_R + 6

    def _draw_mahoraga_slash(self, screen, clone, pos):
        """Passed to CloneArmy.draw as its draw_weapon callback — same
        pattern Phantom Lancer/Chaos Knight/Leonidas already use for their
        own clones' basic-attack swing (see each one's own _draw_clone_*),
        except a painted curse-slash instead of a swung weapon prop:
        Mahoraga fights bare-handed, same as Sukuna's own Hachi/Kai (see
        this plugin's own draw_fx), not with a held weapon. A no-op for
        every other shadow — none of the other nine get an attack swing
        drawn at all, same as before this.

        clone.attack_anim_t/attack_dir/attack_target_pos are the same
        fields CloneArmy._clone_attack already sets on every swing
        regardless of army — just never drawn for Ten Shadows until now.
        `t` mirrors how draw_slash_fx's own callers elsewhere read
        battle.phase_t: 0 at the swing's start, 1 once attack_anim_t
        (counting down from the army's shared attack_anim) has fully
        elapsed. Drawn at attack_target_pos — where the swing actually
        landed — not at `pos` (Mahoraga's own on-screen position, which
        `pos` always is, see CloneArmy.draw): a claw mark belongs on
        whatever it just cut, same as Sukuna's own Hachi/Kai draw theirs at
        battle.defender_start rather than at his own position."""
        if getattr(clone, "shadow_key", None) != "mahoraga" or clone.attack_anim_t <= 0:
            return
        t = 1 - clone.attack_anim_t / self.shadow_army.attack_anim
        # `pos` is already clone.pos shifted by this frame's own hit-flash
        # recoil/screen-shake (see CloneArmy.draw) — apply that exact same
        # shift to the target's own position too, instead of re-deriving
        # shake_x separately (draw_weapon callbacks are never passed it).
        target_pos = clone.attack_target_pos + (pos - clone.pos)
        draw_slash_fx(screen, target_pos, clone.attack_dir, t, size=round(95 * BIG_MAHORAGA_SPRITE_SCALE))

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
            # Once Mahoraga is out, it has no clock of its own (see the
            # BIG_MAHORAGA_* comment) — it's still on the field regardless
            # of Sukuna's own current hp, and nothing else can be summoned
            # at all while it's there, not even a fresh one. And unlike
            # every other shadow, it's a once-per-match answer: once it
            # actually dies to damage, _mahoraga_spent latches True for
            # good (see _tick_big_mahoraga) and only the random nine-shadow
            # pool ever opens back up, however low Sukuna's own hp drops
            # again later — see _big_mahoraga/_sukuna_critical/
            # _summon_big_mahoraga.
            if self._big_mahoraga() is not None:
                battle.log = f"{attacker.name}'s Mahoraga still commands the field!"
            elif self._sukuna_critical() and not self._mahoraga_spent:
                self._summon_big_mahoraga()
            else:
                self._summon_shadow()

    def _sukuna_critical(self):
        """Whether Sukuna's own current hp is low enough that Ten Shadows
        can only ever summon Mahoraga (see MAHORAGA_HP_THRESHOLD_PCT)."""
        fighter = self.fighter
        return fighter.max_hp > 0 and fighter.hp / fighter.max_hp <= MAHORAGA_HP_THRESHOLD_PCT

    def _will_summon_big_mahoraga(self):
        """Whether the Ten Shadows cast currently in progress will actually
        call Mahoraga once it resolves — read by draw_fx to gate the
        windup/channel chant (and by freezes_time to gate the time-stop
        that goes with it) so neither plays for a cast that's really just
        going to be a no-op (Mahoraga's already out), a plain random
        shadow (Sukuna isn't critical yet), or a plain random shadow for a
        different reason (Mahoraga already died once this match — see
        _mahoraga_spent)."""
        return self._sukuna_critical() and self._big_mahoraga() is None and not self._mahoraga_spent

    def freezes_time(self):
        """The whole match holds still for exactly as long as Sukuna is
        actually chanting Mahoraga's own incantation (see
        _draw_mahoraga_chant) — windup and channel only; the instant the
        cast moves into "release" (where apply_tag_effects actually
        summons it), this goes False again and everything else resumes.
        See CharacterPlugin.freezes_time's own docstring for what pausing
        actually does."""
        state = self.battle.attacks.get(self.fighter)
        if state is None or state.ability.tag != "ten_shadows":
            return False
        if state.current_phase not in ("windup", "channel"):
            return False
        return self._will_summon_big_mahoraga()

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
        self._init_shadow_move_state(clone)
        if profile["key"] == "tiger_funeral":
            # Status: taunt — lives on the clone, not on Sukuna himself (see
            # status_library.taunt_redirect's own CloneArmy scan).
            set_status(clone, "taunt", TEN_SHADOWS_DURATION_S)
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

    def _init_shadow_move_state(self, clone):
        """Every per-movement-pattern field the _move_* dispatch table might
        read, seeded unconditionally on spawn since it's cheap and each
        shadow's own movement only ever reads the handful of fields its own
        pattern actually uses — shared by _summon_shadow (the random nine)
        and _summon_big_mahoraga (whose own "bounce" reads none of these,
        just clone.vel/pos like the plain bounce_move every real fighter's
        own roam already uses, but this is cheap enough to seed
        unconditionally anyway rather than branch on which shadow it is)."""
        clone.dash_timer = 0.0
        clone.slither_phase = random.uniform(0, math.tau)
        clone.hop_state = "resting"
        clone.hop_timer = random.uniform(*SHADOW_HOP_REST_S)
        guard_dir = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        if guard_dir.length_squared() == 0:
            guard_dir = pygame.Vector2(1, 0)
        clone.guard_offset = guard_dir.normalize() * SHADOW_GUARD_OFFSET
        clone.pierce_state = "charging"
        clone.pierce_timer = 0.0
        clone.split_cd = 0.0

    # ---- Ten Shadows: Mahoraga (see the "Mahoraga rework" constants) --------
    def _big_mahoraga(self):
        """The one living Mahoraga clone, if Sukuna currently has one out —
        None otherwise. There is never more than one at a time (see
        apply_tag_effects' own duplicate guard, checked before
        _summon_big_mahoraga is ever called), so the first match is always
        the only one. Also doubles as "can Ten Shadows summon anything
        else right now" — see apply_tag_effects. _tick_big_mahoraga is the
        one place a None here (once one has actually existed) gets turned
        into the permanent _mahoraga_spent flag."""
        for clone in self.shadow_army.clones:
            if getattr(clone, "shadow_key", None) == "mahoraga":
                return clone
        return None

    def _summon_big_mahoraga(self):
        """Ten Shadows' answer once Sukuna is genuinely hurt (see
        _sukuna_critical) — replaces the whole pack instead of joining it:
        every other living shadow dies the instant Mahoraga is called. Only
        ever reached with no Mahoraga already out and _mahoraga_spent still
        False (see apply_tag_effects' own guard) — never called to
        "refresh" one, since it has no clock to refresh in the first place
        (see the BIG_MAHORAGA_* comment), and never called a second time
        after its first death, since Mahoraga is a once-per-match summon."""
        battle, attacker = self.battle, self.fighter

        # The rest of the pack can't coexist with it — same "destroyed" beat
        # CloneArmy._destroy_clone gives a shadow that runs out of hp.
        for clone in list(self.shadow_army.clones):
            self.shadow_army.clones.remove(clone)
            battle.floaters.append([clone.pos.x, clone.pos.y - 45, -0.6, 220, "Devoured!", GOLD])
            emit_dark(battle.fx, clone.pos, count=14, radius=30)

        clone = self.shadow_army.spawn(
            stat_pct=BIG_MAHORAGA_ATK_PCT, hp_pct=BIG_MAHORAGA_HP_PCT, duration=float("inf"),
            attack_cooldown=BIG_MAHORAGA_ATTACK_COOLDOWN, attack_range=BIG_MAHORAGA_ATTACK_RANGE,
        )
        clone.shadow_key = "mahoraga"
        # Moves exactly like a real fighter's own roam (plain bounce_move,
        # "bounce" in _move_fns) — deliberately no chase/steering/flavor
        # pattern of its own the way every other shadow gets one, on a much
        # bigger, much tankier body, and per BIG_MAHORAGA_MOVE_SPEED above,
        # a faster one too: CloneArmy.spawn already gave `clone` a random
        # heading at its own shared (slow) spawn_speed, so this keeps that
        # heading but rescales it up to Mahoraga's own dedicated speed
        # instead of re-rolling a fresh direction.
        clone.shadow_move = "bounce"
        if clone.vel.length_squared() > 0:
            clone.vel.scale_to_length(BIG_MAHORAGA_MOVE_SPEED)
        else:
            clone.vel = pygame.Vector2(BIG_MAHORAGA_MOVE_SPEED, 0)
        clone.name = f"{attacker.name}'s Mahoraga"
        clone.armor = BIG_MAHORAGA_ARMOR
        self._init_shadow_move_state(clone)
        # Own on-hit "adaptation" bookkeeping (see _tick_big_mahoraga) —
        # last-seen hp to detect a landed hit, and how many stacks it's
        # already grown.
        clone.mahoraga_last_hp = clone.hp
        clone.mahoraga_adapt_stacks = 0
        # Status: taunt — guarantees every eligible attack aimed at Sukuna
        # lands on Mahoraga instead while it's out (see
        # status_library.taunt_redirect), kept alive every tick by
        # _tick_big_mahoraga (which reads clone.time_left — infinite,
        # same as the duration above) rather than left to one fixed number.
        set_status(clone, "taunt", clone.time_left)

        battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "MAHORAGA!", GOLD])
        battle.log = f"{attacker.name} chants the incantation — Mahoraga answers the call!"
        battle.flash_timer = max(battle.flash_timer, 0.3)
        battle.add_ring(attacker.pos, 120, 0.6, GOLD, width=6)
        battle.add_screen_shake(18, 0.3)
        emit_dark(battle.fx, attacker.pos, count=40, radius=80)
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)

    def _tick_big_mahoraga(self, dt):
        """Mahoraga's own passives, ticked every frame it's alive (see
        ambient_tick) — no-op the instant there isn't one out, except for
        the one-time bookkeeping right below that notices it just died.

        "Always cleanses": every hard-CC/DoT/negative-stat debuff
        status_library.CLEANSABLE covers is stripped the instant it lands,
        same generic Cleanse a buff would give a real fighter, just applied
        continuously instead of as a one-shot. "taunt" and "attack_up" are
        both deliberately outside CLEANSABLE, so this never undoes either.

        "Grows stronger when hit": a genuine hp drop since last frame (a
        landed hit, not just existing chip damage) stacks a permanent
        Attack Up on itself, refreshed to always outlast its own remaining
        lifespan and capped at MAHORAGA_ADAPT_MAX_STACKS.

        Sukuna himself is silenced + disarmed the whole time too (see
        MAHORAGA_SUKUNA_LOCK_S) — Mahoraga is the one fighting now, not a
        second body alongside him.

        "No speed decay": every fighter-vs-fighter bump (Mahoraga's own
        collision with Sukuna or the opponent, via extra_colliders) is a
        real equal-mass elastic swap (see entities.resolve_character_
        collision) — the velocity component along the impact normal gets
        traded between the two bodies. At BIG_MAHORAGA_MOVE_SPEED's own
        scale (well past a real fighter's own roam speed), each of those
        trades bleeds off a big chunk of Mahoraga's speed and dumps it onto
        whichever fighter it just bumped, so left alone it would visibly
        run down over the course of a fight. Rescaling clone.vel back up
        to BIG_MAHORAGA_MOVE_SPEED every tick undoes that — same direction
        whatever the last bounce/collision left it facing, just pinned
        back to its own fixed speed instead of drifting toward zero."""
        clone = self._big_mahoraga()
        if clone is None:
            # The clone _mahoraga_alive_last_tick was tracking (dead now,
            # to a landed hit rather than any timer — see the
            # BIG_MAHORAGA_* comment) just vanished from shadow_army.clones
            # since the last time this ran — latch _mahoraga_spent True for
            # good, right here, the one and only place Mahoraga's death is
            # ever actually noticed (apply_tag_effects/_sukuna_critical's
            # own callers just read the flag afterward).
            if self._mahoraga_alive_last_tick:
                self._mahoraga_alive_last_tick = False
                self._mahoraga_spent = True
            return
        self._mahoraga_alive_last_tick = True
        if clone.vel.length_squared() > 0:
            clone.vel.scale_to_length(BIG_MAHORAGA_MOVE_SPEED)
        cleanse(clone)
        set_status(clone, "taunt", clone.time_left)
        set_status(self.fighter, "silenced", MAHORAGA_SUKUNA_LOCK_S)
        set_status(self.fighter, "disarmed", MAHORAGA_SUKUNA_LOCK_S)
        last_hp = getattr(clone, "mahoraga_last_hp", clone.hp)
        if clone.hp < last_hp and clone.mahoraga_adapt_stacks < MAHORAGA_ADAPT_MAX_STACKS:
            clone.mahoraga_adapt_stacks += 1
            set_status(
                clone, "attack_up", clone.time_left,
                pct=clone.mahoraga_adapt_stacks * MAHORAGA_ADAPT_ATK_PCT_PER_HIT,
            )
            self.battle.floaters.append([clone.pos.x, clone.pos.y - 55, -0.5, 210, "Adapts!", GOLD])
        clone.mahoraga_last_hp = clone.hp

    def clone_basic_attack_landed(self, clone, target, actual, crit):
        """Each shadow's own on-hit flavor (see the SHADOWS table's own
        comment for why these don't reuse bleed/corruption) — Round Deer
        never reaches here at all (its attack_cd is pinned at infinity),
        Tiger Funeral's own payoff already happened on summon, and Rabbit's
        whole gimmick lives in its own movement instead (_move_bounce_split),
        so none of those three needs a branch here. Mahoraga's own on-hit
        attack_down below fires on every landed swing, on top of its own
        separate on-being-hit adaptation (see _tick_big_mahoraga)."""
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
        self._tick_big_mahoraga(dt)

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

    def _move_bounce_split(self, clone, dt, speed_mult):
        """Rabbit Escape: a plain DVD-logo bounce (same reflect physics
        bounce_move gives every real fighter), except every actual wall
        bounce also tries to split (see _maybe_split_rabbit) —
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
            bounced = True
        elif clone.pos.x > BOUND_RIGHT:
            clone.pos.x = BOUND_RIGHT
            clone.vel.x *= -1
            bounced = True
        if clone.pos.y < BOUND_TOP:
            clone.pos.y = BOUND_TOP
            clone.vel.y *= -1
            bounced = True
        elif clone.pos.y > BOUND_BOTTOM:
            clone.pos.y = BOUND_BOTTOM
            clone.vel.y *= -1
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
        (a small shake/puff, so hitting the wall reads as real mass
        colliding with something, not a quiet teleport) for
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
        hit_wall = False
        if clone.pos.x < BOUND_LEFT:
            clone.pos.x = BOUND_LEFT
            hit_wall = True
        elif clone.pos.x > BOUND_RIGHT:
            clone.pos.x = BOUND_RIGHT
            hit_wall = True
        if clone.pos.y < BOUND_TOP:
            clone.pos.y = BOUND_TOP
            hit_wall = True
        elif clone.pos.y > BOUND_BOTTOM:
            clone.pos.y = BOUND_BOTTOM
            hit_wall = True
        if hit_wall:
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

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_dark(self.battle.fx, pos, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos and battle.ability.name == "Kamino"):
            return False
        img = _kamino_sprite(KAMINO_SPRITE_SIZE)
        direction = battle.atk_dir
        if direction.length_squared() != 0:
            default_angle = math.degrees(math.atan2(-_KAMINO_FX_DEFAULT_DIR.y, _KAMINO_FX_DEFAULT_DIR.x))
            angle = 180 + math.degrees(math.atan2(-direction.y, direction.x)) - default_angle
            img = pygame.transform.rotate(img, angle)
        pos = battle.projectile_pos
        screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))
        return True

    def draw_fx(self, screen, shake_x):
        """Hachi and Kai land as bare-handed curse-slashes with no travel
        time (a single cut for Hachi, a fanned-out flurry of 3-5 for Kai),
        Kamino is the exception — a fireball gathers in Sukuna's palm
        (windup), the painted kamino.png fireball flies across the arena
        (draw_projectile above), then it explodes into a burst of
        curse-slashes on impact —
        and Ten Shadows summons a shadow that lingers on screen long
        after the cast itself ends, so its own draw (shadow_army.draw) runs
        unconditionally below, unlike every other branch here which only
        ever draws while Sukuna is mid-attack."""
        battle, s = self.battle, self.fighter
        self.shadow_army.draw(
            screen, shake_x, sprite_alpha=225, ring_color=SUKUNA_PINK, sprite_for=self._shadow_sprite,
            ring_radius_for=self._ring_radius, draw_weapon=self._draw_mahoraga_slash,
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
            if self._will_summon_big_mahoraga():
                # Mahoraga's own norito, chanted before it answers — first
                # line through windup, second through channel, so together
                # they read as one continuous incantation rather than a
                # single static caption (see _draw_mahoraga_chant).
                self._draw_mahoraga_chant(screen, origin, phase, t)

        elif name == "Ten Shadows" and phase == "release":
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            if self._will_summon_big_mahoraga():
                draw_starburst(screen, origin, GOLD, size=60, fade=1 - t)
                draw_expanding_ring(screen, origin, 120 * t, GOLD, width=6)
            else:
                draw_starburst(screen, origin, SUKUNA_PINK, size=40, fade=1 - t)
                draw_expanding_ring(screen, origin, 90 * t, SUKUNA_PINK, width=5)

    def _draw_mahoraga_chant(self, screen, origin, phase, t):
        """windup speaks MAHORAGA_CHANT_LINE_1, channel speaks
        MAHORAGA_CHANT_LINE_2 — each fades in and back out across its own
        phase's own t (0 -> 1 -> 0) instead of just popping in and cutting
        off, so it reads as spoken rather than stamped on screen."""
        line = MAHORAGA_CHANT_LINE_1 if phase == "windup" else MAHORAGA_CHANT_LINE_2
        alpha = round(255 * math.sin(min(1.0, max(0.0, t)) * math.pi))
        if alpha <= 0:
            return
        surf = _chant_font(22).render(line, True, GOLD)
        surf.set_alpha(alpha)
        pos = origin + pygame.Vector2(0, -74)
        screen.blit(surf, surf.get_rect(center=(round(pos.x), round(pos.y))))
