"""Raiju plugin: the Static passive (every landed hit stacks Vulnerability
on the target), Volt Fang's instantly-resolved wall-ricochet basic attack
(see resolve_instant_ricochet — its whole bounce path is computed in one
shot rather than animated frame by frame, and always plays out to its last
bounce even once it's already touched something; every separate bounce-leg
that crosses a body — the real defender, or one of their own clones/
illusions — lands its own separate hit instead of capping out at one, see
resolve_special), Chain Bolt's stun+burn, Static Field's periodic re-stun
zone, Static Link's permanent bounce-budget upgrade, Thunder God's Descent's
stun+burn, and the lightning/sky-strike animation."""

import math
import random

import pygame

from ...core.constants import ARENA_RECT, CHARACTER_HITBOX_R, RAIJU_CYAN, RED, WHITE
from ...core.effects import draw_expanding_ring, draw_lightning, draw_starburst
from ...core.entities import Zone, set_status
from ...core.particles import emit_spark_burst
from ...core.plugin import CharacterPlugin

STATIC_VULN_PER_STACK = 0.05
STATIC_MAX_STACKS = 5
STATIC_STACK_DURATION_S = 6

# Static Field's periodic re-stun: an initial stun the instant an enemy is
# caught inside, then another every STATIC_FIELD_PULSE_S seconds it's still
# standing there.
STATIC_FIELD_STUN_S = 0.2
STATIC_FIELD_PULSE_S = 1

CHAIN_BOLT_STUN_S = 0.1
CHAIN_BOLT_BURN_S = 5

THUNDER_STUN_S = 0.5
THUNDER_BURN_S = 8

# Volt Fang's basic bounce budget: 10 unless Static Link has been cast — see
# resolve_instant_ricochet below.
VOLT_FANG_BASE_MAX_BOUNCES = 10
STATIC_LINK_MAX_BOUNCES = 15

# Volt Fang launches at a shallow angle off the horizontal (toward whichever
# wall gives it the fullest run before its first bounce) instead of beelining
# at the defender — a low-angle zigzag reads as "aimed at the wall to
# ricochet" the way a near-straight shot never would. Rolled fresh
# per cast within this range rather than a single fixed angle, so the bounce
# pattern actually varies cast to cast instead of always tracing the same
# shape.
VOLT_FANG_LAUNCH_ANGLE_DEG_RANGE = (8, 40)


def _volt_fang_bounce_path(origin, direction, bounds, max_bounces):
    """The whole wall-to-wall path Volt Fang's bolt travels, computed in one
    shot by reflecting a straight ray off `bounds` (ARENA_RECT — the bolt
    itself has no radius, same convention as Tusk Act 3's ricochet_step) up
    to `max_bounces` times, instead of stepping it frame by frame like
    battle_loop.ricochet_step does for Johnny. Pure geometry, so it always
    reaches its real last bounce in one call regardless of how it's drawn or
    whether it happens to pass by the defender along the way."""
    pos = pygame.Vector2(origin)
    vel = pygame.Vector2(direction)
    path = [pygame.Vector2(pos)]
    for _ in range(max_bounces):
        tx = ((bounds.right if vel.x > 0 else bounds.left) - pos.x) / vel.x if vel.x else None
        ty = ((bounds.bottom if vel.y > 0 else bounds.top) - pos.y) / vel.y if vel.y else None
        candidates = [t for t in (tx, ty) if t is not None and t > 1e-6]
        if not candidates:
            break
        t = min(candidates)
        pos += vel * t
        if tx is not None and abs(t - tx) < 1e-4:
            vel.x *= -1
        if ty is not None and abs(t - ty) < 1e-4:
            vel.y *= -1
        path.append(pygame.Vector2(pos))
    return path


def _point_segment_dist(p, a, b):
    ab = b - a
    if ab.length_squared() == 0:
        return (p - a).length()
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared()))
    return (p - (a + ab * t)).length()


