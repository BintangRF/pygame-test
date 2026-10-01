"""Johnny plugin: the shared Nail Bullet ammo pool spent by his basic attack
and every skill, the Spin Charge passive that builds Attack Up off his own
landed hits, Tusk Act 2's guaranteed-crit homing shot and bleed, Tusk Act 3's
ricocheting nail, Tusk Act 4's pin, and the nail/teleport animation (a
spinning Tusk spiral trailing every nail; no ground marks). Tusk itself (procedural, see tusk_sprite.py) floats over
Johnny's shoulder during each Tusk Act skill, with per-Act flourishes: Act 2's
fingertip spin, Act 3's spiral-hole portal, Act 4's Golden Spin, punch rush and
infinite-rotation ring on the pinned target. Spin Charge stacks orbit him as
small gold stars."""

import math
import random

import pygame

from ...core.anime_fx import build_muzzle_frames, draw_glow_texture
from ...core.constants import AVATAR_R, GOLD, NAIL_GLOW_BLUE, NAIL_SILVER, WHITE
from ...core.effects import draw_expanding_ring, draw_nail
from ...core.entities import set_status
from ...core.glow import glow_line, glow_polyline
from ...core.motions import ease_out
from ...core.particles import emit_debris, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .tusk_sprite import CREAM, OUTLINE, make_tusk_sprite, tusk_tip_offset, uses_png

CRIT_MULT = 3  # Tusk Act 2 always lands as a critical hit
NAIL_ABILITY_NAMES = ("Nail Bullet", "Tusk Act 2", "Tusk Act 3", "Tusk Act 4")
# The phase a nail actually leaves the finger in, per motion (bolt,
# homing_bolt, ricochet) — where draw_fx fires its muzzle flash.
SHOT_PHASES = ("fire", "chase", "flight")

# Spin Charge (passive): every landed nail — basic or skill alike — stacks
# rotational momentum onto Johnny himself, echoing how Tusk's power comes
# from the Spin technique building up through repeated, precise motion
# rather than any single shot. Refreshed (not just added to) on every hit,
# so it lapses on its own the moment he stops actually landing nails — same
# "use it or lose it" shape as Raiju's own Static passive
# (characters/raiju/plugin.py), just aimed at himself instead of a target.
# It also clears the instant the Nail Bullet clip itself runs dry (see
# consume_ammo below) — emptying the clip forces the charge back to zero,
# but the clip snaps straight back to full in trade, instead of the old
# one-shot-every-few-seconds trickle reload.
SPIN_CHARGE_MAX_STACKS = 20
SPIN_CHARGE_ATK_PCT_PER_STACK = 0.06
SPIN_CHARGE_DURATION_S = 10
# Tusk Act 3/4's ricocheting nail (see the "ricochet" motion): how fast it
# travels, and how many wall bounces it gets before giving up if it never
# touches the defender. Owned here (not a shared engine-wide constant) since
# CharacterPlugin.ricochet_speed/ricochet_max_bounces are per-character.
RICOCHET_SPEED = 3200
RICOCHET_MAX_BOUNCES = 15

# Tusk Act 2's bleed and Tusk Act 4's root duration.
TUSK_ACT2_BLEED_DURATION_S = 10
TUSK_ACT4_ROOT_DURATION_S = 5

# Presentation only: the Tusk spiral that corkscrews behind every nail in
# flight (see _draw_spiral_trail). The trail follows the nail's own recorded
# path (so it bends around Act 3's wall bounces), sampled every
# SPIRAL_STEP_PX, out to SPIRAL_TRAIL_LEN_PX behind the head. Each strand's
# radius widens from SPIRAL_AMP_HEAD_PX at the nail to SPIRAL_AMP_TAIL_PX at
# the tail (a drill cone, not a tube), winding once every
# SPIRAL_WAVELENGTH_PX, and the whole helix turns by SPIRAL_SPIN_PER_FRAME
# radians each frame.
SPIRAL_TRAIL_LEN_PX = 95
SPIRAL_STEP_PX = 4
SPIRAL_AMP_HEAD_PX = 3
SPIRAL_AMP_TAIL_PX = 8
SPIRAL_WAVELENGTH_PX = 34
SPIRAL_SPIN_PER_FRAME = 0.55
SPIRAL_HISTORY_MAX = 24

