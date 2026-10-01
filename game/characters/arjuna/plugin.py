"""Arjuna plugin: the Savyasachi passive (Gandiva fires as a genuine
two-arrow release, on top of Gandiva/Aindrastra/Sammohana all carrying
moves_while_active — see moves.py's own docstring for why both are the same
epithet's payoff), Aindrastra's homing stun, Sammohana's homing sleep +
Vulnerability, Devadatta's fear + Attack Down blast, the Pashupatastra
ultimate's rain of arrows + stun, and the bow-draw/release animation.

Every ability name is pulled straight from the Sanskrit Mahabharata, not the
Javanese wayang retelling:
  - Savyasachi: Arjuna's own epithet ("ambidextrous"), earned during the
    Khandava Vana battle (Adi Parva).
  - Gandiva: his own bow, Agni's gift from that same battle.
  - Aindrastra: Indra's own weapon, taught to Arjuna during his stay in
    Amaravati (Indralokabhigamana Parva).
  - Sammohana: the illusion-astra Chitrasena the Gandharva taught him,
    used in the Virata Parva cattle raid.
  - Devadatta: his own conch, also a gift from Indra.
  - Pashupatastra: Shiva's own absolute weapon, earned through Arjuna's
    penance in the Kirātārjunīya episode (Vana Parva).

Presentation-wise, every bow/arrow visual below is oriented off
battle.atk_dir (recomputed fresh, attacker -> defender, at the start of
every cast — see combat_resolution.try_start_attack) rather than any fixed
left/right assumption, so the bow always points at whichever side of the
arena the opponent actually happens to be standing on, same convention every
other weapon prop in this game (mace, lance, scepter, ...) already follows.
The bow itself is drawn 90 degrees off that facing (weapon_angle's own
`extra_deg`) instead of pointing straight down atk_dir like a lance/mace
would — a real bow held to shoot is perpendicular to its own arrow's flight,
not aimed like a spear — while the arrow (nocked, and in flight) still
points straight along atk_dir like any other projectile in this game.

Animation rework: every cast now reads as its own distinct shape instead of
a recolored arrow each time. bow.png has no string drawn into the art
itself, so up to now "the draw" only ever read through the arrow sliding
back (see the old _draw_bow) — _draw_bowstring below adds a real bent
string that bends to meet the nock, tips anchored perpendicular to atk_dir
(the same axis the bow itself is drawn along, see weapon_angle's own
extra_deg=90 above). Gandiva nocks and looses two arrows side by side
(Savyasachi's own double-release, finally drawn instead of just computed —
see resolve_special). Aindrastra's shot crackles with a small lightning
arc trailing it (Indra's own weapon), Sammohana's trails a fading illusory
afterimage instead of a flat tint (an illusion-astra should visibly not be
one solid arrow). Devadatta trades the reused arrow prop for an actual
staggered shockwave front marching from Arjuna to the target (a conch
blast is sound, not a projectile). Pashupatastra is staged as a divine
descent rather than a volley of plain arrows: the heavens open in a mandala
above the target, Shiva's third eye splits open and one giant radiant arrow
drops out of it onto a burning ground sigil, ending in a pillar of light
(see _draw_pashupatastra and the PASHU_* constants)."""

import math
import random

import pygame

from ...core.anime_fx import draw_glow_texture
from ...core.constants import ARENA_RECT, ARJUNA_ASTRA, AVATAR_R, INDRA_SPARK, WHITE
from ...core.effects import draw_expanding_ring, draw_rotated, draw_starburst, tint_flash, weapon_angle
from ...core.entities import set_status
from ...core.glow import glow_line, glow_polyline
from ...core.motions import MOTIONS, ease_in, ease_out
from ...core.particles import emit_holy, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .weapons import load_arjuna_weapons

# Savyasachi (passive): Arjuna's own epithet — "able to draw and loose with
# either hand at once" — so every Gandiva shot fires as a genuine multi-arrow
# (GANDIVA_ARROW_COUNT) release instead of one (see resolve_special below), on top of the
# moves_while_active freedom already wired into moves.py.
GANDIVA_ARROW_COUNT = 3

# Savyasachi's other half: every landed hit (basic, skill, or ultimate)
# stacks a matching Attack Speed Up on Arjuna himself, same shape as Raiju's
# own Overcharge (see RaijuPlugin.on_damage_dealt) — the stack count is
# stored right on the attack_speed_up status dict rather than a separate
# field, capped at SAVYASACHI_MAX_STACKS, and lapses back to nothing on its
# own if he goes SAVYASACHI_STACK_DURATION_S without landing another hit —
# this is where his sustained damage is actually supposed to come from
# (see core/assets.py's own low-hp/armor tradeoff note), not a stacking
# passive that only ever lived in that comment.
SAVYASACHI_ATK_SPEED_PER_STACK = 0.15
SAVYASACHI_MAX_STACKS = 5
SAVYASACHI_STACK_DURATION_S = 6

AINDRASTRA_STUN_S = 1

