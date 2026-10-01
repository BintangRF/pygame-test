"""Sans plugin: the two passives (Dodge and Karmic Retribution), every tag's
effect (Bone Wall's swarm setup, Blue Soul's wall slam, Bone Cage's root,
Shortcut's teleport, Power Nap's heal, Bad Time's ring of Gaster Blasters), and all of Sans's
presentation — his per-frame sprite (his head: one face picked per moment
from assets/sans/parts/ by sprite.compose, bobbing a little), the bones, and
the blasters.

Passive: Dodge — the instant an enemy attack aimed at Sans starts, he
spends one STAMINA (DODGE_STAMINA_MAX, refilled one every
DODGE_REGEN_S) to be untargetable for that whole attack (the generic
"untargetable" status, refreshed every frame the attack lasts, so the
generic pipeline reports it "Evaded!" — retitled "MISS"), then slips aside
as it whiffs. Only attacks that actually deal damage are worth dodging
(a pure debuff lands its tag effect regardless of untargetable), and he
can't dodge while he can't act or move (stunned, asleep, rooted, ...).

Passive: Karmic Retribution — every hit Sans lands adds KR stacks
(KR_STACKS per tag) to the target: a "sans_karma" status that deals
KR_DPS_PER_STACK armor-ignoring damage per second per stack, and loses one
stack every KR_DECAY_S. Sans's own hits are weak; KR is his damage."""

import math
import random

import pygame

from ...core.constants import (
    ARENA_RECT, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GOLD, GRAY, HEIGHT, SANS_BLUE, SANS_KARMA, WHITE,
    WIDTH,
)
from ...core.effects import rotate_to_dir
from ...core.entities import set_status
from ...core.glow import add_dot, glow_line, glow_ring
from ...core.particles import emit_dark, emit_dust, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .sprite import compose, part

# ---- passive: Dodge -------------------------------------------------------
DODGE_STAMINA_MAX = 3
DODGE_REGEN_S = 2.2
# How long each refresh of "untargetable" lasts — just a buffer longer than
# one frame; the dodged attack refreshes it every frame it's still alive.
DODGE_REFRESH_S = 0.15
# The sidestep as the dodged attack whiffs, and how long the shrug pose holds.
DODGE_HOP_PX = 34
DODGE_POSE_S = 0.45

# ---- passive: Karmic Retribution -------------------------------------------
KR_STATUS = "sans_karma"
KR_DPS_PER_STACK = 0.5
KR_MAX_STACKS = 15
KR_DECAY_S = 0.8
KR_FLOATER_INTERVAL_S = 0.5
KR_STACKS = {"sans_bone": 1, "sans_bone_wall": 1, "sans_blue": 2, "sans_blaster": 3, "sans_cage": 2,
             "sans_bad_time": 2}

# ---- skills -----------------------------------------------------------------
BLUE_STUN_S = 0.9
SHORTCUT_UNTARGETABLE_S = 0.5
SHORTCUT_SAMPLES = 14
# Power Nap: Sans dozes on his feet without dropping his guard — "regen"
# heals NAP_REGEN_PCT of max hp per second, and his dodge STAMINA refills
# NAP_STAMINA_MULT times faster while the "sans_nap" buff lasts.
NAP_STATUS = "sans_nap"
NAP_S = 3.0
NAP_REGEN_PCT = 0.04
NAP_STAMINA_MULT = 3.0
NAP_FLOATER_INTERVAL_S = 0.8
# Bone Cage: the target is rooted inside a ring of bones, and its KR stacks
# stop decaying for as long as it stays caged.
CAGE_ROOT_S = 1.6
CAGE_BONES = 8
CAGE_BONE_LEN = 22
CAGE_RADIUS = 38
CAGE_START_RADIUS = 72

