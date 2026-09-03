"""Sukuna-specific ability logic: Hachi's bleed application, Kai's
multi-hit flurry resolve (it doesn't deal its own damage — it procs Hachi's
basic-attack formula 3-5 times at once), and Kamino's cursed detonation.
The generic damage pipeline in combat_resolution.py and the generic
dispatchers in status_effects.py just call into these hooks — every method
here guards on `attacker is self.sukuna` so it's a no-op in any matchup
without Sukuna."""

import random

from ...core.constants import RED, SUKUNA_PINK
from ...core.entities import set_status
from ...core.particles import emit_dark, emit_explosion


class SukunaAbilityMixin:
    # Kai: guaranteed 3 procs of the basic attack, then each hit past that
    # (up to 5 total) independently rolls to proc as well.
    KAI_BASE_HITS = 3
    KAI_MAX_HITS = 5
    KAI_EXTRA_HIT_CHANCE = 0.5

    def sukuna_resolve_kai_flurry(self):
        """Kai doesn't land its own hit — it procs Sukuna's basic attack
        (Hachi's own dmg formula: atk * dmg_mult) 3-5 times simultaneously,
        each one rolled independently past the guaranteed first three."""
        attacker, defender, ability = self.attacker, self.defender, self.ability
        hits = self.KAI_BASE_HITS
        while hits < self.KAI_MAX_HITS and random.random() < self.KAI_EXTRA_HIT_CHANCE:
            hits += 1
        self._kai_hits = hits

        total = 0
        for _ in range(hits):
            dmg = round(attacker.atk * ability.dmg_mult)
            total += self.deal_damage(attacker, defender, dmg)
        self.damage_applied = True

        set_status(defender, "bleed", 3500, dps=max(1, round(total * 0.08)))
        set_status(defender, "healing_reduced", 3000, pct=0.5)
        defender.shake = 20
        self.apply_impact(defender, ability)
        self.floaters.append(
            [defender.pos.x, defender.pos.y - 40, -0.6, 255, f"-{total} x{hits}", SUKUNA_PINK]
        )
        self.log = f"{attacker.name}'s Kai lands {hits} simultaneous cuts on {defender.name} for {total}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)

    def sukuna_apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.sukuna:
            return
        tag = ability.tag
        if tag == "dismantle":
            set_status(defender, "bleed", 3000, dps=round(attacker.atk * 0.12))
            self.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Sliced!", RED])
            self.log = f"{attacker.name}'s Hachi leaves deep gashes on {defender.name}!"
        elif tag == "kamino":
            set_status(defender, "bleed", 6000, dps=round(attacker.atk * 0.3))
            set_status(defender, "healing_reduced", 6000, pct=0.7)
            self.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "KAMINO!", SUKUNA_PINK])
            self.log = f"{attacker.name} unleashes the cursed technique Kamino on {defender.name}!"
            self.flash_timer = max(self.flash_timer, 500)
            self.add_screen_shake(24, 320)
            self.add_ring(defender.pos, 190, 600, (255, 150, 40), width=7)
            self.add_ring(defender.pos, 170, 750, SUKUNA_PINK, width=5)
            emit_explosion(self.fx, defender.pos, (255, 140, 40), count=46)
            emit_dark(self.fx, defender.pos, count=34, radius=70)
