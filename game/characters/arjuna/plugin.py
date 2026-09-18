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
blast is sound, not a projectile). Pashupatastra finally draws the rain of
arrows its own name/flavor text already claims, converging on the target
from above during "channel" instead of only ever showing rings/starbursts."""

import math
import random

import pygame

from ...core.constants import ARENA_RECT, ARJUNA_GOLD, AVATAR_R, INDRA_SPARK, WHITE
from ...core.effects import draw_expanding_ring, draw_rotated, draw_starburst, tint_flash, weapon_angle
from ...core.entities import set_status
from ...core.motions import ease_in, ease_out
from ...core.particles import emit_holy, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .weapons import load_arjuna_weapons

# Savyasachi (passive): Arjuna's own epithet — "able to draw and loose with
# either hand at once" — so every Gandiva shot fires as a genuine two-arrow
# release instead of one (see resolve_special below), on top of the
# moves_while_active freedom already wired into moves.py.
GANDIVA_ARROW_COUNT = 2

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
# same approach BOW_PRE_ROTATE/ARROW_PRE_ROTATE in weapons.py used), but a
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

# Pashupatastra: the actual rain of arrows the ability's own name/flavor
# text already claims (see moves.py) — PASHUPATASTRA_ARROW_COUNT arrows
# converging on the target from PASHUPATASTRA_FALL_HEIGHT px above, spread
# PASHUPATASTRA_SPREAD px either side, staggered by distance from center so
# they don't all land in lockstep.
PASHUPATASTRA_ARROW_COUNT = 7
PASHUPATASTRA_FALL_HEIGHT = 150
PASHUPATASTRA_SPREAD = 64
# The regular arrow prop (ARROW_TARGET_H=140, see weapons.py) is nearly as
# tall as the whole fall itself — drawn at full size here, every falling
# arrow would constantly poke out past whatever's clamping its travel.
# Rain-specific arrows are a separately scaled-down copy instead (see
# _rain_arrow_image), never the shared battle.weapons["arrow"] used at full
# size everywhere else.
PASHUPATASTRA_ARROW_SCALE = 0.4


_RAIN_ARROW_CACHE = {}


def _rain_arrow_image(arrow_img):
    """A scaled-down copy of the shared arrow prop for Pashupatastra's rain
    (see PASHUPATASTRA_ARROW_SCALE) — cached by the source image's own id
    since battle.weapons["arrow"] is the same instance for the whole match."""
    cached = _RAIN_ARROW_CACHE.get(id(arrow_img))
    if cached is None:
        w, h = arrow_img.get_size()
        target_h = max(20, round(h * PASHUPATASTRA_ARROW_SCALE))
        scale = target_h / h
        cached = pygame.transform.smoothscale(arrow_img, (max(1, round(w * scale)), target_h))
        _RAIN_ARROW_CACHE[id(arrow_img)] = cached
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
        whole bonus, not a target for further stacking."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "gandiva_shot"):
            return False
        attacker, defender, ability = battle.attacker, battle.defender, battle.ability
        if defender is None:
            return False

        total = 0
        for _ in range(GANDIVA_ARROW_COUNT):
            dmg = round(attacker.atk * ability.dmg_mult)
            actual = battle.deal_damage(attacker, defender, dmg)
            total += actual
        battle.damage_applied = True

        defender.shake = 14
        battle.apply_impact(defender, ability)
        battle.floaters.append(
            [defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{total} x{GANDIVA_ARROW_COUNT}", ARJUNA_GOLD]
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
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Feared!", ARJUNA_GOLD])
            battle.log = f"{attacker.name} sounds the conch Devadatta — {defender.name}'s resolve breaks!"
            battle.flash_timer = max(battle.flash_timer, 0.3)
            battle.add_ring(attacker.pos, 60, 0.3, ARJUNA_GOLD, width=3)
            # A second ring right where it actually lands — the blast
            # travels there visibly too (see draw_fx's "channel" phase), so
            # this confirms the payoff on the target instead of only ever
            # showing something happening back at Arjuna.
            battle.add_ring(defender.pos, 90, 0.4, ARJUNA_GOLD, width=4)
            emit_spark_burst(battle.fx, defender.pos, ARJUNA_GOLD, count=14)
        elif tag == "pashupatastra":
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "PASHUPATASTRA!", ARJUNA_GOLD])
            battle.log = f"{attacker.name} calls down Pashupatastra — Shiva's absolute weapon!"
            battle.flash_timer = max(battle.flash_timer, 0.5)
            battle.add_screen_shake(24, 0.32)
            if defender is not None:
                # Status: stunned — even what it doesn't outright kill, a
                # weapon capable of destroying the three worlds should cripple.
                set_status(defender, "stunned", PASHUPATASTRA_STUN_S)
                battle.add_ring(defender.pos, 190, 0.6, WHITE, width=6)
                battle.add_ring(defender.pos, 150, 0.75, ARJUNA_GOLD, width=5)
                emit_holy(battle.fx, defender.pos, count=46, radius=90)

    # ---- presentation ---------------------------------------------------------
    def impact_particles(self, pos, count):
        name = self.battle.ability.name
        color = INDRA_SPARK if name == "Aindrastra" else SAMMOHANA_VIOLET if name == "Sammohana" else ARJUNA_GOLD
        emit_spark_burst(self.battle.fx, pos, color, count=count)
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
            # Savyasachi drawn, not just computed: both arrows the two-hit
            # resolve_special actually fires, side by side.
            perp = _perp(direction)
            for off in (-GANDIVA_ARROW_GAP, GANDIVA_ARROW_GAP):
                draw_rotated(screen, arrow_img, pos + perp * off, angle)
        elif name == "Aindrastra":
            tinted = tint_flash(arrow_img, INDRA_SPARK, 150)
            self._draw_charged_crackle(screen, pos, direction)
            draw_rotated(screen, tinted, pos, angle)
        elif name == "Sammohana":
            tinted = tint_flash(arrow_img, SAMMOHANA_VIOLET, 150)
            self._draw_illusion_trail(screen, tinted, pos, direction, angle)
        return True

    def _draw_charged_crackle(self, screen, pos, direction):
        """A couple of small lightning arcs jumping off the shaft, trailing
        behind the arrowhead — Aindrastra is Indra's own weapon, so it reads
        as charged, not just a recolored Gandiva shot."""
        d = direction.normalize() if direction.length_squared() > 0 else pygame.Vector2(1, 0)
        perp = pygame.Vector2(-d.y, d.x)
        for _ in range(AINDRASTRA_ARC_COUNT):
            back = pos - d * random.uniform(6, 26)
            spark = back + perp * random.uniform(-9, 9)
            pygame.draw.line(screen, INDRA_SPARK, back, spark, 2)
            pygame.draw.line(screen, WHITE, back, spark.lerp(back, 0.4), 1)

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
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t
        if name == "Devadatta" and phase == "windup":
            # A short charge-up right at Arjuna before the blast leaves him.
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, origin, 16 + 24 * t, ARJUNA_GOLD, width=3)
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
                draw_expanding_ring(screen, center, 14 + 26 * local_t, ARJUNA_GOLD, width=3)
        elif name == "Devadatta" and phase == "release":
            # The impact itself — lands right as apply_tag_effects fires
            # (RESOLVE_PHASE["cast"] == "release"), so this burst and the
            # "Feared!" floater/status both land on the same beat.
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            draw_starburst(screen, center, ARJUNA_GOLD, size=34, fade=1 - t)
            draw_expanding_ring(screen, center, 70 * t, ARJUNA_GOLD, width=4)
        elif name == "Pashupatastra" and phase == "windup":
            # Called down from directly above the target, same as Thunder
            # God's Descent — the charge itself is centered on Arjuna, not
            # aimed, so it needs no atk_dir orientation of its own.
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            draw_expanding_ring(screen, origin, 20 + 60 * t, WHITE, width=5)
            draw_starburst(screen, origin, ARJUNA_GOLD, size=16 + 20 * t, fade=t)
        elif name == "Pashupatastra" and phase == "channel":
            # The actual rain of arrows the name/flavor text already claims
            # (see moves.py) — converging on the target from above instead
            # of only ever showing a charge-up ring back at Arjuna.
            target = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            self._draw_arrow_rain(screen, target, t)
        elif name == "Pashupatastra" and phase == "impact":
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            for i in range(7):
                ang = i * (math.tau / 7)
                start = center + pygame.Vector2(math.cos(ang), math.sin(ang)) * (140 * (1 - t))
                pygame.draw.line(screen, ARJUNA_GOLD, start, center, 2)
            draw_starburst(screen, center, WHITE, size=50, fade=1 - t)
            draw_expanding_ring(screen, center, 90 * t, ARJUNA_GOLD, width=6)

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
            offsets = (-GANDIVA_ARROW_GAP, GANDIVA_ARROW_GAP) if twin else (0,)
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

    def _draw_arrow_rain(self, screen, target, t):
        """Shiva's own absolute weapon called down as a literal storm of
        arrows converging on the target from above — PASHUPATASTRA_ARROW_COUNT
        arrows, each offset from center by a fixed (index-derived, not
        random) spread so the whole volley is stable frame to frame instead
        of re-rolling and jittering on every draw call, and staggered by
        that same distance-from-center so they don't all land in lockstep."""
        arrow_img = _rain_arrow_image(self.battle.weapons["arrow"])
        n = PASHUPATASTRA_ARROW_COUNT
        # Clamped to how much headroom the target actually has above it in
        # the arena — a target standing near the top wall would otherwise
        # have its own volley start falling from above the arena border
        # entirely (off past the HUD), regardless of PASHUPATASTRA_FALL_HEIGHT's
        # own fixed value.
        fall_height = max(40, min(PASHUPATASTRA_FALL_HEIGHT, target.y - ARENA_RECT.top - 12))
        for i in range(n):
            spread = (i / (n - 1) - 0.5) * 2 if n > 1 else 0.0  # -1..1
            delay = abs(spread) * 0.35
            local_t = (t - delay) / (1 - delay)
            if local_t <= 0:
                continue
            local_t = min(1.0, local_t)
            pos = pygame.Vector2(
                target.x + spread * PASHUPATASTRA_SPREAD,
                target.y - fall_height * (1 - ease_in(local_t)),
            )
            fall_dir = pygame.Vector2(spread * 14, PASHUPATASTRA_FALL_HEIGHT)
            alpha = min(255, round(255 * local_t))
            draw_rotated(screen, arrow_img, pos, weapon_angle(fall_dir, 0), alpha=alpha)