# ---- Tusk, the Stand itself (presentation only; see tusk_sprite.py) --------
# Which Act shows up for which ability, and how big each one is drawn.
# Act 1 backs up the basic Nail Bullet; Acts 2-4 are the named skills.
TUSK_ACT = {"Nail Bullet": 1, "Tusk Act 2": 2, "Tusk Act 3": 3, "Tusk Act 4": 4}
TUSK_SIZE = {1: 72, 2: 80, 3: 90, 4: 110}
# Tusk floats over Johnny's shoulder, on the side away from the target.
TUSK_OFFSET_BACK = 30
TUSK_OFFSET_UP = 50
TUSK_BOB_PX = 3
# Seconds Tusk takes to fade out once the skill is over.
TUSK_LINGER_S = 0.3
# Act 3's spiral hole portal under Johnny and its colors.
ACT3_PORTAL_SIZE = 84
ACT3_PORTAL_COLOR = (150, 110, 230)
# Act 4's Golden Spin: a glowing golden spiral behind Johnny while it charges,
# the punch flurry Tusk lands on the target, and the infinite-rotation ring
# that spins around the target for as long as it stays pinned.
GOLDEN_SPIN = (255, 205, 90)
PHI = (1 + 5 ** 0.5) / 2
GOLDEN_SPIRAL_SIZE = 78
ACT4_RUSH_FISTS = 7
ACT4_PIN_RING_SIZE = 96
# Spin Charge stacks drawn as small gold stars orbiting Johnny.
SPIN_ORBIT_RADIUS = AVATAR_R + 12
SPIN_ORBIT_SPEED = 2.4


