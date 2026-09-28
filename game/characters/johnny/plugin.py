"""Johnny plugin: the shared Nail Bullet ammo pool spent by his basic attack
and every skill, the Spin Charge passive that builds Attack Up off his own
landed hits, Tusk Act 2's guaranteed-crit homing shot and bleed, Tusk Act 3's
ricocheting nail, Tusk Act 4's pin, and the nail/teleport animation (a
spinning Tusk spiral trailing every nail, and a spiral-hole ground mark
wherever one lands)."""

import math

import pygame

from ...core.anime_fx import build_muzzle_frames
from ...core.constants import AVATAR_R, NAIL_GLOW_BLUE, NAIL_SILVER, WHITE
from ...core.effects import draw_expanding_ring, draw_nail
from ...core.entities import set_status
from ...core.particles import emit_debris, emit_spark_burst
from ...core.plugin import CharacterPlugin

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
SPIN_CHARGE_MAX_STACKS = 7
SPIN_CHARGE_ATK_PCT_PER_STACK = 0.1
SPIN_CHARGE_DURATION_S = 15
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
# The Tusk drill hole left in the ground where a nail lands (see
# _add_spiral_hole): its radius and how long it lingers (fading over its
# last second, like every other decal). Same "tusk" shape as Johnny's
# big-hit ground crack (GROUND_DECAL), just smaller.
SPIRAL_HOLE_RADIUS = 26
SPIRAL_HOLE_DURATION_S = 5.0
# Minimum seconds between two drill holes, so a volley doesn't carpet the floor.
SPIRAL_HOLE_COOLDOWN_S = 2.0


class JohnnyPlugin(CharacterPlugin):
    #: Ground crack this fighter's big hits leave (anime_fx.DECAL_STYLES):
    #: a Tusk drill hole, in the nails' own blue rather than Johnny's green
    #: so it matches the per-nail holes and the spiral trail.
    GROUND_DECAL = "tusk"
    GROUND_DECAL_COLOR = NAIL_GLOW_BLUE
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
        # Seconds (game time, see ambient_tick) until another drill hole
        # may be bored (see _add_spiral_hole).
        self._hole_cd = 0.0
        # The attack a muzzle flash was last fired for (see draw_fx), so
        # each shot gets exactly one.
        self._muzzle_state = None

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
        # Presentation only: bore a drill hole where a Tusk Act nail went
        # in. Not the rapid-fire basic Nail Bullet, or the floor fills up.
        ability = self.battle.ability
        if ability is not None and ability.name in NAIL_ABILITY_NAMES and ability.kind != "basic":
            self._add_spiral_hole(defender)

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
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 70, -0.6, 255, "PINNED!", NAIL_SILVER]
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
        self._hole_cd = max(0.0, self._hole_cd - dt)

    def _add_spiral_hole(self, defender):
        """Leave a small Tusk drill-hole decal where a nail just landed.
        Set just in front of the target on the side the nail came in from
        (Act 3's live bounce velocity, else the line from where the shot
        started), so it reads right away instead of hiding under the body
        until the target moves off it."""
        battle = self.battle
        if self._hole_cd > 0:
            return
        self._hole_cd = SPIRAL_HOLE_COOLDOWN_S
        incoming = battle.ricochet_vel if battle.ability.name == "Tusk Act 3" and battle.ricochet_vel else (
            defender.pos - battle.attacker_start
        )
        pos = pygame.Vector2(defender.pos)
        if incoming.length_squared() > 0:
            pos -= incoming.normalize() * (defender.image.get_width() / 2)
        battle.add_decal(pos, "tusk", NAIL_GLOW_BLUE, SPIRAL_HOLE_RADIUS, duration=SPIRAL_HOLE_DURATION_S)

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
        """Tusk Act 4 telegraphs its pin with a burst of nails radiating out
        from the impact point. Tusk Act 3's ricocheting nail is drawn
        generically by draw_projectile above — a landed hit gets its own
        screen-shake/ring/spark flourish from apply_tag_effects, so it needs
        nothing bespoke here."""
        battle, j = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is j):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t

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
