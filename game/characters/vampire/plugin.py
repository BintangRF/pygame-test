"""Vampire plugin: Bat Swarm's own damage resolve, Crimson Doppelganger
conjuring/deception (and the retaliation when it's attacked — works against
whichever opponent falls for it), Blood Curse's reflect-heal off any cursed
opponent, Blood Pool's healing zone, and Eternal Night's lifesteal window
and movement boost. (Judgment Mark's bonus damage is generic — see
core/status_library.py — so it isn't reimplemented here anymore.)"""

import math
import random

import pygame

from ...core.constants import ARENA_RECT, AVATAR_R, CURSE_COLOR, HEIGHT, RED, WIDTH
from ...core.effects import draw_comet, draw_curse_orb
from ...core.entities import Clone, Zone, set_status
from ...core.particles import emit_blood, emit_dark
from ...core.plugin import CharacterPlugin


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
        """Blood Curse: while any opponent carries the vampire's curse
        status, every hit they land heals the Vampire back — works against
        whoever it's cast on, not just one specific opponent."""
        battle = self.battle
        if attacker is not self.fighter and "cursed" in attacker.statuses:
            curse = attacker.statuses["cursed"]
            curse["stacks"] = curse.get("stacks", 0) + 1
            heal_c = round(actual * (curse["heal_pct"] + curse["stacks"] * 0.05))
            self.fighter.hp = min(self.fighter.max_hp, self.fighter.hp + heal_c)
            self.fighter.meter = min(self.fighter.meter_max, self.fighter.meter + 3)
            battle.floaters.append(
                [self.fighter.pos.x, self.fighter.pos.y - 40, -0.6, 255, f"+{heal_c} Curse", CURSE_COLOR]
            )
        if attacker is self.fighter and self.night_timer > 0:
            self.night_timer = min(12000, self.night_timer + 1500)

    def redirect_check(self, attacker, defender, ability):
        battle = self.battle
        return bool(
            attacker is not self.fighter and defender is self.fighter and battle.clone is not None
            and ability.dmg_mult > 0 and random.random() < 0.5
        )

    def on_attack_redirected(self):
        """If the attacker's hit was quietly redirected onto the
        Doppelganger (see redirect_check), pop the decoy and strike back at
        whoever fell for it instead of resolving a normal hit."""
        battle = self.battle
        if not (battle.attack_target_clone and battle.clone is not None):
            return False
        battle.clone = None
        fooled = battle.attacker
        retal = random.randint(8, 14)
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
        set_status(attacker, "untargetable", 700)
        return True

    # ---- clone / eternal night ------------------------------------------------
    def spawn_clone(self):
        battle, v = self.battle, self.fighter
        offset = pygame.Vector2(random.uniform(-40, 40), random.uniform(-40, 40))
        pos = pygame.Vector2(v.pos) + offset
        pos.x = max(ARENA_RECT.left + AVATAR_R, min(ARENA_RECT.right - AVATAR_R, pos.x))
        pos.y = max(ARENA_RECT.top + AVATAR_R, min(ARENA_RECT.bottom - AVATAR_R, pos.y))
        angle = random.uniform(0, math.tau)
        vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * random.uniform(60, 100)
        battle.clone = Clone(v.image, v.color, pos, vel, 5000)
        battle.log = f"{v.name} conjures a Crimson Doppelganger!"

    def start_eternal_night(self):
        self.night_timer = max(self.night_timer, 6000)
        self.fighter.meter = 0
        self.battle.log = f"{self.fighter.name} unleashes Eternal Night!"

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "curse":
            set_status(defender, "cursed", 5000, heal_pct=0.25, stacks=0)
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Cursed!", CURSE_COLOR])
            battle.log = f"{attacker.name} places Blood Curse on {defender.name}!"
        elif tag == "blood_pool":
            battle.zones.append(Zone("blood", pygame.Vector2(attacker.pos), 75, 6000, attacker))
            battle.log = f"{attacker.name} spills a Blood Pool!"
            battle.add_ring(attacker.pos, 130, 700, CURSE_COLOR, width=5)
            emit_blood(battle.fx, attacker.pos, count=38)
        elif tag == "clone":
            self.spawn_clone()
            emit_dark(battle.fx, self.fighter.pos, count=32)
        elif tag == "eternal_night":
            self.start_eternal_night()
            battle.add_ring(self.fighter.pos, 220, 950, (140, 30, 170), width=6)
            battle.add_ring(self.fighter.pos, 150, 900, (200, 60, 220), width=3)
            emit_dark(battle.fx, self.fighter.pos, count=60, radius=90)

    # ---- zone (Blood Pool) ------------------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        battle = self.battle
        if fighter is zone.owner:
            fighter.hp = min(fighter.max_hp, fighter.hp + 6 * dt)
            fighter.meter = min(fighter.meter_max, fighter.meter + 8 * dt)
        elif not fighter.statuses.get("invulnerable"):
            battle.apply_damage(fighter, 5 * dt)

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
        if name == "Blood Curse":
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
