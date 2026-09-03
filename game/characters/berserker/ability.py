"""Berserker-specific ability logic: Berserker Rage (activation, its
tag-cast side effects, and the forced last-stand that fires instead of a
killing blow), the Fury passive that permanently stacks on any big hit
landed, and Rage's melee-range/damage bonuses. The generic damage pipeline
in combat_resolution.py and the generic dispatchers in status_effects.py
just call into these hooks — every method here guards on
`attacker`/`target is self.berserker` so it's a no-op in any matchup
without a Berserker."""

from ...core.constants import ORANGE
from ...core.entities import set_status
from ...core.particles import emit_debris, emit_explosion


class BerserkerAbilityMixin:
    # Berserker Rage widens the basic attack's melee reach while it's active
    BERSERKER_RAGE_RANGE_BONUS = 90
    # ...and hits harder / swings faster, so the immunity window is also a real damage spike
    BERSERKER_RAGE_DMG_MULT = 1.6
    BERSERKER_RAGE_ATTACK_SPEED = 1.6

    # passive: any single hit that deals at least this much damage permanently
    # toughens the Berserker up — stacks without limit, for the rest of the match
    BERSERKER_FURY_THRESHOLD = 13
    BERSERKER_FURY_ARMOR_GAIN = 1  # armor is on a 0-100 scale, so this is +1.5%
    BERSERKER_FURY_ATK_GAIN = 1.2
    BERSERKER_FURY_SPEED_GAIN = 1.5

    BERSERKER_RAGE_DURATION_MS = 13000

    def berserker_melee_range_bonus(self, attacker, melee_range):
        if melee_range is not None and attacker is self.berserker and "rage" in attacker.statuses:
            return melee_range + self.BERSERKER_RAGE_RANGE_BONUS
        return melee_range

    def berserker_cooldown_bonus(self, attacker, ability, cooldown):
        if ability.tag == "axe_throw" and "rage" in attacker.statuses:
            return round(cooldown * 0.35)
        return cooldown

    def berserker_rage_bonus(self, attacker, defender, ability, dmg, note):
        if attacker is self.berserker and "rage" in attacker.statuses:
            return round(dmg * self.BERSERKER_RAGE_DMG_MULT), note + " [RAGE]"
        return dmg, note

    def berserker_fury_check(self, target, dmg):
        if target is self.berserker and dmg >= self.BERSERKER_FURY_THRESHOLD:
            self.trigger_berserker_fury(target)

    def trigger_berserker_fury(self, b):
        """Passive: a single hit for at least BERSERKER_FURY_THRESHOLD
        permanently raises armor, attack, and move speed — stacks without
        limit for the rest of the match."""
        b.armor += self.BERSERKER_FURY_ARMOR_GAIN
        b.atk += self.BERSERKER_FURY_ATK_GAIN
        b.move_speed_mult += self.BERSERKER_FURY_SPEED_GAIN
        self.floaters.append([b.pos.x, b.pos.y - 70, -0.6, 255, "FURY UP!", ORANGE])
        self.log = f"{b.name}'s Fury grows — armor, power, and speed rise permanently!"

    def berserker_death_save(self, target, dmg):
        """A Berserker about to be finished off gets a last stand instead
        of dying (see start_berserker_rage) — returns the actual damage
        subtracted, or None if this hit doesn't trigger it. Rage is
        one-shot (moves.py: one_shot=True): if it already fired once this
        match — proactively at the HP threshold, or from an earlier death
        save — it's spent, and a second lethal blow just kills normally."""
        if (target is self.berserker and target.hp - dmg <= 0
                and not target.abilities["ultimate"].used):
            actual = target.hp - 1
            target.hp = 1
            self.start_berserker_rage(death_save=True)
            return actual
        return None

    def start_berserker_rage(self, death_save=False):
        b = self.berserker
        set_status(b, "rage", self.BERSERKER_RAGE_DURATION_MS, death_save=death_save)
        # a forced last-stand activation didn't go through the normal
        # attack sequence, so its one-shot flag wouldn't otherwise get set
        b.abilities["ultimate"].used = True
        self.add_screen_shake(16, 280)
        self.flash_timer = max(self.flash_timer, 380)
        if death_save:
            self.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "LAST STAND!", ORANGE])
            self.log = f"{b.name} refuses to fall — Berserker Rage erupts in a last stand!"
        else:
            self.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "RAGE!", ORANGE])
            secs = self.BERSERKER_RAGE_DURATION_MS // 1000
            self.log = f"{b.name} flies into a Berserker Rage — unstoppable for {secs}s!"

    def berserker_apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.berserker:
            return
        if ability.tag == "berserker_rage":
            self.start_berserker_rage()
            self.add_ring(self.berserker.pos, 150, 600, ORANGE, width=6)
            emit_debris(self.fx, self.berserker.pos, count=34, speed=(100, 260))
            emit_explosion(self.fx, self.berserker.pos, ORANGE, count=20)

    def berserker_on_status_expire(self, f, name, data):
        if name != "rage" or not data.get("death_save"):
            return
        if self.winner is not None:
            return  # match was already decided before the last-stand timer ran out
        f.hp = 0
        self.floaters.append([f.pos.x, f.pos.y - 40, -0.6, 255, "Rage Fades...", ORANGE])
        self.log = f"{f.name}'s Berserker Rage fades — the last stand ends."
        self.declare_winner()