# ---- ultimate: Bad Time -------------------------------------------------------
ULT_BLASTERS = 6
ULT_INTERVAL_S = 0.28
ULT_CHARGE_S = 0.4
ULT_BEAM_S = 0.26
ULT_RING_R = 130
ULT_BEAM_HALF_W = 12
ULT_BEAM_MULT = 1.3
ULT_TINT_ALPHA = 70

# ---- presentation -------------------------------------------------------------
BONE_COLOR = (245, 245, 245)
BONE_OUTLINE = (20, 20, 24)
BLASTER_SCALE = 1.4
BEAM_LEN = 700
BEAM_WIDTH = 16
LOW_HP_PCT = 0.35
IDLE_BOB_PX = 2
IDLE_BOB_SPEED = 3.0
BLINK_PERIOD_S = 3.4
BLINK_S = 0.12

_BONE_CACHE = {}
_BLASTER_CACHE = {}


def _bone(length):
    """A plain white bone standing tip-up (rotate_to_dir's convention)."""
    img = _BONE_CACHE.get(length)
    if img is None:
        w = max(6, round(length * 0.3))
        knob = w * 0.3
        img = pygame.Surface((w + 2, length + 2), pygame.SRCALPHA)
        cx = (w + 2) / 2
        for col, grow in ((BONE_OUTLINE, 1), (BONE_COLOR, 0)):
            shaft = pygame.Rect(0, 0, w * 0.42 + grow * 2, length - knob * 2)
            shaft.center = (cx, (length + 2) / 2)
            pygame.draw.rect(img, col, shaft)
            for y in (knob + 1, length + 1 - knob):
                for dx in (-knob * 0.85, knob * 0.85):
                    pygame.draw.circle(img, col, (cx + dx, y), knob + grow)
        _BONE_CACHE[length] = img
    return img


def _blaster(frame):
    """Gaster Blaster frame 0-5 (0-2 jaw shut, 3-5 open), turned so its
    mouth points up (rotate_to_dir's convention) — the sheet draws it
    mouth-down."""
    img = _BLASTER_CACHE.get(frame)
    if img is None:
        src = part(f"gaster_blaster/gaster_blaster_{frame:02d}")
        w, h = src.get_size()
        img = pygame.transform.rotate(
            pygame.transform.scale(src, (round(w * BLASTER_SCALE), round(h * BLASTER_SCALE))), 180)
        _BLASTER_CACHE[frame] = img
    return img


def _frame(t, count):
    return min(count - 1, int(max(0.0, t) * count))


def _clamp_point(p, margin=0):
    return pygame.Vector2(
        max(BOUND_LEFT + margin, min(BOUND_RIGHT - margin, p.x)),
        max(BOUND_TOP + margin, min(BOUND_BOTTOM - margin, p.y)),
    )


def _ray_distance(origin, direction, point):
    """Distance from `point` to the ray origin + s*direction (s >= 0)."""
    rel = point - origin
    s = max(0.0, rel.dot(direction))
    return (rel - direction * s).length()


