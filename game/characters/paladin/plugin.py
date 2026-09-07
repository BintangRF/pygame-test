"""Paladin plugin: Radiant Energy build-up and its bonus-damage payoff,
Divine Shield's Holy Nova retaliation once the barrier breaks (mitigation/
absorb itself is the generic Shield mechanic — core/status_library.py),
Judgment Mark (which just brands the target with the generic Vulnerability
status now — no bespoke detonation of its own), Sacred Ground's healing
zone, and the sword/spear/shield/warhammer weapon animation."""

import math

import pygame

from ...core.constants import ARENA_RECT, AVATAR_R, GOLD, SHIELD_COLOR, WHITE
from ...core.effects import draw_expanding_ring, draw_lightning, draw_rotated, draw_starburst, weapon_angle
from ...core.entities import Zone, set_status
from ...core.motions import ease_back, ease_in, ease_out
from ...core.particles import emit_holy
from ...core.plugin import CharacterPlugin
from ...core.status_library import heal
from .weapons import load_paladin_weapons

# which weapon prop each Paladin ability draws, by ability name (Lunge
# Strike is handled separately — it swings the same sword prop that rests
# on the shield when idle, not a second sword)
WEAPON_BY_ABILITY = {
    "Judgment Mark": "spear",
    "Divine Shield": "shield",
    "Sacred Ground": "warhammer",
    "Heaven's Verdict": "sword_big",
}

SWORD_IDLE_ANGLE = 320  # resting angle against the shield (140 + 180)
SWORD_IDLE_OFFSET = pygame.Vector2(-15, 20)


