"""The Knight plugin: both passives (Soul Vessel and Mantis Claw), every
tag's effect (Dash Slash's blink to a corner and dash back, Crystal Heart's
charged rocket across the arena, Dream Nail's Soul theft and mind-reading,
Shade Hunt's free-roaming Shade, Vengeful Spirit's shove, Focus's
interruptible heal, Abyss Shriek's fear and Soul refill), and all of the
Knight's presentation — his mask hopping, tilting, stretching and tinting
every frame (sprite.compose), his nail (leading the Dash Slash, swung as a
Great Slash when Mantis Claw empowers it, thrust golden for Dream Nail),
the crystal trail, the Shade's flipbook, the Vengeful Spirit flipbook and
the void wraiths — all cut from assets/the_knight/the_knight.png.

Passive: Soul Vessel — every nail hit (Nail Slash, Dash Slash) fills SOUL
(SOUL_GAIN, SOUL_MAX max; a critical hit fills one more), Dream Nail steals
DREAM_SOUL more and each Shade Hunt slash returns SHADE_SOUL, starting from
SOUL_START. The two spells cost SPELL_COST SOUL each, gated through
ammo_ready/consume_ammo the same way Johnny's Nail Bullets are. Abyss
Shriek refills the vessel.

Passive: Mantis Claw — every time he kicks off an arena wall (his roam's own
bounce, Dash Slash's corner kick, Crystal Heart slamming into the far wall)
he wall-jumps off it: move_speed_up for WALLJUMP_S, and his next nail
strike (Nail Slash, Dash Slash, Crystal Heart) hits WALLJUMP_DMG_MULT
harder."""

import math
import random

import pygame

from ...core.constants import (
    ARENA_RECT, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GRAY, GREEN, KNIGHT_SOUL, WHITE,
)
from ...core.entities import set_status
from ...core.glow import add_dot, glow_line, glow_ring
from ...core.motions import ease_out
from ...core.particles import emit_dark, emit_dust, emit_holy, emit_spark_burst
from ...core.plugin import CharacterPlugin
from ...core.status_library import apply_knockback
from .sprite import compose, part

# ---- passive: Soul Vessel ---------------------------------------------------
SOUL_MAX = 6
SOUL_START = 3
SOUL_GAIN = {"knight_nail": 2, "knight_dashslash": 1}
SPELL_COST = {"knight_spirit": 3, "knight_focus": 3}

# ---- passive: Mantis Claw -----------------------------------------------------
WALLJUMP_S = 0.8
WALLJUMP_SPEED = 0.8
WALLJUMP_DMG_MULT = 1.5
# Ignore a second "bounce" right after the first (a corner hits both walls).
WALLJUMP_CD_S = 0.3
WALL_MARGIN_PX = 3

# ---- Dash Slash -------------------------------------------------------------------
DASHSLASH_MULT = 1.6
# Past the target the dash carries on this far, slashing clean through.
DASHSLASH_OVERSHOOT_PX = 40
# Share of the dash (release phase) at which the nail meets the target.
DASHSLASH_CONTACT_T = 0.55
DASHSLASH_FLASH_S = 0.16
# How long each untargetable frame's refresh lasts (the blink).
UNTARGETABLE_REFRESH_S = 0.08

# ---- Crystal Heart ----------------------------------------------------------------
CRYSTAL_MULT = 2.6
CRYSTAL_HIT_HALF_W = 16
CRYSTAL_TRAIL_S = 0.45
CRYSTAL_PINK = (255, 120, 200)
CRYSTAL_DEEP = (170, 40, 130)

# ---- Dream Nail ---------------------------------------------------------------------
DREAM_SOUL = 3
DREAM_SILENCE_S = 1.8
DREAM_GOLD = (255, 215, 130)
DREAM_VIOLET = (190, 140, 255)
# What the target is thinking when the dream nail reads it.
DREAM_THOUGHTS = (
    "...so tired...", "Who... are you?", "It's so dark here...", "Must not fall...",
    "That little shadow again...", "Is this a dream?", "The light... burns...",
)

# ---- Shade Hunt -------------------------------------------------------------------
SHADE_LIFE_S = 4.5
SHADE_SPEED = 300
SHADE_RETURN_SPEED = 340
SHADE_HITS = 3
SHADE_MULT = 0.9
SHADE_SOUL = 1
# Each slash is chase -> wind-up (rear back) -> lunge clean through.
SHADE_RANGE_PX = 70
SHADE_WINDUP_S = 0.2
SHADE_BACKOFF_SPEED = 60
SHADE_LUNGE_S = 0.14
SHADE_LUNGE_PAST_PX = 45
# Presentation: a pale outline so the black silhouette reads on the black
# floor, and the violet void-slash each lunge leaves on the target.
SHADE_SCALE = 1.9
SHADE_FPS = 10
SHADE_OUTLINE = (205, 185, 255)
SHADE_SLASH_COLOR = (175, 125, 255)
SHADE_SLASH_S = 0.22

# ---- other skills -------------------------------------------------------------------
FOCUS_HEAL_PCT = 0.2
SPIRIT_KNOCKBACK_PX = 45
SHRIEK_FEAR_S = 1.2

# ---- presentation -------------------------------------------------------------------
VOID_BLACK = (12, 10, 20)
SLASH_SIZE = 64
SPIRIT_SIZE = 58
SPIRIT_FPS = 18
WRAITHS = 7
WRAITH_ORBIT_R = 46
# The roam is a run of little hops, not a glide.
HOP_PX = 6
HOP_SPEED = 7.0
# His nail art, and which way its tip points in the source sheet.
NAIL_FORWARD_TIP = pygame.Vector2(1, 0)
NAIL_ART_SCALE = 1.4

