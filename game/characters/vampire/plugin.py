"""Vampire plugin: Bat Swarm's own damage resolve, Crimson Doppelganger
conjuring/deception (marking the clone itself with the generic "taunt"
status — see status_library.taunt_redirect — then retaliating once its
target takes the bait; see spawn_clone/on_attack_redirected), Blood Hex's
lockdown (the generic "curse" status — disarm+silence+slow, see
core/status_library.py) plus its own bespoke punish (a cursed opponent who
still lands a hit on the Vampire gets it thrown right back at them — see
on_damage_dealt), Blood Pool's zone (heals the Vampire, poisons and disarms
anyone else standing in it), and Eternal Night's lifesteal window and
movement boost."""

import math
import random

import pygame

from ...core.constants import ARENA_RECT, AVATAR_R, CURSE_COLOR, HEIGHT, RED, WIDTH
from ...core.effects import draw_comet, draw_curse_orb
from ...core.entities import Clone, Zone, set_status
from ...core.particles import emit_blood, emit_dark
from ...core.plugin import CharacterPlugin
from ...core.status_library import heal

# How long a freshly-conjured Crimson Doppelganger sticks around, and (see
# spawn_clone) exactly how long it carries its own "taunt" status — the two
# durations stay in lockstep so taunt never outlives the decoy it exists
# to protect.
CLONE_LIFETIME_MS = 5000

# Blood Hex: how long the lockdown (disarm+silence+slow, see the generic
# "curse" status in core/status_library.py) lasts, how strong its slow half
# is, and how much of any damage a cursed opponent still lands on the
# Vampire gets thrown right back at them (see on_damage_dealt).
CURSE_DURATION_MS = 5000
CURSE_SLOW_PCT = 0.4
# Cut by another 25% (same pass as every other ability-effect damage number
# in this file) to slow matches down further.
CURSE_REFLECT_PCT = 0.375


class VampirePlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.night_timer = 0
        self.night_particle_cd = 0
        self.night_afterimage_cd = 0

    # ---- damage pipeline ----------------------------------------------------
    def heal_bonus(self, attacker, heal_mult):
        if attacker is not self.fighter:
            return heal_mult
        if attacker.hp / attacker.max_hp < 0.3:
            heal_mult += 0.15  # Blood Hunger passive
        if self.night_timer > 0:
            heal_mult += 0.25  # Eternal Night lifesteal boost
        return heal_mult

    def on_damage_dealt(self, attacker, defender, actual):
        """Blood Hex's punish: a cursed opponent is disarmed+silenced (see
        the generic "curse" status applied in apply_tag_effects below), so
        this only ever fires on a hit that landed before the curse took
        hold or right as it expires — when it does, it backfires on them
        instead of hurting the Vampire."""
        battle = self.battle
        if defender is self.fighter and attacker is not self.fighter and "curse" in attacker.statuses:
            reflected = round(actual * CURSE_REFLECT_PCT)
            if reflected > 0:
                actual_reflected = battle.apply_damage(attacker, reflected)
                battle.floaters.append(
                    [attacker.pos.x, attacker.pos.y - 40, -0.6, 255, f"-{actual_reflected} Curse", CURSE_COLOR]
                )
                battle.log = f"{attacker.name}'s curse backfires for {actual_reflected}!"
        if attacker is self.fighter and self.night_timer > 0:
            self.night_timer = min(12000, self.night_timer + 1500)

    def on_attack_redirected(self):
        """If the attacker's hit was quietly redirected onto the
        Doppelganger (see status_library.taunt_redirect, driven by the
        clone's own "taunt" status), pop the decoy and strike back at
        whoever fell for it instead of resolving a normal hit."""
        battle = self.battle
        if not (battle.attack_target_clone and battle.clone is not None):
            return False
        battle.clone = None
        fooled = battle.attacker
        retal = random.randint(6, 11)  # cut by another 25% (was 8-14)
        actual = battle.apply_damage(fooled, retal)
        battle.floaters.append([fooled.pos.x, fooled.pos.y - 40, -0.6, 255, f"-{actual}", RED])
        battle.floaters.append([fooled.pos.x, fooled.pos.y - 55, -0.5, 255, "Fooled!", CURSE_COLOR])
        battle.log = f"{fooled.name} strikes a Crimson Doppelganger — Blood Explosion!"
        battle._miss = True
        battle.damage_applied = True
        return True

    def resolve_special(self):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "swarm"):
            return False
        attacker, defender, ability = battle.attacker, battle.defender, battle.ability
        dmg = round(attacker.atk * ability.dmg_mult)
        actual = battle.deal_damage(attacker, defender, dmg)
        battle.damage_applied = True
        defender.shake = 16
        battle.apply_impact(defender, ability)
        battle.floaters.append([defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{actual}", attacker.color])
        battle.log = f"{attacker.name}'s Bat Swarm strike hits {defender.name} for {actual}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        # Status: untargetable (self — a brief evasion window, not the
        # invulnerable status)
        set_status(attacker, "untargetable", 700)
        return True

    # ---- clone / eternal night ------------------------------------------------
    def spawn_clone(self, opponent):
        battle, v = self.battle, self.fighter
        offset = pygame.Vector2(random.uniform(-40, 40), random.uniform(-40, 40))
        pos = pygame.Vector2(v.pos) + offset
        pos.x = max(ARENA_RECT.left + AVATAR_R, min(ARENA_RECT.right - AVATAR_R, pos.x))
        pos.y = max(ARENA_RECT.top + AVATAR_R, min(ARENA_RECT.bottom - AVATAR_R, pos.y))
        angle = random.uniform(0, math.tau)
        vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * random.uniform(60, 100)
        clone = Clone(v.image, v.color, pos, vel, CLONE_LIFETIME_MS, v)
        # Status: taunt (on the clone, not a fighter — redirects the
        # opponent's next hit onto the decoy, see taunt_redirect)
        set_status(clone, "taunt", CLONE_LIFETIME_MS)
        battle.clone = clone
        battle.log = f"{v.name} conjures a Crimson Doppelganger — {opponent.name} is taunted into it!"

    def start_eternal_night(self):
        self.night_timer = max(self.night_timer, 6000)
        self.fighter.meter = 0
        self.battle.log = f"{self.fighter.name} unleashes Eternal Night!"

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "curse":
            # Status: curse (bundled disarm+silence+slow — no separate
            # disarmed/silenced/slowed statuses needed on top of this one)
            set_status(defender, "curse", CURSE_DURATION_MS, pct=CURSE_SLOW_PCT)
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Cursed!", CURSE_COLOR])
            battle.log = f"{attacker.name} places Blood Hex on {defender.name} — disarmed, silenced, slowed!"
        elif tag == "blood_pool":
            # Status: none directly — poison/disarmed are applied per-tick
            # by zone_tick below while an opponent stands in the zone.
            battle.zones.append(Zone("blood", pygame.Vector2(attacker.pos), 75, 6000, attacker))
            battle.log = f"{attacker.name} spills a Blood Pool!"
            battle.add_ring(attacker.pos, 130, 700, CURSE_COLOR, width=5)
            emit_blood(battle.fx, attacker.pos, count=38)
        elif tag == "clone":
            # Status: taunt (applied on the clone by spawn_clone above)
            self.spawn_clone(defender)
            emit_dark(battle.fx, self.fighter.pos, count=32)
        elif tag == "eternal_night":
            # Status: none — night_timer is a bespoke Vampire field (drives
            # heal_bonus/roam_speed_multiplier above), not a status
            self.start_eternal_night()
            battle.add_ring(self.fighter.pos, 220, 950, (140, 30, 170), width=6)
            battle.add_ring(self.fighter.pos, 150, 900, (200, 60, 220), width=3)
            emit_dark(battle.fx, self.fighter.pos, count=60, radius=90)

    # ---- zone (Blood Pool) ------------------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        # Status: poison (DoT) + disarmed (hard CC) applied to whoever isn't
        # the pool's owner
        if fighter is zone.owner:
            # 0.5% of max hp per second while the Vampire stands in it.
            heal(fighter, 0.005, dt)
            fighter.meter = min(fighter.meter_max, fighter.meter + 8 * dt)
        elif not fighter.statuses.get("invulnerable"):
            # Refreshed every frame the enemy stands in the pool, same
            # trick as Sacred Ground's corruption (paladin/plugin.py) — a
            # short buffer duration so both fade within half a second of
            # stepping out instead of lingering. dps kwarg omitted so it
            # falls back to the canonical POISON_BASE_DPS flat rate in
            # status_library.py, same as every status-effect DoT now.
            set_status(fighter, "poison", 500)
            set_status(fighter, "disarmed", 500)

    def zone_style(self, zone):
        return (170, 30, 50), "Blood Pool"

    # ---- per-frame simulation ---------------------------------------------------
    def attack_speed_multiplier(self, fighter):
        if fighter is self.fighter and fighter.hp / fighter.max_hp < 0.3:
            return 1.3
        return 1.0

    def roam_speed_multiplier(self, fighter, dt_ms):
        if fighter is not self.fighter or self.night_timer <= 0:
            return 1.0
        self.night_afterimage_cd -= dt_ms
        if self.night_afterimage_cd <= 0:
            self.battle.spawn_afterimage(fighter)
            self.night_afterimage_cd = 140
        return 1.4

    def ambient_tick(self, dt_ms):
        if self.night_timer <= 0:
            return
        self.night_timer = max(0, self.night_timer - dt_ms)
        self.night_particle_cd -= dt_ms
        if self.night_particle_cd <= 0:
            emit_dark(self.battle.fx, self.fighter.pos, count=4, radius=70)
            self.night_particle_cd = 55

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_blood(self.battle.fx, pos, self.battle.atk_dir, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos):
            return False
        name = battle.ability.name
        if name == "Blood Bolt":
            draw_comet(screen, battle.projectile_pos, battle.atk_dir, battle.attacker.color,
                       size=1.3 if battle.ability.big else 1.0)
            return True
        if name == "Blood Hex":
            draw_curse_orb(screen, battle.projectile_pos, battle.atk_dir, CURSE_COLOR,
                            size=1.2 if battle.ability.big else 1.0)
            return True
        return False

    def full_screen_overlay(self, screen):
        if self.night_timer <= 0:
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        alpha = min(150, int(150 * min(1.0, self.night_timer / 6000)))
        overlay.fill((30, 0, 50, alpha))
        screen.blit(overlay, (0, 0))
