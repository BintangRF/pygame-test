"""Leonidas plugin: the Spartan Fury passive (a bespoke gauge — separate
from the generic meter_max/meter_gain ultimate-charge resource — that fills
on every hit Leonidas lands or takes and, once full, unloads a temporary
Armor Up + Attack Up + Cleanse, extends Spear Thrust's own melee range, and
turns Spear Thrust into a hold-and-release strike whose damage scales with
however long it sat ready waiting for an enemy to actually walk into range),
Javelin Charge's straight-line charge (mirrored, at the same instant and
each along its own heading, by every Spartan in This Is Sparta!'s own
formation), Shield Slam's armor-break + stun, War Cry's slow + attack-down
field, This Is Sparta!'s own linear/circle Spartan formation, and the spear
weapon animation.

This Is Sparta!'s Spartan formation is a bespoke CloneArmy (see
core/clone_army.py) with can_attack=True (each Spartan auto-attacks on its
own cooldown/range, a plain basic-attack-alike scaled off Spear Thrust's own
dmg_mult, same as Phantom Lancer's own illusions) but can_use_skill/
has_statuses left False — a Spartan never auto-mirrors a skill the generic
way, it only ever does that in the one bespoke, formation-aware way Javelin
Charge's own mirror gives it (_legion_charge). Unlike a roaming CloneArmy, a
Spartan holds a fixed slot around Leonidas instead (see clone_move_step)
rather than bouncing around the arena looking for a target — it only ever
actually swings once the opponent (or one of their own clones) wanders
within its own attack_range of that slot. They're still full CloneArmy
citizens for everything else the engine already does generically: a physical
body (extra_colliders), vulnerable to an eligible single-target attack
redirected onto one of them in place of Leonidas (basic_attack_decoys/
on_attack_redirected) and to an AoE splash landing near Leonidas
(combat_resolution.splash_aoe_to_clones, via clone_army())."""

import math
import random

import pygame

from ...core.clone_army import CloneArmy
from ...core.constants import AVATAR_R, CHARACTER_HITBOX_R, GOLD, LEONIDAS_BRONZE, STUN_COLOR, WHITE
from ...core.effects import draw_expanding_ring, draw_rotated, draw_slash_fx, draw_starburst, weapon_angle
from ...core.entities import Zone, set_status
from ...core.motions import ease_in, ease_out
from ...core.particles import emit_debris, emit_explosion, emit_spark_burst
from ...core.plugin import CharacterPlugin
from ...core.status_library import cleanse
from .weapons import load_leonidas_weapons

# Spartan Fury (passive): gauge gained per landed/received hit, and the
# temporary payoff once it's full — see ambient_tick/on_damage_dealt/
# on_damage_taken/_trigger_fury_surge.
FURY_MAX = 100.0
FURY_GAIN_ON_BASIC = 12.0
FURY_GAIN_ON_SKILL = 16.0
FURY_GAIN_ON_HIT_TAKEN = 10.0
FURY_SURGE_DURATION_S = 12.0
FURY_SURGE_ARMOR_AMOUNT = 16
FURY_SURGE_ATK_PCT = 0.65
FURY_SURGE_RANGE_BONUS = 80

# Spear Thrust's hold-and-release scaling while Spartan Fury is up: the
# longer it's sat ready (basic.timer <= 0) with no enemy yet in range, the
# harder it hits once one finally walks into it — see ambient_tick (the
# charge-up), cooldown_bonus (freezes the held duration the instant the cast
# actually starts, i.e. the instant an enemy stepped into range), and
# outgoing_damage (spends that frozen value on the hit itself).
HOLD_MAX_S = 2.5
HOLD_MAX_BONUS_PCT = 1.2

# Shield Slam: armor-break + stun on landing.
SHIELD_SLAM_ARMOR_BREAK_S = 8
SHIELD_SLAM_ARMOR_BREAK_AMOUNT = 11
SHIELD_SLAM_STUN_S = 1.3

# War Cry: the field dropped at the target's own position.
WAR_CRY_RADIUS = 110
WAR_CRY_DURATION_S = 5
WAR_CRY_SLOW_PCT = 0.6
WAR_CRY_ATTACK_DOWN_PCT = 0.65
WAR_CRY_REFRESH_S = 0.3