_SCALED_CACHE = {}
_TINT_CACHE = {}
_SHADE_CACHE = {}


def _scaled(name, width):
    """A part scaled to `width` px wide, keeping its aspect."""
    key = (name, width)
    img = _SCALED_CACHE.get(key)
    if img is None:
        src = part(name)
        w, h = src.get_size()
        img = pygame.transform.smoothscale(src, (width, max(1, round(h * width / w))))
        _SCALED_CACHE[key] = img
    return img


def _tinted_art(name, width, color):
    """A part recolored (Dream Nail's golden slash and nail)."""
    key = (name, width, color)
    img = _TINT_CACHE.get(key)
    if img is None:
        img = _scaled(name, width).copy()
        img.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        _TINT_CACHE[key] = img
    return img


def _shade_sprite(name, flip):
    """A Shade frame scaled up with a pale outline traced around its
    silhouette — cached per frame and facing."""
    key = (name, flip)
    img = _SHADE_CACHE.get(key)
    if img is None:
        src = part(name)
        body = _scaled(name, round(src.get_width() * SHADE_SCALE))
        if flip:
            body = pygame.transform.flip(body, True, False)
        rim = pygame.mask.from_surface(body, 40).to_surface(setcolor=(*SHADE_OUTLINE, 255), unsetcolor=(0, 0, 0, 0))
        w, h = body.get_size()
        img = pygame.Surface((w + 6, h + 6), pygame.SRCALPHA)
        for dx in (-2, 0, 2):
            for dy in (-2, 0, 2):
                if dx or dy:
                    img.blit(rim, (3 + dx, 3 + dy))
        img.blit(body, (3, 3))
        _SHADE_CACHE[key] = img
    return img


def _rotate_right_facing(img, direction):
    """Rotate art drawn facing +x (the spirit's skull, the crescent's bulge)
    to face `direction`, mirrored first when it points left so the art
    never ends up upside down."""
    if direction.length_squared() == 0:
        return img
    if direction.x < 0:
        img = pygame.transform.flip(img, False, True)
    return pygame.transform.rotate(img, -math.degrees(math.atan2(direction.y, direction.x)))


def _rotate_tip(img, tip, direction):
    """Rotate art whose tip points along `tip` (in the source sheet) so it
    points along `direction` instead."""
    angle = math.degrees(math.atan2(-direction.y, direction.x) - math.atan2(-tip.y, tip.x))
    return pygame.transform.rotate(img, angle)


def _step(value, steps=20):
    """Round a stretch factor to 1/steps so the pose cache stays small."""
    return round(value * steps) / steps


def _clamp_point(p):
    return pygame.Vector2(max(BOUND_LEFT, min(BOUND_RIGHT, p.x)), max(BOUND_TOP, min(BOUND_BOTTOM, p.y)))


def _ray_to_bounds(origin, direction):
    """How far `origin` can travel along unit `direction` before leaving
    the fighters' bounds."""
    reach = []
    if direction.x > 0:
        reach.append((BOUND_RIGHT - origin.x) / direction.x)
    elif direction.x < 0:
        reach.append((BOUND_LEFT - origin.x) / direction.x)
    if direction.y > 0:
        reach.append((BOUND_BOTTOM - origin.y) / direction.y)
    elif direction.y < 0:
        reach.append((BOUND_TOP - origin.y) / direction.y)
    return max(0.0, min(reach)) if reach else 0.0