class PaladinPlugin(CharacterPlugin):
    def weapons(self):
        return load_paladin_weapons()

    # ---- damage pipeline ----------------------------------------------------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is self.fighter and attacker.radiant_energy > 0:
            bonus = round(attacker.radiant_energy)
            attacker.radiant_energy = 0.0
            return dmg + bonus, note + f" (+{bonus} Radiant)"
        return dmg, note

    def on_damage_taken(self, defender, actual):
        if defender is self.fighter:
            defender.radiant_energy += actual * 0.225  # cut by another 25% (was 0.3)

    def on_shield_broken(self, fighter, attacker, data):
        """Divine Shield's mitigation/absorb is now the generic engine's own
        Shield mechanic (status_library.apply_shield_absorb, called from
        combat_resolution.deal_damage) — this only adds Paladin's own
        payoff once that absorb pool is fully spent: Holy Nova, blasting
        back whoever broke it."""
        if fighter is not self.fighter:
            return
        battle = self.battle
        nova = round(self.fighter.atk * 0.6)  # cut by another 25% (was 0.8)
        battle.apply_damage(attacker, nova)
        battle.floaters.append(
            [attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "Holy Nova!", GOLD]
        )
        battle.add_screen_shake(17, 260)
        battle.flash_timer = max(battle.flash_timer, 340)
        battle.add_ring(attacker.pos, 90, 450, GOLD, width=5)
        emit_holy(battle.fx, attacker.pos, count=26, radius=50)

    def cast_divine_shield(self):
        """Status: shield — a flat barrier worth 20% of the Paladin's own
        max hp, sized to this kit's own needs (status_library's "shield" is
        just the generic barrier mechanic; how big it is is every
        character's own call)."""
        battle, p = self.battle, self.fighter
        set_status(p, "shield", 5000, absorb=round(p.max_hp * 0.2))
        p.meter = min(p.meter_max, p.meter + p.meter_gain)
        battle.log = f"{p.name} raises Divine Shield!"

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "mark" and defender is not None and battle.damage_applied:
            # Status: vulnerability (defender takes more damage)
            set_status(defender, "vulnerability", 4000, pct=0.5)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Marked!", GOLD])
            battle.log = f"{attacker.name} brands {defender.name} with Judgment Mark!"
        elif tag == "shield":
            self.cast_divine_shield()
            battle.add_ring(attacker.pos, 90, 500, SHIELD_COLOR, width=4)
            emit_holy(battle.fx, attacker.pos, count=24, radius=48)
        elif tag == "sacred_ground":
            # Status: none directly — regen/corruption are applied per-tick
            # by zone_tick below while a fighter stands in the zone.
            battle.zones.append(Zone("sacred", pygame.Vector2(attacker.pos), 75, 2000, attacker))
            battle.log = f"{attacker.name} creates Sacred Ground!"
            battle.add_ring(attacker.pos, 130, 700, GOLD, width=5)
            emit_holy(battle.fx, attacker.pos, count=40, radius=90)
        elif tag == "heavens_verdict":
            # Status: corruption (defender heals less) + shield (self-buff,
            # same 20%-max-hp barrier as cast_divine_shield above)
            if defender is not None:
                set_status(defender, "corruption", 4000, pct=0.6)
            set_status(attacker, "shield", 3000, absorb=round(attacker.max_hp * 0.02))
            battle.flash_timer = 450
            impact_pos = defender.pos if defender is not None else attacker.pos
            battle.add_ring(impact_pos, 180, 750, GOLD, width=6)
            battle.add_ring(impact_pos, 120, 700, WHITE, width=3)
            emit_holy(battle.fx, impact_pos, count=50, radius=80)

    # ---- zone (Sacred Ground) -------------------------------------------------
    def zone_recenter(self, zone):
        """An aura, not a fixed cast site — it follows the Paladin around
        the arena instead of staying where it was cast."""
        if zone.owner is not None and zone.owner.is_alive():
            zone.center = pygame.Vector2(zone.owner.pos)

    def zone_tick(self, fighter, zone, dt):
        # Status: none for the Paladin's own heal (see heal() call below,
        # same direct style as Vampire's Blood Pool) / corruption for
        # anyone else standing in it
        battle = self.battle
        if fighter is zone.owner:
            # 5% of max hp per second while the Paladin stands in it.
            heal(fighter, 0.05, dt)
        elif not fighter.statuses.get("invulnerable"):
            battle.apply_damage(fighter, 3.75 * dt)  # cut by another 25% (was 5)
            set_status(fighter, "corruption", 500, pct=1.5)

    def zone_slow_multiplier(self, zone):
        return 0.3

    def zone_style(self, zone):
        return (230, 200, 60), "Sacred Ground"

    # ---- weapon animation -----------------------------------------------------
    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is self.fighter and battle.ability.name == "Judgment Mark":
            return True  # the spear prop (drawn in draw_fx) replaces the generic orb
        return False

    def draw_fx(self, screen, shake_x):
        self._draw_sword(screen, shake_x)
        self._draw_weapon_swap(screen, shake_x)

    def _draw_sword(self, screen, shake_x):
        """The Paladin's sword: rests against the shield when idle, and is
        the very same prop that swings for Lunge Strike — not a second sword."""
        battle, p = self.battle, self.fighter
        if not p.is_alive():
            return
        img = battle.weapons["sword"]  # already loaded big (see load_paladin_weapons)
        pos0 = p.pos + pygame.Vector2(shake_x, 0)

        active_ability = battle.ability.name if (battle.mode == "attack" and battle.attacker is p) else None
        is_lunge = active_ability == "Lunge Strike"

        if not is_lunge:
            battle.weapon_trail.clear()
            if active_ability == "Heaven's Verdict":
                return  # the big sword prop (drawn elsewhere) already covers this
            pos = pos0 + SWORD_IDLE_OFFSET
            draw_rotated(screen, img, pos, SWORD_IDLE_ANGLE)
            return

        phase, t = battle.current_phase, battle.phase_t
        if phase == "strike":
            reach = 10 + (AVATAR_R + 30 - 10) * ease_back(t)  # slight overshoot before settling
        else:
            reach = {"windup": 10, "impact": AVATAR_R + 30, "return": 12}.get(phase, 12)
        if phase == "windup":
            extra = -30 * ease_out(t)
        elif phase == "strike":
            extra = -30 + 35 * ease_in(t)
        elif phase == "impact":
            extra = 5 + 6 * math.sin(t * math.pi)
            draw_starburst(screen, pos0 + battle.atk_dir * reach, WHITE, size=30, fade=1 - t)
            draw_expanding_ring(screen, pos0 + battle.atk_dir * reach, 45 * t, GOLD, width=3)
        else:  # return
            extra = 5 - 25 * ease_out(t)
        angle = weapon_angle(battle.atk_dir, extra + 180)
        pos = pos0 + battle.atk_dir * reach

        if phase in ("strike", "impact"):
            battle.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(battle.weapon_trail) > 7:
                battle.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(battle.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(battle.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            battle.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

    def _draw_weapon_swap(self, screen, shake_x):
        battle, p = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is p):
            return
        weapon_key = WEAPON_BY_ABILITY.get(battle.ability.name)
        if weapon_key is None:
            return

        img = battle.weapons[weapon_key]
        phase, t = battle.current_phase, battle.phase_t
        p0 = p.pos + pygame.Vector2(shake_x, 0)
        pos = pygame.Vector2(p0)
        angle = 0.0
        scale = 1.0
        trail_ok = False

        if weapon_key == "sword_big":
            # overhead diagonal chop: tilts back, sweeps through in an arc,
            # snaps on impact, then retracts — not a plain vertical bob
            height = 70
            if phase == "windup":
                pos = p0 + pygame.Vector2(0, -55)
                angle = -35
            elif phase == "arc":
                pos = p0 + pygame.Vector2(0, -55 * (1 - t) - height * 0.15 * math.sin(math.pi * t))
                angle = -35 + 60 * ease_in(t)
            elif phase == "impact":
                pos = p0 + pygame.Vector2(0, -4)
                angle = 25 + 8 * math.sin(t * math.pi)
                scale = 1.0 + 0.15 * (1 - t)
                draw_starburst(screen, pos, GOLD, size=42, fade=1 - t)
                draw_expanding_ring(screen, pos, 70 * t, GOLD, width=4)
            else:  # return
                pos = p0 + pygame.Vector2(0, -55 * t)
                angle = 25 - 60 * ease_out(t)
            if phase == "impact":
                draw_lightning(screen, pygame.Vector2(pos.x, ARENA_RECT.top - 10),
                                pygame.Vector2(pos.x, pos.y - 10), GOLD, segments=9, jitter=20, branches=3)
                for side in (-1, 1):
                    draw_lightning(screen, pygame.Vector2(pos.x + side * 26, ARENA_RECT.top - 10),
                                    pygame.Vector2(pos.x + side * 10, pos.y - 6), GOLD,
                                    segments=6, jitter=14, branches=1)
            trail_ok = phase in ("arc", "impact")

        elif weapon_key == "spear":
            # cocked back over the shoulder during windup, then a clean
            # forward release instead of holding steady the whole time
            if battle.projectile_pos is not None:
                pos = battle.projectile_pos + pygame.Vector2(shake_x, 0)
                angle = weapon_angle(battle.atk_dir, 0)
                trail_ok = True
            else:
                cock = -110 * ease_out(t) if phase == "windup" else 0
                pos = p0 - battle.atk_dir * 8 + pygame.Vector2(0, -6)
                angle = weapon_angle(battle.atk_dir, cock)

        elif weapon_key == "shield":
            # rises into a guard position with a swing, then flashes a
            # ward ring outward once the barrier locks in
            if phase == "windup":
                rise = 30 * (1 - ease_out(t))
                pos = p0 + battle.atk_dir * 20 + pygame.Vector2(0, rise)
                angle = weapon_angle(battle.atk_dir, -20 * (1 - ease_out(t)))
            else:
                pulse = 1.0 + 0.08 * math.sin(pygame.time.get_ticks() * 0.01)
                scale = pulse
                pos = p0 + battle.atk_dir * 20
                angle = weapon_angle(battle.atk_dir, 0)
                if phase == "release" and t < 0.4:
                    draw_expanding_ring(screen, pos, 20 + 60 * (t / 0.4), SHIELD_COLOR, width=4)
                    draw_starburst(screen, pos, SHIELD_COLOR, size=24, fade=1 - t / 0.4)

        elif weapon_key == "warhammer":
            # raised with a backward tilt, then a real diagonal smash down
            # with a dust ring on landing, instead of a pure vertical drop
            if phase in ("windup", "channel"):
                lift = -40 if phase == "windup" else -48
                angle = -20
            else:  # release
                lift = -48 + 48 * ease_in(t)
                angle = -20 + 35 * ease_in(t)
                if t > 0.7:
                    draw_expanding_ring(screen, p0 + pygame.Vector2(0, -6),
                                         65 * ((t - 0.7) / 0.3), GOLD, width=4)
                    draw_starburst(screen, p0 + pygame.Vector2(0, -6), WHITE, size=26, fade=(t - 0.7) / 0.3)
            pos = p0 + pygame.Vector2(0, lift - 10)
            trail_ok = phase == "release"

        scaled_img = img
        if scale != 1.0:
            w, h = img.get_size()
            scaled_img = pygame.transform.smoothscale(img, (max(1, int(w * scale)), max(1, int(h * scale))))

        if trail_ok:
            battle.weapon_trail.append((scaled_img, pygame.Vector2(pos), angle))
            if len(battle.weapon_trail) > 7:
                battle.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(battle.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(battle.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            battle.weapon_trail.clear()

        draw_rotated(screen, scaled_img, pos, angle)

    def impact_particles(self, pos, count):
        emit_holy(self.battle.fx, pos, count=count)
        return True