SAMMOHANA_SLEEP_S = 2
# The Virata Parva version of this astra didn't just make its targets
# drowsy, it left a whole company defenseless at once — Vulnerability for
# the same window means a follow-up hit actually punishes that helplessness
# instead of the sleep being the entire payoff.
SAMMOHANA_VULN_PCT = 0.3

DEVADATTA_FEAR_S = 1
# The epic frames a conch blast as breaking the enemy's will to fight
# outright, not just startling them — a real Attack Down alongside Fear.
DEVADATTA_ATKDOWN_PCT = 0.25

# The text calls Pashupatastra capable of destroying the three worlds — a
# weapon like that should cripple whatever it doesn't outright kill.
PASHUPATASTRA_STUN_S = 1.5

# Motions whose in-flight shot is an actual arrow (see draw_projectile) and
# whose windup is Arjuna visibly drawing the bowstring back (see _draw_bow) —
# Devadatta ("cast") and Pashupatastra ("sky_strike") get their own bespoke
# presentation in draw_fx instead.
BOW_ARROW_MOTIONS = ("bolt", "homing_bolt")

# The bow's fixed resting pose while idle — every other idle weapon prop in
# this game (Chaos Knight's mace, Phantom Lancer's lance, Legion Commander's
# scepter, ...) also rests at one fixed angle/offset rather than continuously
# tracking the opponent, so this stays consistent with that convention; only
# an active shot ever orients off the live battle.atk_dir.
IDLE_ANGLE = 160
IDLE_OFFSET = pygame.Vector2(-6, 16)

# ---- animation rework: per-ability visual identity -------------------------
# A physical bowstring the source art doesn't have (see the module docstring
# above) — anchored BOW_LIMB_HALF_SPAN each side of Arjuna along the bow's
# span axis (perpendicular to atk_dir, same axis weapon_angle(direction, 90)
# already rotates the bow prop onto). bow.png's own opaque art nearly fills
# its whole BOW_TARGET_H canvas (measured directly off the loaded sprite —
# same approach upright() in core/asset_loading.py uses), but a
# string spanning that entire height reads as a pole speared through Arjuna
# rather than a string strung across the bow he's actually holding — a real
# strung bow's string sits well inside the limb tips' own outer curve, not
# at their very ends, so this stays a fraction of that full span instead.
BOWSTRING_COLOR = (214, 186, 130)
BOW_LIMB_HALF_SPAN = AVATAR_R * 0.9

# Savyasachi drawn, not just computed: the two arrows Gandiva actually
# looses (see resolve_special) now both show, nocked and in flight, offset
# this many px either side of the bow's own span axis / the flight line.
GANDIVA_ARROW_GAP = 9
# GANDIVA_ARROW_COUNT arrows spaced GANDIVA_ARROW_GAP apart, centered on 0.
GANDIVA_ARROW_OFFSETS = tuple(
    (i - (GANDIVA_ARROW_COUNT - 1) / 2) * GANDIVA_ARROW_GAP for i in range(GANDIVA_ARROW_COUNT)
)

# Aindrastra: a couple of small crackling arcs trailing the arrowhead —
# Indra's own weapon, charged, not just a tinted shaft.
AINDRASTRA_ARC_COUNT = 3

# Sammohana: single shared color for the illusion-astra's tint/ring/floater/
# impact spark, and the fading afterimage duplicates trailing its arrow.
SAMMOHANA_VIOLET = (194, 154, 232)
SAMMOHANA_MIRAGE_COUNT = 2
SAMMOHANA_MIRAGE_GAP = 16

# Devadatta: a conch blast is sound, not a projectile — DEVADATTA_WAVE_RINGS
# staggered shockwave rings (DEVADATTA_WAVE_STAGGER apart) marching from
# Arjuna to the target instead of the old reused arrow-prop "channel" shot.
DEVADATTA_WAVE_RINGS = 3
DEVADATTA_WAVE_STAGGER = 0.22

# Pashupatastra: Shiva's own weapon, presented as a divine descent rather
# than a volley of ordinary arrows (see draw_fx / _draw_pashupatastra):
#   windup  — the arena dims, Arjuna blazes with a golden wheel under him and
#             fires a beam of light straight up into the heavens; a sacred
#             sigil starts burning into the ground under the target.
#   channel — a mandala opens in the sky above the target with Shiva's third
#             eye splitting open at its heart; one giant radiant arrow drops
#             out of the eye onto the target, trailing a column of light,
#             while thin arrows of pure light rain down around it.
#   impact  — a pillar of light from sky to ground, a blinding flare, rays and
#             a shockwave, the sky mandala collapsing.
#   settle  — the pillar thins away and golden embers drift up.
# Textures are Kenney Particle Pack (CC0, assets/fx/kenney) via
# anime_fx.draw_glow_texture.
PASHU_GOLD = (255, 214, 120)
PASHU_WHITE = (255, 250, 235)
# Shiva is Neelakantha, the blue-throated — a cool accent under the gold.
PASHU_AZURE = (120, 170, 255)
# Max dark wash over the arena while the heavens open (alpha 0-255).
PASHU_DIM_ALPHA = 120
# The sky eye sits at least this far above the target, and is never placed
# lower than PASHU_SKY_MIN_Y on screen (so a target near the top wall still
# gets a visible descent, from above the arena border).
PASHU_SKY_RISE = 150
PASHU_SKY_MIN_Y = 40
PASHU_MANDALA_SIZE = 170
PASHU_SIGIL_SIZE = 130
# The giant arrow: the shared arrow prop scaled by this, tinted toward gold.
PASHU_ARROW_SCALE = 1.5
# Share of "channel" spent with the eye open before the arrow leaves it.
PASHU_ARROW_LAUNCH = 0.3
# Light-arrows raining around the main one: count, ring radius, streak size.
PASHU_RAIN_COUNT = 12
PASHU_RAIN_RADIUS = 70
PASHU_RAIN_STREAK = 90
PASHU_EMBER_COUNT = 14