class KnightPlugin(CharacterPlugin):
    FX_COLOR = KNIGHT_SOUL

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.soul = SOUL_START
        self._clock = 0.0
        # Mantis Claw: last frame's heading (to spot a wall bounce), the
        # bounce cooldown, the speed-burst timer, and the primed strike.
        self._prev_vel = None
        self._walljump_cd = 0.0
        self._walljump_t = 0.0
        self._empowered = False
        self._afterimage_cd = 0.0
        # Dash Slash: {"state", "corner", "kicked", "dash_from", "hit",
        # "hit_at"} for the cast in progress, or None.
        self._ds = None
        # Crystal Heart: the line he just rocketed along, and when.
        self._crystal_trail = None
        # Shade Hunt: the loose Shade ({"pos", "vel", "t", "hits", "cd",
        # "lunge", "returning"}), or None.
        self._shade = None
        # The Nail Slash cast a Mantis Claw empower turned into a Great Slash.
        self._great_state = None
        # Focus: the cast being channeled, and whether a hit broke it.
        self._focus_state = None
        self._focus_broken = False
        # Roam hop: last hop height, to puff dust on each landing.
        self._last_hop = 0.0

    def _opponent(self):
        b = self.battle
        return b.f2 if self.fighter is b.f1 else b.f1

    def _gain_soul(self, amount):
        before = self.soul
        self.soul = min(SOUL_MAX, self.soul + amount)
        if self.soul >= SPELL_COST["knight_spirit"] > before:
            f = self.fighter
            self.battle.floaters.append([f.pos.x, f.pos.y - 50, -0.4, 220, "SOUL", KNIGHT_SOUL])

    def _can_hit(self, target):
        b = self.battle
        return (target is not None and target.is_alive() and not b.is_invulnerable(target)
                and not b.is_vanished(target) and not b.is_untargetable(target))

    def _strike(self, target, mult, color, knock_dir, empowerable=True):
        """One bespoke hit (the Dash Slash, the Crystal Heart line, a Shade slash):
        the usual outgoing modifiers, a Mantis Claw empower if primed, the
        generic damage funnel, and every plugin's on_damage_dealt."""
        battle, k = self.battle, self.fighter
        dmg = round(k.atk * mult * battle.status_outgoing_multiplier(k))
        if empowerable and self._empowered:
            self._empowered = False
            dmg = round(dmg * WALLJUMP_DMG_MULT)
        actual = battle.deal_damage(k, target, dmg)
        target.hit_flash = target.hit_flash_max = 0.1
        target.hit_flash_color, target.hit_flash_heavy, target.hit_flash_crit = WHITE, False, False
        target.visual_recoil += knock_dir * 5
        target.shake = max(target.shake, 10)
        battle.floaters.append([target.pos.x + random.uniform(-8, 8), target.pos.y - 40, -0.6, 255,
                                f"-{actual}", color])
        for p in battle.plugins:
            p.on_damage_dealt(k, target, actual)
        return actual

    # ---- passive: Soul Vessel -----------------------------------------------------
    def ammo_ready(self, attacker, ability):
        if attacker is not self.fighter or ability.tag not in SPELL_COST:
            return True
        return self.soul >= SPELL_COST[ability.tag]

    def consume_ammo(self, attacker, ability):
        if attacker is self.fighter and ability.tag in SPELL_COST:
            self.soul -= SPELL_COST[ability.tag]

    def passive_gauge(self, fighter):
        if fighter is not self.fighter:
            return None
        label = f"SOUL {self.soul}/{SOUL_MAX}" + ("  CLAW!" if self._empowered else "")
        return self.soul / SOUL_MAX, label, KNIGHT_SOUL

    def on_damage_dealt(self, attacker, defender, actual):
        state = self.battle._current
        if attacker is not self.fighter or state is None or state.attacker is not attacker:
            return
        gain = SOUL_GAIN.get(state.ability.tag, 0)
        if gain:
            self._gain_soul(gain + (1 if state.crit else 0))

    # ---- passive: Mantis Claw -------------------------------------------------------
    def _check_wall_jump(self, dt):
        battle, k = self.battle, self.fighter
        self._walljump_cd = max(0.0, self._walljump_cd - dt)
        prev, v = self._prev_vel, pygame.Vector2(k.vel)
        self._prev_vel = v
        if prev is None or self._walljump_cd > 0 or k in battle.attacks or not k.is_alive():
            return
        r = k.hitbox_r + WALL_MARGIN_PX
        if v.x * prev.x < 0 and (k.pos.x <= ARENA_RECT.left + r or k.pos.x >= ARENA_RECT.right - r):
            self._wall_jump(pygame.Vector2(
                ARENA_RECT.left if k.pos.x < ARENA_RECT.centerx else ARENA_RECT.right, k.pos.y))
        elif v.y * prev.y < 0 and (k.pos.y <= ARENA_RECT.top + r or k.pos.y >= ARENA_RECT.bottom - r):
            self._wall_jump(pygame.Vector2(
                k.pos.x, ARENA_RECT.top if k.pos.y < ARENA_RECT.centery else ARENA_RECT.bottom))

    def _wall_jump(self, wall):
        battle, k = self.battle, self.fighter
        self._walljump_cd = WALLJUMP_CD_S
        self._walljump_t = WALLJUMP_S
        self._empowered = True
        set_status(k, "move_speed_up", WALLJUMP_S, pct=WALLJUMP_SPEED)
        emit_dust(battle.fx, wall, count=8, spread=18)
        battle.spawn_afterimage(k)
        battle.floaters.append([k.pos.x, k.pos.y - 48, -0.5, 230, "Wall Jump!", KNIGHT_SOUL])

    def roam_speed_multiplier(self, fighter, dt):
        """No extra speed of its own (move_speed_up already carries the
        burst) — just the afterimage trail while a wall jump lasts."""
        if fighter is self.fighter and self._walljump_t > 0:
            self._afterimage_cd -= dt
            if self._afterimage_cd <= 0:
                self.battle.spawn_afterimage(fighter)
                self._afterimage_cd = 0.06
        return 1.0

    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is self.fighter and self._empowered and ability.tag == "knight_nail":
            self._empowered = False
            dmg = round(dmg * WALLJUMP_DMG_MULT)
            note += " [WALL JUMP]"
        return dmg, note

    def on_damage_taken(self, defender, actual):
        """A hit landing mid-Focus breaks the channel (the heal is lost)."""
        state = self._focus_state
        if (defender is self.fighter and actual > 0 and state is not None
                and state.current_phase in ("windup", "channel")):
            self._focus_broken = True

    # ---- skills ---------------------------------------------------------------------
    def resolve_special(self):
        battle, k = self.battle, self.fighter
        if battle.attacker is not k:
            return False
        tag = battle.ability.tag
        if tag == "knight_dashslash":
            return True  # the whole dash plays out in _dash_slash_frame
        if tag == "knight_crystal":
            self._crystal_launch()
            return True
        return False

    def _crystal_launch(self):
        """Crystal Heart lets go: rocket from where he crouched straight at
        the target's spot right now, all the way to the far wall — a hit
        only if the target is on that line — then wall-jump off it."""
        battle, k = self.battle, self.fighter
        enemy = battle.defender
        start = pygame.Vector2(k.pos)
        aim = (enemy.pos - start) if enemy is not None else pygame.Vector2(battle.atk_dir)
        aim = aim.normalize() if aim.length_squared() > 0 else pygame.Vector2(1, 0)
        dist = _ray_to_bounds(start, aim)
        end = start + aim * dist
        for i in range(1, 6):
            k.pos = start.lerp(end, i / 6)
            battle.spawn_afterimage(k)
        k.pos = pygame.Vector2(end)
        # "cast" pins the caster to attacker_start for the rest of the cast.
        battle.attacker_start = pygame.Vector2(end)
        self._crystal_trail = (start, end, self._clock)
        battle.add_screen_shake(5, 0.15)
        rel = enemy.pos - start if enemy is not None else None
        on_line = (rel is not None and 0 <= rel.dot(aim) <= dist + enemy.hitbox_r
                   and (rel - aim * rel.dot(aim)).length() <= enemy.hitbox_r + CRYSTAL_HIT_HALF_W)
        if on_line and self._can_hit(enemy):
            actual = self._strike(enemy, CRYSTAL_MULT, CRYSTAL_PINK, aim)
            emit_spark_burst(battle.fx, enemy.pos, CRYSTAL_PINK, count=18)
            k.meter = min(k.meter_max, k.meter + k.meter_gain)
            battle.log = f"{k.name} rockets through {enemy.name} with Crystal Heart for {actual}!"
        else:
            if enemy is not None and on_line:
                battle.floaters.append([enemy.pos.x, enemy.pos.y - 50, -0.5, 255, "Evaded!", WHITE])
            battle.log = f"{k.name}'s Crystal Heart streaks across the arena!"
        self._wall_jump(end + aim * k.hitbox_r)

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag, k = self.battle, ability.tag, self.fighter
        if tag == "knight_shade":
            self._shade = {"pos": pygame.Vector2(k.pos), "face": pygame.Vector2(1, 0), "t": 0.0, "hits": 0,
                           "mode": "chase", "mode_t": 0.0, "lunge_from": None, "lunge_to": None,
                           "hit_done": False, "slash_at": -1.0, "slash_pos": None}
            emit_dark(battle.fx, k.pos, count=24, radius=30, color=VOID_BLACK)
            battle.log = f"{k.name}'s Shade tears loose and hunts {defender.name}!"
        elif tag == "knight_dream":
            self._gain_soul(DREAM_SOUL)
            set_status(defender, "silenced", DREAM_SILENCE_S)
            battle.floaters.append([defender.pos.x, defender.pos.y - 62, -0.35, 255,
                                    f"\"{random.choice(DREAM_THOUGHTS)}\"", DREAM_VIOLET])
            emit_holy(battle.fx, defender.pos, count=22, radius=36, color=DREAM_GOLD)
            battle.log = f"{k.name}'s Dream Nail steals {defender.name}'s Soul — silenced!"
        elif tag == "knight_spirit":
            apply_knockback(defender, k.pos, SPIRIT_KNOCKBACK_PX)
            emit_dark(battle.fx, defender.pos, count=10, radius=20, color=VOID_BLACK)
        elif tag == "knight_focus":
            if self._focus_broken:
                battle.floaters.append([k.pos.x, k.pos.y - 50, -0.5, 255, "Focus broken!", GRAY])
                battle.log = f"{k.name}'s Focus is broken — the Soul is lost!"
            else:
                before = k.hp
                k.hp = min(k.max_hp, k.hp + k.max_hp * FOCUS_HEAL_PCT)
                battle.floaters.append([k.pos.x, k.pos.y - 40, -0.6, 255, f"+{round(k.hp - before)}", GREEN])
                emit_holy(battle.fx, k.pos, count=26, radius=40, color=KNIGHT_SOUL)
                battle.log = f"{k.name} focuses Soul and mends."
            k.meter = min(k.meter_max, k.meter + k.meter_gain)
            self._focus_state = None
        elif tag == "knight_shriek":
            set_status(defender, "feared", SHRIEK_FEAR_S, source=pygame.Vector2(k.pos))
            self.soul = SOUL_MAX
            battle.add_ring(defender.pos, 120, 0.6, VOID_BLACK, width=8)
            battle.add_ring(defender.pos, 90, 0.5, KNIGHT_SOUL, width=3)
            emit_dark(battle.fx, defender.pos, count=50, radius=70, color=VOID_BLACK)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Terrified!", WHITE])
            battle.log = f"{k.name} unleashes Abyss Shriek — the Void pours out!"

    # ---- per-frame --------------------------------------------------------------------
    def attack_frame(self, attacker, ability, phase, t):
        if attacker is not self.fighter:
            return
        state = self.battle._current
        if ability.tag == "knight_dashslash":
            self._dash_slash_frame(state, phase, t)
        elif ability.tag == "knight_nail" and phase == "windup" and self._empowered:
            self._great_state = state
        elif ability.tag == "knight_focus" and self._focus_state is not state and phase == "windup":
            self._focus_state, self._focus_broken = state, False

    def _dash_slash_frame(self, state, phase, t):
        """Dash Slash, written over the planted "cast" position every frame:
        vanish (untargetable) and blink into the arena corner farthest from
        the target, cling there for a beat (hittable — the counterplay),
        kick off it (a Mantis Claw wall jump, empowering the strike), then
        dash straight at the target's live position, slashing clean
        through it."""
        battle, k = self.battle, self.fighter
        enemy = state.defender
        ds = self._ds
        if ds is None or ds["state"] is not state:
            corners = [pygame.Vector2(x, y) for x in (BOUND_LEFT, BOUND_RIGHT) for y in (BOUND_TOP, BOUND_BOTTOM)]
            far_from = enemy.pos if enemy is not None else k.pos
            corner = max(corners, key=lambda c: (c - far_from).length_squared())
            ds = self._ds = {"state": state, "corner": corner, "blinked": False, "kicked": False,
                             "dash_from": None, "hit": False, "hit_at": -1.0}
        if phase == "windup":
            set_status(k, "untargetable", UNTARGETABLE_REFRESH_S)
            if random.random() < 0.5:
                emit_dark(battle.fx, k.pos, count=2, radius=16, color=VOID_BLACK)
        elif phase == "channel":
            if not ds["blinked"]:
                ds["blinked"] = True
                emit_dark(battle.fx, k.pos, count=18, radius=26, color=VOID_BLACK)
                emit_dark(battle.fx, ds["corner"], count=18, radius=26, color=VOID_BLACK)
                emit_dust(battle.fx, ds["corner"], count=6, spread=14)
            k.pos = pygame.Vector2(ds["corner"])
        elif phase == "release":
            if not ds["kicked"]:
                ds["kicked"] = True
                ds["dash_from"] = pygame.Vector2(ds["corner"])
                self._wall_jump(ds["corner"])
            if enemy is None:
                return
            aim = enemy.pos - ds["dash_from"]
            aim = aim.normalize() if aim.length_squared() > 0 else pygame.Vector2(state.atk_dir)
            end = _clamp_point(enemy.pos + aim * DASHSLASH_OVERSHOOT_PX)
            k.pos = ds["dash_from"].lerp(end, t * t)
            battle.spawn_afterimage(k)
            if not ds["hit"] and t >= DASHSLASH_CONTACT_T:
                ds["hit"] = True
                if self._can_hit(enemy):
                    ds["hit_at"] = self._clock
                    actual = self._strike(enemy, DASHSLASH_MULT, WHITE, aim)
                    emit_spark_burst(battle.fx, enemy.pos, KNIGHT_SOUL, count=16)
                    battle.add_screen_shake(4, 0.12)
                    k.meter = min(k.meter_max, k.meter + k.meter_gain)
                    battle.log = f"{k.name} dashes out of the corner and slashes {enemy.name} for {actual}!"
                else:
                    battle.floaters.append([enemy.pos.x, enemy.pos.y - 50, -0.5, 255, "Evaded!", WHITE])

    def ambient_tick(self, dt):
        self._clock += dt
        battle, k = self.battle, self.fighter
        self._walljump_t = max(0.0, self._walljump_t - dt)
        self._check_wall_jump(dt)
        live = set(battle.attacks.values())
        if self._focus_state not in live:
            self._focus_state = None
        if self._great_state not in live:
            self._great_state = None
        self._tick_shade(dt)
        k.image = self._pose()

    # ---- presentation: sprite -----------------------------------------------------------
    def _pose(self):
        """Hop/tilt/stretch/tint for this exact moment (coarse steps, so
        sprite.compose's cache stays small)."""
        battle, k = self.battle, self.fighter
        flip = self._opponent().pos.x < k.pos.x
        if not k.is_alive():
            return compose(base="broken_mask", angle=-12 if not flip else 12, dy=6, flip=flip)
        st = k.statuses
        if any(n in st for n in ("stunned", "frozen", "asleep", "rooted", "curse", "feared")):
            wobble = round(8 * math.sin(self._clock * 14))
            return compose(angle=wobble, tint="gray", amount=1.0, flip=flip)

        state = battle.attacks.get(k)
        if state is not None:
            pose = self._attack_pose(state)
            if pose is not None:
                return compose(flip=state.atk_dir.x < 0, **pose)
        return self._hop_pose(flip)

    def _hop_pose(self, flip):
        """The roam: a run of quick little hops — stretched on the way up,
        squashed on each landing (with a puff of dust), leaning into a wall
        jump."""
        battle, k = self.battle, self.fighter
        speed = HOP_SPEED * (1.6 if self._walljump_t > 0 else 1.0)
        hop = abs(math.sin(self._clock * speed))
        if hop < 0.2 <= self._last_hop and k.vel.length_squared() > 0:
            emit_dust(battle.fx, k.pos + pygame.Vector2(0, 26), count=2, spread=10)
        self._last_hop = hop
        if hop < 0.2:
            sx, sy = 1.12, 0.88
        else:
            sx, sy = 1.0 - 0.06 * hop, 1.0 + 0.06 * hop
        angle = 0
        if self._walljump_t > 0:
            angle = -14 * (1 if k.vel.x >= 0 else -1)
        return compose(angle=angle, sx=_step(sx), sy=_step(sy), dy=-round(HOP_PX * hop), flip=flip)

    def _attack_pose(self, state):
        tag, phase, t = state.ability.tag, state.current_phase, state.phase_t
        lean = 1 if state.atk_dir.x >= 0 else -1  # tilt toward the target
        if tag == "knight_nail":
            swing = {"windup": 8, "slash1": -14, "slash2": 14}.get(phase, 0)
            return {"angle": swing * lean}
        if tag == "knight_dashslash":
            if phase == "windup":  # melting into shadow
                fade = round(t * 4) / 4
                return {"tint": "shade", "amount": fade, "sx": _step(1 - 0.25 * t), "sy": _step(1 - 0.25 * t)}
            if phase == "channel":  # clinging in the corner, coiled to spring
                return {"sx": 0.85, "sy": 1.15, "angle": round(3 * math.sin(self._clock * 40)),
                        "tint": "shade", "amount": 0.25}
            return {"sx": 1.3, "sy": 0.8, "angle": -10 * lean}
        if tag == "knight_crystal":
            if phase in ("windup", "channel"):
                charge = (t * 0.33) if phase == "windup" else (0.33 + t * 0.67)
                shiver = round(3 * math.sin(self._clock * 50) * charge)
                return {"sx": 1.15, "sy": 0.85, "dy": 5, "angle": shiver, "tint": "crystal",
                        "amount": round(charge * 4) / 4}
            return {"sx": 1.3, "sy": 0.8, "tint": "crystal", "amount": round((1 - t) * 4) / 4}
        if tag == "knight_dream":
            if phase in ("windup", "channel"):
                return {"angle": 12 * lean, "tint": "soul", "amount": 0.5}
            return {"angle": -18 * lean, "sx": 1.08}
        if tag == "knight_shade":
            # his Shade tearing loose: he darkens, then the color comes back
            return {"tint": "shade", "amount": 0.75 if phase != "release" else 0.25, "sx": 0.92, "sy": 1.08}
        if tag == "knight_spirit":
            if phase == "windup":
                return {"angle": 10 * lean, "sx": 0.92}
            return {"angle": -6 * lean, "sx": 1.06} if phase == "fire" else {}
        if tag == "knight_focus":
            if self._focus_broken:
                return {"tint": "gray", "amount": 1.0}
            glow = round(min(1.0, t if phase == "windup" else 1.0) * 4) / 4
            if phase == "release":
                glow = round((1 - t) * 4) / 4
            return {"tint": "soul", "amount": glow, "dy": -2 * (phase == "channel")}
        if tag == "knight_shriek":
            if phase in ("windup", "channel"):
                return {"angle": round(4 * math.sin(self._clock * 40)), "tint": "shade", "amount": 0.75,
                        "sx": 1.1, "sy": 1.1}
            return {"tint": "shade", "amount": 0.25}
        return None

    # ---- presentation: fx -----------------------------------------------------------------
    def draw_fx(self, screen, shake_x):
        battle, k = self.battle, self.fighter
        offset = pygame.Vector2(shake_x, 0)
        self._draw_crystal_trail(screen, offset)
        self._draw_shade(screen, offset)
        state = battle._current
        if state is None or state.attacker is not k:
            return
        tag, phase, t = state.ability.tag, state.current_phase, state.phase_t
        if tag == "knight_nail" and phase in ("slash1", "slash2"):
            if state is self._great_state:
                self._draw_great_slash(screen, k.pos + offset, state.atk_dir, phase, t)
            self._draw_slash(screen, k.pos + offset, state.atk_dir, phase, t)
        elif tag == "knight_dashslash":
            self._draw_dash_slash(screen, state, phase, t, offset)
        elif tag == "knight_crystal" and phase in ("windup", "channel"):
            self._draw_crystal_charge(screen, state, phase, t, offset)
        elif tag == "knight_dream":
            self._draw_dream(screen, state, phase, t, offset)
        elif tag == "knight_focus" and phase in ("windup", "channel") and not self._focus_broken:
            strength = t if phase == "windup" else 1.0
            glow_ring(screen, k.pos + offset, 30 - 8 * strength, KNIGHT_SOUL, width=2, intensity=strength)
            add_dot(screen, k.pos + offset, 36, KNIGHT_SOUL, 0.45 * strength)
        elif tag == "knight_shriek":
            self._draw_wraiths(screen, state, phase, t, offset)

    def _draw_slash(self, screen, pos, direction, phase, t, image=None):
        """A crescent swept across the target-side of the Knight — the
        second swing mirrored across the first."""
        side = 1 if phase == "slash1" else -1
        sweep = pygame.Vector2(direction).rotate(side * (40 - 80 * ease_out(t)))
        crescent = image or _scaled("nail_slash", SLASH_SIZE)
        if side < 0:
            crescent = pygame.transform.flip(crescent, False, True)
        img = _rotate_right_facing(crescent, sweep)
        img.set_alpha(round(255 * (1 - 0.6 * t)))
        center = pos + sweep * 34
        screen.blit(img, img.get_rect(center=(round(center.x), round(center.y))))

    def _draw_crystal_charge(self, screen, state, phase, t, offset):
        """Crystal shards gathering on the crouching Knight, and a faint
        aim line toward the target that brightens as the charge fills."""
        k = self.fighter
        charge = (t * 0.33) if phase == "windup" else (0.33 + t * 0.67)
        pos = k.pos + offset
        if state.defender is not None:
            aim = state.defender.pos - k.pos
            if aim.length_squared() > 0:
                aim = aim.normalize()
                end = k.pos + aim * _ray_to_bounds(k.pos, aim) + offset
                for i in range(0, 20, 2):  # dashed preview line
                    glow_line(screen, pos.lerp(end, i / 20), pos.lerp(end, (i + 1) / 20), CRYSTAL_PINK,
                              width=1, intensity=0.25 + 0.5 * charge)
        for i in range(6):
            ang = i * math.tau / 6 + self._clock * 2
            r = 40 - 22 * charge
            p = pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * r
            s = 4 + 3 * charge
            pts = [(p.x, p.y - s * 1.6), (p.x + s, p.y), (p.x, p.y + s * 1.6), (p.x - s, p.y)]
            pygame.draw.polygon(screen, CRYSTAL_DEEP, pts)
            pygame.draw.polygon(screen, CRYSTAL_PINK, pts, width=1)
        add_dot(screen, pos, 20 + 18 * charge, CRYSTAL_PINK, 0.5 * charge)

    def _draw_crystal_trail(self, screen, offset):
        """The pink streak Crystal Heart leaves along its line, shattering
        into shards as it fades."""
        if self._crystal_trail is None:
            return
        start, end, born = self._crystal_trail
        age = self._clock - born
        if age > CRYSTAL_TRAIL_S:
            self._crystal_trail = None
            return
        fade = 1 - age / CRYSTAL_TRAIL_S
        a, b = start + offset, end + offset
        glow_line(screen, a, b, CRYSTAL_PINK, width=max(2, round(12 * fade)), intensity=fade)
        pygame.draw.line(screen, WHITE, a, b, max(1, round(4 * fade)))
        rng = random.Random(int(born * 1000))
        for i in range(10):
            p = a.lerp(b, rng.random()) + pygame.Vector2(rng.uniform(-10, 10), rng.uniform(-10, 10)) * (1 + age * 4)
            s = 3 * fade + 1
            pygame.draw.polygon(screen, CRYSTAL_PINK, [(p.x, p.y - s * 1.6), (p.x + s, p.y), (p.x, p.y + s * 1.6),
                                                       (p.x - s, p.y)])

    def _draw_dream(self, screen, state, phase, t, offset):
        """Dream Nail: golden essence drawn into the raised nail while it
        charges, then a big golden dream-slash across the target."""
        k = self.fighter
        if phase in ("windup", "channel"):
            strength = t if phase == "windup" else 1.0
            pos = k.pos + offset
            glow_ring(screen, pos, 24 + 4 * math.sin(self._clock * 9), DREAM_GOLD, width=2, intensity=strength)
            for i in range(5):
                ang = i * math.tau / 5 - self._clock * 3
                r = 48 * (1 - (self._clock * 1.5 + i / 5) % 1)
                add_dot(screen, pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * r, 5, DREAM_VIOLET, 0.8 * strength)
        elif phase == "release" and state.defender is not None:
            self._draw_dream_thrust(screen, state, t, offset)
            self._draw_slash(screen, state.defender.pos + offset - state.atk_dir * 30, state.atk_dir, "slash1", t,
                             image=_tinted_art("nail_slash", round(SLASH_SIZE * 1.4), DREAM_GOLD))

    def _tick_shade(self, dt):
        """Shade Hunt: the loose Shade hunts the target on its own. Each of
        its SHADE_HITS slashes reads as a real attack — chase into range,
        rear back for SHADE_WINDUP_S, then lunge clean through the target
        (the hit lands mid-lunge, handing SHADE_SOUL back to the Knight) —
        and once it's done (or out of time) it streams home and rejoins him."""
        shade = self._shade
        if shade is None:
            return
        battle, k = self.battle, self.fighter
        enemy = self._opponent()
        shade["t"] += dt
        shade["mode_t"] += dt
        done = shade["hits"] >= SHADE_HITS or shade["t"] >= SHADE_LIFE_S or not enemy.is_alive()
        if done and shade["mode"] in ("chase", "windup"):
            shade["mode"], shade["mode_t"] = "return", 0.0
        mode = shade["mode"]
        to_enemy = enemy.pos - shade["pos"]
        if mode == "chase":
            dist = to_enemy.length()
            if dist > 0:
                shade["face"] = to_enemy / dist
                shade["pos"] += shade["face"] * SHADE_SPEED * dt
            if dist <= SHADE_RANGE_PX:
                shade["mode"], shade["mode_t"] = "windup", 0.0
        elif mode == "windup":
            if to_enemy.length_squared() > 0:
                shade["face"] = to_enemy.normalize()
            shade["pos"] -= shade["face"] * SHADE_BACKOFF_SPEED * dt
            if shade["mode_t"] >= SHADE_WINDUP_S:
                aim = pygame.Vector2(shade["face"])
                shade.update(mode="lunge", mode_t=0.0, hit_done=False, lunge_from=pygame.Vector2(shade["pos"]),
                             lunge_to=_clamp_point(enemy.pos + aim * SHADE_LUNGE_PAST_PX))
        elif mode == "lunge":
            u = min(1.0, shade["mode_t"] / SHADE_LUNGE_S)
            shade["pos"] = shade["lunge_from"].lerp(shade["lunge_to"], u)
            emit_dark(battle.fx, shade["pos"], count=2, radius=10, color=VOID_BLACK)
            if not shade["hit_done"] and u >= 0.5:
                shade["hit_done"] = True
                shade["hits"] += 1
                if self._can_hit(enemy):
                    shade.update(slash_at=self._clock, slash_pos=pygame.Vector2(enemy.pos))
                    self._strike(enemy, SHADE_MULT, SHADE_SLASH_COLOR, shade["face"], empowerable=False)
                    self._gain_soul(SHADE_SOUL)
                    battle.add_ring(enemy.pos, 46, 0.3, SHADE_SLASH_COLOR, width=3)
                    emit_dark(battle.fx, enemy.pos, count=14, radius=20, color=VOID_BLACK)
            if u >= 1.0:
                shade["mode"], shade["mode_t"] = "chase", 0.0
        else:  # return
            to_knight = k.pos - shade["pos"]
            dist = to_knight.length()
            if dist < 18:
                emit_dark(battle.fx, k.pos, count=16, radius=24, color=VOID_BLACK)
                self._shade = None
                return
            shade["face"] = to_knight / dist
            shade["pos"] += shade["face"] * SHADE_RETURN_SPEED * dt
        if random.random() < 0.4:
            emit_dark(battle.fx, shade["pos"], count=1, radius=12, color=VOID_BLACK)

    def _draw_shade(self, screen, offset):
        """The Shade itself (outlined so it reads on the black floor): its
        float cycle while chasing, its idle pose rearing back and flying
        home, its lunge frame mid-strike with a streak behind it — plus the
        violet void-slash each landed lunge leaves across the target."""
        shade = self._shade
        if shade is None:
            return
        mode = shade["mode"]
        if mode == "lunge":
            name = "shade/shade_lunge"
        elif mode in ("windup", "return"):
            name = "shade/shade_idle"
        else:
            name = f"shade/shade_float_{int(self._clock * SHADE_FPS) % 5:02d}"
        img = _shade_sprite(name, shade["face"].x < 0)
        bob = 0 if mode == "lunge" else 3 * math.sin(self._clock * 6)
        p = shade["pos"] + offset + pygame.Vector2(0, bob)
        if mode == "windup":
            pulse = 0.5 + 0.5 * math.sin(self._clock * 40)
            add_dot(screen, p, 40 + 8 * pulse, SHADE_OUTLINE, 0.6 + 0.4 * pulse)
        else:
            add_dot(screen, p, 36, (130, 110, 190), 0.6)
        if mode == "lunge":
            glow_line(screen, shade["lunge_from"] + offset, p, SHADE_SLASH_COLOR, width=5, intensity=0.8)
        screen.blit(img, img.get_rect(center=(round(p.x), round(p.y))))
        since = self._clock - shade["slash_at"]
        if shade["slash_pos"] is not None and 0 <= since < SHADE_SLASH_S:
            self._draw_slash(screen, shade["slash_pos"] + offset - shade["face"] * 20, shade["face"], "slash1",
                             since / SHADE_SLASH_S,
                             image=_tinted_art("nail_slash", round(SLASH_SIZE * 1.3), SHADE_SLASH_COLOR))

    def _draw_dash_slash(self, screen, state, phase, t, offset):
        """A flickering aim line from the corner while he clings, then the
        dash itself: a white streak behind him, his nail leading the way,
        and a crescent across the target the instant it connects."""
        ds, k, enemy = self._ds, self.fighter, state.defender
        if ds is None or ds["state"] is not state or enemy is None:
            return
        if phase == "channel":
            a, b = k.pos + offset, enemy.pos + offset
            if int(self._clock * 20) % 2 == 0:
                for i in range(0, 16, 2):
                    glow_line(screen, a.lerp(b, i / 16), a.lerp(b, (i + 1) / 16), WHITE, width=1,
                              intensity=0.3 + 0.5 * t)
        elif phase == "release" and ds["dash_from"] is not None:
            a, b = ds["dash_from"] + offset, k.pos + offset
            glow_line(screen, a, b, KNIGHT_SOUL, width=6, intensity=0.8)
            pygame.draw.line(screen, WHITE, a, b, 2)
            aim = enemy.pos - ds["dash_from"]
            if aim.length_squared() > 0:
                aim = aim.normalize()
                img = _rotate_tip(_scaled("nail_thrust", round(54 * NAIL_ART_SCALE)), NAIL_FORWARD_TIP, aim)
                tip = k.pos + aim * 30 + offset
                screen.blit(img, img.get_rect(center=(round(tip.x), round(tip.y))))
            since = self._clock - ds["hit_at"]
            if 0 <= since < DASHSLASH_FLASH_S:
                self._draw_slash(screen, enemy.pos + offset - aim * 20, aim, "slash1", since / DASHSLASH_FLASH_S)

    def _draw_great_slash(self, screen, pos, direction, phase, t):
        """Mantis Claw's empowered swing: the full nail-art Great Slash —
        his nail with its crescent of force — swept wide in front of him."""
        side = 1 if phase == "slash1" else -1
        sweep = pygame.Vector2(direction).rotate(side * (50 - 100 * ease_out(t)))
        img = _rotate_tip(_scaled("nail_great", round(55 * NAIL_ART_SCALE * 1.3)), NAIL_FORWARD_TIP, sweep)
        img.set_alpha(round(255 * (1 - 0.5 * t)))
        center = pos + sweep * 40
        add_dot(screen, center, 30, KNIGHT_SOUL, 0.35 * (1 - t))
        screen.blit(img, img.get_rect(center=(round(center.x), round(center.y))))

    def _draw_dream_thrust(self, screen, state, t, offset):
        """Dream Nail's thrust: his nail, glowing gold, driving into the
        target's dream."""
        src = _tinted_art("nail_thrust", round(54 * NAIL_ART_SCALE * 1.2), DREAM_GOLD)
        img = _rotate_tip(src, NAIL_FORWARD_TIP, state.atk_dir)
        start = self.fighter.pos + state.atk_dir * 20
        tip = state.defender.pos - state.atk_dir * 10
        p = start.lerp(tip, ease_out(min(1.0, t * 2))) + offset
        add_dot(screen, p, 22, DREAM_GOLD, 0.5 * (1 - t))
        screen.blit(img, img.get_rect(center=(round(p.x), round(p.y))))

    def _draw_wraiths(self, screen, state, phase, t, offset):
        """Void wraiths — inky blobs with glowing eyes — swirl around the
        Knight while he shrieks, then rush the target on impact."""
        k = self.fighter
        target = state.defender.pos if state.defender is not None else state.defender_start
        for i in range(WRAITHS):
            ang = self._clock * 3.2 + i * math.tau / WRAITHS
            orbit = k.pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * WRAITH_ORBIT_R
            if phase == "windup":
                pos, size = k.pos.lerp(orbit, t), 0.5 + 0.5 * t
            elif phase == "channel":
                pos, size = orbit, 1.0
            elif phase == "impact":
                pos, size = orbit.lerp(target + pygame.Vector2(math.cos(ang), math.sin(ang)) * 18, ease_out(t)), 1.0
            else:
                pos, size = target, max(0.0, 1 - t)
            if size <= 0.05:
                continue
            p = pos + offset
            pygame.draw.circle(screen, VOID_BLACK, (round(p.x), round(p.y)), round(15 * size))
            pygame.draw.circle(screen, (40, 36, 60), (round(p.x), round(p.y)), round(15 * size), width=2)
            eyes = _scaled(f"void_eyes/void_eyes_{i % 4:02d}", max(4, round(24 * size)))
            screen.blit(eyes, eyes.get_rect(center=(round(p.x), round(p.y))))

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is not self.fighter or battle.projectile_pos is None:
            return False
        if battle.ability.tag != "knight_spirit":
            return False
        frame = int(self._clock * SPIRIT_FPS) % 6
        img = _rotate_right_facing(_scaled(f"vengeful_spirit/vengeful_spirit_{frame:02d}", SPIRIT_SIZE),
                                   battle.atk_dir)
        pos = battle.projectile_pos
        add_dot(screen, pos, 26, KNIGHT_SOUL, 0.35)
        screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))
        if random.random() < 0.5:
            emit_dark(battle.fx, pos, count=1, radius=8, color=VOID_BLACK)
        return True