class JohnnyPlugin(CharacterPlugin):
    #: Every hit he lands is a Stand-charged nail, so his hit effects glow
    #: the nail's own blue rather than the gold of his emblem ring.
    FX_COLOR = NAIL_GLOW_BLUE
    #: Hit-flash flare (anime_fx.build_impact_burst_frames): a spinning swirl.
    BURST_TEXTURE = "twirl_02"

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        # Presentation only: the nail's recorded flight path (newest last)
        # that the spiral trail is drawn along, which AttackState it belongs
        # to (a fresh shot starts a fresh trail), and the helix's own spin.
        self._trail = []
        self._trail_owner = None
        self._spiral_spin = 0.0
        # The attack a muzzle flash was last fired for (see draw_fx), so
        # each shot gets exactly one.
        self._muzzle_state = None
        # Tusk's on-screen state (see _draw_tusk): which Act was last out,
        # its last opacity/facing, and the game time it was last active, so
        # it fades out over TUSK_LINGER_S instead of popping away.
        self._time = 0.0
        self._tusk_act = None
        self._tusk_alpha = 0.0
        self._tusk_facing = 1
        self._tusk_last_t = -1.0
        # Whoever Tusk Act 4 last pinned (the infinite-rotation ring is drawn
        # around them while their "rooted" status lasts).
        self._pin_target = None

    # ---- Nail Bullet ammo pool ----------------------------------------------
    def ammo_ready(self, attacker, ability):
        if attacker is not self.fighter or ability.kind == "ultimate":
            return True
        return attacker.nail_bullets > 0

    def consume_ammo(self, attacker, ability):
        if attacker is not self.fighter or ability.kind == "ultimate":
            return
        attacker.nail_bullets -= 1
        if attacker.nail_bullets <= 0:
            # The clip runs dry: Spin Charge snaps back to zero, but the
            # tradeoff is the clip itself snaps straight back to full
            # instead of trickling back in one shot at a time.
            attacker.statuses.pop("spin_charge", None)
            attacker.statuses.pop("attack_up", None)
            attacker.nail_bullets = attacker.nail_bullets_max

    # ---- Tusk Act 3/4: ricocheting nail flight -----------------------------
    def ricochet_speed(self, attacker, ability):
        return RICOCHET_SPEED

    def ricochet_max_bounces(self, attacker, ability):
        return RICOCHET_MAX_BOUNCES

    # ---- passive: Spin Charge -----------------------------------------------
    def on_damage_dealt(self, attacker, defender, actual):
        """Every landed nail stacks Spin Charge on Johnny himself, capped at
        SPIN_CHARGE_MAX_STACKS — each stack refreshes the same generic Attack
        Up status (status_outgoing_multiplier already applies it to every hit
        he deals, so there's no bespoke outgoing_damage math here) worth
        SPIN_CHARGE_ATK_PCT_PER_STACK, for SPIN_CHARGE_DURATION_S. Missing
        with a shot lets the timer run out on its own instead of stacking
        further, same lapse behavior as Raiju's Static."""
        if attacker is not self.fighter or defender is None or actual <= 0:
            return
        cur = attacker.statuses.get("spin_charge", {})
        stacks = min(SPIN_CHARGE_MAX_STACKS, cur.get("stacks", 0) + 1)
        set_status(attacker, "spin_charge", SPIN_CHARGE_DURATION_S, stacks=stacks)
        set_status(attacker, "attack_up", SPIN_CHARGE_DURATION_S, pct=stacks * SPIN_CHARGE_ATK_PCT_PER_STACK)

    # ---- Tusk Act 2: homing crit + bleed -----------------------------------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is self.fighter and ability.tag == "tusk_act2":
            # Flags the generic critical-hit tier (impact_fx.py's
            # impact_tier/apply_impact) — also skips combat_resolution's own
            # generic crit roll for this same hit, so a guaranteed Tusk Act 2
            # crit never doubles up with a second, stacking multiplier.
            self.battle.crit = True
            return round(dmg * CRIT_MULT), note + " [CRITICAL]"
        return dmg, note

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "tusk_act2" and defender is not None and battle.damage_applied:
            # Status: bleed (DoT) — dps kwarg omitted so it falls back to
            # the canonical BLEED_BASE_DPS flat rate in status_library.py,
            # same as every other bleed source now.
            set_status(defender, "bleed", TUSK_ACT2_BLEED_DURATION_S)
            battle.log = f"{attacker.name}'s Tusk Act 2 rips into {defender.name} — bleeding!"
        elif tag == "tusk_act3" and defender is not None and battle.damage_applied:
            # Status: none — a pure ricochet hit, no status attached
            # A ricochet that actually connects — miss already got the
            # generic "whistles past" floater from do_damage(), so this only
            # ever fires on a landed hit.
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 60, -0.6, 255, "ACT 3!", NAIL_SILVER]
            )
            battle.log = f"{attacker.name}'s ricocheting Tusk Act 3 finds its mark!"
            battle.add_screen_shake(10, 0.16)
            battle.add_ring(defender.pos, 55, 0.32, NAIL_SILVER, width=3)
            emit_spark_burst(battle.fx, defender.pos, NAIL_SILVER, count=16)
        elif tag == "tusk_act4" and defender is not None:
            # Status: rooted (hard CC — movement only, can still fight back)
            set_status(defender, "rooted", TUSK_ACT4_ROOT_DURATION_S)
            self._pin_target = defender
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 70, -0.6, 255, "PINNED!", NAIL_SILVER]
            )
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 95, -0.8, 255, "ARI ARI ARI!", GOLDEN_SPIN]
            )
            battle.log = f"{attacker.name}'s Tusk Act 4 pins {defender.name} in place!"
            battle.flash_timer = max(battle.flash_timer, 0.42)
            battle.add_screen_shake(22, 0.3)
            battle.add_ring(defender.pos, 160, 0.7, NAIL_SILVER, width=6)
            emit_debris(battle.fx, defender.pos, count=36, speed=(60, 180))

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        """A ranged fighter's own hit effect: metal shrapnel from the nail
        itself, plus a quick Stand-glow ring flash marking the exact point
        of impact — every Johnny attack is a fired nail (see moves.py's own
        docstring), so the strike needs its own visible "punch" the way a
        melee swing's own cut mark already gets, not just a puff of debris."""
        emit_debris(self.battle.fx, pos, count=count)
        self.battle.add_ring(pos, 22, 0.18, NAIL_GLOW_BLUE, width=2)
        return True

    def ambient_tick(self, dt):
        self._time += dt

    def _record_trail(self):
        """Append the nail's current position to the spiral's path. A new
        AttackState means a new shot, so the old path is dropped; a nail
        that has stopped moving (held in place through "impact"/"settle")
        lets the trail reel itself in from the tail instead."""
        battle = self.battle
        if battle._current is not self._trail_owner:
            self._trail_owner = battle._current
            self._trail = []
        pos = pygame.Vector2(battle.projectile_pos)
        if self._trail and (pos - self._trail[-1]).length_squared() < 1:
            if len(self._trail) > 1:
                self._trail.pop(0)
            return
        self._trail.append(pos)
        if len(self._trail) > SPIRAL_HISTORY_MAX:
            self._trail.pop(0)

    def _sample_trail(self):
        """Walk the recorded path back from the nail, returning
        (point, unit tangent, distance-from-head) every SPIRAL_STEP_PX, out
        to SPIRAL_TRAIL_LEN_PX or the end of the path."""
        pts = self._trail[::-1]
        samples = []
        travelled, target = 0.0, 0.0
        for a, b in zip(pts, pts[1:]):
            seg = b - a
            seg_len = seg.length()
            if seg_len < 1e-6:
                continue
            tangent = -seg / seg_len  # points toward the head (direction of travel)
            while target <= travelled + seg_len and target <= SPIRAL_TRAIL_LEN_PX:
                samples.append((a + seg * ((target - travelled) / seg_len), tangent, target))
                target += SPIRAL_STEP_PX
            travelled += seg_len
            if target > SPIRAL_TRAIL_LEN_PX:
                break
        return samples

    def _draw_spiral_trail(self, screen, color):
        """Tusk's spin made visible: two interleaved strands corkscrewing
        around the nail's own path, widening into a cone toward the tail
        and fading out. The half of each turn swinging "behind" the path is
        drawn dimmer and thinner, which is what sells it as a 3D helix
        rather than two flat sine waves."""
        samples = self._sample_trail()
        if len(samples) < 3:
            return
        self._spiral_spin += SPIRAL_SPIN_PER_FRAME
        k = math.tau / SPIRAL_WAVELENGTH_PX
        for strand in (0.0,):
            prev = None
            for pt, tangent, dist in samples:
                frac = dist / SPIRAL_TRAIL_LEN_PX
                amp = SPIRAL_AMP_HEAD_PX + (SPIRAL_AMP_TAIL_PX - SPIRAL_AMP_HEAD_PX) * frac
                phase = dist * k - self._spiral_spin + strand
                normal = pygame.Vector2(-tangent.y, tangent.x)
                cur = pt + normal * (amp * math.sin(phase))
                front = math.cos(phase) > 0
                if prev is not None:
                    fade = 1.0 - frac
                    shade = 1.0 if front else 0.45
                    col = tuple(int(ch * fade * shade) for ch in color)
                    width = max(1, round((3 if front else 2) * fade + 0.5))
                    pygame.draw.line(screen, col, prev, cur, width)
                    if front and fade > 0.5:
                        pygame.draw.line(screen, WHITE, prev, cur, 1)
                prev = cur

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos
                and battle.ability.name in NAIL_ABILITY_NAMES):
            return False
        name = battle.ability.name
        # The spiral goes down first so the nail itself sits on top of it.
        self._record_trail()
        self._draw_spiral_trail(screen, NAIL_SILVER if name == "Tusk Act 4" else NAIL_GLOW_BLUE)
        # Every nail — fingernail bullets, not steel ones (see draw_nail) —
        # uses the same Stand-charged blue glow. Act 3 gets a bigger size:
        # it launches from wherever Johnny (moves_while_active) is
        # currently standing, so at the instant it's fired it's sitting
        # right on top of his own avatar, and needs the extra size to still
        # read clearly there, bounce after bounce.
        if name == "Tusk Act 3":
            # Its own live velocity orients it correctly on every bounce,
            # unlike the fixed attacker_start-relative direction every
            # other nail below uses.
            direction = battle.ricochet_vel if battle.ricochet_vel else (
                battle.projectile_pos - battle.attacker_start
            )
            draw_nail(screen, battle.projectile_pos, direction, NAIL_GLOW_BLUE)
        else:
            direction = battle.projectile_pos - battle.attacker_start
            draw_nail(screen, battle.projectile_pos, direction, NAIL_GLOW_BLUE)
        return True

    def draw_fx(self, screen, shake_x):
        """Always: the Spin Charge orbit around Johnny and Act 4's
        infinite-rotation ring on a pinned target. While a Tusk Act skill is
        out: Tusk itself over his shoulder (fading out after), each Act's
        own flourish (Act 2's fingertip spin, Act 3's spiral-hole portal,
        Act 4's Golden Spin and punch rush), plus one muzzle flash per shot
        and Act 4's radiating-nail pin burst."""
        battle, j = self.battle, self.fighter
        shake = pygame.Vector2(shake_x, 0)
        if j.is_alive():
            self._draw_spin_orbit(screen, j.pos + shake)
        self._draw_pin_ring(screen, shake)

        attacking = battle.mode == "attack" and battle.attacker is j
        name = battle.ability.name if attacking else None
        phase, t = (battle.current_phase, battle.phase_t) if attacking else (None, 0.0)
        act = TUSK_ACT.get(name)
        if act is not None:
            self._draw_act_fx(screen, shake, act, phase, t)
        self._draw_tusk(screen, shake, act, phase, t)
        if not attacking:
            return

        # One muzzle flash per shot, as the nail leaves the finger.
        if phase in SHOT_PHASES and battle._current is not self._muzzle_state:
            self._muzzle_state = battle._current
            d = battle.atk_dir
            heading = math.degrees(math.atan2(-d.y, d.x))
            battle.add_impact_stamp(j.pos + d * (AVATAR_R + 4), build_muzzle_frames(NAIL_GLOW_BLUE, 72, heading), 0.12)

        if name == "Tusk Act 4" and phase == "impact":
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            for i in range(8):
                ang = i * (math.pi / 4)
                nail_pos = center + pygame.Vector2(math.cos(ang), math.sin(ang)) * 30 * t
                draw_nail(screen, nail_pos, pygame.Vector2(math.cos(ang), math.sin(ang)), NAIL_SILVER, size=1.1)
            draw_expanding_ring(screen, center, 50 * t, NAIL_SILVER, width=4)

    # ---- Tusk ---------------------------------------------------------------
    def _facing(self):
        """+1 if the target is to Johnny's right, -1 if left (Tusk faces it)."""
        return 1 if self.battle.atk_dir.x >= 0 else -1

    def _tusk_anchor(self, shake, act, phase, t, facing):
        """Where Tusk floats: over Johnny's shoulder on the side away from
        the target, bobbing gently — except Act 4, which rushes over to the
        target through "impact" and drifts back through "settle"."""
        j = self.fighter
        home = (j.pos + shake + pygame.Vector2(-facing * TUSK_OFFSET_BACK, -TUSK_OFFSET_UP)
                + pygame.Vector2(0, math.sin(self._time * 4) * TUSK_BOB_PX))
        if act == 4 and phase in ("impact", "settle"):
            dest = pygame.Vector2(self.battle.defender_start) + shake + pygame.Vector2(-facing * 38, -8)
            if phase == "impact":
                return home.lerp(dest, ease_out(min(1.0, t * 2.5)))
            return dest.lerp(home, ease_out(t))
        return home

    @staticmethod
    def _tusk_tip(anchor, act, facing):
        """World position of the Act's fingertip/fist (see
        tusk_sprite.tusk_tip_offset — PNG art or procedural sprite)."""
        off = tusk_tip_offset(act, TUSK_SIZE[act])
        return anchor + pygame.Vector2(off.x * facing, off.y)

    def _draw_tusk(self, screen, shake, act, phase, t):
        """The Stand itself, faded in through "windup", out through "settle"
        and then over TUSK_LINGER_S, with a soft pink glow behind it."""
        if act is not None:
            alpha = min(1.0, t * 2) if phase == "windup" else (1 - t if phase == "settle" else 1.0)
            self._tusk_act, self._tusk_alpha = act, alpha
            self._tusk_facing, self._tusk_last_t = self._facing(), self._time
        else:
            if self._tusk_act is None:
                return
            act = self._tusk_act
            alpha = self._tusk_alpha * (1 - (self._time - self._tusk_last_t) / TUSK_LINGER_S)
            if alpha <= 0 or not self.fighter.is_alive():
                self._tusk_act = None
                return
        facing = self._tusk_facing
        anchor = self._tusk_anchor(shake, act, phase, t, facing)
        size = TUSK_SIZE[act]
        draw_glow_texture(screen, "light_01", anchor, size * 1.5, (255, 150, 210), fade=0.4 * alpha)
        img = make_tusk_sprite(act, size)
        # PNG art is front-facing (and Act 4's chest marks would read
        # backwards mirrored), so only the side-on procedural sprite flips.
        if facing < 0 and not uses_png(act):
            img = pygame.transform.flip(img, True, False)
        if alpha < 1:
            img = img.copy()
            img.set_alpha(int(255 * alpha))
        screen.blit(img, img.get_rect(center=(round(anchor.x), round(anchor.y))))

    def _draw_act_fx(self, screen, shake, act, phase, t):
        """Each Act's own flourish (drawn under Tusk itself)."""
        battle, j = self.battle, self.fighter
        facing = self._facing()
        anchor = self._tusk_anchor(shake, act, phase, t, facing)
        tip = self._tusk_tip(anchor, act, facing)
        if act == 2:
            # The nail spinning on Tusk's fingertip before it's loosed.
            if phase == "windup":
                draw_glow_texture(screen, "twirl_02", tip, 40 + 14 * t, NAIL_GLOW_BLUE, fade=0.6 + 0.4 * t,
                                  angle=-self._time * 1000)
                draw_glow_texture(screen, "star_04", tip, 22, WHITE)
            elif phase == "chase" and t < 0.25:
                draw_glow_texture(screen, "star_08", tip, 56, WHITE, fade=1 - t * 4)
        elif act == 3:
            # A spiral hole opening under Johnny, kept open while the nail flies.
            s = {"windup": ease_out(t), "flight": 1.0, "settle": 1 - t}.get(phase, 0.0)
            if s > 0.02:
                pos = j.pos + shake
                size = ACT3_PORTAL_SIZE * (0.4 + 0.6 * s)
                draw_glow_texture(screen, "twirl_03", pos, size, ACT3_PORTAL_COLOR, fade=s, angle=self._time * 420)
                draw_glow_texture(screen, "twirl_03", pos, size * 0.7, NAIL_GLOW_BLUE, fade=0.7 * s,
                                  angle=self._time * 420 + 180)
                draw_glow_texture(screen, "magic_02", pos, size * 1.15, ACT3_PORTAL_COLOR, fade=0.5 * s,
                                  angle=-self._time * 120)
        elif act == 4:
            # Golden Spin charging behind Johnny.
            s = {"windup": ease_out(t), "chase": 1.0, "impact": 1 - t}.get(phase, 0.0)
            if s > 0.02:
                pos = j.pos + shake
                draw_glow_texture(screen, "light_03", pos, 150 * s, GOLDEN_SPIN, fade=0.35 * s)
                self._draw_golden_spiral(screen, pos, GOLDEN_SPIRAL_SIZE * (0.6 + 0.4 * s), self._time * 2.5, s)
            if phase == "chase":
                draw_glow_texture(screen, "twirl_01", tip, 44, GOLDEN_SPIN, angle=-self._time * 900)
            elif phase == "impact" and t < 0.85:
                self._draw_rush(screen, pygame.Vector2(battle.defender_start) + shake, facing, 1 - t)

    def _draw_rush(self, screen, target, facing, fade):
        """Act 4's punch flurry: fists flickering in all over the target,
        each with a short golden speed streak. Re-rolled a few times a
        second (seeded off game time) so the barrage reads as a rapid rush."""
        rng = random.Random(int(self._time * 30))
        for _ in range(ACT4_RUSH_FISTS):
            p = target + pygame.Vector2(rng.uniform(-28, 28), rng.uniform(-28, 28))
            origin = p - pygame.Vector2(facing * rng.uniform(18, 32), rng.uniform(-6, 6))
            glow_line(screen, origin, p, GOLDEN_SPIN, width=2, intensity=0.8 * fade)
            pygame.draw.circle(screen, OUTLINE, p, 7)
            pygame.draw.circle(screen, CREAM, p, 5)
            draw_glow_texture(screen, "star_08", p, 26, WHITE, fade=fade)

    def _draw_golden_spiral(self, screen, center, size, spin, intensity):
        """A glowing golden (logarithmic, growth factor PHI per quarter turn)
        double spiral — the Golden Spin motif. `size` is the outer radius."""
        if intensity <= 0.02:
            return
        a = size / PHI ** 8
        for arm, k in ((0.0, 1.0), (math.pi, 0.55)):
            pts = []
            for i in range(60):
                theta = i / 59 * 4 * math.pi
                r = a * PHI ** (theta / (math.pi / 2))
                ang = theta + spin + arm
                pts.append(center + pygame.Vector2(math.cos(ang), math.sin(ang)) * r)
            glow_polyline(screen, pts, GOLDEN_SPIN, width=3, intensity=intensity * k)

    def _draw_pin_ring(self, screen, shake):
        """Act 4's infinite rotation: golden swirls spinning around the
        pinned target for as long as its "rooted" status lasts."""
        tgt = self._pin_target
        if tgt is None:
            return
        rooted = tgt.statuses.get("rooted")
        if rooted is None or not tgt.is_alive():
            self._pin_target = None
            return
        fade = min(1.0, rooted.get("time", 0.0))
        pos = tgt.pos + shake
        draw_glow_texture(screen, "twirl_01", pos, ACT4_PIN_RING_SIZE, GOLDEN_SPIN, fade=0.8 * fade,
                          angle=self._time * 360)
        draw_glow_texture(screen, "twirl_01", pos, ACT4_PIN_RING_SIZE * 0.78, NAIL_GLOW_BLUE, fade=0.6 * fade,
                          angle=self._time * 360 + 180)
        self._draw_golden_spiral(screen, pos, 30, -self._time * 4, 0.5 * fade)

    def _draw_spin_orbit(self, screen, pos):
        """Spin Charge made visible: one small gold star per stack orbiting
        Johnny."""
        stacks = self.fighter.statuses.get("spin_charge", {}).get("stacks", 0)
        for i in range(stacks):
            ang = self._time * SPIN_ORBIT_SPEED + i * math.tau / stacks
            p = pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * SPIN_ORBIT_RADIUS
            draw_glow_texture(screen, "star_04", p, 24, GOLD, fade=1.0)
