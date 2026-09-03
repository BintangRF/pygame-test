"""Johnny-specific ability logic: the shared Nail Bullet ammo pool spent by
his basic attack and every skill, Tusk Act 2's guaranteed-crit homing shot
and bleed, Tusk Act 3's ricocheting nail, and Tusk Act 4's pin. The generic
damage pipeline in combat_resolution.py and the generic dispatchers in
status_effects.py just call into these hooks — every method here guards on
`attacker`/`f is self.johnny` so it's a no-op in any matchup without
Johnny."""

from ...core.constants import NAIL_SILVER
from ...core.entities import set_status
from ...core.particles import emit_debris, emit_spark_burst


class JohnnyAbilityMixin:
    CRIT_MULT = 1.6  # Tusk Act 2 always lands as a critical hit
    RELOAD_MS = 3000  # how long one spent Nail Bullet takes to come back

    # ---- Nail Bullet ammo pool --------------------------------------------
    def johnny_ammo_ready(self, attacker, ability):
        if attacker is not self.johnny or ability.kind == "ultimate":
            return True
        return attacker.nail_bullets > 0

    def johnny_consume_nail_bullet(self, attacker, ability):
        if attacker is not self.johnny or ability.kind == "ultimate":
            return
        attacker.nail_bullets = max(0, attacker.nail_bullets - 1)

    def johnny_reload_tick(self, f, dt_ms):
        if f is not self.johnny or f.nail_bullets >= f.nail_bullets_max:
            return
        self.johnny_reload_cd -= dt_ms
        if self.johnny_reload_cd <= 0:
            f.nail_bullets = min(f.nail_bullets_max, f.nail_bullets + 1)
            self.johnny_reload_cd = self.RELOAD_MS

    # ---- Tusk Act 2: homing crit + bleed -----------------------------------
    def johnny_critical_bonus(self, attacker, defender, ability, dmg, note):
        if attacker is self.johnny and ability.tag == "tusk_act2":
            return round(dmg * self.CRIT_MULT), note + " [CRITICAL]"
        return dmg, note

    def johnny_apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.johnny:
            return
        tag = ability.tag
        if tag == "tusk_act2" and defender is not None and self.damage_applied:
            set_status(defender, "bleed", 4000, dps=max(1, round(attacker.atk * 0.18)))
            self.log = f"{attacker.name}'s Tusk Act 2 rips into {defender.name} — bleeding!"
        elif tag == "tusk_act3" and defender is not None and self.damage_applied:
            # A ricochet that actually connects (see is_dodgeable/DODGEABLE_TAGS
            # in core/motions.py and the "ricochet" motion in battle_loop.py) —
            # miss already got the generic "whistles past" floater from
            # do_damage(), so this only ever fires on a landed hit.
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 60, -0.6, 255, "ACT 3!", NAIL_SILVER]
            )
            self.log = f"{attacker.name}'s ricocheting Tusk Act 3 finds its mark!"
            self.add_screen_shake(10, 160)
            self.add_ring(defender.pos, 55, 320, NAIL_SILVER, width=3)
            emit_spark_burst(self.fx, defender.pos, NAIL_SILVER, count=16)
        elif tag == "tusk_act4" and defender is not None:
            set_status(defender, "rooted", 4000)
            self.floaters.append(
                [defender.pos.x, defender.pos.y - 70, -0.6, 255, "PINNED!", NAIL_SILVER]
            )
            self.log = f"{attacker.name}'s Tusk Act 4 pins {defender.name} in place!"
            self.flash_timer = max(self.flash_timer, 420)
            self.add_screen_shake(22, 300)
            self.add_ring(defender.pos, 160, 700, NAIL_SILVER, width=6)
            emit_debris(self.fx, defender.pos, count=36, speed=(60, 180))
