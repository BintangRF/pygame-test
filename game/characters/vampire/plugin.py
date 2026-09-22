"""Vampire plugin: Bat Swarm's own barrage setup and vampire/bats.png projectile
visual (the actual per-projectile flight/damage is the generic swarm engine
in core/battle_loop.py — see resolve_special/draw_projectile below), Crimson
Doppelganger
conjuring/deception (marking the clone itself with the generic "taunt"
status — see status_library.taunt_redirect — then retaliating once its
target takes the bait; see spawn_clone/on_attack_redirected), the Blood
Hunger passive (the generic "lifesteal" status kept refreshed on the
Vampire every frame, so every basic attack and skill always heals it, topped
up once its own hp drops low, and the generic "damage_reduction" status
layered on top at that same low-hp threshold — see ambient_tick/heal_bonus),
Blood Hex's
lockdown (the generic "curse" status — disarm+silence+slow, see
core/status_library.py) plus its own bespoke punish (a cursed opponent who
still lands a hit on the Vampire gets it thrown right back at them — see
on_damage_dealt), Blood Pool's zone (heals the Vampire, poisons and disarms
anyone else standing in it), and Eternal Night's window (movement speed,
faster basic/skill swings, and blind+poison on every landed hit — see
attack_speed_multiplier/roam_speed_multiplier/on_damage_dealt)."""

import math
import random

import pygame

from ...core.asset_loading import load_sprite
from ...core.constants import ARENA_RECT, AVATAR_R, CURSE_COLOR, GRAY, HEIGHT, RED, WIDTH
from ...core.effects import draw_bolt_fx, draw_curse_orb, draw_slash_fx, rotate_to_dir
from ...core.entities import Clone, Zone, set_status
from ...core.particles import emit_blood, emit_dark
from ...core.plugin import CharacterPlugin
from ...core.status_library import heal

# Bat Swarm's own projectile sprite (assets/vampire/bats.png — a symmetric pair of
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
        img = pygame.transform.rotate(load_sprite("vampire/bats.png", size), 180)
        _BAT_SPRITE_CACHE[size] = img
    return img

# How long a freshly-conjured Crimson Doppelganger sticks around, and (see
# spawn_clone) exactly how long it carries its own "taunt" status — the two
# durations stay in lockstep so taunt never outlives the decoy it exists
# to protect.
CLONE_LIFETIME_S = 5

# Crimson Doppelganger's own hp: a pct of the Vampire's own current max_hp
# (not a flat constant — see spawn_clone), same "scaled off its owner" model
# every clone-owning character now uses.
CLONE_HP_PCT = 0.15

# Crimson Doppelganger's bespoke punish: if whoever fell for the taunt
# lands a hit on the decoy anyway, they take this much straight back (see
# on_attack_redirected). Cut by another 25% (was 8-14), same pass as every
# other ability-effect damage number in this file.
CLONE_RETALIATION_DMG_MIN = 8
CLONE_RETALIATION_DMG_MAX = 15

# Blood Hex: how long the lockdown (disarm+silence+slow, see the generic
# "curse" status in core/status_library.py) lasts, how strong its slow half
# is, and how much of any damage a cursed opponent still lands on the
# Vampire gets thrown right back at them (see on_damage_dealt).
CURSE_DURATION_S = 5
CURSE_SLOW_PCT = 0.4
# Cut by another 25% (same pass as every other ability-effect damage number
# in this file) to slow matches down further.

# Passive: Blood Hunger — the Vampire keeps the generic "lifesteal" status
# (StatusLibraryMixin.lifesteal_pct — flat 100% of whatever damage actually
# landed, see apply_lifesteal in combat_resolution.py) refreshed on itself
# every frame (see ambient_tick below), so every basic attack and skill
# always heals it; below BLOOD_HUNGER_HP_PCT own hp, heal_bonus below tops
# that up by BLOOD_HUNGER_HEAL_BONUS more, and ambient_tick also layers the
# generic "damage_reduction" status on top, worth BLOOD_HUNGER_DR_PCT — pure
# sustain doesn't help against a single hit that outright outpaces it, so
# the same low-hp trigger now also blunts incoming damage directly, on a
# Vampire that otherwise carries 0 armor of its own (see core/assets.py).
BLOOD_HUNGER_HP_PCT = 0.35
BLOOD_HUNGER_HEAL_BONUS = 0.3
BLOOD_HUNGER_DR_PCT = 0.2
# How long the "lifesteal" status is set for each time ambient_tick
# refreshes it — kept well above one frame so it never actually lapses.
BLOOD_HUNGER_LIFESTEAL_DURATION_S = 1.0