class SansPlugin(CharacterPlugin):

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.stamina = float(DODGE_STAMINA_MAX)
        # Enemy AttackStates already judged for a dodge / actually dodged /
        # already slipped away from (pruned once they finish).
        self._judged = set()
        self._dodged = set()
        self._slid = set()
        self._dodge_pose_t = 0.0
        self._clock = 0.0
        # Bad Time's live blasters: [{"pos", "born", "aim", "fired", "hit"}].
        self._ult_blasters = []
        self._ult_elapsed = 0.0
        self._nap_floater_cd = 0.0
        # Gaster Blaster's spot beside Sans for the current cast.
        self._blaster_pos = None
        # Bone Cage: who's caged and for how much longer.
        self._cage_target = None
        self._cage_t = 0.0

    def _opponent(self):
        b = self.battle
        return b.f2 if self.fighter is b.f1 else b.f1

    # ---- passive: Dodge -----------------------------------------------------
    def _judge_incoming(self, state):
        if state in self._judged:
            return
        self._judged.add(state)
        sans, ab = self.fighter, state.ability
        worth_dodging = ab.cast_target != "self" and (ab.dmg_mult > 0 or ab.kind == "ultimate")
        if not (worth_dodging and state.defender is sans and state.redirect_target is None):
            return
        if not sans.is_alive() or self.stamina < 1:
            return
        if not (self.battle.can_act(sans) and self.battle.can_move(sans)):
            return
        self.stamina -= 1
        self._dodged.add(state)
        set_status(sans, "untargetable", DODGE_REFRESH_S)

    def _slip_away(self, state):
        """The dodged attack just resolved (and whiffed): sidestep out of
        its line and retitle the generic "Evaded!" floater."""
        battle, sans = self.battle, self.fighter
        self._slid.add(state)
        self._dodge_pose_t = DODGE_POSE_S
        for fl in battle.floaters:
            if fl[4] == "Evaded!" and abs(fl[0] - sans.pos.x) < 1:
                fl[4], fl[5] = "MISS", WHITE
        if sans in battle.attacks:
            return  # planted mid-cast; his own motion owns his position
        battle.spawn_afterimage(sans)
        perp = pygame.Vector2(-state.atk_dir.y, state.atk_dir.x) * random.choice((-1, 1))
        sans.pos = _clamp_point(sans.pos + perp * DODGE_HOP_PX)

    def incoming_defense(self, attacker, defender, dmg):
        """Damage that skips the generic untargetable check (a
        resolve_special multi-hit, a contact-checked whirl) still whiffs
        while Sans is dodging that attacker's attack."""
        if defender is self.fighter and any(st.attacker is attacker for st in self._dodged):
            return 0
        return dmg

    def passive_gauge(self, fighter):
        if fighter is not self.fighter:
            return None
        return self.stamina / DODGE_STAMINA_MAX, f"DODGE {int(self.stamina)}/{DODGE_STAMINA_MAX}", SANS_BLUE

    # ---- passive: Karmic Retribution ------------------------------------------
    def add_karma(self, target, stacks):
        if target is self.fighter or target not in (self.battle.f1, self.battle.f2) or not target.is_alive():
            return
        s = target.statuses.get(KR_STATUS)
        if s is None:
            set_status(target, KR_STATUS, KR_DECAY_S, stacks=0, decay=KR_DECAY_S, shown=0.0, floater_cd=0.0)
            s = target.statuses[KR_STATUS]
        s["stacks"] = min(KR_MAX_STACKS, s["stacks"] + stacks)
        s["decay"] = KR_DECAY_S
        s["time"] = (s["stacks"] - 1) * KR_DECAY_S + s["decay"]

    def _tick_karma(self, target, dt):
        s = target.statuses.get(KR_STATUS)
        if s is None:
            return
        battle = self.battle
        if target.is_alive() and battle.winner is None:
            actual = battle.apply_damage(target, s["stacks"] * KR_DPS_PER_STACK * dt, ignore_armor=True)
            s["shown"] += actual
            s["floater_cd"] -= dt
            if s["floater_cd"] <= 0 and s["shown"] >= 1:
                battle.floaters.append([target.pos.x + 14, target.pos.y - 30, -0.4, 230,
                                        f"-{round(s['shown'])} KR", SANS_KARMA])
                s["shown"] -= round(s["shown"])
                s["floater_cd"] = KR_FLOATER_INTERVAL_S
        if not self._is_caged(target):
            s["decay"] -= dt
        if s["decay"] <= 0:
            s["stacks"] -= 1
            s["decay"] = KR_DECAY_S
        if s["stacks"] <= 0:
            target.statuses.pop(KR_STATUS, None)
        else:
            s["time"] = (s["stacks"] - 1) * KR_DECAY_S + s["decay"]

    def on_damage_dealt(self, attacker, defender, actual):
        state = self.battle._current
        if attacker is not self.fighter or state is None or state.attacker is not attacker:
            return
        stacks = KR_STACKS.get(state.ability.tag, 0)
        if stacks:
            self.add_karma(defender, stacks)

    # ---- skills -------------------------------------------------------------
    def resolve_special(self):
        battle, sans = self.battle, self.fighter
        if battle.attacker is not sans:
            return False
        tag = battle.ability.tag
        if tag == "sans_bone_wall":
            if battle.roll_blind_miss(sans):
                battle.swarm_projectiles = []
                battle.floaters.append([sans.pos.x, sans.pos.y - 50, -0.5, 255, "Blinded!", GRAY])
                battle.log = f"{sans.name}'s Bone Wall clatters to the floor — blinded!"
                return True
            battle.spawn_swarm_projectiles()
            sans.meter = min(sans.meter_max, sans.meter + sans.meter_gain)
            battle.log = f"{sans.name} raises a Bone Wall!"
            return True
        if tag == "sans_bad_time":
            self._ult_blasters = []
            battle.flash_timer = max(battle.flash_timer, 0.2)
            battle.log = f"{sans.name}: \"you're gonna have a bad time.\""
            return True
        return False

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        tag = ability.tag
        if tag == "sans_blue":
            self._blue_slam(defender)
        elif tag == "sans_shortcut":
            self._shortcut()
        elif tag == "sans_cage":
            self._cage(defender)
        elif tag == "sans_nap":
            self._nap()

    def _blue_slam(self, target):
        """Blue Soul: gravity takes hold and throws the target into the
        nearest wall, stunning it on impact."""
        battle = self.battle
        p = target.pos
        walls = [
            (p.x - BOUND_LEFT, pygame.Vector2(BOUND_LEFT, p.y)),
            (BOUND_RIGHT - p.x, pygame.Vector2(BOUND_RIGHT, p.y)),
            (p.y - BOUND_TOP, pygame.Vector2(p.x, BOUND_TOP)),
            (BOUND_BOTTOM - p.y, pygame.Vector2(p.x, BOUND_BOTTOM)),
        ]
        _, wall = min(walls, key=lambda w: w[0])
        start = pygame.Vector2(p)
        target.pos = wall
        set_status(target, "stunned", BLUE_STUN_S)
        battle.add_screen_shake(7, 0.22)
        battle.add_ring(wall, 70, 0.45, SANS_BLUE, width=4)
        emit_dust(battle.fx, wall, count=18)
        emit_spark_burst(battle.fx, start, SANS_BLUE, count=14)
        battle.floaters.append([wall.x, wall.y - 50, -0.5, 255, "Blue Soul!", SANS_BLUE])
        battle.log = f"{self.fighter.name} turns {target.name}'s soul blue — slammed into the wall!"

    def _cage(self, target):
        """Bone Cage: the bones snap shut — rooted, and KR frozen in place."""
        battle = self.battle
        set_status(target, "rooted", CAGE_ROOT_S)
        self._cage_target, self._cage_t = target, CAGE_ROOT_S
        battle.add_ring(target.pos, CAGE_RADIUS + 20, 0.35, WHITE, width=3)
        emit_dust(battle.fx, target.pos, count=12)
        battle.floaters.append([target.pos.x, target.pos.y - 55, -0.5, 255, "Caged!", WHITE])
        battle.log = f"{self.fighter.name} locks {target.name} in a Bone Cage — KR won't fade!"

    def _is_caged(self, target):
        return self._cage_t > 0 and target is self._cage_target and "rooted" in target.statuses

    def _shortcut(self):
        """Teleport to whichever sampled spot is farthest from the enemy and
        catch his breath (full STAMINA)."""
        battle, sans = self.battle, self.fighter
        enemy = self._opponent()
        spots = [pygame.Vector2(random.uniform(BOUND_LEFT, BOUND_RIGHT), random.uniform(BOUND_TOP, BOUND_BOTTOM))
                 for _ in range(SHORTCUT_SAMPLES)]
        dest = max(spots, key=lambda s: (s - enemy.pos).length_squared())
        battle.spawn_afterimage(sans)
        emit_dark(battle.fx, sans.pos, count=18, radius=30, color=SANS_BLUE)
        sans.pos = dest
        # "cast" pins the caster to attacker_start for the rest of the cast.
        battle.attacker_start = pygame.Vector2(dest)
        emit_dark(battle.fx, dest, count=18, radius=30, color=SANS_BLUE)
        self.stamina = float(DODGE_STAMINA_MAX)
        set_status(sans, "untargetable", SHORTCUT_UNTARGETABLE_S)
        sans.meter = min(sans.meter_max, sans.meter + sans.meter_gain)
        battle.floaters.append([dest.x, dest.y - 50, -0.5, 255, "heh.", WHITE])
        battle.log = f"{sans.name} takes a shortcut."

    def _nap(self):
        """Power Nap: heal over time and refill STAMINA fast, while still
        free to act and dodge."""
        battle, sans = self.battle, self.fighter
        set_status(sans, "regen", NAP_S, pct=NAP_REGEN_PCT)
        set_status(sans, NAP_STATUS, NAP_S)
        self._nap_floater_cd = NAP_FLOATER_INTERVAL_S
        battle.add_ring(sans.pos, 60, 0.4, SANS_BLUE, width=3)
        battle.floaters.append([sans.pos.x, sans.pos.y - 55, -0.4, 255, "zzz...", GRAY])
        battle.log = f"{sans.name} takes a power nap."

    # ---- ultimate: Bad Time ---------------------------------------------------
    def _phase_duration(self, name):
        return next((d for n, d in self.battle.seq if n == name), 0.0)

    def _ult_frame(self, phase, t):
        battle, sans = self.battle, self.fighter
        whirl = self._phase_duration("whirl")
        if phase == "whirl":
            elapsed = t * whirl
        elif phase == "release":
            elapsed = whirl + t * self._phase_duration("release")
        else:
            return
        enemy = battle.defender
        if enemy is None:
            return
        while len(self._ult_blasters) < ULT_BLASTERS and elapsed >= len(self._ult_blasters) * ULT_INTERVAL_S:
            i = len(self._ult_blasters)
            ang = i * 2.39996 + random.uniform(-0.3, 0.3)  # golden angle: never two on the same side
            pos = _clamp_point(enemy.pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * ULT_RING_R)
            self._ult_blasters.append({"pos": pos, "born": elapsed, "aim": None, "fired": False, "hit": False})
            emit_dark(battle.fx, pos, count=8, radius=24, color=WHITE)
        for bl in self._ult_blasters:
            age = elapsed - bl["born"]
            if not bl["fired"]:
                aim = enemy.pos - bl["pos"]
                bl["aim"] = aim.normalize() if aim.length_squared() > 0 else pygame.Vector2(1, 0)
                if age >= ULT_CHARGE_S:
                    bl["fired"] = True
                    self._ult_fire(bl, enemy)
        self._ult_elapsed = elapsed

    def _ult_fire(self, bl, enemy):
        battle, sans = self.battle, self.fighter
        battle.add_screen_shake(4, 0.12)
        if not enemy.is_alive():
            return
        if _ray_distance(bl["pos"], bl["aim"], enemy.pos) > enemy.hitbox_r + ULT_BEAM_HALF_W:
            return
        if battle.is_invulnerable(enemy) or battle.is_vanished(enemy) or battle.is_untargetable(enemy):
            battle.floaters.append([enemy.pos.x, enemy.pos.y - 50, -0.5, 255, "Evaded!", WHITE])
            return
        dmg = round(sans.atk * ULT_BEAM_MULT * battle.status_outgoing_multiplier(sans))
        actual = battle.deal_damage(sans, enemy, dmg)
        bl["hit"] = True
        # Lighter than apply_impact's ultimate tier on purpose: six beams
        # each triggering its hit-stop/zoom/flash would stall the whole volley.
        battle.add_screen_shake(6, 0.15)
        enemy.hit_flash = enemy.hit_flash_max = 0.12
        enemy.hit_flash_color = (200, 225, 255)
        enemy.hit_flash_heavy = enemy.hit_flash_crit = False
        enemy.visual_recoil += bl["aim"] * 6
        enemy.shake = max(enemy.shake, 14)
        emit_spark_burst(battle.fx, enemy.pos, WHITE, count=10)
        battle.floaters.append([enemy.pos.x + random.uniform(-12, 12), enemy.pos.y - 40, -0.6, 255,
                                f"-{actual} ULT!", GOLD])
        for p in battle.plugins:
            p.on_damage_dealt(sans, enemy, actual)

    # ---- per-frame ------------------------------------------------------------
    def attack_frame(self, attacker, ability, phase, t):
        state = self.battle._current
        if attacker is not self.fighter:
            self._judge_incoming(state)
            if state in self._dodged:
                set_status(self.fighter, "untargetable", DODGE_REFRESH_S)
                if state.damage_applied and state not in self._slid:
                    self._slip_away(state)
            return
        if ability.tag == "sans_bad_time":
            self._ult_frame(phase, t)

    def ambient_tick(self, dt):
        battle, sans = self.battle, self.fighter
        self._clock += dt
        live = set(battle.attacks.values())
        self._judged &= live
        self._dodged &= live
        self._slid &= live
        napping = NAP_STATUS in sans.statuses
        if not self._dodged:
            regen = dt / DODGE_REGEN_S * (NAP_STAMINA_MULT if napping else 1.0)
            self.stamina = min(DODGE_STAMINA_MAX, self.stamina + regen)
        if napping:
            self._nap_floater_cd -= dt
            if self._nap_floater_cd <= 0:
                self._nap_floater_cd = NAP_FLOATER_INTERVAL_S
                battle.floaters.append([sans.pos.x + 16, sans.pos.y - 50, -0.4, 220, "z", GRAY])
        self._dodge_pose_t = max(0.0, self._dodge_pose_t - dt)
        self._cage_t = max(0.0, self._cage_t - dt)
        if self._cage_target is not None and not self._is_caged(self._cage_target):
            self._cage_target, self._cage_t = None, 0.0
        self._tick_karma(self._opponent(), dt)
        sans.image = self._pose()

    # ---- presentation: sprite ---------------------------------------------------
    def _pose(self):
        """Pick the face (+ sweat) and its bob for this exact moment."""
        battle, sans = self.battle, self.fighter
        st = sans.statuses
        enemy = self._opponent()
        flip = enemy.pos.x < sans.pos.x
        sweat = (f"sweat/sweat_{int(self._clock * 5) % 3:02d}",) if self.stamina < 1 else ()
        bob = round(IDLE_BOB_PX * math.sin(self._clock * IDLE_BOB_SPEED))

        if not sans.is_alive():
            return compose("face/face_10", flip=flip, dy=4)
        if any(n in st for n in ("stunned", "frozen", "rooted", "curse", "feared")):
            return compose("wrapped_face/wrapped_face_00", flip=flip, dy=round(math.sin(self._clock * 30)))
        if "asleep" in st or (NAP_STATUS in st and sans not in battle.attacks and self._dodge_pose_t <= 0):
            return compose("face/face_04", sweat, flip=flip, dy=round(3 * math.sin(self._clock * 1.5)))

        state = battle.attacks.get(sans)
        if state is not None:
            pose = self._attack_pose(state)
            if pose is not None:
                face, dy = pose
                return compose(face, sweat, flip=state.atk_dir.x < 0, dy=dy)

        if self._dodge_pose_t > 0:
            return compose("face/face_02", sweat, flip=flip, dy=-4)
        low = sans.hp / sans.max_hp < LOW_HP_PCT
        if sans.hit_flash > 0:
            face = "face/face_07" if sans.hp / sans.max_hp < 0.5 else "face/face_03"
        elif self._clock % BLINK_PERIOD_S < BLINK_S:
            face = "face/face_04"
        else:
            face = "face/face_05" if low else "face/face_00"
        return compose(face, sweat, flip=flip, dy=bob)

    def _attack_pose(self, state):
        """(face, dy) for Sans's own attack: a little hop up on the windup,
        a dip as it goes off."""
        tag, phase, t = state.ability.tag, state.current_phase, state.phase_t
        flicker = int(self._clock * 10) % 2
        hop = -round(4 * math.sin(math.pi * t))
        if tag == "sans_bone":
            if phase == "windup":
                return "face/face_00", hop
            return ("face/face_03", 2) if phase in ("fire", "impact") else ("face/face_00", 0)
        if tag == "sans_bone_wall":
            return "face/face_12", hop if phase == "windup" else 0
        if tag == "sans_blue":
            eye = "face_blue_eye/face_blue_eye_00"
            if phase == "release":
                return eye, round(4 * t)
            return eye, -3
        if tag == "sans_blaster":
            return "face/face_05", hop if phase == "windup" else 2 * flicker
        if tag == "sans_shortcut":
            return "face/face_14", hop
        if tag == "sans_cage":
            return "face/face_02", hop if phase != "release" else 2
        if tag == "sans_nap":
            return "face/face_04", round(2 * t)
        if tag == "sans_bad_time":
            if phase == "release":
                return "face/face_04", 2
            return f"face_blue_eye/face_blue_eye_{flicker:02d}", -3 if phase == "whirl" else hop
        return None

    # ---- presentation: fx -------------------------------------------------------
    def draw_fx(self, screen, shake_x):
        battle, sans = self.battle, self.fighter
        offset = pygame.Vector2(shake_x, 0)
        if self._cage_target is not None:
            self._draw_cage(screen, self._cage_target.pos + offset, CAGE_RADIUS, 1.0)
        state = battle._current
        if state is None or state.attacker is not sans:
            self._blaster_pos = None
            return
        tag, phase, t = state.ability.tag, state.current_phase, state.phase_t
        if tag == "sans_cage" and phase in ("windup", "channel") and state.defender is not None:
            # windup + channel = the bones rising and closing in
            k = t * 0.33 if phase == "windup" else 0.33 + t * 0.67
            radius = CAGE_START_RADIUS + (CAGE_RADIUS - CAGE_START_RADIUS) * k
            self._draw_cage(screen, state.defender.pos + offset, radius, min(1.0, k * 2))
        elif tag == "sans_blue" and phase in ("windup", "channel") and battle.defender is not None:
            self._draw_blue_soul(screen, battle.defender.pos + offset, t if phase == "windup" else 1.0)
        elif tag == "sans_blaster":
            self._draw_skill_blaster(screen, phase, t, offset)
        elif tag == "sans_bad_time":
            self._draw_ult(screen, offset)

    def _draw_cage(self, screen, center, radius, grow):
        """A slowly turning ring of bones pointing outward from `center`."""
        length = max(4, round(CAGE_BONE_LEN * grow))
        bone = _bone(length)
        spin = self._clock * 0.8
        for i in range(CAGE_BONES):
            ang = spin + i * math.tau / CAGE_BONES
            d = pygame.Vector2(math.cos(ang), math.sin(ang))
            img = rotate_to_dir(bone, d)
            pos = center + d * radius
            screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))

    def _draw_blue_soul(self, screen, pos, strength):
        glow_ring(screen, pos, 26 + 6 * math.sin(self._clock * 12), SANS_BLUE, width=3, intensity=strength)
        heart = pos + pygame.Vector2(0, -44)
        s = 7
        pts = [(heart.x, heart.y + s), (heart.x - s, heart.y - s * 0.2), (heart.x - s * 0.5, heart.y - s),
               (heart.x, heart.y - s * 0.5), (heart.x + s * 0.5, heart.y - s), (heart.x + s, heart.y - s * 0.2)]
        pygame.draw.polygon(screen, SANS_BLUE, pts)
        add_dot(screen, heart, 14, SANS_BLUE, 0.6 * strength)

    def _draw_skill_blaster(self, screen, phase, t, offset):
        battle = self.battle
        if self._blaster_pos is None:
            d = battle.atk_dir
            side = pygame.Vector2(-d.y, d.x)
            self._blaster_pos = _clamp_point(battle.attacker_start + side * 42 - d * 14)
        target = battle.defender.pos if battle.defender is not None else battle.defender_start
        aim = target - self._blaster_pos
        aim = aim.normalize() if aim.length_squared() > 0 else pygame.Vector2(battle.atk_dir)
        if phase == "windup":
            frame, beam_t = 0, None
        elif phase == "channel":
            frame, beam_t = _frame(t, 3), None
        else:
            frame, beam_t = 3 + _frame(t, 3), t
        self._draw_blaster(screen, self._blaster_pos + offset, aim, frame, beam_t,
                           grow=min(1.0, t * 1.6) if phase == "windup" else 1.0)

    def _draw_ult(self, screen, offset):
        elapsed = self._ult_elapsed
        for bl in self._ult_blasters:
            age = elapsed - bl["born"]
            if not bl["fired"]:
                frame, beam_t = _frame(age / ULT_CHARGE_S, 3), None
            else:
                fire_age = age - ULT_CHARGE_S
                if fire_age > ULT_BEAM_S + 0.15:
                    continue
                frame, beam_t = 3 + _frame(fire_age / ULT_BEAM_S, 3), min(1.0, fire_age / ULT_BEAM_S)
            self._draw_blaster(screen, bl["pos"] + offset, bl["aim"], frame, beam_t,
                               grow=min(1.0, age / 0.12))

    def _draw_blaster(self, screen, pos, aim, frame, beam_t, grow=1.0):
        img = rotate_to_dir(_blaster(frame), aim)
        if grow < 1.0:
            w, h = img.get_size()
            img = pygame.transform.smoothscale(img, (max(1, round(w * grow)), max(1, round(h * grow))))
        mouth = pos + aim * (_blaster(0).get_height() * 0.42 * grow)
        if beam_t is None:
            add_dot(screen, mouth, 10 + 8 * grow, (190, 225, 255), 0.5 * grow)
        else:
            fade = max(0.0, 1.0 - beam_t)
            width = max(2, round(BEAM_WIDTH * (0.35 + 0.65 * fade)))
            end = mouth + aim * BEAM_LEN
            screen.set_clip(ARENA_RECT)
            glow_line(screen, mouth, end, (170, 215, 255), width=width, intensity=0.4 + 0.6 * fade)
            pygame.draw.line(screen, WHITE, mouth, end, max(1, width - 4))
            screen.set_clip(None)
        screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is not self.fighter:
            return False
        if battle.motion == "swarm":
            bone = _bone(battle.ability.swarm_size)
            for proj in battle.swarm_projectiles:
                if not proj["alive"] or proj["delay"] > 0:
                    continue
                v = proj["vel"]
                img = rotate_to_dir(bone, pygame.Vector2(-v.y, v.x))
                screen.blit(img, img.get_rect(center=(round(proj["pos"].x), round(proj["pos"].y))))
            return True
        if battle.ability.tag == "sans_bone" and battle.projectile_pos is not None:
            img = pygame.transform.rotate(_bone(22), self._clock * 900 % 360)
            pos = battle.projectile_pos
            screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))
            return True
        return False

    def full_screen_overlay(self, screen):
        """Bad Time dims the whole room while the blasters are out."""
        battle = self.battle
        state = battle.attacks.get(self.fighter)
        if state is None or state.ability.tag != "sans_bad_time" or state.current_phase == "release":
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 10, ULT_TINT_ALPHA))
        screen.blit(overlay, (0, 0))