def _draw_volt_beam(screen, start, end):
    """Volt Fang's own bespoke bolt style — thinner and tighter-jittered
    than the shared draw_lightning (used for Chain Bolt/Static Field/Thunder
    God's Descent), plus small perpendicular glitch-ticks scattered along
    its length, closer to the thin, mostly-straight streaked laser look of
    the reference art than a chaotic forked bolt would be."""
    diff = end - start
    length = diff.length()
    if length < 1:
        return
    direction = diff / length
    perp = pygame.Vector2(-direction.y, direction.x)
    segments = max(1, round(length / 26))
    pts = [start]
    for i in range(1, segments):
        base = start.lerp(end, i / segments)
        pts.append(base + perp * random.uniform(-3, 3))
    pts.append(end)
    glow = tuple(int(c * 0.5) for c in RAIJU_CYAN)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, glow, pts[i], pts[i + 1], 5)
    for i in range(len(pts) - 1):
        pygame.draw.line(screen, RAIJU_CYAN, pts[i], pts[i + 1], 2)
    for _ in range(max(1, segments // 2)):
        t = random.uniform(0.08, 0.92)
        base = start.lerp(end, t)
        tip = base + perp * random.uniform(8, 16) * random.choice((-1, 1))
        pygame.draw.line(screen, WHITE, base, tip, 1)


class RaijuPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        # Static Link is a one-shot self-upgrade (see moves.py), not a
        # timed buff — once cast it stays on for the rest of the match.
        self.static_link_active = False
        # Volt Fang's whole bounce path for the current attack, computed
        # once by resolve_instant_ricochet and just held here for
        # draw_projectile to keep drawing every frame until the attack ends.
        self._volt_path = []

    # ---- passive: Static -----------------------------------------------------
    def on_damage_dealt(self, attacker, defender, actual):
        """Every landed hit (basic, skill, or ultimate) stacks Static on the
        target, capped at STATIC_MAX_STACKS — each stack is a flat
        STATIC_VULN_PER_STACK bonus via the generic Vulnerability status
        (status_damage_multiplier in status_library.py already applies it to
        every hit against the target, so there's no bespoke incoming_defense
        hook here)."""
        if attacker is not self.fighter or defender is None or actual <= 0:
            return
        cur = defender.statuses.get("static", {})
        stacks = min(STATIC_MAX_STACKS, cur.get("stacks", 0) + 1)
        set_status(defender, "static", STATIC_STACK_DURATION_S, stacks=stacks)
        set_status(defender, "vulnerability", STATIC_STACK_DURATION_S, pct=stacks * STATIC_VULN_PER_STACK)

    # ---- Volt Fang: instant wall-to-wall bounce resolution --------------------
    def resolve_instant_ricochet(self, attacker, ability):
        if attacker is not self.fighter or ability.tag != "volt_fang":
            return False
        battle, defender = self.battle, self.battle.defender
        # Aimed at a wall, not at the defender: keep their general side (so
        # the bolt still trends toward them over its bounce path) but pick
        # whichever vertical wall gives it the fullest run before the first
        # bounce, at a shallow angle rolled fresh this cast — a long diagonal
        # zigzag reads as "aimed at the wall to ricochet" the way a
        # near-straight shot at the defender never would, and randomizing
        # the angle keeps the whole bounce pattern from tracing the exact
        # same shape every single time.
        dx = 1.0 if (defender.pos.x - attacker.pos.x) >= 0 else -1.0
        dy = -1.0 if attacker.pos.y > ARENA_RECT.centery else 1.0
        angle = math.radians(random.uniform(*VOLT_FANG_LAUNCH_ANGLE_DEG_RANGE))
        direction = pygame.Vector2(dx * math.cos(angle), dy * math.sin(angle))

        max_bounces = STATIC_LINK_MAX_BOUNCES if self.static_link_active else VOLT_FANG_BASE_MAX_BOUNCES
        path = _volt_fang_bounce_path(attacker.pos, direction, ARENA_RECT, max_bounces)

        self._volt_path = path
        battle.projectile_pos = pygame.Vector2(path[-1])
        return True

    def resolve_special(self):
        """Volt Fang deals its damage itself instead of going through the
        normal single-hit do_damage() pipeline: every separate leg of the
        path resolve_instant_ricochet already computed gets checked against
        every body actually out on the field for the real defender's side
        (the defender itself, Vampire's own Doppelganger if it's standing in
        for them, Phantom Lancer's illusions) — one full basic-attack-sized
        hit per leg that actually crosses a body, so a path that clips the
        same target 3 times lands 3 separate hits, not one. A leg that
        crosses nothing at all is simply skipped; the whole path only reads
        as a miss if literally none of it touched anything.

        Deliberately skips the attacker-side status_outgoing_multiplier/
        outgoing_damage plugin chain and heal_ratio/lifesteal, same
        simplification the engine's other multi-hit specials already accept
        (see Sukuna's Kai/Vampire's Bat Swarm) — Volt Fang carries neither
        anyway. Meter gain and the impact flourish fire once per cast, not
        once per leg, same as Kai."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "volt_fang"):
            return False
        attacker, ability, defender = battle.attacker, battle.ability, battle.defender
        path = self._volt_path
        battle.damage_applied = True

        clone_targets = []
        if battle.clone is not None and battle.clone.owner is defender:
            clone_targets.append(battle.clone)
        defender_plugin = battle.plugin_for(defender)
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        if army is not None:
            clone_targets.extend(army.clones)

        defender_hits = 0
        clone_hits = []  # [[clone, count], ...] in first-struck order
        clone_slot = {}
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            struck_clone = next(
                (c for c in clone_targets if c.is_alive() and _point_segment_dist(c.pos, a, b) <= CHARACTER_HITBOX_R),
                None,
            )
            if struck_clone is not None:
                slot = clone_slot.setdefault(id(struck_clone), len(clone_hits))
                if slot == len(clone_hits):
                    clone_hits.append([struck_clone, 0])
                clone_hits[slot][1] += 1
            elif defender.is_alive() and _point_segment_dist(defender.pos, a, b) <= CHARACTER_HITBOX_R:
                defender_hits += 1

        if defender_hits == 0 and not clone_hits:
            self._miss = True
            battle.floaters.append([defender.pos.x, defender.pos.y - 50, -0.5, 255, "Evaded!", WHITE])
            battle.log = f"{attacker.name}'s {ability.name} whistles past {defender.name}!"
            return True

        total = 0
        for _ in range(defender_hits):
            dmg = round(attacker.atk * ability.dmg_mult)
            actual = battle.deal_damage(attacker, defender, dmg)
            total += actual
            for plugin in battle.plugins:
                plugin.on_damage_dealt(attacker, defender, actual)
        if defender_hits:
            defender.shake = 13
            battle.apply_impact(defender, ability)
            text = f"-{total}" + (f" x{defender_hits}" if defender_hits > 1 else "")
            battle.floaters.append([defender.pos.x, defender.pos.y - 40, -0.6, 255, text, attacker.color])

        clone_total = 0
        clone_hit_count = 0
        for clone, count in clone_hits:
            is_vampire_clone = clone is battle.clone
            for _ in range(count):
                if not clone.is_alive():
                    break
                dmg = round(attacker.atk * ability.dmg_mult)
                if is_vampire_clone:
                    clone.hp -= dmg
                    battle.floaters.append([clone.pos.x, clone.pos.y - 30, -0.5, 200, f"-{dmg}", RED])
                    emit_spark_burst(battle.fx, clone.pos, attacker.color, count=6)
                    if clone.hp <= 0 and battle.clone is clone:
                        battle.floaters.append([clone.pos.x, clone.pos.y - 45, -0.6, 220, "Destroyed!", WHITE])
                        battle.clone = None
                    actual = dmg
                else:
                    actual = army.damage_clone(clone, dmg, ability=ability, knock_dir=battle.atk_dir)
                clone_total += actual
                clone_hit_count += 1

        parts = []
        if defender_hits:
            parts.append(f"ricochets through {defender.name} {defender_hits}x for {total}")
        if clone_hit_count:
            parts.append(f"clips a decoy {clone_hit_count}x for {clone_total}")
        battle.log = f"{attacker.name}'s Volt Fang " + " and ".join(parts) + "!"

        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "chain_bolt" and defender is not None and battle.damage_applied:
            set_status(defender, "stunned", CHAIN_BOLT_STUN_S)
            set_status(defender, "burn", CHAIN_BOLT_BURN_S)
            battle.log = f"{attacker.name}'s Chain Bolt stuns and sears {defender.name}!"
            emit_spark_burst(battle.fx, defender.pos, RAIJU_CYAN, count=16)
        elif tag == "static_field" and defender is not None:
            zone = Zone("static", pygame.Vector2(defender.pos), 70, 6, attacker)
            zone.pulse_timers = {}  # id(fighter) -> seconds until its next re-stun pulse
            battle.zones.append(zone)
            battle.log = f"{attacker.name} charges the ground under {defender.name} with a Static Field!"
            battle.add_ring(defender.pos, 120, 0.6, RAIJU_CYAN, width=5)
            emit_spark_burst(battle.fx, defender.pos, RAIJU_CYAN, count=30)
        elif tag == "static_link":
            self.static_link_active = True
            battle.floaters.append(
                [attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "STATIC LINK!", RAIJU_CYAN]
            )
            battle.log = f"{attacker.name} forges a Static Link — Volt Fang bounces even further now!"
            battle.add_ring(attacker.pos, 90, 0.5, RAIJU_CYAN, width=4)
            emit_spark_burst(battle.fx, attacker.pos, RAIJU_CYAN, count=24)
        elif tag == "thunder_descent" and defender is not None:
            set_status(defender, "stunned", THUNDER_STUN_S)
            set_status(defender, "burn", THUNDER_BURN_S)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "THUNDER GOD!", RAIJU_CYAN])
            battle.log = f"{attacker.name} calls down Thunder God's Descent on {defender.name}!"
            battle.flash_timer = max(battle.flash_timer, 0.48)
            battle.add_screen_shake(24, 0.3)
            battle.add_ring(defender.pos, 180, 0.75, RAIJU_CYAN, width=6)
            battle.add_ring(defender.pos, 120, 0.65, WHITE, width=3)
            emit_spark_burst(battle.fx, defender.pos, RAIJU_CYAN, count=50)

    # ---- zone (Static Field) -----------------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        """Called once per frame per fighter standing in the zone (dt in
        seconds) — the owner is immune to their own field; anyone else gets
        an immediate stun on first contact, then another every
        STATIC_FIELD_PULSE_S seconds they're still standing in it (tracked
        per-fighter on the zone itself, so it resets clean every fresh
        Static Field cast)."""
        if fighter is zone.owner or fighter.statuses.get("invulnerable"):
            return
        battle = self.battle
        timers = zone.pulse_timers
        remaining = timers.get(id(fighter), 0.0) - dt
        if remaining <= 0:
            set_status(fighter, "stunned", STATIC_FIELD_STUN_S)
            remaining = STATIC_FIELD_PULSE_S
            battle.add_ring(fighter.pos, 30, 0.18, RAIJU_CYAN, width=2)
            emit_spark_burst(battle.fx, fighter.pos, RAIJU_CYAN, count=6)
        timers[id(fighter)] = remaining

    def zone_style(self, zone):
        return RAIJU_CYAN, "Static Field"

    def zone_decorate(self, screen, zone):
        for _ in range(2):
            a = random.uniform(0, math.tau)
            inner = pygame.Vector2(zone.center) + pygame.Vector2(math.cos(a), math.sin(a)) * random.uniform(
                0, zone.radius * 0.6
            )
            outer = pygame.Vector2(zone.center) + pygame.Vector2(math.cos(a), math.sin(a)) * zone.radius
            draw_lightning(screen, inner, outer, RAIJU_CYAN, segments=3, jitter=6)

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_spark_burst(self.battle.fx, pos, RAIJU_CYAN, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos):
            self._volt_path = []
            return False
        name = battle.ability.name
        if name == "Chain Bolt":
            draw_lightning(screen, battle.attacker_start, battle.projectile_pos, RAIJU_CYAN, segments=5, jitter=8)
            pygame.draw.circle(screen, WHITE, (int(battle.projectile_pos.x), int(battle.projectile_pos.y)), 4)
            return True
        if name == "Volt Fang":
            # The whole path was already computed in one shot by
            # resolve_instant_ricochet — just keep it fully drawn (every
            # bounce, start to finish) every frame it's live, instead of
            # revealing it bounce by bounce.
            path = self._volt_path
            for i in range(len(path) - 1):
                _draw_volt_beam(screen, path[i], path[i + 1])
            if path:
                end = path[-1]
                pygame.draw.circle(screen, WHITE, (int(end.x), int(end.y)), 5)
            return True
        return False

    def draw_fx(self, screen, shake_x):
        """Volt Fang telegraphs its instant strike with a brief charge-up
        spark while Raiju holds still (no dash-in, no travel — the whole
        bounce path just appears at "impact", see draw_projectile). Thunder
        God's Descent telegraphs with rising static before a single bolt
        splits the sky onto the target — Chain Bolt needs nothing extra
        here, draw_projectile above already covers it."""
        battle, r = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is r):
            return
        name = battle.ability.name
        if name == "Volt Fang" and battle.current_phase == "windup":
            origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
            draw_starburst(screen, origin, RAIJU_CYAN, size=10 + 12 * battle.phase_t, fade=battle.phase_t)
            return
        if name != "Thunder God's Descent":
            return
        phase, t = battle.current_phase, battle.phase_t
        origin = pygame.Vector2(battle.attacker_start) + pygame.Vector2(shake_x, 0)
        if phase == "channel":
            for _ in range(4):
                top = origin + pygame.Vector2(random.uniform(-24, 24), -60 - random.uniform(0, 30) * t)
                draw_lightning(screen, origin, top, RAIJU_CYAN, segments=4, jitter=10, branches=1)
            draw_starburst(screen, origin, RAIJU_CYAN, size=16 + 14 * t, fade=t)
        elif phase == "impact":
            target = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            sky = pygame.Vector2(target.x, ARENA_RECT.top - 30)
            draw_lightning(screen, sky, target, RAIJU_CYAN, segments=10, jitter=24, branches=4)
            for frac in (-1.4, -0.7, 0.7, 1.4):
                branch = target + pygame.Vector2(frac * 40, -70)
                draw_lightning(screen, sky.lerp(target, 0.35), branch, RAIJU_CYAN,
                                segments=4, jitter=12, branches=1)
            draw_expanding_ring(screen, target, 90 * t, RAIJU_CYAN, width=5)
            draw_expanding_ring(screen, target, 60 * t, WHITE, width=3)
            draw_starburst(screen, target, WHITE, size=46, fade=1 - t)
