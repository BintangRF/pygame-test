"""Vampire plugin: Bat Swarm's own barrage setup and bats.png projectile
visual (the actual per-projectile flight/damage is the generic swarm engine
in core/battle_loop.py — see resolve_special/draw_projectile below), Crimson
Doppelganger
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

from ...core.asset_loading import load_sprite
from ...core.constants import ARENA_RECT, AVATAR_R, CURSE_COLOR, GRAY, HEIGHT, RED, WIDTH
from ...core.effects import draw_comet, draw_curse_orb, rotate_to_dir
from ...core.entities import Clone, Zone, set_status
from ...core.particles import emit_blood, emit_dark
from ...core.plugin import CharacterPlugin
from ...core.status_library import heal

# Bat Swarm's own projectile sprite (assets/bats.png — a symmetric pair of
# wings drawn tip-down) loaded once per pixel size and cached, same pattern
# as _nail_bullet_image in core/effects.py. Pre-rotated 180 degrees at load
# time so it reads as tip-up, matching rotate_to_dir's own convention (it
# expects an image "drawn tip-up" and rotates it to face a direction).
# BAT_SPRITE_SIZE is only the fallback used if the ability itself doesn't set
# its own Ability.swarm_size (see abilities.py) — Bat Swarm always does (see
# moves.py), so this is really just a safety net.
_BAT_SPRITE_CACHE = {}

def _bat_sprite(size):
    img = _BAT_SPRITE_CACHE.get(size)
    if img is None:
        img = pygame.transform.rotate(load_sprite("bats.png", size), 180)
        _BAT_SPRITE_CACHE[size] = img
    return img

# How long a freshly-conjured Crimson Doppelganger sticks around, and (see
# spawn_clone) exactly how long it carries its own "taunt" status — the two
# durations stay in lockstep so taunt never outlives the decoy it exists
# to protect.
CLONE_LIFETIME_S = 5

# Blood Hex: how long the lockdown (disarm+silence+slow, see the generic
# "curse" status in core/status_library.py) lasts, how strong its slow half
# is, and how much of any damage a cursed opponent still lands on the
# Vampire gets thrown right back at them (see on_damage_dealt).
CURSE_DURATION_S = 5
CURSE_SLOW_PCT = 0.4
# Cut by another 25% (same pass as every other ability-effect damage number
# in this file) to slow matches down further.
CURSE_REFLECT_PCT = 1


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
        battle = self.battle
        if attacker is self.fighter and self.night_timer > 0:
            self.night_timer = min(12, self.night_timer + 1.5)

    def on_attack_redirected(self):
        """If the attacker's hit was quietly redirected onto the
        Doppelganger (see status_library.taunt_redirect, driven by the
        clone's own "taunt" status), pop the decoy and strike back at
        whoever fell for it instead of resolving a normal hit. Checked
        against battle.redirect_target specifically (not just "some redirect
        happened") since taunt_redirect can now also pick a different
        character's own decoy (Phantom Lancer's illusion clones)."""
        battle = self.battle
        if battle.clone is None or battle.redirect_target is not battle.clone:
            return False
        battle.clone = None
        fooled = battle.attacker
        retal = random.randint(6, 11)  # cut by another 25% (was 8-14)
        actual = battle.apply_damage(fooled, retal)
        battle.floaters.append([fooled.pos.x, fooled.pos.y - 40, -0.6, 255, f"-{actual}", RED])
        battle.floaters.append([fooled.pos.x, fooled.pos.y - 55, -0.5, 255, "Fooled!", CURSE_COLOR])
        battle.log = f"{fooled.name} strikes a Crimson Doppelganger — Blood Explosion!"
        battle.damage_applied = True
        # _miss deliberately left False (unlike a genuine miss/evade) — the
        # decoy really did get hit, so apply_ability_tag_effects still runs
        # right after this and lands the attack's own tag effect (Sukuna's
        # bleed, Raiju's static stack, ...) on battle.redirect_target — same
        # "clone still gets hit by status-library effects" treatment a real
        # fighter would get (see status_effects.apply_ability_tag_effects).
        return True

    def resolve_special(self):
        """Bat Swarm no longer lands one flat hit — it hands off to the
        generic swarm engine (spawn_swarm_projectiles/update_swarm_projectiles
        in core/battle_loop.py), which spends the whole "barrage" phase
        flying a full barrage of individually-tracked bats through the whole
        arena, at random (not targeted) points, and dealing each one's own
        damage share the instant it actually touches any enemy-side body's
        live position — the defender, or one of its own illusions, whichever
        happens to be in the way (see _swarm_enemy_bodies; finalize_swarm
        gives the log summary once the barrage ends). This just does the
        one-time setup right as the barrage begins: roll whether the whole
        cast whiffs (Blind), otherwise launch the bats and give the usual
        per-cast feedback."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "swarm"):
            return False
        attacker, ability = battle.attacker, battle.ability
        if battle.roll_blind_miss(attacker):
            battle.swarm_projectiles = []
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 50, -0.5, 255, "Blinded!", GRAY])
            battle.log = f"{attacker.name}'s Bat Swarm fizzles out — blinded!"
            return True
        battle.spawn_swarm_projectiles()
        emit_dark(battle.fx, attacker.pos, count=26, radius=60)
        battle.log = f"{attacker.name} unleashes a Bat Swarm!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        # Status: untargetable (self — a brief evasion window while the bats
        # are still forming around the caster, not the invulnerable status)
        set_status(attacker, "untargetable", 0.4)
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
        clone = Clone(v.image, v.color, pos, vel, CLONE_LIFETIME_S, v)
        # Status: taunt (on the clone, not a fighter — redirects the
        # opponent's next hit onto the decoy, see taunt_redirect)
        set_status(clone, "taunt", CLONE_LIFETIME_S)
        battle.clone = clone
        battle.log = f"{v.name} conjures a Crimson Doppelganger — {opponent.name} is taunted into it!"

    def start_eternal_night(self):
        self.night_timer = max(self.night_timer, 6)
        self.fighter.meter = 0
        self.battle.log = f"{self.fighter.name} unleashes Eternal Night!"

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "curse":
            # Status: curse (bundled disarm+silence+slow — no separate
            # disarmed/silenced/slowed statuses needed on top of this one)
            set_status(defender, "curse", CURSE_DURATION_S, pct=CURSE_SLOW_PCT)
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Cursed!", CURSE_COLOR])
            battle.log = f"{attacker.name} places Blood Hex on {defender.name} — disarmed, silenced, slowed!"
        elif tag == "blood_pool" and defender is not None:
            # Status: none directly — poison/disarmed are applied per-tick
            # by zone_tick below while an opponent stands in the zone.
            battle.zones.append(Zone("blood", pygame.Vector2(defender.pos), 75, 6, attacker))
            battle.log = f"{attacker.name} spills a Blood Pool under {defender.name}!"
            battle.add_ring(defender.pos, 130, 0.7, CURSE_COLOR, width=5)
            emit_blood(battle.fx, defender.pos, count=38)
        elif tag == "clone":
            # Status: taunt (applied on the clone by spawn_clone above)
            self.spawn_clone(defender)
            emit_dark(battle.fx, self.fighter.pos, count=32)
        elif tag == "eternal_night":
            # Status: none — night_timer is a bespoke Vampire field (drives
            # heal_bonus/roam_speed_multiplier above), not a status
            self.start_eternal_night()
            battle.add_ring(self.fighter.pos, 220, 0.95, (140, 30, 170), width=6)
            battle.add_ring(self.fighter.pos, 150, 0.9, (200, 60, 220), width=3)
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
            set_status(fighter, "poison", 0.5)
            set_status(fighter, "disarmed", 0.5)

    def zone_style(self, zone):
        return (170, 30, 50), "Blood Pool"

    # ---- per-frame simulation ---------------------------------------------------
    def attack_speed_multiplier(self, fighter):
        if fighter is self.fighter and fighter.hp / fighter.max_hp < 0.3:
            return 1.3
        return 1.0

    def roam_speed_multiplier(self, fighter, dt):
        if fighter is not self.fighter or self.night_timer <= 0:
            return 1.0
        self.night_afterimage_cd -= dt
        if self.night_afterimage_cd <= 0:
            self.battle.spawn_afterimage(fighter)
            self.night_afterimage_cd = 0.14
        return 1.4

    def ambient_tick(self, dt):
        if self.night_timer <= 0:
            return
        self.night_timer = max(0, self.night_timer - dt)
        self.night_particle_cd -= dt
        if self.night_particle_cd <= 0:
            emit_dark(self.battle.fx, self.fighter.pos, count=4, radius=70)
            self.night_particle_cd = 0.055

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_blood(self.battle.fx, pos, self.battle.atk_dir, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is not self.fighter:
            return False
        if battle.motion == "swarm":
            size = battle.ability.swarm_size
            sprite = _bat_sprite(size)
            for proj in battle.swarm_projectiles:
                if not proj["alive"] or proj["delay"] > 0:
                    continue  # not yet armed — stays invisible until launched
                img = rotate_to_dir(sprite, proj["vel"])
                screen.blit(img, img.get_rect(center=(round(proj["pos"].x), round(proj["pos"].y))))
            return True
        if not battle.projectile_pos:
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
        alpha = min(150, int(150 * min(1.0, self.night_timer / 6)))
        overlay.fill((30, 0, 50, alpha))
        screen.blit(overlay, (0, 0))