# Blood Pool: how big the zone is and how long it lingers (see
# apply_tag_effects below), and the pct of max hp healed per second while
# the Vampire stands in its own pool (see zone_tick below). The heal is a
# flat rate — called straight through heal(), not routed through
# heal_bonus, so it stays the same regardless of Blood Hunger/Eternal Night.
BLOOD_POOL_RADIUS = 100
BLOOD_POOL_DURATION_S = 6
BLOOD_POOL_HEAL_PCT = 0.01
# How long the "poison" status is set for on each tick an opponent stands
# in the pool (zone_tick) — refreshed every frame, so this is just the
# buffer that lets it fade shortly after they step out.
BLOOD_POOL_POISON_DURATION_S = 1

# Ultimate: Eternal Night — while the window is active (night_timer > 0)
# the Vampire moves faster, every landed basic attack or skill also swings
# faster, and blinds+poisons whoever it hits (see roam_speed_multiplier/
# attack_speed_multiplier/on_damage_dealt).
ETERNAL_NIGHT_MOVE_SPEED = 1.8
ETERNAL_NIGHT_ATTACK_SPEED = 1.3
ETERNAL_NIGHT_BLIND_CHANCE = 0.2
ETERNAL_NIGHT_BLIND_DURATION_S = 2.0
ETERNAL_NIGHT_POISON_DURATION_S = 6.0
# How long the window itself lasts: the initial grant on cast, how much
# every landed hit extends it by, and the hard cap that extension can't
# push past (see start_eternal_night/on_damage_dealt).
ETERNAL_NIGHT_DURATION_S = 6
ETERNAL_NIGHT_EXTEND_S = 1.5
ETERNAL_NIGHT_MAX_DURATION_S = 12

# Bat Swarm: how long the caster is untargetable for while the bats are
# still forming around it (see resolve_special) — a brief evasion window,
# not the invulnerable status.
BAT_SWARM_UNTARGETABLE_DURATION_S = 0.4


class VampirePlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.night_timer = 0
        self.night_particle_cd = 0
        self.night_afterimage_cd = 0

    # ---- passive: Blood Hunger, plus damage pipeline --------------------------
    def heal_bonus(self, attacker, heal_mult):
        """Passive: Blood Hunger's low-hp top-up — the always-on heal
        itself is just the generic "lifesteal" status kept refreshed on the
        Vampire (see ambient_tick below); this only adds the extra bit once
        its own hp drops below BLOOD_HUNGER_HP_PCT."""
        if attacker is self.fighter and attacker.hp / attacker.max_hp < BLOOD_HUNGER_HP_PCT:
            heal_mult += BLOOD_HUNGER_HEAL_BONUS
        return heal_mult

    def on_damage_dealt(self, attacker, defender, actual):
        """Ultimate: Eternal Night — while the window is active (night_timer
        > 0), every landed basic attack or skill (this fires for each one,
        including a Bat Swarm projectile's own hit — see battle_loop.py)
        extends the window itself, and blinds + poisons whoever it hit (the
        attack-speed half of the ultimate is in attack_speed_multiplier
        below)."""
        if attacker is not self.fighter or self.night_timer <= 0:
            return
        self.night_timer = min(ETERNAL_NIGHT_MAX_DURATION_S, self.night_timer + ETERNAL_NIGHT_EXTEND_S)
        # Status: blind (chance-based miss) + poison (DoT) — both on
        # `defender`, refreshed on every hit landed during the window.
        set_status(defender, "blind", ETERNAL_NIGHT_BLIND_DURATION_S, chance=ETERNAL_NIGHT_BLIND_CHANCE)
        set_status(defender, "poison", ETERNAL_NIGHT_POISON_DURATION_S)

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
        retal = random.randint(CLONE_RETALIATION_DMG_MIN, CLONE_RETALIATION_DMG_MAX)
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
        set_status(attacker, "untargetable", BAT_SWARM_UNTARGETABLE_DURATION_S)
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
        clone = Clone(v.image, v.color, pos, vel, CLONE_LIFETIME_S, v, round(v.max_hp * CLONE_HP_PCT))
        # Status: taunt (on the clone, not a fighter — redirects the
        # opponent's next hit onto the decoy, see taunt_redirect)
        set_status(clone, "taunt", CLONE_LIFETIME_S)
        battle.clone = clone
        battle.log = f"{v.name} conjures a Crimson Doppelganger — {opponent.name} is taunted into it!"

    def start_eternal_night(self):
        # Meter reset is generic now — see try_start_attack() in
        # core/combat_resolution.py.
        self.night_timer = max(self.night_timer, ETERNAL_NIGHT_DURATION_S)
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
        elif tag == "blood_pool":
            # Status: none directly — poison/disarmed are applied per-tick
            # by zone_tick below while an opponent stands in the zone.
            # cast_target="self" (see moves.py) — the pool is centered on
            # the Vampire's own position, not the defender's: it's a self
            # heal the Vampire is guaranteed to be standing in the instant
            # it's cast, with the enemy having to walk into it to eat the
            # poison/disarm, not a debuff dropped at the enemy's feet.
            battle.zones.append(
                Zone("blood", pygame.Vector2(attacker.pos), BLOOD_POOL_RADIUS, BLOOD_POOL_DURATION_S, attacker)
            )
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            battle.log = f"{attacker.name} spills a Blood Pool beneath their own feet!"
            battle.add_ring(attacker.pos, BLOOD_POOL_RADIUS + 30, 0.7, CURSE_COLOR, width=5)
            emit_blood(battle.fx, attacker.pos, count=38)
        elif tag == "clone":
            # Status: taunt (applied on the clone by spawn_clone above)
            self.spawn_clone(defender)
            emit_dark(battle.fx, self.fighter.pos, count=32)
        elif tag == "eternal_night":
            # Status: none — night_timer is a bespoke Vampire field (drives
            # attack_speed_multiplier/roam_speed_multiplier/on_damage_dealt
            # above), not a status
            self.start_eternal_night()
            battle.add_ring(self.fighter.pos, 220, 0.95, (140, 30, 170), width=6)
            battle.add_ring(self.fighter.pos, 150, 0.9, (200, 60, 220), width=3)
            emit_dark(battle.fx, self.fighter.pos, count=60, radius=90)

    # ---- zone (Blood Pool) ------------------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        # Status: poison (DoT) applied to whoever isn't the pool's owner
        if fighter is zone.owner:
            # Meter gain is a flat, one-time award on cast now (see
            # apply_tag_effects' own tag == "blood_pool" branch), same as
            # every other skill in this game — no longer accrued per second
            # just for standing in the Vampire's own pool.
            heal(fighter, BLOOD_POOL_HEAL_PCT, dt)
        else:
            # Refreshed every frame the enemy stands in the pool, same
            # trick as Sacred Ground's corruption (paladin/plugin.py) — a
            # short buffer duration so both fade within half a second of
            # stepping out instead of lingering. dps kwarg omitted so it
            # falls back to the canonical POISON_BASE_DPS flat rate in
            # status_library.py, same as every status-effect DoT now.
            set_status(fighter, "poison", BLOOD_POOL_POISON_DURATION_S)

    def zone_style(self, zone):
        return (170, 30, 50), "Blood Pool"

    # ---- per-frame simulation ---------------------------------------------------
    def attack_speed_multiplier(self, fighter):
        """Ultimate: Eternal Night's attack-speed half (the blind/poison
        half is in on_damage_dealt above) — a flat +15% to the Vampire's
        own basic attack and skill speed while the window is active."""
        if fighter is self.fighter and self.night_timer > 0:
            return ETERNAL_NIGHT_ATTACK_SPEED
        return 1.0

    def roam_speed_multiplier(self, fighter, dt):
        if fighter is not self.fighter or self.night_timer <= 0:
            return 1.0
        self.night_afterimage_cd -= dt
        if self.night_afterimage_cd <= 0:
            self.battle.spawn_afterimage(fighter)
            self.night_afterimage_cd = 0.14
        return ETERNAL_NIGHT_MOVE_SPEED

    def ambient_tick(self, dt):
        v = self.fighter
        # Status: lifesteal — refreshed every frame so it never actually
        # expires, the always-on half of Blood Hunger (see heal_bonus above
        # for the low-hp top-up).
        set_status(v, "lifesteal", BLOOD_HUNGER_LIFESTEAL_DURATION_S)
        # Status: damage_reduction — the other half of Blood Hunger's low-hp
        # kick-in, refreshed every frame right alongside lifesteal while hp
        # stays under BLOOD_HUNGER_HP_PCT, and dropped the instant it heals
        # back above that (no lingering buff once it's safe again).
        if v.is_alive() and v.hp / v.max_hp < BLOOD_HUNGER_HP_PCT:
            set_status(v, "damage_reduction", BLOOD_HUNGER_LIFESTEAL_DURATION_S, pct=BLOOD_HUNGER_DR_PCT)
        else:
            v.statuses.pop("damage_reduction", None)
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

    def draw_fx(self, screen, shake_x):
        """Shadow Spin's own claw-connect moment — bare-handed (no weapon
        prop to layer the flipbook under/over, unlike every other melee
        basic), so just the painted slash flipbook right at the point of
        contact, once the dash-in actually lands the Vampire next to its
        target."""
        battle, v = self.battle, self.fighter
        if not (
            battle.mode == "attack" and battle.attacker is v and battle.motion == "spin"
            and battle.current_phase == "impact"
        ):
            return
        p = v.pos + pygame.Vector2(shake_x, 0)
        strike_pos = p + battle.atk_dir * (AVATAR_R + 10)
        draw_slash_fx(screen, strike_pos, battle.atk_dir, battle.phase_t, size=95)

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
            draw_bolt_fx(screen, battle.projectile_pos, battle.atk_dir, battle.attacker.color,
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
