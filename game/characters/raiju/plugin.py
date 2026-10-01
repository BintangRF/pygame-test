"""Raiju plugin: the Static passive (every landed hit stacks Armor Break
on the target, and the same stack count now also charges Overcharge — a
matching Attack Speed Up on Raiju himself, see on_damage_dealt), Volt Fang's
instantly-resolved wall-ricochet basic attack
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

from ...core.constants import (
    ARENA_RECT,
    BOUND_BOTTOM,
    BOUND_LEFT,
    BOUND_RIGHT,
    BOUND_TOP,
    CHARACTER_HITBOX_R,
    HEIGHT,
    RAIJU_CYAN,
    RED,
    WHITE,
    WIDTH,
)
from ...core.effects import draw_expanding_ring, draw_lightning, draw_starburst
from ...core.entities import Zone, set_status
from ...core.glow import add_dot, glow_polyline
from ...core.motions import MOTIONS
from ...core.particles import emit_lightning_spark, emit_spark_burst
from ...core.plugin import CharacterPlugin

# flat armor points each Static stack strips off the target (generic
# Armor Break "amount" — see StatusLibraryMixin.effective_armor)
STATIC_ARMOR_BREAK_PER_STACK = 2.5
STATIC_MAX_STACKS = 10
STATIC_STACK_DURATION_S = 10

# Overcharge: the same Static stack count also charges Raiju's own Attack
# Speed Up, in lockstep with the Armor Break it stacks on the target
# (same stack count, same refresh, same STATIC_STACK_DURATION_S) — so
# landing hits now pays Raiju back too, not just wearing the target down.
OVERCHARGE_ATK_SPEED_PER_STACK = 1.5

# Static Field's own zone: how far its re-stun radius reaches and how long
# the field itself lingers before it clears.
STATIC_FIELD_RADIUS = 90
STATIC_FIELD_DURATION_S = 5

# Static Field's periodic re-stun: an initial stun the instant an enemy is
# caught inside, then another every STATIC_FIELD_PULSE_S seconds it's still
# standing there.
STATIC_FIELD_STUN_S = 0.5
STATIC_FIELD_PULSE_S = 1

CHAIN_BOLT_STUN_S = 0.6
CHAIN_BOLT_BURN_S = 10

THUNDER_STUN_S = 1
THUNDER_BURN_S = 15

# Volt Fang's basic bounce budget: 10 unless Static Link has been cast — see
# resolve_instant_ricochet below.
VOLT_FANG_BASE_MAX_BOUNCES = 15
STATIC_LINK_MAX_BOUNCES = 25

# Volt Fang launches at a shallow angle off the horizontal (toward whichever
# wall gives it the fullest run before its first bounce) instead of beelining
# at the defender — a low-angle zigzag reads as "aimed at the wall to
# ricochet" the way a near-straight shot never would. Rolled fresh
# per cast within this range rather than a single fixed angle, so the bounce
# pattern actually varies cast to cast instead of always tracing the same
# shape.
VOLT_FANG_LAUNCH_ANGLE_DEG_RANGE = (8, 40)

# Volt Fang vs. Vampire's own Crimson Doppelganger: since that clone isn't a
# CloneArmy clone and takes this hit directly, it needs the same
# 2x-vs-a-real-fighter clone tax CloneArmy.damage_clone applies to every
# other clone, applied manually here (see resolve_special).
VOLT_FANG_CLONE_HIT_DMG_MULT = 2

# Raiju's own random blink: a flat chance, rolled on every attack he starts
# (basic, skill, or ultimate alike — see strike_point_override), to
# teleport to a random spot in the arena before that attack plays out.
RAIJU_ATTACK_BLINK_CHANCE = 1

# Thunder God's Descent's telegraph (see _draw_thunder_telegraph), purely
# visual: across the whole build-up ("windup" + "channel", read straight
# from MOTIONS so it stays in sync with the motion's own timing) a target
# marker locks onto the strike spot, contracting from THUNDER_MARKER_START_MULT
# times the blast radius down to the ability's real aoe_radius, so the area
# it settles on is the area the bolt actually hits. Distant sky flashes fire
# at fixed points of that build-up, each flickering the whole screen for a
# short window (see full_screen_overlay).
THUNDER_BUILDUP_PHASES = ("windup", "channel")
THUNDER_MARKER_START_MULT = 1.7
THUNDER_FLASH_AT = (0.35, 0.8)
THUNDER_FLASH_WINDOW = 0.05
THUNDER_FLASH_ALPHA = 65
THUNDER_FLASH_COLOR = (200, 240, 255)


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
    glow_polyline(screen, pts, RAIJU_CYAN, width=2, intensity=0.75)
    for _ in range(max(1, segments // 4)):
        t = random.uniform(0.08, 0.92)
        base = start.lerp(end, t)
        mid = base + perp * random.uniform(4, 8) * random.choice((-1, 1)) + direction * random.uniform(-4, 4)
        tip = mid + (mid - base) + direction * random.uniform(-5, 5)
        glow_polyline(screen, [base, mid, tip], RAIJU_CYAN, width=1, intensity=0.55)


class RaijuPlugin(CharacterPlugin):
    #: Ground crack this fighter's big hits leave (anime_fx.DECAL_STYLES):
    #: a forked Lichtenberg burn.
    GROUND_DECAL = "lightning"
    #: Hit-flash flare (anime_fx.build_impact_burst_frames): crackling electricity.
    BURST_TEXTURE = "spark_02"

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        # Static Link is a one-shot self-upgrade (see moves.py), not a
        # timed buff — once cast it stays on for the rest of the match.
        self.static_link_active = False
        # Volt Fang's whole bounce path for the current attack, computed
        # once by resolve_instant_ricochet and just held here for
        # draw_projectile to keep drawing every frame until the attack ends.
        self._volt_path = []
        # Alpha of this frame's Thunder God's Descent screen flicker, set by
        # draw_fx (where the attack state is bound) and consumed by
        # full_screen_overlay later in the same frame's draw.
        self._thunder_flicker = 0

    # ---- passive: Static, plus Overcharge ------------------------------------
    def on_damage_dealt(self, attacker, defender, actual):
        """Every landed hit (basic, skill, or ultimate) stacks Static on the
        target, capped at STATIC_MAX_STACKS — each stack is a flat
        STATIC_ARMOR_BREAK_PER_STACK armor points off via the generic Armor
        Break status (effective_armor in status_library.py already applies
        it to every hit against the target, so there's no bespoke
        incoming_defense hook here). The same stack count also charges Overcharge, a matching
        Attack Speed Up kept on Raiju himself — he's building the same
        current up in his own body as he's dumping into the target."""
        if attacker is not self.fighter or defender is None or actual <= 0:
            return
        cur = defender.statuses.get("static", {})
        stacks = min(STATIC_MAX_STACKS, cur.get("stacks", 0) + 1)
        set_status(defender, "static", STATIC_STACK_DURATION_S, stacks=stacks)
        set_status(defender, "armor_break", STATIC_STACK_DURATION_S, amount=stacks * STATIC_ARMOR_BREAK_PER_STACK)
        set_status(attacker, "attack_speed_up", STATIC_STACK_DURATION_S, pct=stacks * OVERCHARGE_ATK_SPEED_PER_STACK)

    # ---- random blink: rolled on every attack, any ability -------------------
    def _random_blink(self, attacker):
        """RAIJU_ATTACK_BLINK_CHANCE roll (see strike_point_override):
        teleport straight to a random point in the arena. Must also
        overwrite battle.attacker_start, not just attacker.pos — every one
        of Raiju's own motions ("cast", "sky_strike", "homing_bolt",
        "instant_ricochet") re-derives the attacker's per-frame position
        from attacker_start rather than touching attacker.pos directly
        (Raiju has no moves_while_active), and attacker_start still
        defaults to wherever Raiju stood before this cast (see
        combat_resolution.py's try_start_attack), so leaving it alone would
        play the whole animation from his old spot instead of the new one."""
        battle = self.battle
        dest = pygame.Vector2(random.uniform(BOUND_LEFT, BOUND_RIGHT), random.uniform(BOUND_TOP, BOUND_BOTTOM))
        emit_spark_burst(battle.fx, attacker.pos, RAIJU_CYAN, count=18)
        battle.add_ring(attacker.pos, 70, 0.4, RAIJU_CYAN, width=4)
        attacker.pos = pygame.Vector2(dest)
        battle.attacker_start = pygame.Vector2(dest)
        battle.add_ring(dest, 70, 0.4, RAIJU_CYAN, width=4)
        emit_spark_burst(battle.fx, dest, RAIJU_CYAN, count=18)

    def strike_point_override(self, attacker, ability):
        if attacker is not self.fighter:
            return None
        if random.random() < RAIJU_ATTACK_BLINK_CHANCE:
            self._random_blink(attacker)
        return None

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
        # same shape every single time. A forced redirect (taunt) trends the
        # whole path toward the decoy's own side instead — see resolve_
        # special's own redirect_target handling, which restricts every
        # leg's hit-check to just that one body once this is set, so aiming
        # anywhere else would make the path unable to ever actually connect.
        aim_pos = battle.redirect_target.pos if battle.redirect_target is not None else defender.pos
        dx = 1.0 if (aim_pos.x - attacker.pos.x) >= 0 else -1.0
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

        A forced redirect_target (a taunting decoy — see resolve_instant_
        ricochet's own aim_pos, and status_library.taunt_redirect's "even a
        genuine homing shot... still gets pulled onto it" rule, which
        ignore_clone=True on this ability was never meant to override)
        makes it the ONLY thing this whole path can hit — the real defender
        is excluded entirely rather than left as just another candidate
        the path might clip instead, same guarantee the generic do_damage()
        pipeline already gives every other single-target ability.

        Deliberately skips the attacker-side status_outgoing_multiplier/
        outgoing_damage plugin chain and heal_ratio/lifesteal, same
        simplification the engine's other multi-hit specials already accept
        (see Sukuna's Kai/Vampire's Bat Swarm) — Volt Fang carries neither
        anyway, redirected hits included. Meter gain and the impact
        flourish fire once per cast, not once per leg, same as Kai."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "volt_fang"):
            return False
        attacker, ability, defender = battle.attacker, battle.ability, battle.defender
        path = self._volt_path
        battle.damage_applied = True

        defender_plugin = battle.plugin_for(defender)
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        redirect_target = battle.redirect_target
        if (
            redirect_target is not None
            and redirect_target is not battle.clone
            and (army is None or redirect_target not in army.clones)
        ):
            # The taunting decoy expired or died between cast and resolve
            # (e.g. Vampire's clone timing out mid-cast) — fall back to the
            # normal path instead of treating a stale decoy as an army clone.
            redirect_target = None
        if redirect_target is not None:
            clone_targets = [redirect_target]
            check_defender = False
        else:
            clone_targets = []
            if battle.clone is not None and battle.clone.owner is defender:
                clone_targets.append(battle.clone)
            if army is not None:
                clone_targets.extend(army.clones)
            check_defender = True

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
            elif check_defender and defender.is_alive() and _point_segment_dist(defender.pos, a, b) <= defender.hitbox_r:
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
                    dmg *= VOLT_FANG_CLONE_HIT_DMG_MULT
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
            zone = Zone("static", pygame.Vector2(defender.pos), STATIC_FIELD_RADIUS, STATIC_FIELD_DURATION_S, attacker)
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
        """Every landed hit — Volt Fang's own multi-leg ricochet strikes
        included — discharges as jagged lightning shards plus a quick white
        flash ring, instead of the plain circular emit_spark_burst every
        other electric-flavored hit in the game uses (see
        emit_lightning_spark's own docstring)."""
        battle = self.battle
        emit_lightning_spark(battle.fx, pos, RAIJU_CYAN, count=count)
        battle.add_ring(pos, 26, 0.22, WHITE, width=2)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos):
            self._volt_path = []
            return False
        name = battle.ability.name
        if name == "Chain Bolt":
            draw_lightning(screen, battle.attacker_start, battle.projectile_pos, RAIJU_CYAN, segments=5, jitter=8)
            add_dot(screen, battle.projectile_pos, 14, RAIJU_CYAN)
            add_dot(screen, battle.projectile_pos, 5, WHITE)
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
                add_dot(screen, end, 16, RAIJU_CYAN)
                add_dot(screen, end, 6, WHITE)
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
        if phase in THUNDER_BUILDUP_PHASES:
            self._draw_thunder_telegraph(screen, shake_x, phase, t)
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

    def _draw_thunder_telegraph(self, screen, shake_x, phase, t):
        """Thunder God's Descent's warning before the bolt lands: a marker on
        the strike spot (battle.defender_start, the same live-tracked point
        the "impact" bolt comes down on) that contracts onto the real blast
        radius and fills in as the build-up progresses, with a rotating
        crosshair inside it, plus distant sky flashes at THUNDER_FLASH_AT
        that flicker the screen (see full_screen_overlay) and, on the final
        flash, a faint leader streak from the sky down to the mark."""
        battle = self.battle
        target = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
        seq = dict(MOTIONS["sky_strike"])
        total = sum(seq[p] for p in THUNDER_BUILDUP_PHASES)
        before = sum(seq[p] for p in THUNDER_BUILDUP_PHASES[:THUNDER_BUILDUP_PHASES.index(phase)])
        progress = (before + seq[phase] * t) / total

        radius = battle.ability.aoe_radius or 90
        ring_r = radius * (THUNDER_MARKER_START_MULT - (THUNDER_MARKER_START_MULT - 1) * progress)
        disc = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        center = (radius + 2, radius + 2)
        pygame.draw.circle(disc, (*RAIJU_CYAN, int(20 + 50 * progress)), center, radius)
        pygame.draw.circle(disc, (*RAIJU_CYAN, int(90 + 110 * progress)), center, radius, width=2)
        screen.blit(disc, disc.get_rect(center=(round(target.x), round(target.y))))

        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.03)
        pygame.draw.circle(screen, WHITE if pulse > 0.5 else RAIJU_CYAN,
                           (round(target.x), round(target.y)), round(ring_r), width=2)
        spin = progress * math.tau * 0.75
        for i in range(4):
            a = spin + i * math.pi / 2
            d = pygame.Vector2(math.cos(a), math.sin(a))
            pygame.draw.line(screen, RAIJU_CYAN, target + d * ring_r * 0.35, target + d * ring_r * 0.8, 3)
            pygame.draw.line(screen, WHITE, target + d * ring_r * 0.45, target + d * ring_r * 0.7, 1)
        pygame.draw.circle(screen, WHITE, (round(target.x), round(target.y)), max(2, round(3 + 4 * progress)))

        for i, at in enumerate(THUNDER_FLASH_AT):
            if at <= progress < at + THUNDER_FLASH_WINDOW:
                self._thunder_flicker = max(self._thunder_flicker, THUNDER_FLASH_ALPHA)
                # A distant bolt somewhere across the sky, well clear of the
                # strike itself so it reads as the storm gathering, not as
                # the hit landing early.
                x = random.uniform(ARENA_RECT.left, ARENA_RECT.right) + shake_x
                sky = pygame.Vector2(x, ARENA_RECT.top - 20)
                draw_lightning(screen, sky, sky + pygame.Vector2(random.uniform(-30, 30), random.uniform(60, 120)),
                               RAIJU_CYAN, segments=5, jitter=10, branches=1)
                if i == len(THUNDER_FLASH_AT) - 1:
                    faint = tuple(int(c * 0.45) for c in RAIJU_CYAN)
                    pygame.draw.line(screen, faint, (target.x, ARENA_RECT.top - 20), target, 2)

    def full_screen_overlay(self, screen):
        """Thunder God's Descent's build-up flashes (see
        _draw_thunder_telegraph, which sets the alpha during draw_fx): a
        brief pale-blue flicker over the whole screen, cleared right after
        so it only ever lasts the frames its flash window covers."""
        if self._thunder_flicker <= 0:
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((*THUNDER_FLASH_COLOR, self._thunder_flicker))
        screen.blit(overlay, (0, 0))
        self._thunder_flicker = 0
