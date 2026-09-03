"""Johnny plugin: the shared Nail Bullet ammo pool spent by his basic attack
and every skill, Tusk Act 2's guaranteed-crit homing shot and bleed, Tusk
Act 3's ricocheting nail, Tusk Act 4's pin, and the nail/teleport animation."""

import math

import pygame

from ...core.constants import NAIL_GLOW_BLUE, NAIL_SILVER
from ...core.effects import draw_expanding_ring, draw_nail
from ...core.entities import set_status
from ...core.particles import emit_debris, emit_spark_burst
from ...core.plugin import CharacterPlugin

CRIT_MULT = 1.6  # Tusk Act 2 always lands as a critical hit
RELOAD_MS = 3000  # how long one spent Nail Bullet takes to come back
NAIL_ABILITY_NAMES = ("Nail Bullet", "Tusk Act 2", "Tusk Act 3", "Tusk Act 4")


class JohnnyPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.reload_cd = RELOAD_MS

    # ---- Nail Bullet ammo pool ----------------------------------------------
    def ammo_ready(self, attacker, ability):
        if attacker is not self.fighter or ability.kind == "ultimate":
            return True
        return attacker.nail_bullets > 0

    def consume_ammo(self, attacker, ability):
        if attacker is not self.fighter or ability.kind == "ultimate":
            return
        attacker.nail_bullets = max(0, attacker.nail_bullets - 1)

    def ambient_tick(self, dt_ms):
        f = self.fighter
        if f.nail_bullets >= f.nail_bullets_max:
            return
        self.reload_cd -= dt_ms
        if self.reload_cd <= 0:
            f.nail_bullets = min(f.nail_bullets_max, f.nail_bullets + 1)
            self.reload_cd = RELOAD_MS

    # ---- Tusk Act 2: homing crit + bleed -----------------------------------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is self.fighter and ability.tag == "tusk_act2":
            return round(dmg * CRIT_MULT), note + " [CRITICAL]"
        return dmg, note

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "tusk_act2" and defender is not None and battle.damage_applied:
            set_status(defender, "bleed", 4000, dps=max(1, round(attacker.atk * 0.18)))
            battle.log = f"{attacker.name}'s Tusk Act 2 rips into {defender.name} — bleeding!"
        elif tag == "tusk_act3" and defender is not None and battle.damage_applied:
            # A ricochet that actually connects — miss already got the
            # generic "whistles past" floater from do_damage(), so this only
            # ever fires on a landed hit.
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 60, -0.6, 255, "ACT 3!", NAIL_SILVER]
            )
            battle.log = f"{attacker.name}'s ricocheting Tusk Act 3 finds its mark!"
            battle.add_screen_shake(10, 160)
            battle.add_ring(defender.pos, 55, 320, NAIL_SILVER, width=3)
            emit_spark_burst(battle.fx, defender.pos, NAIL_SILVER, count=16)
        elif tag == "tusk_act4" and defender is not None:
            set_status(defender, "rooted", 4000)
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 70, -0.6, 255, "PINNED!", NAIL_SILVER]
            )
            battle.log = f"{attacker.name}'s Tusk Act 4 pins {defender.name} in place!"
            battle.flash_timer = max(battle.flash_timer, 420)
            battle.add_screen_shake(22, 300)
            battle.add_ring(defender.pos, 160, 700, NAIL_SILVER, width=6)
            emit_debris(battle.fx, defender.pos, count=36, speed=(60, 180))

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_debris(self.battle.fx, pos, count=count)  # metal shrapnel from the nail
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos
                and battle.ability.name in NAIL_ABILITY_NAMES):
            return False
        name = battle.ability.name
        # Every nail — fingernail bullets, not steel ones (see draw_nail) —
        # uses the same Stand-charged blue glow. Act 3 gets a bigger size:
        # it launches from wherever Johnny (moves_while_active) is
        # currently standing, so at the instant it's fired it's sitting
        # right on top of his own avatar, and needs the extra size to still
        # read clearly there, bounce after bounce.
        if name == "Tusk Act 3":
            # Its own live velocity orients it correctly on every bounce,
            # unlike the fixed attacker_start-relative direction every
            # other nail below uses.
            direction = battle.ricochet_vel if battle.ricochet_vel else (
                battle.projectile_pos - battle.attacker_start
            )
            draw_nail(screen, battle.projectile_pos, direction, NAIL_GLOW_BLUE, size=1.6)
        else:
            direction = battle.projectile_pos - battle.attacker_start
            draw_nail(screen, battle.projectile_pos, direction, NAIL_GLOW_BLUE,
                      size=1.3 if battle.ability.big else 1.0)
        return True

    def draw_fx(self, screen, shake_x):
        """Tusk Act 4 telegraphs its pin with a burst of nails radiating out
        from the impact point. Tusk Act 3's ricocheting nail is drawn
        generically by draw_projectile above — a landed hit gets its own
        screen-shake/ring/spark flourish from apply_tag_effects, so it needs
        nothing bespoke here."""
        battle, j = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is j):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t

        if name == "Tusk Act 4" and phase == "impact":
            center = pygame.Vector2(battle.defender_start) + pygame.Vector2(shake_x, 0)
            for i in range(8):
                ang = i * (math.pi / 4)
                nail_pos = center + pygame.Vector2(math.cos(ang), math.sin(ang)) * 30 * t
                draw_nail(screen, nail_pos, pygame.Vector2(math.cos(ang), math.sin(ang)), NAIL_SILVER, size=1.1)
            draw_expanding_ring(screen, center, 50 * t, NAIL_SILVER, width=4)
