"""The per-frame simulation tick: ambient background particles, cooldowns,
roaming movement, status/zone ticks, ambient status-flavor particles
(Eternal Night motes, Berserker Rage embers), and the attack-sequence phase
machine — `apply_motion_frame` maps each ability's motion phases (from
motions.py) onto the attacker's actual position and any shared per-motion
bookkeeping like projectile position or afterimage trails.
"""

import math
import random

import pygame

from .constants import ARENA_RECT, CHARACTER_HITBOX_R
from .entities import bounce_move, set_status
from .motions import MOTIONS, RESOLVE_PHASE, ease_in, ease_in_out, ease_out, is_dodgeable
from .particles import emit_dark, emit_debris


class BattleLoopMixin:
    MAX_FLOATERS = 30
    # how much a non-owner's roam speed is cut while standing inside each
    # zone kind — Sacred Ground slows harder than Blood Pool/Static Field
    ZONE_SLOW_MULT = {"sacred": 0.3, "blood": 0.5, "static": 0.5}
    # Tusk Act 3's ricocheting nail (see the "ricochet" motion): how fast it
    # travels, and how many wall bounces it gets before giving up if it
    # never touches the defender.
    RICOCHET_SPEED = 900
    RICOCHET_MAX_BOUNCES = 5

    def update_particles(self, dt_ms):
        dt = dt_ms / 1000
        for p in self.particles:
            p["pos"] += p["vel"] * dt
            if p["pos"].y > ARENA_RECT.bottom:
                p["pos"].y = ARENA_RECT.top
                p["pos"].x = random.uniform(ARENA_RECT.left, ARENA_RECT.right)
            if p["pos"].x < ARENA_RECT.left:
                p["pos"].x = ARENA_RECT.right
            elif p["pos"].x > ARENA_RECT.right:
                p["pos"].x = ARENA_RECT.left

    # ---- update -----------------------------------------------------------------
    def update(self, dt_ms):
        self.update_particles(dt_ms)
        self.update_camera_shake(dt_ms)
        self.update_afterimages(dt_ms)
        self.update_rings(dt_ms)
        self.fx.update(dt_ms)
        for f in (self.f1, self.f2):
            f.display_hp += (f.hp - f.display_hp) * min(1.0, dt_ms / 150)
            f.shake *= 0.85
            f.visual_recoil *= 0.8
            f.hit_flash = max(0.0, f.hit_flash - dt_ms)
            f.scale_x += (1.0 - f.scale_x) * min(1.0, dt_ms / 140)
            f.scale_y += (1.0 - f.scale_y) * min(1.0, dt_ms / 140)
            if f is self.vampire and f.hp / f.max_hp < 0.3:
                speed_boost = 1.3
            elif f is self.berserker and "rage" in f.statuses:
                speed_boost = self.BERSERKER_RAGE_ATTACK_SPEED
            else:
                speed_boost = 1.0
            for ab in f.abilities["skills"] + [f.abilities["basic"], f.abilities["ultimate"]]:
                ab.timer = max(0, ab.timer - dt_ms * speed_boost)
            self.tick_dots(f, dt_ms)
            self.johnny_reload_tick(f, dt_ms)
            self.tick_statuses(f, dt_ms)

        if self.hit_stop_timer > 0:
            self.hit_stop_timer = max(0, self.hit_stop_timer - dt_ms)

        if self.time_scale < 1.0:
            self.time_scale = min(1.0, self.time_scale + dt_ms / self.TIME_SCALE_RECOVER_MS)

        if self.zoom > 1.0:
            self.zoom += (1.0 - self.zoom) * min(1.0, dt_ms / 260)

        if self.clone is not None:
            self.clone.time_left -= dt_ms
            self.clone.shake *= 0.85
            self.clone.scale_x += (1.0 - self.clone.scale_x) * min(1.0, dt_ms / 140)
            self.clone.scale_y += (1.0 - self.clone.scale_y) * min(1.0, dt_ms / 140)
            bounce_move(self.clone, dt_ms)
            if self.clone.time_left <= 0:
                self.clone = None

        if self.night_timer > 0:
            self.night_timer = max(0, self.night_timer - dt_ms)
            self.night_particle_cd -= dt_ms
            if self.night_particle_cd <= 0 and self.vampire is not None:
                emit_dark(self.fx, self.vampire.pos, count=4, radius=70)
                self.night_particle_cd = 55
        if self.flash_timer > 0:
            self.flash_timer = max(0, self.flash_timer - dt_ms)

        if self.berserker is not None and "rage" in self.berserker.statuses:
            self.rage_particle_cd -= dt_ms
            if self.rage_particle_cd <= 0:
                emit_debris(self.fx, self.berserker.pos, count=4, speed=(30, 90))
                self.rage_particle_cd = 65

        self.update_zones(dt_ms)

        for fl in self.floaters:
            fl[1] += fl[2] * dt_ms
            fl[3] -= dt_ms * 0.35
        self.floaters = [fl for fl in self.floaters if fl[3] > 0][-self.MAX_FLOATERS:]

        if self.mode == "gameover":
            return
        if self.mode == "roam":
            self.update_roam(dt_ms)
            # No pacing gate: try to fire the instant anything is ready.
            # start_attack()/choose_ability() are cheap no-ops when nothing
            # qualifies, so this is safe to call every frame.
            self.start_attack()
        elif self.mode == "attack":
            self.update_attack(dt_ms)

    def update_roam(self, dt_ms):
        for f in (self.f1, self.f2):
            self.roam_step(f, dt_ms)

    def roam_step(self, f, dt_ms):
        """Move a single fighter one roam-tick's worth (bounce_move, scaled by
        its own speed multiplier and whatever's standing in its way). Shared
        by update_roam (both fighters, every frame in "roam" mode) and
        update_attack's Nail Bullet dodge window (just the defender, while
        the attacker is mid-animation — see johnny_dodge_window in
        combat_resolution.py for why only that one shot lets this happen)."""
        if not f.is_alive():
            return
        if f.statuses.get("rooted") or self.is_stunned(f):
            return  # pinned (Tusk Act 4) or stunned — no roam movement at all
        mult = f.move_speed_mult
        if f is self.vampire and self.night_timer > 0:
            mult *= 1.4
            self.night_afterimage_cd -= dt_ms
            if self.night_afterimage_cd <= 0:
                self.spawn_afterimage(f)
                self.night_afterimage_cd = 140
        if f is self.berserker and "rage" in f.statuses:
            mult *= 3.0
        for z in self.zones:
            if z.owner is not f and (f.pos - z.center).length() <= z.radius:
                mult *= self.ZONE_SLOW_MULT.get(z.kind, 0.5)
        bounce_move(f, dt_ms, mult)

    def ricochet_step(self, dt_ms):
        """Advance Tusk Act 3's bouncing nail one tick: straight-line motion
        that reflects off the arena's actual walls (ARENA_RECT, not the
        character-radius-inset BOUND_* used for fighters, since the nail
        itself has no radius) — same DVD-logo idea as bounce_move, just on
        self.ricochet_pos/vel instead of a Character, and counting bounces
        toward RICOCHET_MAX_BOUNCES instead of bouncing forever."""
        dt = dt_ms / 1000
        self.ricochet_pos += self.ricochet_vel * dt
        bounced = False
        if self.ricochet_pos.x < ARENA_RECT.left:
            self.ricochet_pos.x = ARENA_RECT.left
            self.ricochet_vel.x *= -1
            bounced = True
        elif self.ricochet_pos.x > ARENA_RECT.right:
            self.ricochet_pos.x = ARENA_RECT.right
            self.ricochet_vel.x *= -1
            bounced = True
        if self.ricochet_pos.y < ARENA_RECT.top:
            self.ricochet_pos.y = ARENA_RECT.top
            self.ricochet_vel.y *= -1
            bounced = True
        elif self.ricochet_pos.y > ARENA_RECT.bottom:
            self.ricochet_pos.y = ARENA_RECT.bottom
            self.ricochet_vel.y *= -1
            bounced = True
        if bounced:
            self.ricochet_bounces += 1

    def update_camera_shake(self, dt_ms):
        self.camera_shake.update(dt_ms)

    def update_afterimages(self, dt_ms):
        for ai in self.afterimages:
            ai["alpha"] -= dt_ms * 0.7
        self.afterimages = [ai for ai in self.afterimages if ai["alpha"] > 0]

    def update_rings(self, dt_ms):
        for r in self.rings:
            r["elapsed"] += dt_ms
        self.rings = [r for r in self.rings if r["elapsed"] < r["duration"]]

    def toggle_debug(self):
        self.debug = not self.debug

    def update_attack(self, dt_ms):
        if self.hit_stop_timer > 0:
            return  # animation freezes; camera shake/particles keep going via update()
        dt_ms *= self.time_scale  # ultimates dip into slow motion around their impact

        if is_dodgeable(self.ability):
            # Every other move freezes the defender mid-animation (it's
            # always going to land on strike_point/defender_start regardless).
            # A dodgeable shot doesn't home in — it flies to where the
            # defender *was* standing — so letting them keep drifting on
            # their current bounce heading is what makes it possible (not
            # guaranteed) to have wandered clear by impact; see the
            # evade-radius check in do_damage().
            self.roam_step(self.defender, dt_ms)

        phase_name, duration = self.seq[self.seq_index]
        self.current_phase = phase_name
        self.phase_elapsed += dt_ms
        t = min(1.0, self.phase_elapsed / duration)
        self.phase_t = t

        self.apply_motion_frame(phase_name, t, dt_ms)

        resolve_phase = RESOLVE_PHASE.get(self.motion)
        if phase_name == resolve_phase and not self.damage_applied:
            self.resolve_ability()
            self.damage_applied = True

        if self.phase_elapsed >= duration:
            self.seq_index += 1
            self.phase_elapsed = 0
            if self.seq_index >= len(self.seq):
                # Every existing motion already ends back at attacker_start
                # via its own "return"/"settle" animation, so snapping here
                # is normally a no-op cleanup — except Tusk Act 3, which
                # teleports Johnny to attack_final_pos (the wall-impact
                # point) and must NOT be dragged back to where he started. A
                # dodgeable shot (Nail Bullet) is the other exception, in the
                # other direction: the attacker's been roam_step-ing the
                # whole animation (see apply_motion_frame's "bolt" branch)
                # and was never anchored to attacker_start to begin with, so
                # snapping here would teleport him backwards mid-stride.
                if not self.ability.moves_while_active:
                    self.attacker.pos = pygame.Vector2(self.attack_final_pos)
                self.finish_attack()

    def apply_motion_frame(self, phase, t, dt_ms):
        a = self.attacker
        amp = 1.4 if self.ability.big else 1.0

        if self.ability.moves_while_active:
            # This ability needs no dash-in, no committed firing stance — its
            # user just keeps doing the same plain linear DVD-logo bounce
            # roam as always (see roam_step), instead of freezing/leaning
            # in place like every other attack's motion branch below does.
            # Whatever's motion-specific below (a projectile's own path,
            # mostly) still runs on top of that.
            self.roam_step(a, dt_ms)

        if self.motion == "melee_dash":
            if phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 8 * ease_out(t)
            elif phase == "strike":
                a.pos = self.attacker_start.lerp(self.strike_point, ease_in(t))
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                a.pos = self.strike_point.lerp(self.attacker_start, ease_out(t))

        elif self.motion == "melee_slam":
            height = 95 * amp
            if phase == "windup":
                lean_ease = ease_in_out if self.ability.big else ease_out
                a.pos = self.attacker_start - self.atk_dir * 10 * lean_ease(t)
            elif phase == "arc":
                base = self.attacker_start.lerp(self.strike_point, t)
                a.pos = base + pygame.Vector2(0, -height * math.sin(math.pi * t))
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                base = self.strike_point.lerp(self.attacker_start, t)
                a.pos = base + pygame.Vector2(0, -height * 0.4 * math.sin(math.pi * t))

        elif self.motion == "spin":
            spin_speed = {"windup": 0.015, "spin_travel": 0.045,
                          "impact": 0.03, "return": 0.02}.get(phase, 0.02)
            a.spin_angle += dt_ms * spin_speed
            perp = pygame.Vector2(-self.atk_dir.y, self.atk_dir.x)
            if phase == "windup":
                a.pos = pygame.Vector2(self.attacker_start)
            elif phase == "spin_travel":
                main = self.attacker_start.lerp(self.strike_point, t)
                wobble = perp * math.sin(t * 3 * math.pi) * 22 * amp * (1 - t)
                a.pos = main + wobble
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                a.pos = self.strike_point.lerp(self.attacker_start, t)

        elif self.motion == "bolt":
            if self.ability.moves_while_active:
                # Attacker's position was already handled by roam_step above
                # (Nail Bullet — the only "bolt" user that doesn't freeze in
                # place); this just animates the nail itself.
                if phase == "windup":
                    self.projectile_pos = None
                else:
                    # On a genuine miss the nail doesn't stop dead at
                    # defender_start — it keeps sailing on the same straight
                    # line at the same speed it had during "fire", through
                    # impact and settle, until it exits the arena, so a
                    # dodge reads as "the nail flew past" instead of "it
                    # vanished in place". A confirmed hit is the opposite:
                    # like a homing shot's impact, it just stops and
                    # disappears right there — no reason to keep flying
                    # through someone it already landed on.
                    if phase == "fire" and self.projectile_origin is None:
                        self.projectile_origin = pygame.Vector2(a.pos)
                        self.projectile_travel_ms = 0.0
                    if self.projectile_origin is not None:
                        self.projectile_travel_ms += dt_ms
                        fire_ms = dict(MOTIONS["bolt"])["fire"]
                        travel_t = self.projectile_travel_ms / fire_ms
                        flight = self.defender_start - self.projectile_origin
                        pos = self.projectile_origin + flight * travel_t
                        if self.projectile_hit_confirmed or not ARENA_RECT.collidepoint(pos):
                            self.projectile_pos = None
                            self.projectile_origin = None  # gone — stop tracking
                        else:
                            self.projectile_pos = pos
                            # The real hit-box check: every frame the nail is
                            # actually in flight, see if it's touching the
                            # defender's *current* position (not the stale
                            # aim point) — the instant it does, lock the hit
                            # in for do_damage() to read at resolve time (and
                            # for next frame's check above to stop the nail),
                            # so a genuine mid-flight touch can never later
                            # be reported as a miss just because the
                            # defender kept drifting afterward.
                            if (
                                is_dodgeable(self.ability) and not self.attack_target_clone
                                and self.defender is not None
                                and (pos - self.defender.pos).length() <= CHARACTER_HITBOX_R
                            ):
                                self.projectile_hit_confirmed = True
                    else:
                        self.projectile_pos = None
            elif phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 10 * math.sin(math.pi * t)
                self.projectile_pos = None
            elif phase == "fire":
                a.pos = pygame.Vector2(self.attacker_start)
                self.projectile_pos = self.attacker_start.lerp(self.defender_start, t)
            elif phase == "impact":
                a.pos = pygame.Vector2(self.attacker_start)
                self.projectile_pos = None
            elif phase == "settle":
                a.pos = self.attacker_start + self.atk_dir * 4 * math.sin(math.pi * t)
                self.projectile_pos = None

        elif self.motion == "cast":
            a.pos = pygame.Vector2(self.attacker_start)
            a.pos.y -= 4 * math.sin(math.pi * t)

        elif self.motion == "instant_cut":
            # no dash, no projectile — Sukuna barely leans in, and the cut
            # itself appears directly on the target (see draw_sukuna_effects)
            if phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 6 * math.sin(math.pi * t)
            else:
                a.pos = pygame.Vector2(self.attacker_start)

        elif self.motion == "swarm":
            if phase == "scatter":
                jitter = pygame.Vector2(random.uniform(-14, 14), random.uniform(-14, 14))
                a.pos = self.attacker_start + jitter
                set_status(a, "untargetable", 250)
            elif phase == "reposition":
                a.pos = self.attacker_start.lerp(self.strike_point, ease_in(t))
                set_status(a, "untargetable", 250)
            elif phase == "strike":
                a.pos = pygame.Vector2(self.strike_point)

        elif self.motion == "claw":
            # Berserker rakes in place — no dash toward the target, just a
            # small weight-shift as each claw swipe lands, like an animal
            # clawing rather than lunging.
            perp = pygame.Vector2(-self.atk_dir.y, self.atk_dir.x)
            if phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 6 * ease_out(t)
            elif phase == "slash1":
                a.pos = self.attacker_start + perp * 4 * math.sin(math.pi * t)
            elif phase == "slash2":
                a.pos = self.attacker_start - perp * 4 * math.sin(math.pi * t)
            elif phase == "return":
                a.pos = pygame.Vector2(self.attacker_start)

        elif self.motion == "flicker_slash":
            # a true teleport, not a lerp: Raiju disappears at the start
            # point and reappears already at striking distance (see
            # draw_fighter's is_flicker_hidden for the vanish/reappear
            # visual), only dashing back smoothly on the way out.
            if phase in ("vanish", "reappear"):
                a.pos = pygame.Vector2(self.attacker_start if phase == "vanish" else self.strike_point)
            elif phase == "strike":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                a.pos = self.strike_point.lerp(self.attacker_start, ease_out(t))

        elif self.motion == "sky_strike":
            # Raiju barely moves — this is a ritual call to the storm, not a
            # melee approach; the sky bolt itself lands on the target (see
            # draw_raiju_effects).
            a.pos = pygame.Vector2(self.attacker_start)
            a.pos.y -= 6 * math.sin(math.pi * min(1.0, t))

        elif self.motion == "homing_bolt":
            # Johnny stays put and fires — the nail does the moving, and
            # unlike "bolt" it keeps re-aiming at the defender's *live*
            # position every frame instead of a fixed point (true homing).
            if phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 10 * math.sin(math.pi * t)
                self.projectile_pos = None
            elif phase == "chase":
                a.pos = pygame.Vector2(self.attacker_start)
                live_target = self.defender.pos if self.defender is not None else self.defender_start
                self.projectile_pos = self.attacker_start.lerp(live_target, ease_in(t))
            else:
                a.pos = pygame.Vector2(self.attacker_start)
                self.projectile_pos = None

        elif self.motion == "ricochet":
            # Tusk Act 3: attacker's position was already handled by
            # roam_step above (moves_while_active — no dash-in, no
            # teleport). This just animates the nail: it launches on
            # windup's heading and bounces off the arena walls like a DVD
            # logo (ricochet_step), checking the defender's hit-box every
            # frame it's alive, until either it touches them (vanish
            # immediately, same rule as Nail Bullet) or it burns through its
            # bounce budget (fizzles out unseen for the rest of the phase).
            if phase == "windup":
                self.projectile_pos = None
            elif phase == "flight":
                if self.ricochet_pos is None:
                    self.ricochet_pos = pygame.Vector2(a.pos)
                    self.ricochet_vel = pygame.Vector2(self.atk_dir) * self.RICOCHET_SPEED
                    self.ricochet_bounces = 0
                if self.projectile_hit_confirmed or self.ricochet_bounces >= self.RICOCHET_MAX_BOUNCES:
                    self.projectile_pos = None
                else:
                    self.ricochet_step(dt_ms)
                    self.projectile_pos = pygame.Vector2(self.ricochet_pos)
                    if (
                        self.defender is not None
                        and (self.ricochet_pos - self.defender.pos).length() <= CHARACTER_HITBOX_R
                    ):
                        self.projectile_hit_confirmed = True
            else:
                self.projectile_pos = None

        trailing_phase = (
            (self.motion == "melee_dash" and phase == "strike")
            or (self.motion == "melee_slam" and phase in ("arc", "impact"))
            or (self.motion == "spin" and phase == "spin_travel")
            or (self.motion == "claw" and phase in ("slash1", "slash2"))
            or (self.motion == "flicker_slash" and phase == "return")
        )
        if trailing_phase:
            self.afterimage_cd -= dt_ms
            if self.afterimage_cd <= 0:
                self.spawn_afterimage(a)
                self.afterimage_cd = 25