# Aindrastra/Sammohana light trail: the last HOMING_TRAIL_LEN drawn positions
# of the homing arrow, kept by draw_projectile and redrawn as a tapering
# streak (HOMING_TRAIL_WIDTH px at the arrow down to 1 at the tail). Stored
# per frame rather than recomputed off a straight line, so the streak bends
# with the shot's own mid-flight course corrections.
HOMING_TRAIL_LEN = 14
HOMING_TRAIL_WIDTH = 6


_DIVINE_ARROW_CACHE = {}


def _divine_arrow_image(arrow_img):
    """Pashupatastra's giant arrow: the shared arrow prop scaled up by
    PASHU_ARROW_SCALE and flashed toward gold so it reads as light, not
    wood — cached by the source image's id since battle.weapons["arrow"] is
    the same instance for the whole match."""
    cached = _DIVINE_ARROW_CACHE.get(id(arrow_img))
    if cached is None:
        w, h = arrow_img.get_size()
        big = pygame.transform.smoothscale(
            arrow_img, (max(1, round(w * PASHU_ARROW_SCALE)), max(1, round(h * PASHU_ARROW_SCALE))))
        cached = tint_flash(big, PASHU_GOLD, 90)
        _DIVINE_ARROW_CACHE[id(arrow_img)] = cached
    return cached


def _perp(direction):
    """Unit perpendicular of `direction` (or a fixed fallback for a
    zero-length one) — the shared axis every twin-arrow/afterimage offset
    below is measured along."""
    if direction.length_squared() == 0:
        return pygame.Vector2(0, 1)
    d = direction.normalize()
    return pygame.Vector2(-d.y, d.x)


