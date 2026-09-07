"""Berserker plugin: Berserker Rage (activation, its tag-cast side effects,
and the forced last-stand that fires instead of a killing blow), the Fury
passive that permanently stacks on any big hit landed, Rage's melee-range/
damage/speed bonuses, and the axe/Axe-Throw weapon animation."""

import math

import pygame

from ...core.constants import AVATAR_R, HEIGHT, ORANGE, RED, WHITE, WIDTH
from ...core.effects import (
    draw_expanding_ring,
    draw_fan,
    draw_rotated,
    draw_slash,
    draw_slash_arc,
    draw_starburst,
    weapon_angle,
)
from ...core.entities import set_status
from ...core.motions import ease_in, ease_out
from ...core.particles import emit_debris, emit_explosion
from ...core.plugin import CharacterPlugin
from .weapons import load_berserker_weapons

# Berserker Rage widens the basic attack's melee reach while it's active
RAGE_RANGE_BONUS = 65
# ...and hits harder / swings faster, so the immunity window is also a real damage spike
RAGE_DMG_MULT = 1.2
RAGE_ATTACK_SPEED = 1.2
RAGE_MOVE_SPEED = 3.0
RAGE_DURATION_MS = 13000

# passive: any single hit that deals at least this much damage permanently
# toughens the Berserker up — stacks without limit, for the rest of the match
FURY_THRESHOLD = 4
FURY_ARMOR_GAIN = 0.5  # armor is on a 0-100 scale, so this is +0.5%
FURY_ATK_GAIN = 0.7
FURY_SPEED_GAIN = 0.7

AXE_THROW_SPREAD_START = 20


class BerserkerPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.rage_particle_cd = 0

    def weapons(self):
        return load_berserker_weapons()

    # ---- ability gating -------------------------------------------------------
    def melee_range_bonus(self, attacker, melee_range):
        if melee_range is not None and attacker is self.fighter and self._is_raging(attacker):
            return melee_range + RAGE_RANGE_BONUS
        return melee_range

    def cooldown_bonus(self, attacker, ability, cooldown):
        if attacker is self.fighter and ability.tag == "axe_throw" and self._is_raging(attacker):
            return round(cooldown * 0.45)
        return cooldown

    # ---- damage pipeline ----------------------------------------------------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        """The actual damage math for Rage's boost is generic now (see
        start_rage's apply_attack_up — status_outgoing_multiplier already
        applied it before this hook ever runs); this only adds the [RAGE]
        note, since the generic multiplier has no annotation mechanism."""
        if attacker is self.fighter and self._is_raging(attacker):
            return dmg, note + " [RAGE]"
        return dmg, note

    @staticmethod
    def _is_raging(fighter):
        """Rage has no status of its own — it's just the standard buff
        bundle start_rage() applies, all sharing one clock. Invulnerable is
        the one of those no other status in the bundle overlaps with, so it
        doubles as "is this fighter currently raging"."""
        return "invulnerable" in fighter.statuses

    def pre_damage(self, target, dmg):
        if target is not self.fighter:
            return None
        if dmg >= FURY_THRESHOLD:
            self._trigger_fury(target)
        if target.hp - dmg <= 0 and not target.abilities["ultimate"].used:
            actual = target.hp - 1
            target.hp = 1
            self.start_rage(death_save=True)
            return actual
        return None

    def _trigger_fury(self, b):
        """Passive: a single hit for at least FURY_THRESHOLD permanently
        raises armor, attack, and move speed — stacks without limit for the
        rest of the match."""
        battle = self.battle
        b.armor += FURY_ARMOR_GAIN
        b.atk += FURY_ATK_GAIN
        b.move_speed_mult += FURY_SPEED_GAIN
        battle.floaters.append([b.pos.x, b.pos.y - 70, -0.6, 255, "FURY UP!", ORANGE])
        battle.log = f"{b.name}'s Fury grows — armor, power, and speed rise permanently!"

    def start_rage(self, death_save=False):
        # Status: attack_up + attack_speed_up + move_speed_up + invulnerable
        # (the whole Rage buff bundle, all sharing one clock)
        battle, b = self.battle, self.fighter
        # Rage has no status of its own — it's entirely the standard *_up
        # bundle plus the generic Invulnerable status, all on one shared
        # clock (apply_damage()/tick_library_effects()/status_outgoing_
        # multiplier already read every one of these with no knowledge of
        # Berserker at all). Berserker's own bespoke bits (melee-range
        # bonus, axe-throw cooldown cut, "[RAGE]" note, overlay/particles)
        # detect the window via _is_raging(); the death-save/last-stand
        # timer rides along as a plain kwarg on the Invulnerable status.
        set_status(b, "attack_up", RAGE_DURATION_MS, pct=RAGE_DMG_MULT - 1)
        set_status(b, "attack_speed_up", RAGE_DURATION_MS, pct=RAGE_ATTACK_SPEED - 1)
        set_status(b, "move_speed_up", RAGE_DURATION_MS, pct=RAGE_MOVE_SPEED - 1)
        set_status(b, "invulnerable", RAGE_DURATION_MS, death_save=death_save)
        # a forced last-stand activation didn't go through the normal
        # attack sequence, so its one-shot flag wouldn't otherwise get set
        b.abilities["ultimate"].used = True
        battle.add_screen_shake(16, 280)
        battle.flash_timer = max(battle.flash_timer, 380)
        if death_save:
            battle.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "LAST STAND!", ORANGE])
            battle.log = f"{b.name} refuses to fall — Berserker Rage erupts in a last stand!"
        else:
            battle.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "RAGE!", ORANGE])
            secs = RAGE_DURATION_MS // 1000
            battle.log = f"{b.name} flies into a Berserker Rage — unstoppable for {secs}s!"

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter or ability.tag != "berserker_rage":
            return
        battle = self.battle
        self.start_rage()
        battle.add_ring(self.fighter.pos, 150, 600, ORANGE, width=6)
        emit_debris(battle.fx, self.fighter.pos, count=34, speed=(100, 260))
        emit_explosion(battle.fx, self.fighter.pos, ORANGE, count=20)

    def on_status_expire(self, fighter, name, data):
        if fighter is not self.fighter or name != "invulnerable" or not data.get("death_save"):
            return
        battle = self.battle
        if battle.winner is not None:
            return  # match was already decided before the last-stand timer ran out
        fighter.hp = 0
        battle.floaters.append([fighter.pos.x, fighter.pos.y - 40, -0.6, 255, "Rage Fades...", ORANGE])
        battle.log = f"{fighter.name}'s Berserker Rage fades — the last stand ends."
        battle.declare_winner()

    # ---- per-frame simulation ---------------------------------------------------
    # attack/move speed while raging come from the generic attack_speed_up/
    # move_speed_up statuses applied in start_rage() — no bespoke multiplier
    # hooks needed here anymore (the engine already reads those generically
    # in battle_loop.py, and duplicating it here would double-apply it).

    def ambient_tick(self, dt_ms):
        if not self._is_raging(self.fighter):
            return
        self.rage_particle_cd -= dt_ms
        if self.rage_particle_cd <= 0:
            emit_debris(self.battle.fx, self.fighter.pos, count=4, speed=(30, 90))
            self.rage_particle_cd = 65

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_debris(self.battle.fx, pos, count=count)  # metal shrapnel/debris
        return True

    def full_screen_overlay(self, screen):
        b = self.fighter
        if not self._is_raging(b):
            return
        remaining = b.statuses["invulnerable"]["time"]
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        alpha = min(110, int(110 * min(1.0, remaining / 8000)))
        overlay.fill((160, 30, 10, alpha))
        screen.blit(overlay, (0, 0))

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is self.fighter and battle.ability.name == "Axe Throw":
            self._draw_axe_fan(screen)
            return True
        return False

    def draw_fx(self, screen, shake_x):
        """The Berserker's axe: swung for Reckless Cleave, thrown as the
        Axe Throw projectile (see _draw_axe_fan), and raised overhead during
        the Berserker Rage roar."""
        battle, b = self.battle, self.fighter
        if not b.is_alive():
            return
        if not (battle.mode == "attack" and battle.attacker is b):
            return
        name = battle.ability.name
        if name not in ("Reckless Cleave", "Berserker Rage"):
            return

        img = battle.weapons["axe"]
        p = b.pos + pygame.Vector2(shake_x, 0)
        phase, t = battle.current_phase, battle.phase_t

        if name == "Berserker Rage":
            lift = 40 + 8 * math.sin(pygame.time.get_ticks() * 0.02)
            pos = p + pygame.Vector2(0, -lift)
            if phase == "channel":
                draw_expanding_ring(screen, p, 20 + 80 * t, ORANGE, width=5)
                draw_starburst(screen, p, ORANGE, size=20 + 20 * t, fade=t)
            draw_rotated(screen, img, pos, 0)
            return

        # Two crossing rakes (like a claw swipe), not a dash-in strike: the
        # axe sweeps one diagonal on slash1, the opposite diagonal on
        # slash2, while the body barely moves (see apply_motion_frame).
        # Each rake also gets its own draw_slash_arc sweep (red then orange,
        # so the crossing diagonals stay visually distinct) plus a bright
        # cut mark and starburst pop right as the axe connects.
        if phase == "windup":
            reach, extra = 10, -60 * ease_out(t)
        elif phase == "slash1":
            reach = AVATAR_R + 14
            extra = -60 + 120 * ease_in(t)
            swing_dir = battle.atk_dir.rotate(-35)
            draw_slash_arc(screen, p, swing_dir, radius=44 + 10 * t, spread_deg=90,
                            color=RED, width=6, fade=1 - t)
            if t > 0.55:
                strike_pos = p + battle.atk_dir * reach
                draw_slash(screen, strike_pos, swing_dir, WHITE, length=32, width=5)
                draw_starburst(screen, strike_pos, WHITE, size=26, fade=(1 - t) / 0.45)
        elif phase == "slash2":
            reach = AVATAR_R + 14
            extra = 60 - 120 * ease_in(t)
            swing_dir = battle.atk_dir.rotate(35)
            draw_slash_arc(screen, p, swing_dir, radius=48 + 12 * t, spread_deg=100,
                            color=ORANGE, width=7, fade=1 - t)
            if t > 0.55:
                strike_pos = p + battle.atk_dir * reach
                draw_slash(screen, strike_pos, swing_dir, WHITE, length=36, width=6)
                draw_starburst(screen, strike_pos, WHITE, size=30, fade=(1 - t) / 0.45)
        else:  # return
            reach = AVATAR_R + 14 - (AVATAR_R + 4) * ease_out(t)
            extra = -60 + 60 * ease_out(t)
        angle = weapon_angle(battle.atk_dir, extra + 180)
        pos = p + battle.atk_dir * reach

        if phase in ("slash1", "slash2"):
            battle.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(battle.weapon_trail) > 7:
                battle.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(battle.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(battle.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            battle.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

    def _draw_axe_fan(self, screen):
        """Axe Throw hits as a widening fan/cone with a fixed maximum reach."""

        battle = self.battle
        phase, t = battle.current_phase, battle.phase_t
        color = battle.attacker.color

        base_angle = math.atan2(
            battle.atk_dir.y,
            battle.atk_dir.x,
        )

        # Fixed ability range — independent of target distance. Read straight
        # off the ability so the visual never drifts from the actual hit
        # area splash_cone (combat_resolution.splash_aoe_to_clones) checks —
        # a clone standing inside the drawn fan must always be inside the
        # real one too.
        full_reach = battle.ability.aoe_radius
        end_spread_deg = battle.ability.aoe_cone_deg

        if phase == "fire":
            reach = full_reach * ease_out(t)
            spread = math.radians(
                AXE_THROW_SPREAD_START
                + (end_spread_deg - AXE_THROW_SPREAD_START) * t
            )

            draw_fan(
                screen,
                battle.attacker_start,
                base_angle,
                spread,
                reach,
                color,
                fill_alpha=130,
            )

            for frac in (-0.9, -0.45, 0.0, 0.45, 0.9):
                a = base_angle + spread / 2 * frac

                pos = (
                    battle.attacker_start
                    + pygame.Vector2(math.cos(a), math.sin(a)) * reach
                )

                angle_deg = (
                    pygame.time.get_ticks() * 0.9
                    + frac * 140
                ) % 360

                draw_rotated(
                    screen,
                    battle.weapons["axe"],
                    pos,
                    angle_deg,
                )

        elif phase == "impact":
            spread = math.radians(end_spread_deg)

            draw_fan(
                screen,
                battle.attacker_start,
                base_angle,
                spread,
                full_reach,
                color,
                fill_alpha=int(120 * (1 - t)),
            )

            # Impact remains at the actual target position.
            draw_starburst(
                screen,
                battle.defender_start,
                WHITE,
                size=38,
                fade=1 - t,
            )

            draw_expanding_ring(
                screen,
                battle.defender_start,
                60 * t,
                color,
                width=4,
            )