# This Is Sparta!: the Spartan formation's own numbers (CloneArmy.spawn) and
# geometry (see _summon_phalanx) — cap=4 plus Leonidas himself matches the
# five-strong formation this ultimate is themed on. "linear" arranges the
# four across a forward-facing arc, "circle" spaces them evenly all the way
# around Leonidas; either way each Spartan's own slot direction (out from
# the formation's own center, through its own slot) doubles as the heading
# it charges along once Javelin Charge fires (see _legion_charge/
# clone_move_step).
LEGION_CAP = 4
LEGION_DURATION_S = 14
LEGION_STAT_PCT = 0.4
LEGION_HP_PCT = 0.18
LEGION_CIRCLE_RADIUS = 95
LEGION_ARC_RADIUS = 100
LEGION_ARC_DEG = 140
# Javelin Charge's own mirror: each Spartan checks a straight corridor along
# its own slot direction for the opponent (or one of the opponent's own
# clones) — LEGION_CHARGE_REACH comfortably clears the arena's own
# corner-to-corner diagonal (~537, see ARENA_RECT in core/constants.py) so a
# charge launched from anywhere in the formation still reaches the far wall.
LEGION_CHARGE_REACH = 560
LEGION_CHARGE_WIDTH = CHARACTER_HITBOX_R + 10
# Purely a visual dash-out-and-back for a charging Spartan (see
# clone_move_step) — the formation slot itself never actually moves, so a
# Spartan is always back in position by the time the next frame's formation
# math runs again next tick past this window.
LEGION_CHARGE_VISUAL_S = 0.35
LEGION_CHARGE_DASH_DIST = 70
# Each Spartan also auto-attacks like any other CloneArmy with can_attack=True
# (see core/clone_army.py's own _clone_attack/_pick_attack_target) — a plain
# basic-attack-alike scaled off Leonidas's own Spear Thrust dmg_mult, on
# whichever's nearer once in range: the real opponent, or one of the
# opponent's own clones.
SPARTAN_ATTACK_COOLDOWN_S = 1.0
SPARTAN_ATTACK_RANGE = 100
SPARTAN_ATTACK_ANIM_S = 0.26
# Every Spartan is drawn smaller than Leonidas himself (see _spartan_sprite/
# _spartan_ring_radius) — a full-size copy of him in every slot read as a
# second Leonidas rather than a supporting soldier. Purely cosmetic: hitbox/
# collision radius stays the same flat AVATAR_R every clone uses regardless
# (same convention Sukuna's own shrunk-down Rabbit Escape uses — see
# characters/sukuna/plugin.py's RABBIT_SPRITE_SCALE).
SPARTAN_SPRITE_SCALE = 0.7

# Idle resting pose for the spear prop — held low and angled back, same
# convention every other character's weapon prop uses (see IDLE_ANGLE/
# IDLE_OFFSET in characters/legion_commander/plugin.py).
IDLE_ANGLE = 205
IDLE_OFFSET = pygame.Vector2(-12, 18)
# The held-and-charging pose while Spartan Fury is up and Spear Thrust is
# ready-and-waiting (see _draw_spear's idle branch) — raised and levelled
# out toward a guard stance instead of resting low, so "holding a charged
# thrust" reads as a visibly different stance from the plain idle rest, not
# just a ring hovering over an otherwise-unchanged pose.
HOLD_ANGLE = 235
HOLD_OFFSET = pygame.Vector2(-2, -16)
# Periodic spark trickle at the held weapon while it charges (see
# ambient_tick) — fires more often the closer the hold is to HOLD_MAX_S, same
# "read as an escalating charge-up" idea Berserker's own rage_particle_cd
# uses for its ambient embers.
HOLD_PARTICLE_CD_MAX = 0.5
HOLD_PARTICLE_CD_MIN = 0.1


class LeonidasPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self._fury = 0.0
        # Seconds Spear Thrust has been off cooldown and waiting on an enemy
        # to step into range, while Spartan Fury is up (see ambient_tick) —
        # frozen into _basic_hold_used and reset to 0 the instant a fresh
        # cast actually starts (see cooldown_bonus), so outgoing_damage always
        # spends exactly the hold that specific cast waited through.
        self._basic_hold = 0.0
        self._basic_hold_used = 0.0
        self._hold_particle_cd = 0.0
        self.army = CloneArmy(
            self, cap=LEGION_CAP, stat_pct=LEGION_STAT_PCT, duration=LEGION_DURATION_S,
            can_attack=True, attack_cooldown=SPARTAN_ATTACK_COOLDOWN_S, attack_range=SPARTAN_ATTACK_RANGE,
            attack_anim=SPARTAN_ATTACK_ANIM_S, clone_hp_pct=LEGION_HP_PCT,
        )
        self._spartan_sprite_cache = None

    def weapons(self):
        return load_leonidas_weapons()

    def clone_army(self):
        return self.army

    def extra_colliders(self):
        # Deliberately NOT self.army.extra_colliders() — the whole point of
        # This Is Sparta! is a formation that holds its exact shape (see
        # clone_move_step), and the generic fighter-vs-fighter bump physics
        # (resolve_character_collision) would shove a Spartan out of its own
        # slot the instant a real fighter (or an enemy's own clone) so much
        # as brushes past it, only for clone_move_step to snap it straight
        # back next frame — a one-frame jitter every time anyone walks
        # through the formation. Leaving Spartans out of collision entirely
        # means the formation never visibly distorts, at the cost of a
        # Spartan no longer being a physical obstacle to walk around.
        return []

    def basic_attack_decoys(self):
        return self.army.redirect_pool()

    def on_attack_redirected(self):
        battle = self.battle
        clone = battle.redirect_target
        if clone is None or clone not in self.army.clones:
            return False
        attacker, ability = battle.attacker, battle.ability
        dmg = round(attacker.atk * ability.dmg_mult)
        dmg = round(dmg * battle.status_outgoing_multiplier(attacker))
        actual = self.army.damage_clone(clone, dmg, ability=ability, knock_dir=battle.atk_dir)
        battle.damage_applied = True
        battle.log = f"{attacker.name}'s {ability.name} cuts down one of {self.fighter.name}'s Spartans!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    # ---- passive: Spartan Fury ------------------------------------------------
    def passive_gauge(self, fighter):
        """Charging up toward FURY_MAX (see on_damage_dealt/on_damage_taken —
        gated off the instant "spartan_fury" itself is up, so landing/taking
        hits during the surge banks nothing toward the next one) shows as a
        filling bronze bar; once it triggers, the same bar instead shows the
        "spartan_fury" status's own remaining time (set by
        _trigger_fury_surge) counting back down from full — the generic
        status timer already IS the decay, so extending FURY_SURGE_DURATION_S
        alone is enough to make this bar drain more slowly. Either way the
        gauge sits at a flat 0 for the surge's whole duration and only starts
        climbing again once it actually expires."""
        if fighter is not self.fighter:
            return None
        surge = fighter.statuses.get("spartan_fury")
        if surge is not None:
            return surge["time"] / FURY_SURGE_DURATION_S, "FURY!", GOLD
        return self._fury / FURY_MAX, "FURY", LEONIDAS_BRONZE

    def on_damage_dealt(self, attacker, defender, actual):
        if not (
            attacker is self.fighter and defender is not None and actual > 0
            and "spartan_fury" not in self.fighter.statuses
        ):
            return
        if self.battle.ability.kind == "basic":
            self._fury = min(FURY_MAX, self._fury + FURY_GAIN_ON_BASIC)
        else:
            self._fury = min(FURY_MAX, self._fury + FURY_GAIN_ON_SKILL)

    def on_damage_taken(self, defender, actual):
        if defender is self.fighter and actual > 0 and "spartan_fury" not in self.fighter.statuses:
            self._fury = min(FURY_MAX, self._fury + FURY_GAIN_ON_HIT_TAKEN)

    def _trigger_fury_surge(self):
        battle, lion = self.battle, self.fighter
        self._fury = 0.0
        self._basic_hold = 0.0
        cleanse(lion)
        set_status(lion, "spartan_fury", FURY_SURGE_DURATION_S)
        set_status(lion, "armor_up", FURY_SURGE_DURATION_S, amount=FURY_SURGE_ARMOR_AMOUNT)
        set_status(lion, "attack_up", FURY_SURGE_DURATION_S, pct=FURY_SURGE_ATK_PCT)
        battle.floaters.append([lion.pos.x, lion.pos.y - 65, -0.6, 255, "SPARTAN FURY!", LEONIDAS_BRONZE])
        battle.log = f"{lion.name}'s Spartan Fury erupts — cleansed, hardened, and holding the line!"
        battle.add_screen_shake(14, 0.24)
        battle.add_ring(lion.pos, 110, 0.5, LEONIDAS_BRONZE, width=5)
        emit_spark_burst(battle.fx, lion.pos, LEONIDAS_BRONZE, count=24)

    def on_status_expire(self, fighter, name, data):
        if fighter is self.fighter and name == "spartan_fury":
            self._basic_hold = 0.0

    def melee_range_bonus(self, attacker, melee_range):
        if attacker is self.fighter and melee_range is not None and "spartan_fury" in attacker.statuses:
            return melee_range + FURY_SURGE_RANGE_BONUS
        return melee_range

    def cooldown_bonus(self, attacker, ability, cooldown):
        if attacker is self.fighter and ability is self.fighter.abilities["basic"]:
            self._basic_hold_used = self._basic_hold
            self._basic_hold = 0.0
        return cooldown

    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is self.fighter and ability.kind == "basic" and self._basic_hold_used > 0:
            hold_ratio = min(1.0, self._basic_hold_used / HOLD_MAX_S)
            bonus_pct = hold_ratio * HOLD_MAX_BONUS_PCT
            # The release itself scales with how long it was held, not just a
            # flat "surging or not" flourish — a barely-held thrust barely
            # pops, a fully-held one throws a proper burst and shakes the
            # screen, so the payoff actually reads as "the longer you wait,
            # the harder it hits" instead of a single on/off flourish.
            battle = self.battle
            emit_spark_burst(battle.fx, defender.pos, GOLD, count=round(8 + 20 * hold_ratio))
            battle.add_screen_shake(6 + 12 * hold_ratio, 0.16 + 0.12 * hold_ratio)
            return round(dmg * (1 + bonus_pct)), note + f" [HELD +{round(bonus_pct * 100)}%]"
        return dmg, note

    def clone_basic_attack_roll(self, clone, dmg):
        """Every Spartan's own auto-attack (CloneArmy._clone_attack, from
        can_attack=True) never goes through outgoing_damage above at all —
        this is the hook built for exactly that gap (see its own docstring
        in core/plugin.py). While Spartan Fury is up, the whole formation's
        basic attacks hit as hard as Leonidas's own fully-held release
        (HOLD_MAX_BONUS_PCT flat, not scaled per-clone — a Spartan swings on
        its own short attack_cd the instant something's in range, so there's
        no meaningful "held ready" window of its own to measure against)."""
        if "spartan_fury" in self.fighter.statuses:
            return round(dmg * (1 + HOLD_MAX_BONUS_PCT)), False
        return dmg, False

    def clone_basic_attack_landed(self, clone, target, actual, crit):
        if actual > 0 and "spartan_fury" in self.fighter.statuses:
            emit_spark_burst(self.battle.fx, target.pos, GOLD, count=10)

    # ---- Javelin Charge: single-target charge, mirrored by the formation ----
    def _legion_charge(self, ability):
        """Every living Spartan charges along its own formation slot
        direction at the same instant Leonidas's own Javelin Charge lands —
        an independent straight-corridor check per Spartan (not a shared
        target), since each one is charging its own heading, not
        Leonidas's own atk_dir."""
        if not self.army.clones:
            return
        battle, owner = self.battle, self.fighter
        opponent = battle.f2 if battle.f1 is owner else battle.f1
        opp_plugin = battle.plugin_for(opponent)
        opp_army = opp_plugin.clone_army() if opp_plugin is not None else None

        for clone in list(self.army.clones):
            clone.charge_flash_t = LEGION_CHARGE_VISUAL_S
            direction = clone.formation_dir
            dmg = round(clone.atk * ability.dmg_mult)

            if opponent.is_alive():
                to_target = opponent.pos - clone.pos
                fwd = to_target.dot(direction)
                if 0 <= fwd <= LEGION_CHARGE_REACH and (to_target - direction * fwd).length() <= LEGION_CHARGE_WIDTH:
                    actual = battle.deal_damage(owner, opponent, dmg, reflect_target=clone)
                    if actual > 0:
                        opponent.hit_flash = opponent.hit_flash_max = 0.09
                        opponent.hit_flash_heavy = False
                        opponent.visual_recoil += direction * 6
                        battle.floaters.append(
                            [opponent.pos.x, opponent.pos.y - 30, -0.5, 210, f"-{actual}", owner.color]
                        )
                        emit_spark_burst(battle.fx, opponent.pos, owner.color, count=8)

            if opp_army is not None:
                for eclone in list(opp_army.clones):
                    to_target = eclone.pos - clone.pos
                    fwd = to_target.dot(direction)
                    if 0 <= fwd <= LEGION_CHARGE_REACH and (to_target - direction * fwd).length() <= LEGION_CHARGE_WIDTH:
                        opp_army.damage_clone(eclone, dmg, ability=ability, knock_dir=direction)

            battle.add_ring(clone.pos, 36, 0.22, owner.color, width=3)

    # ---- tag effects --------------------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "javelin_charge":
            self._legion_charge(ability)
            if self.army.clones:
                battle.log = f"{attacker.name} and the Spartan phalanx charge as one!"
        elif tag == "shield_slam":
            if defender is not None and battle.damage_applied:
                set_status(defender, "armor_break", SHIELD_SLAM_ARMOR_BREAK_S, amount=SHIELD_SLAM_ARMOR_BREAK_AMOUNT)
                set_status(defender, "stunned", SHIELD_SLAM_STUN_S)
                battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Shattered!", WHITE])
                battle.log = f"{attacker.name}'s Shield Slam shatters {defender.name}'s guard!"
        elif tag == "war_cry":
            if defender is not None:
                battle.zones.append(
                    Zone("war_cry", pygame.Vector2(defender.pos), WAR_CRY_RADIUS, WAR_CRY_DURATION_S, attacker)
                )
                battle.log = f"{attacker.name}'s War Cry breaks {defender.name}'s resolve!"
                battle.add_ring(defender.pos, 120, 0.6, LEONIDAS_BRONZE, width=5)
                emit_debris(battle.fx, defender.pos, count=20)
        elif tag == "phalanx_call":
            self._summon_phalanx()

    # ---- zone (War Cry) -------------------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        if fighter is zone.owner:
            return
        set_status(fighter, "slowed", WAR_CRY_REFRESH_S, pct=WAR_CRY_SLOW_PCT)
        set_status(fighter, "attack_down", WAR_CRY_REFRESH_S, pct=WAR_CRY_ATTACK_DOWN_PCT)

    def zone_style(self, zone):
        return LEONIDAS_BRONZE, "War Cry"

    # ---- This Is Sparta!: formation summon -----------------------------------
    def _summon_phalanx(self):
        battle, lion = self.battle, self.fighter
        formation = random.choice(("linear", "circle"))
        self.army.clones = []

        facing = pygame.Vector2(battle.atk_dir)
        if facing.length_squared() == 0:
            facing = pygame.Vector2(1, 0)
        facing_angle = math.atan2(facing.y, facing.x)

        if formation == "circle":
            radius = LEGION_CIRCLE_RADIUS
            base_angle = random.uniform(0, math.tau)
            angles = [base_angle + i * (math.tau / LEGION_CAP) for i in range(LEGION_CAP)]
        else:
            radius = LEGION_ARC_RADIUS
            spread = math.radians(LEGION_ARC_DEG)
            angles = [
                facing_angle + spread * (i / (LEGION_CAP - 1) - 0.5)
                for i in range(LEGION_CAP)
            ]

        for angle in angles:
            direction = pygame.Vector2(math.cos(angle), math.sin(angle))
            clone = self.army.spawn(
                near=lion.pos + direction * radius, cap=LEGION_CAP,
                stat_pct=LEGION_STAT_PCT, duration=LEGION_DURATION_S, hp_pct=LEGION_HP_PCT,
            )
            clone.formation_dir = direction
            clone.formation_radius = radius
            clone.charge_flash_t = 0.0
            clone.name = f"{lion.name}'s Spartan"
            # Status: invulnerable — a Spartan can dish out damage (auto-
            # attacks, the Javelin Charge mirror) but never takes any itself
            # (see CloneArmy.damage_clone's own invulnerable check), same
            # generic immunity Berserker Rage gives a real fighter. This
            # army has has_statuses=False (no DoT/tick pipeline for these
            # clones), so nothing ever decrements this — it simply holds for
            # as long as the Spartan itself is out (clone.time_left, from
            # duration=LEGION_DURATION_S above), not a separately-timed buff.
            set_status(clone, "invulnerable", LEGION_DURATION_S)

        battle.floaters.append([lion.pos.x, lion.pos.y - 75, -0.6, 255, "THIS IS SPARTA!", LEONIDAS_BRONZE])
        battle.log = f"{lion.name} calls forth the phalanx in {formation} formation!"
        battle.flash_timer = max(battle.flash_timer, 0.4)
        battle.add_screen_shake(20, 0.3)
        battle.add_ring(lion.pos, 170, 0.7, LEONIDAS_BRONZE, width=6)
        emit_explosion(battle.fx, lion.pos, LEONIDAS_BRONZE, count=30)

    # ---- Spartan formation: hold position + Javelin Charge dash visual -----
    def clone_move_step(self, clone, dt, speed_mult):
        """Every Spartan is pinned to its own formation slot, recomputed
        fresh off Leonidas's own live position every single frame — never
        eased/lerped toward it and never clamped to the arena bounds (unlike
        every other roaming clone in this game), on purpose: clamping would
        squash the formation's own shape out of true the moment Leonidas
        stands close enough to a wall that some slot would otherwise land
        outside it, which is exactly the kind of "falls apart" this
        formation must never do. The one exception is Javelin Charge's own
        brief mirrored dash (see _legion_charge/LEGION_CHARGE_VISUAL_S) — a
        purely additive offset on top of the slot, so the Spartan is already
        back in perfect formation the instant that dash's own timer runs
        out."""
        center = pygame.Vector2(self.fighter.pos)
        target = center + clone.formation_dir * clone.formation_radius
        if clone.charge_flash_t > 0:
            clone.charge_flash_t = max(0.0, clone.charge_flash_t - dt)
            t = 1 - clone.charge_flash_t / LEGION_CHARGE_VISUAL_S
            curve = math.sin(math.pi * min(1.0, t))
            target = target + clone.formation_dir * LEGION_CHARGE_DASH_DIST * curve
        clone.pos = target
        clone.vel = pygame.Vector2()

    def ambient_tick(self, dt):
        lion = self.fighter
        if lion.is_alive():
            if self._fury >= FURY_MAX:
                self._trigger_fury_surge()
            charging = (
                "spartan_fury" in lion.statuses and lion not in self.battle.attacks
                and lion.abilities["basic"].timer <= 0
            )
            if charging:
                self._basic_hold = min(HOLD_MAX_S, self._basic_hold + dt)
                hold_ratio = self._basic_hold / HOLD_MAX_S
                self._hold_particle_cd -= dt
                if self._hold_particle_cd <= 0:
                    weapon_pos = lion.pos + HOLD_OFFSET
                    emit_spark_burst(self.battle.fx, weapon_pos, GOLD, count=round(3 + 5 * hold_ratio))
                    self._hold_particle_cd = HOLD_PARTICLE_CD_MAX - (
                        HOLD_PARTICLE_CD_MAX - HOLD_PARTICLE_CD_MIN
                    ) * hold_ratio
            else:
                self._hold_particle_cd = 0.0
        self.army.tick(dt)

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_debris(self.battle.fx, pos, count=count)
        return True

    def draw_fx(self, screen, shake_x):
        self._draw_spear(screen, shake_x)
        self.army.draw(
            screen, shake_x, ring_color=LEONIDAS_BRONZE, draw_weapon=self._draw_clone_spear,
            sprite_for=self._spartan_sprite, ring_radius_for=self._spartan_ring_radius,
        )

    def _spartan_sprite(self, clone):
        """A smaller copy of Leonidas's own sprite (see SPARTAN_SPRITE_SCALE)
        — cached once since it never changes for the rest of the match, same
        lazy-cache shape Legion Commander's own flame_arrow_sprite/Vampire's
        _bat_sprite use for a fixed-size prop."""
        if self._spartan_sprite_cache is None:
            size = max(8, round(self.fighter.image.get_width() * SPARTAN_SPRITE_SCALE))
            self._spartan_sprite_cache = pygame.transform.smoothscale(self.fighter.image, (size, size))
        return self._spartan_sprite_cache

    def _spartan_ring_radius(self, clone):
        return max(6, round((AVATAR_R + 6) * SPARTAN_SPRITE_SCALE))

    def _draw_spear(self, screen, shake_x):
        battle, lion = self.battle, self.fighter
        if not lion.is_alive():
            return
        img = battle.weapons["spear"]
        pos0 = lion.pos + pygame.Vector2(shake_x, 0)
        surging = "spartan_fury" in lion.statuses
        active_name = battle.ability.name if (battle.mode == "attack" and battle.attacker is lion) else None

        if active_name is None:
            battle.weapon_trail.clear()
            if surging:
                # A raised, levelled-out guard stance instead of the plain
                # resting pose, plus a growing double ring — one around
                # Leonidas himself, one tight around the held weapon — and a
                # brightening core, all scaled by how much of the hold is
                # actually banked, so "charging a held thrust" reads as an
                # obvious, escalating state instead of a small ring hovering
                # over an unchanged idle pose.
                hold_ratio = min(1.0, self._basic_hold / HOLD_MAX_S)
                wobble = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.02)
                weapon_pos = pos0 + HOLD_OFFSET
                draw_expanding_ring(screen, pos0, AVATAR_R + 14 + 22 * hold_ratio * wobble, GOLD, width=2)
                draw_expanding_ring(screen, weapon_pos, 10 + 16 * hold_ratio * wobble, WHITE, width=2)
                draw_starburst(screen, weapon_pos, GOLD, size=10 + 18 * hold_ratio, fade=0.4 + 0.6 * hold_ratio)
                draw_rotated(screen, img, weapon_pos, HOLD_ANGLE)
            else:
                draw_rotated(screen, img, pos0 + IDLE_OFFSET, IDLE_ANGLE)
            return

        phase, t = battle.current_phase, battle.phase_t
        trail_ok = False

        if active_name == "Spear Thrust":
            # A stationary double-thrust ("slash" motion — see moves.py):
            # two forward jabs with no dash-in, mirroring Phantom Lancer's
            # own Spear Slash. While Spartan Fury is up, both jabs read as
            # the held charge finally releasing — a brighter, wider impact
            # flash the longer it was actually held (hold_used_ratio, not
            # just a flat "surging or not" bump) instead of a plain stab —
            # see outgoing_damage for the actual damage/particle/shake payoff
            # behind that release.
            hold_used_ratio = min(1.0, self._basic_hold_used / HOLD_MAX_S) if surging else 0.0
            tip_reach = AVATAR_R + 34
            if phase == "windup":
                reach, extra = 8, -18 * ease_out(t)
            elif phase == "slash1":
                reach = 8 + (tip_reach - 8) * ease_in(t)
                extra = -18 + 18 * ease_in(t)
                if t > 0.55:
                    strike_pos = pos0 + battle.atk_dir * tip_reach
                    draw_starburst(screen, strike_pos, WHITE, size=22 + 18 * hold_used_ratio, fade=(1 - t) / 0.45)
                    draw_expanding_ring(screen, strike_pos, 30 * t, GOLD if surging else lion.color, width=3)
            elif phase == "slash2":
                reach = 14 + (tip_reach - 14) * ease_in(t)
                extra = 0
                if t > 0.55:
                    strike_pos = pos0 + battle.atk_dir * tip_reach
                    draw_starburst(screen, strike_pos, WHITE, size=26 + 20 * hold_used_ratio, fade=(1 - t) / 0.45)
                    draw_expanding_ring(screen, strike_pos, 34 * t, GOLD if surging else lion.color, width=3)
            else:  # return
                reach, extra = tip_reach - (tip_reach - 12) * ease_out(t), 0
            angle = weapon_angle(battle.atk_dir, extra)
            pos = pos0 + battle.atk_dir * reach
            trail_ok = phase in ("slash1", "slash2")

        elif active_name == "Javelin Charge":
            angle = weapon_angle(battle.atk_dir, 0)
            pos = pos0 + battle.atk_dir * (AVATAR_R + 16)
            if phase == "impact":
                draw_starburst(screen, pos0, WHITE, size=40, fade=1 - t)
                draw_expanding_ring(screen, pos0, 60 * t, lion.color, width=5)

        elif active_name == "Shield Slam":
            tip_reach = AVATAR_R + 26
            if phase == "windup":
                reach, extra = 8, -30 * ease_out(t)
            elif phase == "strike":
                reach = 8 + (tip_reach - 8) * ease_in(t)
                extra = -30 + 30 * ease_in(t)
            elif phase == "impact":
                reach, extra = tip_reach, 0
                strike_pos = pos0 + battle.atk_dir * reach
                draw_starburst(screen, strike_pos, WHITE, size=34, fade=1 - t)
                draw_expanding_ring(screen, strike_pos, 50 * t, STUN_COLOR, width=5)
            else:  # return
                reach, extra = tip_reach - (tip_reach - 10) * ease_out(t), 0
            angle = weapon_angle(battle.atk_dir, extra)
            pos = pos0 + battle.atk_dir * reach
            trail_ok = phase in ("strike", "impact")

        elif active_name == "War Cry":
            angle, pos = IDLE_ANGLE, pos0 + IDLE_OFFSET
            if phase in ("channel", "release"):
                draw_expanding_ring(screen, pos0, 30 + 90 * t, lion.color, width=4)

        else:  # This Is Sparta!
            angle, pos = IDLE_ANGLE, pos0 + IDLE_OFFSET
            if phase == "release":
                draw_starburst(screen, pos0, GOLD, size=50, fade=1 - t)
                draw_expanding_ring(screen, pos0, 140 * t, lion.color, width=6)

        if trail_ok:
            battle.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(battle.weapon_trail) > 6:
                battle.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(battle.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(battle.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            battle.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

        # The painted slash flipbook, drawn on top of the spear itself —
        # Spear Thrust only (Shield Slam/Javelin Charge/War Cry/This Is
        # Sparta! keep their own existing starburst/ring accents as-is).
        if active_name == "Spear Thrust" and phase in ("slash1", "slash2"):
            strike_pos = pos0 + battle.atk_dir * tip_reach
            draw_slash_fx(screen, strike_pos, battle.atk_dir, t, size=85 if phase == "slash1" else 95)

    def _draw_clone_spear(self, screen, clone, pos):
        """Rested outward toward its own formation slot direction when idle,
        a raised held-and-charging guard while Spartan Fury is up and it
        isn't otherwise busy (mirrors Leonidas's own held pose in
        _draw_spear — same hold_ratio, Leonidas's own _basic_hold, not a
        separate one per Spartan, so the whole formation visibly charges and
        releases in lockstep with him), one continuous thrust-out-and-back
        toward clone.attack_dir while its own auto-attack swing plays (see
        core/clone_army.py's CloneArmy._clone_attack — can_attack=True means
        every Spartan swings on its own cooldown/range, same as Phantom
        Lancer's own illusions), and a full dash-out pose along its own
        formation direction while Javelin Charge's mirror is playing (see
        LeonidasPlugin._legion_charge) — checked in that priority order
        since a charging/swinging Spartan is mid action regardless of
        whether Spartan Fury also happens to be up."""
        img = self.battle.weapons["spear"]
        surging = "spartan_fury" in self.fighter.statuses
        holding = False

        if clone.charge_flash_t > 0:
            weapon_pos = pos + clone.formation_dir * (AVATAR_R + 16)
            angle = weapon_angle(clone.formation_dir, 0)
        elif clone.attack_anim_t > 0:
            t = 1 - clone.attack_anim_t / SPARTAN_ATTACK_ANIM_S
            reach = 8 + (AVATAR_R + 18) * math.sin(math.pi * t)
            angle = weapon_angle(clone.attack_dir, 0)
            weapon_pos = pos + clone.attack_dir * reach
            if 0.4 < t < 0.6:
                fade = 1 - abs(t - 0.5) / 0.2
                # A Spartan's own swing hits just as hard as Leonidas's held
                # release while Spartan Fury is up (see
                # clone_basic_attack_roll) — reads that way too, not just a
                # plain flourish.
                draw_starburst(screen, weapon_pos, GOLD if surging else WHITE, size=32 if surging else 24, fade=fade)
        elif surging:
            holding = True
            hold_ratio = min(1.0, self._basic_hold / HOLD_MAX_S)
            wobble = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.02)
            weapon_pos = pos + clone.formation_dir * 18
            angle = weapon_angle(clone.formation_dir, -22)
            ring_r = (AVATAR_R + 8) * SPARTAN_SPRITE_SCALE + 10 * hold_ratio * wobble
            draw_expanding_ring(screen, pos, ring_r, GOLD, width=2)
            draw_starburst(screen, weapon_pos, GOLD, size=8 + 14 * hold_ratio, fade=0.4 + 0.6 * hold_ratio)
        else:
            weapon_pos = pos + clone.formation_dir * 14
            angle = weapon_angle(clone.formation_dir, 0)

        if surging and not holding:
            # A subtler ambient glow while mid-charge/mid-swing — the fuller
            # held-guard treatment above only plays while a Spartan actually
            # has nothing else going on.
            pulse = 3 + 3 * math.sin(pygame.time.get_ticks() * 0.02)
            draw_expanding_ring(screen, pos, AVATAR_R + 8 + pulse, GOLD, width=2)
        draw_rotated(screen, img, weapon_pos, angle)