class ArjunaPlugin(CharacterPlugin):
    #: Hit-flash flare (anime_fx.build_impact_burst_frames): a radiant divine flare.
    BURST_TEXTURE = "star_09"

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        # Recent in-flight positions of the current homing arrow (see
        # HOMING_TRAIL_LEN), appended by draw_projectile and cleared by
        # draw_fx whenever no "chase" is in progress, so a new shot never
        # inherits the previous one's streak.
        self._arrow_trail = []

    def weapons(self):
        return load_arjuna_weapons()

    # ---- passive: Savyasachi — Gandiva fires twice -------------------------
    def resolve_special(self):
        """Every Gandiva shot looses two arrows at once instead of one — the
        literal payoff of Arjuna's own epithet (Savyasachi, "ambidextrous"):
        one hand alone never fires this bow. Modeled on Sukuna's own Kai
        (see SukunaPlugin.resolve_special) — a multi-hit ability resolves its
        own damage directly through battle.deal_damage() rather than the
        normal single-hit do_damage() pipeline, so (like Kai) this
        deliberately skips status_outgoing_multiplier/outgoing_damage for
        each individual arrow; the two-arrow burst itself is Savyasachi's
        whole bonus, not a target for further stacking.

        Gandiva Shot sets ignore_clone=True purely so a stray, unrelated
        illusion never fools a "genuine homing shot" (see moves.py's own
        comment) — that was never meant to also make it immune to an
        actively taunting decoy (Sukuna's Mahoraga, Vampire's own Crimson
        Doppelganger), which status_library.taunt_redirect already
        guarantees overrides ignore_clone for the normal do_damage()
        pipeline. Bypassing that pipeline entirely (see the class docstring
        above) accidentally bypassed the taunt guarantee right along with
        it, so both arrows explicitly check battle.resolve_redirected_hit()
        first and land on the decoy instead whenever one is forced."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "gandiva_shot"):
            return False
        attacker, defender, ability = battle.attacker, battle.defender, battle.ability
        if defender is None:
            return False

        if battle.redirect_target is not None:
            hits = sum(1 for _ in range(GANDIVA_ARROW_COUNT) if battle.resolve_redirected_hit())
            battle.damage_applied = True
            if hits:
                battle.log = f"{attacker.name}'s twin-handed Gandiva tears into {battle.redirect_target.name}!"
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            return True

        total = 0
        for _ in range(GANDIVA_ARROW_COUNT):
            dmg = round(attacker.atk * ability.dmg_mult)
            actual = battle.deal_damage(attacker, defender, dmg)
            total += actual
        battle.damage_applied = True

        defender.shake = 14
        battle.apply_impact(defender, ability)
        battle.floaters.append(
            [defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{total} x{GANDIVA_ARROW_COUNT}", ARJUNA_ASTRA]
        )
        battle.log = f"{attacker.name}'s twin-handed Gandiva strikes {defender.name} twice for {total}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def on_damage_dealt(self, attacker, defender, actual):
        """Savyasachi's stacking half: every landed hit builds one more
        stack of Attack Speed Up on Arjuna, refreshing its own duration —
        capped, and left to lapse on its own the moment he stops connecting
        for SAVYASACHI_STACK_DURATION_S, same self-reinforcing shape as
        Raiju's Overcharge."""
        if attacker is not self.fighter or actual <= 0:
            return
        cur = attacker.statuses.get("attack_speed_up", {})
        stacks = min(SAVYASACHI_MAX_STACKS, cur.get("stacks", 0) + 1)
        set_status(
            attacker, "attack_speed_up", SAVYASACHI_STACK_DURATION_S,
            pct=stacks * SAVYASACHI_ATK_SPEED_PER_STACK, stacks=stacks,
        )

    # ---- tag effects --------------------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "aindrastra" and defender is not None and battle.damage_applied:
            set_status(defender, "stunned", AINDRASTRA_STUN_S)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Stunned!", INDRA_SPARK])
            battle.log = f"{attacker.name}'s Aindrastra strikes {defender.name} with Indra's own thunderbolt!"
            battle.add_ring(defender.pos, 70, 0.35, INDRA_SPARK, width=4)
            emit_spark_burst(battle.fx, defender.pos, INDRA_SPARK, count=20)
        elif tag == "sammohana" and defender is not None and battle.damage_applied:
            set_status(defender, "asleep", SAMMOHANA_SLEEP_S)
            # Status: vulnerability — the same defenselessness the Virata
            # Parva version of this astra left an entire company in.
            set_status(defender, "vulnerability", SAMMOHANA_SLEEP_S, pct=SAMMOHANA_VULN_PCT)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Asleep!", SAMMOHANA_VIOLET])
            battle.log = f"{attacker.name}'s Sammohana lulls {defender.name} into a defenseless sleep!"
            battle.add_ring(defender.pos, 60, 0.4, SAMMOHANA_VIOLET, width=3)
        elif tag == "devadatta" and defender is not None:
            # No damage of its own (dmg_mult 0.0), so do_damage() never runs
            # for this cast at all — same reason Static Field/Doppelganger
            # don't gate on battle.damage_applied either (see
            # RaijuPlugin/PhantomLancerPlugin's own versions).
            set_status(defender, "feared", DEVADATTA_FEAR_S)
            # Status: attack_down — the epic's own framing of a conch blast
            # as shattering enemy morale, not just a startling noise.
            set_status(defender, "attack_down", DEVADATTA_FEAR_S, pct=DEVADATTA_ATKDOWN_PCT)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Feared!", ARJUNA_ASTRA])
            battle.log = f"{attacker.name} sounds the conch Devadatta — {defender.name}'s resolve breaks!"
            battle.flash_timer = max(battle.flash_timer, 0.3)
            battle.add_ring(attacker.pos, 60, 0.3, ARJUNA_ASTRA, width=3)
            # A second ring right where it actually lands — the blast
            # travels there visibly too (see draw_fx's "channel" phase), so
            # this confirms the payoff on the target instead of only ever
            # showing something happening back at Arjuna.
            battle.add_ring(defender.pos, 90, 0.4, ARJUNA_ASTRA, width=4)
            emit_spark_burst(battle.fx, defender.pos, ARJUNA_ASTRA, count=14)
        elif tag == "pashupatastra":
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "PASHUPATASTRA!", ARJUNA_ASTRA])
            battle.log = f"{attacker.name} calls down Pashupatastra — Shiva's absolute weapon!"
            battle.flash_timer = max(battle.flash_timer, 0.5)
            battle.add_screen_shake(24, 0.32)
            if defender is not None:
                # Status: stunned — even what it doesn't outright kill, a
                # weapon capable of destroying the three worlds should cripple.
                set_status(defender, "stunned", PASHUPATASTRA_STUN_S)
                battle.add_ring(defender.pos, 190, 0.6, WHITE, width=6)
                battle.add_ring(defender.pos, 150, 0.75, ARJUNA_ASTRA, width=5)
                emit_holy(battle.fx, defender.pos, count=46, radius=90, color=ARJUNA_ASTRA)

    # ---- presentation ---------------------------------------------------------
    def impact_particles(self, pos, count):
        """A ranged fighter's own hit effect: the usual colored spark burst,
        plus a quick expanding ring flash marking the exact point an arrow
        actually struck — every Arjuna attack travels before it lands
        (Gandiva has no melee_range at all, see moves.py), so the impact
        itself needs its own visible "punch" the way a melee swing's own
        cut mark already gets, not just a burst of sparks."""
        name = self.battle.ability.name
        color = INDRA_SPARK if name == "Aindrastra" else SAMMOHANA_VIOLET if name == "Sammohana" else ARJUNA_ASTRA
        emit_spark_burst(self.battle.fx, pos, color, count=count)
        self.battle.add_ring(pos, 24, 0.2, color, width=2)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos):
            return False
        name = battle.ability.name
        if name not in ("Gandiva", "Aindrastra", "Sammohana"):
            return False
        arrow_img = battle.weapons["arrow"]
        pos = battle.projectile_pos
        # Gandiva's own moves_while_active means Arjuna keeps roaming through
        # windup, so by the time "fire" actually starts he's drifted away
        # from battle.attacker_start (captured back at the start of the
        # whole cast) — battle_loop.py's own "bolt" handling already tracks
        # the shot's real launch point separately as projectile_origin
        # (captured fresh right as "fire" begins) for exactly this reason.
        # Using attacker_start here instead made the arrow's rotation drift
        # off the line it was actually flying by however far Arjuna had
        # roamed during windup — sometimes negligible, sometimes a visible
        # tilt, depending on which way he happened to be bouncing that cast.
        # Aindrastra/Sammohana ("homing_bolt") never set projectile_origin at
        # all (that motion always pins the attacker to attacker_start, see
        # apply_motion_frame), so this falls back to the old, still-correct
        # behavior for them.
        origin = battle.projectile_origin if battle.projectile_origin is not None else battle.attacker_start
        direction = pos - origin
        angle = weapon_angle(direction, 0)

        if name == "Gandiva":
            # Savyasachi drawn, not just computed: every arrow the
            # GANDIVA_ARROW_COUNT-hit resolve_special actually fires, side by side.
            perp = _perp(direction)
            for off in GANDIVA_ARROW_OFFSETS:
                draw_rotated(screen, arrow_img, pos + perp * off, angle)
        elif name == "Aindrastra":
            tinted = tint_flash(arrow_img, INDRA_SPARK, 150)
            self._draw_light_trail(screen, pos, INDRA_SPARK)
            self._draw_charged_crackle(screen, pos, direction)
            draw_rotated(screen, tinted, pos, angle)
        elif name == "Sammohana":
            tinted = tint_flash(arrow_img, SAMMOHANA_VIOLET, 150)
            self._draw_light_trail(screen, pos, SAMMOHANA_VIOLET)
            self._draw_illusion_trail(screen, tinted, pos, direction, angle)
        return True

    def _draw_light_trail(self, screen, pos, color):
        """A glowing streak left behind the homing arrow (Aindrastra/
        Sammohana): records this frame's position, then draws the recorded
        path oldest to newest, each segment wider and brighter than the
        last (faded toward black the same way particles.py fades, since the
        scene is drawn opaque), with a thin white core along the newer half
        so the head of the streak reads as hot light rather than paint."""
        trail = self._arrow_trail
        if not trail or (trail[-1] - pos).length_squared() > 0.25:
            trail.append(pygame.Vector2(pos))
            if len(trail) > HOMING_TRAIL_LEN:
                trail.pop(0)
        n = len(trail)
        if n < 2:
            return
        # a glowing streak that thickens and brightens toward the arrowhead
        chunks = 4
        for k in range(chunks):
            lo, hi = (n - 1) * k // chunks, (n - 1) * (k + 1) // chunks + 1
            if hi - lo < 2:
                continue
            ratio = (k + 1) / chunks
            glow_polyline(screen, trail[lo:hi], color, width=max(1, round(HOMING_TRAIL_WIDTH * 0.6 * ratio)),
                          intensity=0.3 + 0.7 * ratio)

    def _draw_charged_crackle(self, screen, pos, direction):
        """A couple of small lightning arcs jumping off the shaft, trailing
        behind the arrowhead — Aindrastra is Indra's own weapon, so it reads
        as charged, not just a recolored Gandiva shot."""
        d = direction.normalize() if direction.length_squared() > 0 else pygame.Vector2(1, 0)
        perp = pygame.Vector2(-d.y, d.x)
        for _ in range(AINDRASTRA_ARC_COUNT):
            back = pos - d * random.uniform(6, 26)
            spark = back + perp * random.uniform(-9, 9)
            kink = back.lerp(spark, 0.5) + d * random.uniform(-4, 4)
            glow_polyline(screen, [back, kink, spark], INDRA_SPARK, width=1)

    def _draw_illusion_trail(self, screen, arrow_img, pos, direction, angle):
        """Sammohana is an illusion-astra — its arrow trails fading duplicate
        afterimages behind it instead of flying as one solid shaft, so it
        reads as a mirage even before it puts anything to sleep."""
        d = direction.normalize() if direction.length_squared() > 0 else pygame.Vector2(1, 0)
        for i in range(SAMMOHANA_MIRAGE_COUNT, 0, -1):
            ghost_pos = pos - d * (SAMMOHANA_MIRAGE_GAP * i)
            draw_rotated(screen, arrow_img, ghost_pos, angle, alpha=max(40, 150 - i * 55))
        draw_rotated(screen, arrow_img, pos, angle)

    def draw_fx(self, screen, shake_x):
        battle, aj = self.battle, self.fighter
        self._draw_bow(screen, shake_x)
        if not (battle.mode == "attack" and battle.attacker is aj):
            self._arrow_trail.clear()
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t
        if phase != "chase":
            self._arrow_trail.clear()
        if name == "Devadatta" and phase == "windup":
            # A short charge-up right at Arjuna before the blast leaves him.
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, origin, 16 + 24 * t, ARJUNA_ASTRA, width=3)
        elif name == "Devadatta" and phase == "channel":
            # A conch blast is a sound wave, not a projectile — this used to
            # reuse the arrow prop flying point-to-point, which mixed the
            # bow's own signature into an ability that draws no bow at all.
            # DEVADATTA_WAVE_RINGS staggered rings marching from Arjuna to
            # wherever the defender actually is instead: still visibly
            # crosses the whole distance (the guaranteed hit stays obvious,
            # not implied — see apply_tag_effects), but now reads as an
            # actual shockwave front.
            start = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            end = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            span = 1 - DEVADATTA_WAVE_STAGGER * (DEVADATTA_WAVE_RINGS - 1)
            for i in range(DEVADATTA_WAVE_RINGS):
                local_t = t - i * DEVADATTA_WAVE_STAGGER
                if local_t <= 0:
                    continue
                local_t = min(1.0, local_t / span)
                center = start.lerp(end, local_t)
                draw_expanding_ring(screen, center, 14 + 26 * local_t, ARJUNA_ASTRA, width=3)
        elif name == "Devadatta" and phase == "release":
            # The impact itself — lands right as apply_tag_effects fires
            # (RESOLVE_PHASE["cast"] == "release"), so this burst and the
            # "Feared!" floater/status both land on the same beat.
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            draw_starburst(screen, center, ARJUNA_ASTRA, size=34, fade=1 - t)
            draw_expanding_ring(screen, center, 70 * t, ARJUNA_ASTRA, width=4)
        elif name == "Pashupatastra":
            self._draw_pashupatastra(screen, shake_x, phase, t)

    def _draw_pashupatastra(self, screen, shake_x, phase, t):
        """Shiva's own weapon called down as a divine descent (see the
        PASHU_* constants for the beat-by-beat breakdown). Everything lands
        on battle.defender_start — the same point RESOLVE_PHASE's "impact"
        resolves the hit on — so the sigil marks exactly where the payoff
        arrives."""
        battle = self.battle
        shake = pygame.Vector2(shake_x, 0)
        target = pygame.Vector2(battle.defender_start) + shake
        caster = pygame.Vector2(self.fighter.pos) + shake
        sky = pygame.Vector2(target.x, max(PASHU_SKY_MIN_Y, min(target.y - PASHU_SKY_RISE, ARENA_RECT.top + 30)))
        windup_s = MOTIONS["sky_strike"][0][1]
        channel_s = MOTIONS["sky_strike"][1][1]
        # One continuous 0..1 across windup+channel so spins never snap.
        if phase == "windup":
            build = t * windup_s / (windup_s + channel_s)
        elif phase == "channel":
            build = (windup_s + t * channel_s) / (windup_s + channel_s)
        else:
            build = 1.0

        dim = {"windup": ease_out(t), "channel": 1.0, "impact": 1 - t}.get(phase, 0.0)
        self._draw_pashu_dim(screen, dim)

        if phase == "windup":
            e = ease_out(t)
            # Arjuna blazes and calls up to the heavens.
            draw_glow_texture(screen, "magic_03", caster, 70 + 30 * e, PASHU_GOLD, fade=e, angle=build * 300)
            draw_glow_texture(screen, "light_01", caster, 50 + 70 * e, PASHU_GOLD, fade=0.8 * e)
            top = caster.lerp(pygame.Vector2(caster.x, 0), e)
            glow_line(screen, caster, top, PASHU_GOLD, width=5)
            glow_line(screen, caster, top, PASHU_WHITE, width=2)
            self._draw_pashu_sigil(screen, target, e * 0.7, build)
            self._draw_pashu_mandala(screen, sky, 0.45 + 0.25 * e, 0.6 * e, build)

        elif phase == "channel":
            # The calling beam thins out as the sky answers.
            glow_line(screen, caster, pygame.Vector2(caster.x, 0), PASHU_GOLD, width=max(1, round(5 * (1 - t))),
                      intensity=1 - t)
            draw_glow_texture(screen, "light_01", caster, 110, PASHU_GOLD, fade=0.8 * (1 - t))
            self._draw_pashu_sigil(screen, target, 0.7 + 0.3 * t, build)
            self._draw_pashu_mandala(screen, sky, 0.7 + 0.3 * ease_out(t), 1.0, build)
            # Shiva's third eye splitting open at the mandala's heart.
            open_k = ease_out(min(1.0, t / PASHU_ARROW_LAUNCH))
            draw_glow_texture(screen, "light_01", sky, 120, PASHU_WHITE, fade=open_k, stretch=(0.1 + 0.3 * open_k, 1.0))
            draw_glow_texture(screen, "flare_01", sky, 150, PASHU_GOLD, fade=0.55 * open_k)
            self._draw_pashu_rain(screen, target, sky, t)
            if t > PASHU_ARROW_LAUNCH:
                k = ease_in((t - PASHU_ARROW_LAUNCH) / (1 - PASHU_ARROW_LAUNCH))
                self._draw_pashu_arrow(screen, sky, sky.lerp(target, k))

        elif phase == "impact":
            # Pillar of light from the heavens to the ground.
            glow_line(screen, sky, target, PASHU_GOLD, width=round(6 + 22 * (1 - t)), intensity=1 - 0.5 * t)
            glow_line(screen, sky, target, PASHU_WHITE, width=round(2 + 7 * (1 - t)), intensity=1 - t)
            self._draw_pashu_mandala(screen, sky, 1.0 - 0.8 * ease_in(t), 1 - t, build + t * 0.8)
            self._draw_pashu_sigil(screen, target, 1 - t, build + t)
            e = ease_out(t)
            draw_glow_texture(screen, "light_03", target, 80 + 300 * e, PASHU_GOLD, fade=1 - t)
            draw_glow_texture(screen, "circle_03", target, 60 + 260 * e, PASHU_AZURE, fade=0.8 * (1 - t))
            draw_glow_texture(screen, "star_09", target, 230 - 60 * t, PASHU_GOLD, fade=1 - t, angle=t * 45)
            draw_glow_texture(screen, "flare_01", target, 320, PASHU_WHITE, fade=(1 - t) ** 2)
            for i in range(12):
                d = pygame.Vector2(1, 0).rotate(i * 30 + 15)
                inner = 26 + 40 * e
                glow_line(screen, target + d * inner, target + d * (inner + 50 + 110 * e), PASHU_GOLD,
                          width=3 if i % 2 else 2, intensity=1 - t)

        elif phase == "settle":
            glow_line(screen, sky, target, PASHU_GOLD, width=max(1, round(5 * (1 - t))), intensity=0.6 * (1 - t))
            self._draw_pashu_sigil(screen, target, 0.4 * (1 - t), 2.0 + t)
            for i in range(PASHU_EMBER_COUNT):
                # Seeded per index, so embers scatter but don't re-roll per frame.
                rng = random.Random(i * 7919 + 17)
                dx = rng.uniform(-65, 65)
                rise = rng.uniform(40, 120)
                p = target + pygame.Vector2(dx + math.sin(t * 6 + i) * 6, -rise * (0.3 + t))
                draw_glow_texture(screen, "star_04", p, 18, PASHU_GOLD if i % 3 else PASHU_AZURE, fade=1 - t)

    def _draw_pashu_dim(self, screen, strength):
        """A dark wash over the arena while the heavens open, so the light
        effects drawn after it read as the brightest thing on screen."""
        alpha = int(PASHU_DIM_ALPHA * strength)
        if alpha <= 0:
            return
        overlay = pygame.Surface(ARENA_RECT.size, pygame.SRCALPHA)
        overlay.fill((4, 2, 12, alpha))
        screen.blit(overlay, ARENA_RECT.topleft)

    def _draw_pashu_sigil(self, screen, pos, strength, spin):
        """The sacred seal burning into the ground under the target."""
        if strength <= 0.02:
            return
        size = PASHU_SIGIL_SIZE
        draw_glow_texture(screen, "magic_01", pos, size, PASHU_GOLD, fade=strength, angle=spin * 160)
        draw_glow_texture(screen, "magic_02", pos, size * 0.72, PASHU_WHITE, fade=strength * 0.8, angle=-spin * 260)
        draw_glow_texture(screen, "circle_02", pos, size * 1.08, PASHU_AZURE, fade=strength * 0.6)

    def _draw_pashu_mandala(self, screen, pos, scale, strength, spin):
        """The heavens opening above the target: counter-rotating golden
        wheels with a soft halo and an azure rim."""
        if strength <= 0.02 or scale <= 0.02:
            return
        size = PASHU_MANDALA_SIZE * scale
        draw_glow_texture(screen, "light_03", pos, size * 1.2, PASHU_GOLD, fade=0.3 * strength)
        draw_glow_texture(screen, "magic_03", pos, size, PASHU_GOLD, fade=strength, angle=spin * 120)
        draw_glow_texture(screen, "magic_02", pos, size * 0.8, PASHU_WHITE, fade=0.8 * strength, angle=-spin * 220)
        draw_glow_texture(screen, "circle_03", pos, size * 0.95, PASHU_AZURE, fade=0.7 * strength)

    def _draw_pashu_arrow(self, screen, sky, tip):
        """The giant radiant arrow dropping out of the third eye, tip at
        `tip`, with a column of light streaming behind it back to the sky."""
        down = pygame.Vector2(0, 1)
        arrow = _divine_arrow_image(self.battle.weapons["arrow"])
        center = tip - down * (arrow.get_height() * 0.38)
        # The light column stops at the arrow's tail so the shaft itself
        # stays readable as an arrow instead of dissolving into the beam.
        tail = center - down * (arrow.get_height() * 0.4)
        if tail.y > sky.y:
            glow_line(screen, sky, tail, PASHU_GOLD, width=9, intensity=0.7)
            glow_line(screen, sky, tail, PASHU_WHITE, width=3)
        draw_glow_texture(screen, "light_01", center, 150, PASHU_GOLD, fade=0.3, stretch=(0.3, 1.3))
        draw_rotated(screen, arrow, center, weapon_angle(down, 0))
        draw_glow_texture(screen, "star_08", tip, 80, PASHU_WHITE, fade=1.0, angle=pygame.time.get_ticks() * 0.3)

    def _draw_pashu_rain(self, screen, target, sky, t):
        """Thin arrows of pure light raining around the main arrow, landing
        on a ring around the target with a spark each. Offsets/delays are
        fixed per index so the volley is stable frame to frame."""
        fall = max(60.0, target.y - sky.y)
        for i in range(PASHU_RAIN_COUNT):
            ang = math.tau * i / PASHU_RAIN_COUNT + 0.3
            r = PASHU_RAIN_RADIUS * (0.55 + 0.45 * ((i * 37) % 10) / 10)
            land = target + pygame.Vector2(math.cos(ang), math.sin(ang)) * r
            delay = 0.1 + (i % 4) * 0.13
            local = (t - delay) / 0.3
            if local <= 0:
                continue
            color = PASHU_WHITE if i % 3 == 0 else PASHU_GOLD
            if local < 1:
                p = pygame.Vector2(land.x, land.y - fall * (1 - ease_in(local)))
                draw_glow_texture(screen, "trace_01", p, PASHU_RAIN_STREAK, color, fade=min(1.0, local * 3),
                                  stretch=(0.7, 1.0))
                draw_glow_texture(screen, "star_04", p + pygame.Vector2(0, PASHU_RAIN_STREAK * 0.4), 20, PASHU_WHITE,
                                  fade=min(1.0, local * 3))
            elif local < 1.6:
                k = (local - 1) / 0.6
                draw_glow_texture(screen, "star_04", land, 34 - 16 * k, color, fade=1 - k)

    def _draw_bow(self, screen, shake_x):
        """The bow: rested at a fixed idle pose when not shooting (see
        IDLE_ANGLE/IDLE_OFFSET), drawn back through Gandiva/Aindrastra/
        Sammohana's shared "windup" phase and released through "fire"/
        "chase" — always oriented off battle.atk_dir while active, which
        combat_resolution.try_start_attack recomputes fresh (attacker ->
        defender) at the start of every single cast, so the bow is
        guaranteed to point at wherever the opponent actually is, never a
        stale or mirrored direction left over from a previous attack on the
        other side of the arena. The bow's own sprite has no string to
        physically redraw, so the "draw" itself is sold entirely by the
        nocked arrow sliding back along -direction and snapping forward on
        release, rather than by deforming the bow art."""
        battle, aj = self.battle, self.fighter
        if not aj.is_alive():
            return
        bow_img = battle.weapons["bow"]
        pos0 = aj.pos + pygame.Vector2(shake_x, 0)

        active = (
            battle.mode == "attack" and battle.attacker is aj
            and battle.motion in BOW_ARROW_MOTIONS
        )
        if not active:
            draw_rotated(screen, bow_img, pos0 + IDLE_OFFSET, IDLE_ANGLE)
            return

        phase, t = battle.current_phase, battle.phase_t
        direction = battle.atk_dir
        if phase == "windup":
            draw_pct = ease_out(t)
            show_nock = True
        elif phase in ("fire", "chase"):
            # Snaps forward fast the instant the shot releases — the arrow
            # itself is drawn separately by draw_projectile from here on.
            draw_pct = max(0.0, 0.9 - t * 3.5)
            show_nock = draw_pct > 0.08
        else:  # impact/settle
            draw_pct = 0.1
            show_nock = False

        draw_rotated(screen, bow_img, pos0, weapon_angle(direction, 90))
        grip = pos0 + direction * (AVATAR_R * 0.25)
        nock = grip - direction * (14 * draw_pct)
        self._draw_bowstring(screen, pos0, direction, nock)
        if show_nock:
            arrow_img = battle.weapons["arrow"]
            twin = battle.ability.tag == "gandiva_shot"
            perp = _perp(direction)
            offsets = GANDIVA_ARROW_OFFSETS if twin else (0,)
            for off in offsets:
                draw_rotated(screen, arrow_img, nock + perp * off, weapon_angle(direction, 0))

    def _draw_bowstring(self, screen, pos0, direction, nock):
        """A real bent bowstring, pulled back to meet the nocked arrow(s) —
        bow.png itself has no string drawn into the art (see this class's
        own docstring), so tension previously only ever read through the
        arrow sliding back. Anchored at the bow's own limb tips
        (BOW_LIMB_HALF_SPAN either side of pos0 along the bow's span axis,
        perpendicular to atk_dir — the same axis weapon_angle(direction, 90)
        above already rotates the bow prop onto) and bent to `nock`, so the
        string always meets exactly where the arrow(s) actually sit."""
        perp = _perp(direction)
        tip_a = pos0 + perp * BOW_LIMB_HALF_SPAN
        tip_b = pos0 - perp * BOW_LIMB_HALF_SPAN
        pygame.draw.lines(screen, BOWSTRING_COLOR, False, [tip_a, nock, tip_b], 2)
