"""The per-frame simulation tick: ambient background particles, cooldowns,
roaming movement, status/zone ticks, ambient status-flavor particles (via
each plugin's ambient_tick), and the attack-sequence phase machine —
`apply_motion_frame` maps each ability's motion phases (from motions.py)
onto the attacker's actual position and any shared per-motion bookkeeping
like projectile position or afterimage trails. Every roam/attack-speed
bonus is read from self.plugins (core/plugin.py) instead of naming
characters, via plugin_for(f) or a chained loop.
"""

import math
import random

import pygame

from .constants import ARENA_RECT, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, CHARACTER_HITBOX_R, WHITE
from .entities import bounce_move, resolve_character_collision
from .motions import RESOLVE_PHASE, ease_in, ease_in_out, ease_out, is_dodgeable
from .particles import emit_dark, emit_debris


class BattleLoopMixin:
    # Raised from 30 alongside the longer floater lifetime below and the new
    # periodic DoT floaters (status_library._accrue_dot_floater) — both put
    # more floaters on screen at once, so the cap needs headroom to match or
    # a busy multi-DoT fight would start dropping the oldest ones early.
    MAX_FLOATERS = 45
    # Stretches every floater's lifetime to ~1.3s (255 alpha / (1000*0.2)),
    # up from the original ~0.7s, so damage/DoT numbers stay legible a bit
    # longer without lingering (0.11 was tried and felt like it overstayed).
    # FLOATER_RISE_SCALE is cut way down separately (not just to match the
    # longer life) so the number drifts only a short distance overall — a
    # subtle rise-and-settle instead of sliding most of the way up the
    # screen. draw_floaters (hud.py) layers the sway/shrink on top of this
    # same alpha-driven life progress.
    FLOATER_FADE_RATE = 0.2
    FLOATER_RISE_SCALE = 0.035

    # Ability.tag == "swarm" (Vampire's Bat Swarm today, reusable by any
    # future character's own multi-projectile ability) — fallback defaults
    # for how many individual projectiles a barrage launches and how fast
    # each one actually flies (px/s — deliberately more leisurely than
    # BOLT_SPEED's 800: a swarm should read as surrounding the target, not as
    # a single fast shot). Each ability can override either via its own
    # swarm_count/swarm_speed (see abilities.py) instead of every character's
    # swarm sharing one identical feel; these only apply when it leaves them
    # unset.
    SWARM_PROJECTILE_COUNT = 10
    SWARM_PROJECTILE_SPEED = 300
    # swarm_pattern="fan"'s own default total spread (degrees) when an
    # ability leaves its own swarm_fan_deg unset — see abilities.py.
    SWARM_FAN_DEG_DEFAULT = 40
    # "staggered"/"random" timing (see Ability.swarm_timing) spreads each
    # projectile's own launch delay across a window sized to this fraction
    # of "time to cross the arena's width once at this ability's own speed"
    # — a stable reference to scale off (unlike the barrage phase's own
    # duration, which is now derived FROM these delays plus each
    # projectile's flight time — see spawn_swarm_projectiles — so it can't
    # be the thing delays are sized against without a circular dependency).
    SWARM_TIMING_WINDOW_RATIO = 0.4

    def update_particles(self, dt):
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
    def update(self, dt):
        self.update_particles(dt)
        self.update_camera_shake(dt)
        self.update_afterimages(dt)
        self.update_rings(dt)
        self.fx.update(dt)
        for f in (self.f1, self.f2):
            f.display_hp += (f.hp - f.display_hp) * min(1.0, dt / 0.15)
            f.shake *= 0.85
            f.visual_recoil *= 0.8
            self.decay_launch_speed(f, dt)
            f.hit_flash = max(0.0, f.hit_flash - dt)
            f.scale_x += (1.0 - f.scale_x) * min(1.0, dt / 0.14)
            f.scale_y += (1.0 - f.scale_y) * min(1.0, dt / 0.14)
            # Fully invisible while vanished (movement is untouched — this
            # only ever affects render.py's draw_fighter), not just faint.
            vanish_target = 0.0 if "vanished" in f.statuses else 255.0
            f.vanish_alpha += (vanish_target - f.vanish_alpha) * min(1.0, dt / 0.09)
            speed_boost = 1.0
            for plugin in self.plugins:
                speed_boost *= plugin.attack_speed_multiplier(f)
            speed_boost *= self.status_attack_speed_multiplier(f)
            for ab in f.abilities["skills"] + [f.abilities["basic"], f.abilities["ultimate"]]:
                ab.timer = max(0, ab.timer - dt * speed_boost)
            self.tick_library_effects(f, dt)
            self.tick_statuses(f, dt)

        for plugin in self.plugins:
            plugin.ambient_tick(dt)

        if self.zoom > 1.0:
            self.zoom += (1.0 - self.zoom) * min(1.0, dt / 0.26)

        if self.clone is not None:
            # A full participant in the generic status-library pipeline
            # (see entities.Clone) — whatever status an enemy zone/tag
            # effect/redirected hit landed on it last frame actually ticks
            # here, same as a real fighter's own tick_library_effects/
            # tick_statuses call above.
            self.tick_library_effects(self.clone, dt)
            self.tick_statuses(self.clone, dt)
            if not self.clone.is_alive():
                # Killed by a zone/status-library DoT rather than a landed
                # basic attack (see VampirePlugin.on_attack_redirected for
                # that path, which pops it outright with its own
                # retaliation instead) — no retaliation here, just the same
                # destroyed beat CloneArmy.damage_clone gives one of
                # Phantom Lancer's own illusions.
                self.floaters.append([self.clone.pos.x, self.clone.pos.y - 45, -0.6, 220, "Destroyed!", WHITE])
                emit_dark(self.fx, self.clone.pos, count=14, radius=30)
                self.clone = None

        if self.clone is not None:
            self.clone.time_left -= dt
            self.clone.shake *= 0.85
            self.clone.scale_x += (1.0 - self.clone.scale_x) * min(1.0, dt / 0.14)
            self.clone.scale_y += (1.0 - self.clone.scale_y) * min(1.0, dt / 0.14)
            bounce_move(self.clone, dt)
            if self.clone.time_left <= 0:
                self.clone = None

        if self.flash_timer > 0:
            self.flash_timer = max(0, self.flash_timer - dt)

        self.update_zones(dt)

        # fl[2]/fl[3] (drift speed, fade rate) are calibrated per millisecond
        # of frame delta — dt is seconds now, so scale it back up here rather
        # than rescale every floater literal scattered across every ability.
        dt_ms_equiv = dt * 1000
        for fl in self.floaters:
            if len(fl) < 7:
                # Lazily extended once per floater, right here, instead of
                # touching every one of the ~40 floaters.append(...) call
                # sites scattered across every character's plugin.py: fl[6]
                # banks the alpha it was spawned with, so draw_floaters can
                # read alpha/fl[6] as a 1->0 life-progress ratio to drive its
                # shrink-as-it-fades effect.
                fl.append(fl[3])
            fl[1] += fl[2] * dt_ms_equiv * self.FLOATER_RISE_SCALE
            fl[3] -= dt_ms_equiv * self.FLOATER_FADE_RATE
        self.floaters = [fl for fl in self.floaters if fl[3] > 0][-self.MAX_FLOATERS:]

        if self.winner is None and not (self.f1.is_alive() and self.f2.is_alive()):
            self.declare_winner()
        if self.mode == "gameover":
            return

        self.update_roam(dt)
        # Each fighter gets its own independent chance to start a new cast
        # every frame — no pacing gate: try_start_attack()/choose_ability()
        # are cheap no-ops when nothing qualifies for that fighter, so this
        # is safe to call every frame. Unlike the old single shared
        # attacker/defender lock, both fighters can end up with an entry in
        # self.attacks the same frame — that's what lets them act
        # concurrently instead of alternating turns.
        for f, opponent in ((self.f1, self.f2), (self.f2, self.f1)):
            if f not in self.attacks:
                self.try_start_attack(f, opponent)

        for state in list(self.attacks.values()):
            self._current = state
            self.update_attack(dt)
        self._current = None

        self.resolve_collisions()

    def resolve_collisions(self):
        """Character-vs-character bump: whenever two roaming bodies (the two
        fighters, Vampire's clone, or one of Phantom Lancer's illusions —
        see CharacterPlugin.extra_colliders) overlap this frame — whether
        from roam drift or a dodgeable shot's defender still moving
        mid-attack — separate them and bounce off each other, same DVD-logo
        feel as bounce_move's wall collision instead of passing through.
        Each actual bump also fires CharacterPlugin.on_collision(a, b) for
        every plugin (Sukuna's Rabbit Escape is the only one that cares)."""
        movers = [f for f in (self.f1, self.f2) if f.is_alive()]
        if self.clone is not None:
            movers.append(self.clone)
        for plugin in self.plugins:
            movers.extend(plugin.extra_colliders())
        for i in range(len(movers)):
            for j in range(i + 1, len(movers)):
                if resolve_character_collision(movers[i], movers[j]):
                    for plugin in self.plugins:
                        plugin.on_collision(movers[i], movers[j])

    def update_roam(self, dt):
        """Move every fighter that isn't currently the attacker of its own
        in-flight AttackState — that attack's own apply_motion_frame owns
        its position this frame instead (see the update pass in update()).
        A fighter being attacked never stops moving for it, dodgeable or
        not — every ability now tracks the defender's live position instead
        of relying on them holding still (see apply_motion_frame's live
        strike-point tracking and update_attack's defender_start refresh),
        so nobody ever has to freeze for a hit to read as connecting."""
        for f in (self.f1, self.f2):
            if f in self.attacks:
                continue
            self.roam_step(f, dt)

    def roam_step(self, f, dt):
        """Move a single fighter one roam-tick's worth (bounce_move, scaled by
        its own speed multiplier and whatever's standing in its way). Shared
        by update_roam (both fighters, every frame in "roam" mode) and
        update_attack's dodgeable-shot dodge window (just the defender,
        while the attacker is mid-animation — see is_dodgeable in
        combat_resolution.py for why only that kind of shot lets this
        happen)."""
        if not f.is_alive():
            return
        if not self.can_move(f):
            return  # pinned/stunned/frozen/asleep — no roam movement at all
        if self.forced_flee_step(f, dt):
            return
        mult = f.move_speed_mult * self.status_move_speed_multiplier(f)
        for plugin in self.plugins:
            mult *= plugin.roam_speed_multiplier(f, dt)
        for z in self.zones:
            if z.owner is not f and (f.pos - z.center).length() <= z.radius:
                owner_plugin = self.plugin_for(z.owner)
                mult *= owner_plugin.zone_slow_multiplier(z) if owner_plugin else 0.5
        bounce_move(f, dt, mult)

    def ricochet_step(self, dt):
        """Advance Tusk Act 3's bouncing nail one tick: straight-line motion
        that reflects off the arena's actual walls (ARENA_RECT, not the
        character-radius-inset BOUND_* used for fighters, since the nail
        itself has no radius) — same DVD-logo idea as bounce_move, just on
        self.ricochet_pos/vel instead of a Character, and counting bounces
        toward self.ricochet_max_bounces (the attacker's own plugin —
        CharacterPlugin.ricochet_max_bounces — set when flight starts)
        instead of bouncing forever."""
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

    def _swarm_perimeter_point(self, t):
        """A point at fraction `t` (0-1) walked clockwise around ARENA_RECT's
        own perimeter starting from its top-left corner — used so a "radial"
        swarm's projectiles launch from every edge of the arena in
        proportion to that edge's own length, instead of a circle drawn
        through it (which would bunch them toward the square's corners)."""
        r = ARENA_RECT
        perim = 2 * (r.width + r.height)
        d = (t % 1.0) * perim
        if d < r.width:
            return pygame.Vector2(r.left + d, r.top)
        d -= r.width
        if d < r.height:
            return pygame.Vector2(r.right, r.top + d)
        d -= r.height
        if d < r.width:
            return pygame.Vector2(r.right - d, r.bottom)
        d -= r.width
        return pygame.Vector2(r.left, r.bottom - d)

    def _swarm_exit_distance(self, origin, direction, rect):
        """Distance a straight-line ray from `origin` along unit `direction`
        travels before it exits `rect` on the far side — a standard ray/AABB
        slab test, used so each swarm projectile's own flight is sized to
        genuinely cross the whole arena edge-to-edge (however long that
        takes for its own particular spawn point and heading) instead of an
        arbitrary fixed travel distance. Falls back to the rect's own width
        if the ray is somehow degenerate (shouldn't happen given how
        spawn/aim points are chosen, but better than a zero-length flight)."""
        big = 10_000.0
        if abs(direction.x) > 1e-9:
            tx_far = max((rect.left - origin.x) / direction.x, (rect.right - origin.x) / direction.x)
        else:
            tx_far = big
        if abs(direction.y) > 1e-9:
            ty_far = max((rect.top - origin.y) / direction.y, (rect.bottom - origin.y) / direction.y)
        else:
            ty_far = big
        exit_dist = min(tx_far, ty_far)
        return exit_dist if exit_dist > 1 else rect.width

    def spawn_swarm_projectiles(self):
        """Populate self.swarm_projectiles for the current
        Ability.tag == "swarm" attack — generic across any such ability
        (driven entirely by its own swarm_pattern/swarm_timing, see
        abilities.py), not specific to the Vampire or to bats. Called once,
        right as the "barrage" phase begins (see RESOLVE_PHASE["swarm"] and
        resolve_ability() in combat_resolution.py) by the attacking
        character's own resolve_special (e.g. VampirePlugin.resolve_special),
        which is still where any character-specific setup/flavor around the
        cast itself belongs — this only builds the plain pos/vel/delay/dmg
        projectile list; what each one actually looks like on screen is
        entirely up to that plugin's own draw_projectile.

        This is a genuine area attack, not a targeted one: each projectile's
        own aim point is a plain random spot anywhere in the arena (or, for
        "linear", just a straight line in atk_dir), never the defender's own
        position — nothing here is "aimed at" any character or clone at all.
        See update_swarm_projectiles for the live hit-box check that decides
        whether anything actually happened to be standing where a projectile
        ends up flying through.

        Every projectile keeps flying its own full edge-to-edge distance
        (_swarm_exit_distance) regardless of whether/how many times it
        connects along the way — it pierces rather than vanishing on hit
        (see update_swarm_projectiles) — so the "barrage" phase itself has
        no fixed duration of its own either: it's stretched here (by
        overwriting that phase's entry in self.seq, same trick
        try_start_attack() already uses for "bolt"'s distance-derived "fire"
        duration) to
        whatever the single slowest/most-delayed projectile actually needs
        to finish its own full journey, so nothing is ever cut short."""
        ability = self.ability
        attacker = self.attacker
        pattern = ability.swarm_pattern or "radial"
        timing = ability.swarm_timing or "simultaneous"
        count = ability.swarm_count or self.SWARM_PROJECTILE_COUNT
        speed = ability.swarm_speed or self.SWARM_PROJECTILE_SPEED
        per_hit_dmg = max(1, round(attacker.atk * ability.dmg_mult / count))
        # Sized off "time to cross the arena once at this ability's own
        # speed" rather than the barrage phase's own duration — that
        # duration is itself derived FROM these delays below, so it can't
        # also be what they're scaled against.
        delay_window = (ARENA_RECT.width / speed) * self.SWARM_TIMING_WINDOW_RATIO

        if timing == "staggered":
            delays = [delay_window * i / max(1, count - 1) for i in range(count)]
        elif timing == "random":
            delays = [random.uniform(0, delay_window) for _ in range(count)]
        else:  # "simultaneous"
            delays = [0.0] * count

        projectiles = []
        longest_flight = 0.0
        for i in range(count):
            if pattern == "linear":
                # One straight-line volley: every projectile lines up off a
                # single edge (perpendicular to atk_dir, on the far side of
                # the arena) and flies straight across in the same direction
                # — no aim point at all, just a heading.
                direction = pygame.Vector2(self.atk_dir)
                perp = pygame.Vector2(-direction.y, direction.x)
                span = ARENA_RECT.width * 0.8
                offset = perp * random.uniform(-span / 2, span / 2)
                spawn = pygame.Vector2(ARENA_RECT.center) - direction * (ARENA_RECT.width * 0.5) + offset
            elif pattern == "fan":
                # Every projectile launches from the ATTACKER's own current
                # position (not a random perimeter point) — a tight spread
                # of `count` fixed headings across swarm_fan_deg, centered on
                # atk_dir, evenly spaced (the single-projectile case just
                # fires straight down atk_dir, no spread to divide).
                fan_deg = ability.swarm_fan_deg or self.SWARM_FAN_DEG_DEFAULT
                angle = fan_deg * (i / (count - 1) - 0.5) if count > 1 else 0.0
                direction = self.atk_dir.rotate(angle)
                spawn = pygame.Vector2(attacker.pos)
            else:  # "radial"
                spawn = self._swarm_perimeter_point(random.random())
                aim = pygame.Vector2(random.uniform(BOUND_LEFT, BOUND_RIGHT), random.uniform(BOUND_TOP, BOUND_BOTTOM))
                direction = aim - spawn
                direction = direction.normalize() if direction.length_squared() > 0 else pygame.Vector2(1, 0)
            bat_speed = speed * random.uniform(0.85, 1.15)
            vel = direction * bat_speed
            exit_distance = self._swarm_exit_distance(spawn, direction, ARENA_RECT)
            delay = delays[i]
            longest_flight = max(longest_flight, delay + exit_distance / bat_speed)
            projectiles.append({
                "pos": spawn, "vel": vel, "delay": delay, "dmg": per_hit_dmg, "alive": True,
                "hit": set(), "traveled": 0.0, "exit_distance": exit_distance,
            })
        self.swarm_projectiles = projectiles
        # Small buffer so float accumulation in update_swarm_projectiles
        # never cuts the very last projectile's own final frame short.
        barrage_needed = longest_flight * 1.05
        self.seq = [(n, barrage_needed if n == "barrage" else d) for n, d in self.seq]

    def _swarm_enemy_bodies(self, defender):
        """Every enemy-side body a stray swarm projectile can incidentally
        strike: the defender itself, plus any living illusion in the
        defender's own clone army (Phantom Lancer's Juxtapose) — never the
        attacker's own side (itself, or its own Crimson Doppelganger decoy),
        same as every other ability in this engine only ever threatens the
        opponent's side of the field. Returns (body, army) pairs — army is
        None for the real defender, the owning CloneArmy for an illusion (so
        the caller knows to route damage through CloneArmy.damage_clone
        instead of the normal deal_damage formula)."""
        bodies = []
        if defender is not None and defender.is_alive():
            bodies.append((defender, None))
        defender_plugin = self.plugin_for(defender) if defender is not None else None
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        if army is not None:
            bodies.extend((clone, army) for clone in list(army.clones))
        return bodies

    def update_swarm_projectiles(self, dt):
        """Advance every live swarm projectile one tick: hold at its spawn
        point until its own launch delay elapses, then fly in a straight
        line and check every frame whether it's touching *any* enemy-side
        body's live position (see _swarm_enemy_bodies) — a real area attack,
        not one aimed at a specific character or clone, so actually moving
        away is what lets some miss, and whichever enemy body happens to be
        in the way (the defender, or one of its own illusions) is what takes
        the hit.

        A projectile pierces rather than dying on its first hit — each body
        it touches only ever takes that one projectile's damage share once
        (tracked per-projectile in "hit", by body identity), but it keeps
        flying afterward and can go on to hit a different body further
        along its path. It only ever disappears once it's actually
        travelled its own full edge-to-edge distance (see
        _swarm_exit_distance / spawn_swarm_projectiles's "traveled"/
        "exit_distance" bookkeeping), never from merely leaving some
        arbitrary boundary early or from having already connected.

        Called every frame during "barrage"/"settle" (see
        apply_motion_frame's "swarm" branch) regardless of whether this
        specific frame is also the one resolve_ability() fires on."""
        attacker, defender = self.attacker, self.defender
        plugin = self.plugin_for(attacker)
        bodies = self._swarm_enemy_bodies(defender)
        for proj in self.swarm_projectiles:
            if not proj["alive"]:
                continue
            if proj["delay"] > 0:
                proj["delay"] -= dt
                continue
            step = proj["vel"] * dt
            proj["pos"] += step
            proj["traveled"] += step.length()

            for body, army in bodies:
                if not body.is_alive() or id(body) in proj["hit"]:
                    continue
                if army is None and (
                    self.is_invulnerable(body) or self.is_vanished(body) or self.is_untargetable(body)
                ):
                    continue
                if (proj["pos"] - body.pos).length() > CHARACTER_HITBOX_R:
                    continue
                proj["hit"].add(id(body))
                if army is not None:
                    # damage_clone() already gives its own floater/spark/
                    # knockback feedback and returns dmg unmitigated (clones
                    # have no armor of their own), so no extra feedback here.
                    actual = army.damage_clone(body, proj["dmg"], ability=self.ability, knock_dir=proj["vel"])
                else:
                    actual = self.deal_damage(attacker, body, proj["dmg"])
                    body.shake = max(body.shake, 7)
                    body.hit_flash = body.hit_flash_max = 0.08
                    body.visual_recoil += proj["vel"].normalize() * 5
                    self.floaters.append([
                        body.pos.x + random.uniform(-10, 10), body.pos.y - 30,
                        -0.5, 255, f"-{actual}", attacker.color,
                    ])
                self.swarm_hit_count += 1
                self.swarm_dmg_total += actual
                for p in self.plugins:
                    p.on_damage_dealt(attacker, body, actual)
                if plugin is not None:
                    plugin.impact_particles(body.pos, 6)

            if proj["traveled"] >= proj["exit_distance"]:
                proj["alive"] = False

    def finalize_swarm(self):
        """Runs once, right as "settle" begins (see apply_motion_frame's
        "swarm" branch and self.swarm_finalized): tallies the barrage into a
        single log line. Unlike a normal AoE ability, a swarm's clone-army
        splash isn't a separate guaranteed blast (splash_aoe_to_clones) —
        update_swarm_projectiles already lets individual projectiles hit an
        illusion exactly like any other enemy-side body, incidentally, so a
        clone standing well clear of the whole barrage correctly takes
        nothing extra here."""
        attacker, defender, ability = self.attacker, self.defender, self.ability
        if defender is None:
            return
        if self.swarm_hit_count > 0:
            # Not necessarily all on `defender` — a stray projectile can just
            # as easily have caught one of its own illusions instead (see
            # _swarm_enemy_bodies), so the summary stays deliberately vague
            # about exactly who took each hit.
            self.log = f"{attacker.name}'s {ability.name} connects {self.swarm_hit_count}x for {self.swarm_dmg_total}!"
        else:
            self.log = f"{attacker.name}'s {ability.name} finds nothing but air!"

    def update_camera_shake(self, dt):
        self.camera_shake.update(dt)

    def update_afterimages(self, dt):
        # 0.7 is calibrated per millisecond of frame delta — see the
        # equivalent note on the floater update in update() above.
        for ai in self.afterimages:
            ai["alpha"] -= dt * 1000 * 0.7
        self.afterimages = [ai for ai in self.afterimages if ai["alpha"] > 0]

    def update_rings(self, dt):
        for r in self.rings:
            r["elapsed"] += dt
        self.rings = [r for r in self.rings if r["elapsed"] < r["duration"]]

    def toggle_debug(self):
        self.debug = not self.debug

    def update_attack(self, dt):
        # The defender is never frozen for this (see update_roam) — it
        # keeps roaming through its own entire duration, dodgeable or not.

        phase_name, duration = self.seq[self.seq_index]
        self.current_phase = phase_name
        self.phase_elapsed += dt
        t = min(1.0, self.phase_elapsed / duration)
        self.phase_t = t

        if self.defender is not None and not self.attack_target_clone and not is_dodgeable(self.ability):
            # Keep defender_start tracking the defender's actual live
            # position for the whole cast — a dodgeable shot (Nail Bullet,
            # Tusk Act 3) needs its own fixed-at-cast-time snapshot instead
            # (that's what makes it outrunnable), and a clone-redirected
            # attack already aims at a snapshot of the decoy. Every other
            # (guaranteed-hit) ability reads this live, so it still visually
            # connects with a target that was never frozen in place for it
            # (see apply_motion_frame's melee live strike-point tracking and
            # "bolt"'s own non-dodgeable flight, which both key off this).
            self.defender_start = pygame.Vector2(self.defender.pos)

        self.apply_motion_frame(phase_name, t, dt)

        if (
            self.motion == "ricochet" and phase_name == "flight"
            and (self.projectile_hit_confirmed or self.ricochet_bounces >= self.ricochet_max_bounces)
        ):
            # The nail's outcome (a confirmed touch, or its bounce budget
            # burned through with no hit) is already decided the instant
            # apply_motion_frame stops drawing it — cut "flight" short
            # instead of leaving it invisible for whatever's left of its
            # long fixed duration before "settle" actually resolves the hit.
            self.phase_elapsed = duration

        resolve_phase = RESOLVE_PHASE.get(self.motion)
        if phase_name == resolve_phase and not self.damage_applied:
            self.resolve_ability()
            self.damage_applied = True

        if self.phase_elapsed >= duration:
            self.seq_index += 1
            self.phase_elapsed = 0
            if self.seq_index >= len(self.seq):
                # No end-of-sequence position snap any more: every motion
                # that plays a scripted "return"/"settle" phase already hands
                # the attacker off to plain roam_step the instant its own
                # resolve phase fires (see apply_motion_frame), so by the
                # time the sequence ends the attacker is already wherever
                # normal roaming carried it — snapping it back to a
                # remembered point here would just undo that with a visible
                # teleport.
                self.finish_attack()

    def _live_strike_point(self):
        """strike_point re-derived every frame from the now-live
        defender_start (see update_attack's own per-frame refresh) instead
        of the one-time snapshot try_start_attack() took at cast start —
        called from melee_dash/melee_slam/spin's own travel phases so the
        dash keeps homing toward a defender that's never frozen in place
        for it (see update_roam), rather than lunging at where they used to
        stand. Not used by any motion a strike_point_override plugin hook
        (Chaos Knight's Reality Rift, Legion Commander's Duel, Raiju's
        random blink) ever touches — none of those use these three
        motions — so there's no risk of this generic formula overwriting a
        character's own custom destination.

        "charge" deliberately does NOT use this — see _charge_end_point."""
        return self.attacker_start + (self.defender_start - self.attacker_start) * 0.75

    def _charge_end_point(self):
        """Where a "charge"-motion dash actually ends: the arena edge along
        atk_dir, like Piercing Ox's own bull charge (SukunaPlugin.
        _move_pierce/_ox_charge_direction) always running until it slams
        into the wall rather than stopping wherever the defender happens to
        be standing. Computed once at cast start (try_start_attack) from a
        fixed atk_dir, same as Piercing Ox never re-aiming mid-charge —
        unlike _live_strike_point above, passing through (or already past)
        the defender's position never cuts this dash short."""
        origin, d = self.attacker_start, self.atk_dir
        candidates = []
        if d.x > 1e-6:
            candidates.append((BOUND_RIGHT - origin.x) / d.x)
        elif d.x < -1e-6:
            candidates.append((BOUND_LEFT - origin.x) / d.x)
        if d.y > 1e-6:
            candidates.append((BOUND_BOTTOM - origin.y) / d.y)
        elif d.y < -1e-6:
            candidates.append((BOUND_TOP - origin.y) / d.y)
        t = min(candidates) if candidates else 0.0
        return origin + d * max(0.0, t)

    def apply_motion_frame(self, phase, t, dt):
        a = self.attacker
        amp = 1.4 if self.ability.big else 1.0

        if self.ability.moves_while_active:
            # This ability needs no dash-in, no committed firing stance — its
            # user just keeps doing the same plain linear DVD-logo bounce
            # roam as always (see roam_step), instead of freezing/leaning
            # in place like every other attack's motion branch below does.
            # Whatever's motion-specific below (a projectile's own path,
            # mostly) still runs on top of that.
            self.roam_step(a, dt)

        if self.motion == "melee_dash":
            if phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 8 * ease_out(t)
            elif phase == "strike":
                self.strike_point = self._live_strike_point()
                a.pos = self.attacker_start.lerp(self.strike_point, ease_in(t))
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                # The hit already landed — flow straight into normal roaming
                # from here instead of holding still or teleport-snapping
                # back once the sequence ends.
                self.roam_step(a, dt)

        elif self.motion == "melee_slam":
            height = 95 * amp
            if phase == "windup":
                lean_ease = ease_in_out if self.ability.big else ease_out
                a.pos = self.attacker_start - self.atk_dir * 10 * lean_ease(t)
            elif phase == "arc":
                self.strike_point = self._live_strike_point()
                base = self.attacker_start.lerp(self.strike_point, t)
                a.pos = base + pygame.Vector2(0, -height * math.sin(math.pi * t))
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                self.roam_step(a, dt)

        elif self.motion == "spin":
            # calibrated per millisecond of frame delta, like the floater/
            # afterimage rates above — dt is seconds, so scale it back up.
            spin_speed = {"windup": 0.015, "spin_travel": 0.045,
                          "impact": 0.03, "return": 0.02}.get(phase, 0.02)
            a.spin_angle += dt * 1000 * spin_speed
            perp = pygame.Vector2(-self.atk_dir.y, self.atk_dir.x)
            if phase == "windup":
                a.pos = pygame.Vector2(self.attacker_start)
            elif phase == "spin_travel":
                self.strike_point = self._live_strike_point()
                main = self.attacker_start.lerp(self.strike_point, t)
                wobble = perp * math.sin(t * 3 * math.pi) * 22 * amp * (1 - t)
                a.pos = main + wobble
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                self.roam_step(a, dt)

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
                        self.projectile_travel = 0.0
                    if self.projectile_origin is not None:
                        self.projectile_travel += dt
                        # Read the actual "fire" duration for *this* cast, not
                        # the static table — try_start_attack() overrides it
                        # per distance for "bolt" (see BOLT_SPEED), so the travel
                        # lerp below has to track the same figure or the nail
                        # would drift out of sync with the phase timer.
                        fire_duration = dict(self.seq)["fire"]
                        travel_t = self.projectile_travel / fire_duration
                        dodgeable = is_dodgeable(self.ability)
                        if not dodgeable:
                            # Non-dodgeable bolts (Gandiva) are guaranteed to
                            # connect. The defender is never frozen for it
                            # (see update_roam) — instead update_attack()
                            # keeps defender_start refreshed to their live
                            # position every frame, so this lerp re-aims at
                            # a moving goalpost each frame instead of a
                            # stale one, and still visually lands on them.
                            # Without this clamp travel_t keeps growing
                            # through "impact"/"settle" just like Nail
                            # Bullet's own past-target sail, so the arrow
                            # flies straight through and past its target
                            # instead of stopping on it, even though the
                            # damage still lands on schedule.
                            travel_t = min(travel_t, 1.0)
                        flight = self.defender_start - self.projectile_origin
                        pos = self.projectile_origin + flight * travel_t
                        if not dodgeable and travel_t >= 1.0:
                            self.projectile_hit_confirmed = True
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
                            #
                            # `not self.damage_applied` matters just as much
                            # as the touch check itself: do_damage() reads
                            # this flag once, at the "impact" phase — but
                            # apply_motion_frame keeps running (and the nail
                            # keeps flying) through "impact" and "settle"
                            # too. Without this guard, a nail already
                            # resolved as a miss could still graze the
                            # live-moving defender afterward, flip this flag
                            # true, and vanish on the spot — contradicting
                            # its own "flies past on a miss" animation (and
                            # a miss that sometimes disappears mid-flight
                            # anyway is indistinguishable from a real hit).
                            if (
                                not self.damage_applied and dodgeable
                                and not self.attack_target_clone and self.defender is not None
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
                self.roam_step(a, dt)
                self.projectile_pos = None

        elif self.motion == "cast":
            a.pos = pygame.Vector2(self.attacker_start)
            a.pos.y -= 4 * math.sin(math.pi * t)

        elif self.motion == "instant":
            # no dash, no projectile — Sukuna barely leans in, and the cut
            # itself appears directly on the target (see draw_fx). Skipped
            # entirely for a moves_while_active user (Before-Hassasin's
            # Twin Fangs, up close) — roam_step above already handled a.pos,
            # same as "bolt"'s own moves_while_active branch below.
            if self.ability.moves_while_active:
                pass
            elif phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 6 * math.sin(math.pi * t)
            elif phase == "settle":
                self.roam_step(a, dt)
            else:  # "impact"
                a.pos = pygame.Vector2(self.attacker_start)

        elif self.motion == "swarm":
            # A ranged, arena-wide conjure now, not a melee teleport-strike —
            # the attacker just plants and channels (a small bob, like
            # "cast") while the actual attack plays out as a whole barrage of
            # separately-tracked projectiles (see spawn_swarm_projectiles/
            # update_swarm_projectiles above); finalize_swarm below tallies
            # the result once the barrage is over. Skipped for a
            # moves_while_active user (Before-Hassasin's Twin Fangs, at
            # range) — roam_step above already handled a.pos, same as
            # "bolt"/"instant"'s own moves_while_active branches.
            if not self.ability.moves_while_active:
                if phase == "settle":
                    self.roam_step(a, dt)
                else:
                    a.pos = pygame.Vector2(self.attacker_start)
                    a.pos.y -= 5 * math.sin(math.pi * t)
            if phase in ("barrage", "settle"):
                self.update_swarm_projectiles(dt)
            if phase == "settle" and not self.swarm_finalized:
                self.finalize_swarm()
                self.swarm_finalized = True

        elif self.motion == "slash":
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
                self.roam_step(a, dt)

        elif self.motion == "flicker_slash":
            # a true teleport, not a lerp: the attacker disappears at the
            # start point and reappears already at striking distance (see
            # draw_fighter's is_flicker_hidden for the vanish/reappear
            # visual), only dashing back smoothly on the way out.
            if phase in ("vanish", "reappear"):
                a.pos = pygame.Vector2(self.attacker_start if phase == "vanish" else self.strike_point)
            elif phase == "strike":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                self.roam_step(a, dt)

        elif self.motion == "sky_strike":
            # Raiju barely moves — this is a ritual call to the storm, not a
            # melee approach; the sky bolt itself lands on the target (see
            # RaijuPlugin.draw_fx).
            if phase == "settle":
                self.roam_step(a, dt)
            else:
                a.pos = pygame.Vector2(self.attacker_start)
                a.pos.y -= 6 * math.sin(math.pi * min(1.0, t))

        elif self.motion == "homing_bolt":
            # The attacker stays put and fires — the nail does the moving,
            # and unlike "bolt" it keeps re-aiming at the defender's *live*
            # position every frame instead of a fixed point (true homing).
            if phase == "windup":
                a.pos = self.attacker_start - self.atk_dir * 10 * math.sin(math.pi * t)
                self.projectile_pos = None
            elif phase == "chase":
                a.pos = pygame.Vector2(self.attacker_start)
                live_target = self.defender.pos if self.defender is not None else self.defender_start
                self.projectile_pos = self.attacker_start.lerp(live_target, ease_in(t))
            elif phase == "settle":
                self.roam_step(a, dt)
                self.projectile_pos = None
            else:  # "impact"
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
            #
            # That "vanish on touch" early-stop is only meaningful for a
            # dodgeable shot (Tusk Act 3), where projectile_hit_confirmed is
            # what do_damage() later reads to decide hit vs. miss. Tusk Act
            # 4 also uses "ricochet" but is unavoidable (not in
            # DODGEABLE_TAGS) — its hit is guaranteed regardless of this
            # flag, so it must NOT be set (and the nail must NOT vanish)
            # just because the bounce path happened to graze the defender's
            # hit-box early; otherwise the ultimate's long flight reads as
            # invisible for almost its entire duration.
            if phase == "windup":
                self.projectile_pos = None
            elif phase == "flight":
                if self.ricochet_pos is None:
                    plugin = self.plugin_for(a)
                    self.ricochet_pos = pygame.Vector2(a.pos)
                    self.ricochet_vel = pygame.Vector2(self.atk_dir) * plugin.ricochet_speed(a, self.ability)
                    self.ricochet_bounces = 0
                    self.ricochet_max_bounces = plugin.ricochet_max_bounces(a, self.ability)
                if self.projectile_hit_confirmed or self.ricochet_bounces >= self.ricochet_max_bounces:
                    self.projectile_pos = None
                else:
                    self.ricochet_step(dt)
                    self.projectile_pos = pygame.Vector2(self.ricochet_pos)
                    if (
                        is_dodgeable(self.ability) and self.defender is not None
                        and (self.ricochet_pos - self.defender.pos).length() <= CHARACTER_HITBOX_R
                    ):
                        self.projectile_hit_confirmed = True
            else:
                self.projectile_pos = None

        elif self.motion == "charge":
            # Piercing Ox's own charge (SukunaPlugin._move_pierce), without
            # its wall-slam pause: no "windup" lean-back — the attacker is
            # already mid-charge from frame 0 — and the travel itself lerps
            # at a flat, constant speed (plain t, no ease_in/ease_out) for a
            # dead-straight dash instead of melee_dash's accelerating one.
            # self.strike_point is set once in try_start_attack from
            # _charge_end_point() and never re-derived here (unlike
            # melee_dash/melee_slam/spin's own _live_strike_point calls) —
            # running through the defender along the way never stops the
            # dash short of the arena edge.
            if phase == "charge":
                a.pos = self.attacker_start.lerp(self.strike_point, t)
            elif phase == "impact":
                a.pos = pygame.Vector2(self.strike_point)
            elif phase == "return":
                self.roam_step(a, dt)

        elif self.motion == "instant_ricochet":
            # Raiju's Volt Fang: unlike "ricochet" above (which animates its
            # bounce path wall-touch by wall-touch over a long "flight"),
            # this motion never steps frame by frame at all — the whole
            # bounce path resolves in one shot the instant "impact" begins
            # (see CharacterPlugin.resolve_instant_ricochet / RaijuPlugin's
            # own version), then just stays drawn (RaijuPlugin.
            # draw_projectile) for the rest of "impact"/"settle" so it reads
            # before vanishing. Raiju himself never moves during any of this
            # (no moves_while_active) — the roam_step call above only ever
            # fires for an ability that opts into it.
            if phase == "windup":
                self.projectile_pos = None
            elif phase == "impact" and not self.instant_ricochet_resolved:
                for plugin in self.plugins:
                    if plugin.resolve_instant_ricochet(a, self.ability):
                        break
                self.instant_ricochet_resolved = True
            elif phase == "settle":
                self.roam_step(a, dt)

        trailing_phase = (
            (self.motion == "melee_dash" and phase == "strike")
            or (self.motion == "melee_slam" and phase in ("arc", "impact"))
            or (self.motion == "spin" and phase == "spin_travel")
            or (self.motion == "slash" and phase in ("slash1", "slash2"))
            or (self.motion == "flicker_slash" and phase == "return")
            or (self.motion == "charge" and phase == "charge")
        )
        if trailing_phase:
            self.afterimage_cd -= dt
            if self.afterimage_cd <= 0:
                self.spawn_afterimage(a)
                self.afterimage_cd = 0.025
