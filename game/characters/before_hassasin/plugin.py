"""Before-Hassasin plugin: Twin Fangs' dual-range passive (a bare-blade
slash up close, 3 knives thrown in 3 genuinely different directions at range
— see forced_ability/_refresh_basic_motion/resolve_special), Death Scent's
lingering disarm+silence+vulnerability smoke (a Zone, not a one-shot debuff
— see zone_tick) with its own follow-up blink into melee, Trace of Death's 3-way
random payoff (a stat buff / a primed crit+bleed on the next Twin Fangs / an
instant hex on the opponent), Zabaniya's arena-wide blackout (the opponent
and every one of their own clones blinded — see _blind_clones, Twin Fangs
itself forced back to its melee mode so it becomes a
guaranteed hit against literally every one of the opponent's own bodies at
once - the real fighter and every clone/illusion standing in for them, each
struck by its own full, independently-resolved Twin Fangs swing and drawn
with its own instant-slash cut, all landing at the same instant - see
resolve_special/_resolve_death_swing - instead of one ordinary hit plus a
flat-rate AoE splash tacked onto the clones), and the bare-handed dagger
animation for all of it."""

import math
import random

import pygame

from ...core.constants import (
    BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, Hassasin_VIOLET, HEIGHT, LETHAL_MARK_COLOR,
    POISON_COLOR, WHITE, WIDTH,
)
from ...core.effects import draw_expanding_ring, draw_slash_fx, draw_starburst
from ...core.entities import Zone, set_status
from ...core.particles import emit_dark
from ...core.plugin import CharacterPlugin

# Passive: how close the opponent has to be for Twin Fangs to resolve as a
# melee slash instead of a 3-knife throw — matches the usual melee-range
# scale other characters' own basic attacks use (CK's Mace Slash, Berserker's
# Reckless Cleave, ...), even though Twin Fangs itself sets no melee_range at
# all (see moves.py) so it's never gated by distance, only its *animation* is.
BH_MELEE_RANGE = 115
_KNIFE_BLADE_COLOR = (210, 210, 220)
_KNIFE_HILT_COLOR = (70, 55, 40)

# Death Scent: the smoke cloud's own size and how long it lingers, and how
# long each disarmed/silenced/vulnerability refresh lasts while an enemy
# stands inside it — short, so stepping clear of the cloud lets all three
# lapse within a fraction of a second instead of the old fixed lockdown
# persisting regardless of position (see zone_tick, same refresh-buffer
# pattern Vampire's Blood Pool zone_tick uses for poison/disarmed).
DEATH_SCENT_RADIUS = 130
DEATH_SCENT_ZONE_DURATION_S = 6
DEATH_SCENT_TICK_S = 0.4
# Armor Vulnerability while inside the smoke — a pct of the target's own
# current armor (base stat, plus Armor Up, minus Armor Break — see
# StatusLibraryMixin.effective_armor), same scale as a couple of Raiju's own
# Static stacks (STATIC_VULN_PER_STACK) stacked up.
DEATH_SCENT_VULN_PCT = 0.7

# Trace of Death: every payoff (see _cast_trace_of_death) lasts the same
# window before fading unused.
TRACE_BUFF_DURATION_S = 6
TRACE_ATTACK_UP_PCT = 1.8
TRACE_ARMOR_UP_AMOUNT = 20
TRACE_MOVE_SPEED_UP_PCT = 2
# Lethal Mark: the next Twin Fangs (melee or ranged alike) to actually swing
# while this is up crits for this multiplier and leaves the target bleeding.
LETHAL_MARK_CRIT_MULT = 2.4
LETHAL_MARK_BLEED_S = 10
# Hex: the instant poison+blind payoff, thrown straight at the opponent
# instead of buffing Before-Hassasin itself.
HEX_POISON_S = 6
HEX_BLIND_S = 6
HEX_BLIND_CHANCE = 1

# Zabaniya: how long the blackout lasts, and the opponent's own blind chance
# for the duration. Twin Fangs' own reach while Death is up needs no radius
# at all any more (see resolve_special/_resolve_death_swing) - every one of
# the opponent's bodies is targeted outright, wherever it actually stands.
ZABANIYA_DURATION_S = 8
ZABANIYA_BLIND_CHANCE = 1


class BeforeHassasinPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        # Set by outgoing_damage (melee) or resolve_special (ranged) the
        # instant a Lethal-Mark-boosted Twin Fangs is thrown, read (and
        # cleared) by on_damage_dealt right after — lets the crit multiplier
        # and the bleed it earns share one landed hit.
        self._lethal_mark_pending = False
        self._death_particle_cd = 0.0
        # Every point Death's own arena-wide Twin Fangs actually connected
        # with this cast (the real opponent plus every one of their clones),
        # set by _resolve_death_swing and read right back by draw_fx's own
        # _draw_slash the same frame - one independent instant-slash cut
        # drawn per point instead of a single shared blast.
        self._death_hit_points = []

    # ---- passive: Twin Fangs' own dual-range animation ----------------------
    def forced_ability(self, attacker):
        """Twin Fangs never forces anything (returns None, same as the base
        default) — this hook is only used here as an early, guaranteed-fresh
        touchpoint (called at the very top of choose_ability, every frame
        while roaming) to flip the basic's own `motion` before anything
        downstream reads it."""
        if attacker is self.fighter:
            self._refresh_basic_motion(attacker)
        return None

    def _refresh_basic_motion(self, attacker):
        """Twin Fangs sets no melee_range at all (see moves.py) — it's
        always ready regardless of distance. What changes is purely its own
        `motion`: "instant" (a bare-blade slash landing directly on the
        target, see _draw_slash) within BH_MELEE_RANGE, "swarm" (3 knives
        thrown in 3 genuinely different directions — swarm_pattern="fan",
        see resolve_special) beyond it — mutated directly on the shared
        Ability object right before choose_ability/try_start_attack reads it, so
        whichever one actually fires always matches the range it was cast
        from. While Death is up, it's always forced to "instant" regardless
        of range instead — Death's own guaranteed hit against every one of
        the opponent's own bodies at once (see resolve_special/
        _resolve_death_swing) is only ever intercepted for the "instant"
        motion, never the swarm engine's own per-projectile hit-or-miss."""
        battle = self.battle
        basic = attacker.abilities["basic"]
        if "death_ultimate" in attacker.statuses:
            basic.motion = "instant"
            return
        opponent = battle.f2 if attacker is battle.f1 else battle.f1
        basic.motion = "instant" if (attacker.pos - opponent.pos).length() <= BH_MELEE_RANGE else "swarm"

    # ---- passive: the ranged half of Twin Fangs (3 knives, 3 directions) ----
    def resolve_special(self):
        """Twin Fangs' own ranged mode (motion == "swarm", see
        _refresh_basic_motion) — 3 knives thrown at once in 3 fixed,
        genuinely different directions (swarm_pattern="fan", see moves.py),
        dealt through the generic swarm engine (spawn_swarm_projectiles/
        update_swarm_projectiles in core/battle_loop.py) so any of them can
        independently connect with the real defender or one of their own
        clones — usually just one does, since they're not all aimed at the
        same point. The melee half (motion == "instant") is untouched by
        this — it still goes through the normal do_damage() pipeline (see
        outgoing_damage for its own Lethal Mark handling) unless Death is up
        (see _resolve_death_swing below, checked first), this only ever
        intercepts the ranged one."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "twin_fangs"):
            return False
        if "death_ultimate" in self.fighter.statuses:
            return self._resolve_death_swing()
        if battle.motion != "swarm":
            return False
        attacker, ability = self.fighter, battle.ability
        if battle.roll_blind_miss(attacker):
            battle.swarm_projectiles = []
            battle.log = f"{attacker.name}'s Twin Fangs throw goes wide — blinded!"
            return True
        # Lethal Mark: consumed here rather than in outgoing_damage — a
        # swarm attack never goes through that chain at all. Always
        # (re)written, never left untouched, so a Lethal Mark used up on a
        # throw that whiffs entirely (no knife actually connects, so
        # on_damage_dealt never fires to clear it) can't linger and
        # wrongly bleed some later, unrelated landed hit.
        self._lethal_mark_pending = attacker.statuses.pop("bh_lethal_mark", None) is not None
        battle.spawn_swarm_projectiles()
        # Every knife hits for this same full amount, not split by count
        # (see spawn_swarm_projectiles' own per_hit_dmg formula) — usually
        # only one of the 3 actually connects (they're thrown in different
        # directions, not all at the target), so a single connecting knife
        # is still worth one full Twin Fangs hit, not a third of one.
        # status_outgoing_multiplier folds in Attack Up/Down (Trace of
        # Death's own "stats" payoff among them) — do_damage() applies this
        # generically for the melee half; a swarm attack bypasses do_damage()
        # entirely, so it has to be applied here by hand or Attack Up would
        # silently do nothing for a ranged Twin Fangs throw.
        mult = LETHAL_MARK_CRIT_MULT if self._lethal_mark_pending else 1.0
        mult *= battle.status_outgoing_multiplier(attacker)
        full_dmg = round(attacker.atk * ability.dmg_mult * mult)
        for proj in battle.swarm_projectiles:
            proj["dmg"] = full_dmg
        if self._lethal_mark_pending:
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "Lethal Mark!", LETHAL_MARK_COLOR])
        battle.log = f"{attacker.name} hurls a spread of throwing knives!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        emit_dark(battle.fx, attacker.pos, count=14, radius=40)
        return True

    # ---- ultimate: Death's own arena-wide Twin Fangs -------------------------
    def _resolve_death_swing(self):
        """While Death is up, Twin Fangs never goes through the normal
        single-target do_damage() pipeline at all - every one of the
        opponent's own bodies (the real fighter, plus every clone/illusion
        standing in for them - see _death_targets) takes its own full,
        independently-dealt Twin Fangs hit at the same instant, computed the
        exact same way a normal melee swing would be (Lethal Mark's crit
        multiplier and Attack Up/Down both folded in once, shared by every
        target rather than recomputed per hit), instead of one ordinary hit
        on whichever target got picked plus a separate flat-rate AoE splash
        landing on the rest. _death_hit_points collects where each of those
        swings actually connected so draw_fx's own _draw_slash can play one
        instant-slash cut per point, all at once, instead of a single shared
        blast."""
        battle, attacker = self.battle, self.fighter
        ability = battle.ability
        opponent = battle.f2 if attacker is battle.f1 else battle.f1

        self._death_hit_points = []
        if battle.roll_blind_miss(attacker):
            battle.log = f"{attacker.name}'s Twin Fangs goes wide — blinded!"
            return True

        # Lethal Mark: same always-(re)written pop as the swarm branch above
        # - a Death swing that ends up hitting nothing (every body immune/
        # untargetable/vanished) still needs to clear a stale mark rather
        # than let it linger onto some later, unrelated hit.
        self._lethal_mark_pending = attacker.statuses.pop("bh_lethal_mark", None) is not None
        mult = LETHAL_MARK_CRIT_MULT if self._lethal_mark_pending else 1.0
        mult *= battle.status_outgoing_multiplier(attacker)
        full_dmg = round(attacker.atk * ability.dmg_mult * mult)
        if self._lethal_mark_pending:
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "Lethal Mark!", LETHAL_MARK_COLOR])

        hit_any = False
        for kind, target in self._death_targets(opponent):
            if kind == "fighter":
                if battle.is_invulnerable(target) or battle.is_untargetable(target) or battle.is_vanished(target):
                    continue
                pos = pygame.Vector2(target.pos)
                actual = battle.deal_damage(attacker, target, full_dmg)
                battle.apply_impact(target, ability)
                battle.floaters.append([target.pos.x, target.pos.y - 40, -0.6, 255, f"-{actual}", attacker.color])
                if actual > 0 and self._lethal_mark_pending:
                    set_status(target, "bleed", LETHAL_MARK_BLEED_S)
                    battle.floaters.append(
                        [target.pos.x, target.pos.y - 55, -0.5, 255, "Marked!", LETHAL_MARK_COLOR]
                    )
            elif kind == "clone":
                army, clone = target
                pos = pygame.Vector2(clone.pos)
                army.damage_clone(clone, full_dmg, ability=ability, knock_dir=clone.pos - attacker.pos)
            else:  # "vampire_clone"
                pos = pygame.Vector2(target.pos)
                battle._splash_vampire_clone(target, full_dmg)
            hit_any = True
            self._death_hit_points.append(pos)

        self._lethal_mark_pending = False
        if hit_any:
            battle.log = f"{attacker.name}'s Zabaniya-empowered Twin Fangs cuts down every last one of {opponent.name}'s bodies at once!"
        else:
            battle.log = f"{attacker.name}'s Twin Fangs finds nothing left standing!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        emit_dark(battle.fx, attacker.pos, count=14, radius=40)
        return True

    def _death_targets(self, opponent):
        """Every body currently standing in for `opponent` - the real
        fighter, every clone in their own CloneArmy (Phantom Lancer's
        illusions, Chaos Knight's Phantasm, or any future character's own
        decoy kit - see CharacterPlugin.clone_army), and Vampire's own
        Crimson Doppelganger (battle.clone, tracked outside any CloneArmy -
        see entities.Clone) - as ("fighter", opponent), ("clone", (army,
        clone)), or ("vampire_clone", clone) tuples for _resolve_death_swing
        to hit one by one. Fully generic, no per-character wiring needed:
        whichever kinds of decoy `opponent` actually has right now are
        included, none guessed or assumed."""
        battle = self.battle
        targets = [("fighter", opponent)]
        defender_plugin = battle.plugin_for(opponent)
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        if army is not None:
            targets.extend(("clone", (army, clone)) for clone in list(army.clones))
        vampire_clone = battle.clone
        if vampire_clone is not None and vampire_clone.owner is opponent:
            targets.append(("vampire_clone", vampire_clone))
        return targets

    # ---- passive: Lethal Mark's primed crit+bleed ---------------------------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is not self.fighter or ability.kind != "basic":
            return dmg, note
        # Always (re)written, never left untouched (see resolve_special's own
        # note on the same pattern) — a melee Twin Fangs with no mark up must
        # actively clear any stale True a previous *ranged* throw's total
        # whiff could have left behind, not just skip past it.
        self._lethal_mark_pending = attacker.statuses.pop("bh_lethal_mark", None) is not None
        if self._lethal_mark_pending:
            return round(dmg * LETHAL_MARK_CRIT_MULT), note + " [LETHAL MARK]"
        return dmg, note

    def on_damage_dealt(self, attacker, defender, actual):
        if attacker is not self.fighter or not self._lethal_mark_pending:
            return
        self._lethal_mark_pending = False
        if actual <= 0:
            return
        set_status(defender, "bleed", LETHAL_MARK_BLEED_S)
        self.battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Marked!", LETHAL_MARK_COLOR])

    # ---- tag effects --------------------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "death_scent" and defender is not None:
            # No damage of its own (dmg_mult 0, see moves.py) — do_damage()
            # is never even called for a 0-dmg cast, so this never gates on
            # battle.damage_applied (that flag would just stay False
            # forever). Drops a lingering Zone centered on the opponent's
            # own position instead of a one-shot debuff — disarmed/silenced
            # only actually apply, refreshed, while they stand inside it
            # (see zone_tick), then Before-Hassasin blinks in right beside
            # them regardless.
            battle.zones.append(
                Zone("bh_smoke", pygame.Vector2(defender.pos), DEATH_SCENT_RADIUS, DEATH_SCENT_ZONE_DURATION_S,
                     attacker)
            )
            self._blink_to(defender)
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Death Scent!", Hassasin_VIOLET])
            battle.log = f"{attacker.name} chokes the air around {defender.name} with Death Scent!"
            battle.add_ring(defender.pos, DEATH_SCENT_RADIUS, 0.5, Hassasin_VIOLET, width=4)
            emit_dark(battle.fx, defender.pos, count=30, radius=DEATH_SCENT_RADIUS * 0.8)
        elif tag == "trace_of_death":
            self._cast_trace_of_death(attacker, defender)
        elif tag == "death_ultimate":
            self._cast_death(attacker, defender)

    def _blink_to(self, defender):
        """Death Scent's own follow-up: Before-Hassasin blinks to melee
        range of `defender` the instant the lockdown lands — a plain
        reposition (no forced follow-up swing of its own, unlike Chaos
        Knight's Reality Rift), same distance math as that ability's own
        strike_point_override in characters/chaos_knight/plugin.py. Also
        overwrites battle.attacker_start, not just attacker.pos directly —
        "cast" motion's own per-frame position write (still running every
        remaining frame of this same "release" phase) reads attacker_start
        unconditionally, and would otherwise instantly stomp a bare position
        assignment right back to where the cast started."""
        attacker, battle = self.fighter, self.battle
        direction = attacker.pos - defender.pos
        if direction.length_squared() == 0:
            direction = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        direction = direction.normalize()
        dest = defender.pos + direction * BH_MELEE_RANGE
        dest.x = max(BOUND_LEFT, min(BOUND_RIGHT, dest.x))
        dest.y = max(BOUND_TOP, min(BOUND_BOTTOM, dest.y))
        attacker.pos = pygame.Vector2(dest)
        battle.attacker_start = pygame.Vector2(dest)
        emit_dark(battle.fx, dest, count=16, radius=30)

    # ---- zone (Death Scent's smoke) ------------------------------------------
    def zone_tick(self, fighter, zone, dt):
        """Called once per frame for whoever is standing inside Death
        Scent's smoke (the zone's own owner is immune to it, same as every
        other enemy-only zone in this game) — refreshes disarmed+silenced+
        vulnerability at a short, constantly-renewed duration instead of
        setting one long lockdown up front, so all three actually drop
        within DEATH_SCENT_TICK_S of stepping clear of the cloud rather than
        lingering at whatever duration was left when they walked out."""
        if fighter is zone.owner or fighter.statuses.get("invulnerable"):
            return
        set_status(fighter, "disarmed", DEATH_SCENT_TICK_S)
        set_status(fighter, "silenced", DEATH_SCENT_TICK_S)
        set_status(fighter, "vulnerability", DEATH_SCENT_TICK_S, pct=DEATH_SCENT_VULN_PCT)

    def zone_style(self, zone):
        return Hassasin_VIOLET, "Death Scent"

    def zone_decorate(self, screen, zone):
        """A handful of soft drifting puffs inside the cloud, drawn every
        frame regardless of whether anyone's currently standing in it (same
        "always-visible zone" contract as Raiju's own Static Field arcs) —
        reads as smoke rather than an empty ring."""
        for _ in range(3):
            r = random.uniform(0, zone.radius * 0.85)
            a = random.uniform(0, math.tau)
            pos = zone.center + pygame.Vector2(math.cos(a), math.sin(a)) * r
            size = random.uniform(10, 20)
            puff = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            pygame.draw.circle(puff, (*Hassasin_VIOLET, 70), (size, size), size)
            screen.blit(puff, puff.get_rect(center=(int(pos.x), int(pos.y))))

    def _cast_trace_of_death(self, attacker, defender):
        """One of 3 equal-odds payoffs every cast — see the module docstring
        for what each one does; TRACE_BUFF_DURATION_S covers all three the
        same way (a stat buff and Lethal Mark both fade unused after this
        long, the hex's own poison/blind last exactly this long too)."""
        battle = self.battle
        roll = random.choice(("stats", "mark", "hex"))
        if roll == "stats":
            # Status: attack_up + armor_up + move_speed_up, all self
            set_status(attacker, "attack_up", TRACE_BUFF_DURATION_S, pct=TRACE_ATTACK_UP_PCT)
            set_status(attacker, "armor_up", TRACE_BUFF_DURATION_S, amount=TRACE_ARMOR_UP_AMOUNT)
            set_status(attacker, "move_speed_up", TRACE_BUFF_DURATION_S, pct=TRACE_MOVE_SPEED_UP_PCT)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "Empowered!", Hassasin_VIOLET])
            battle.log = f"{attacker.name}'s Trace of Death empowers their attack, armor and speed!"
        elif roll == "mark":
            # Status: bh_lethal_mark — a bare flag, no kwargs of its own;
            # consumed by outgoing_damage/on_damage_dealt above.
            set_status(attacker, "bh_lethal_mark", TRACE_BUFF_DURATION_S)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "Lethal Mark!", LETHAL_MARK_COLOR])
            battle.log = f"{attacker.name} primes a lethal strike — the next Twin Fangs will crit and bleed!"
        else:
            # Status: poison + blind, landed instantly on the opponent
            # instead of buffing Before-Hassasin itself.
            if defender is not None:
                set_status(defender, "poison", HEX_POISON_S)
                set_status(defender, "blind", HEX_BLIND_S, chance=HEX_BLIND_CHANCE)
                battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Hexed!", POISON_COLOR])
                battle.log = f"{attacker.name}'s Trace of Death instantly hexes {defender.name}!"
        battle.add_ring(attacker.pos, 70, 0.35, Hassasin_VIOLET, width=4)
        emit_dark(battle.fx, attacker.pos, count=24, radius=50)

    def _cast_death(self, attacker, defender):
        """Status: death_ultimate (self) — read by full_screen_overlay for
        the blackout, by _refresh_basic_motion to force Twin Fangs into its
        "instant" motion regardless of range, and by resolve_special to
        intercept every Twin Fangs cast into _resolve_death_swing instead of
        the normal single-target pipeline for as long as it's up."""
        battle = self.battle
        set_status(attacker, "death_ultimate", ZABANIYA_DURATION_S)
        if defender is not None:
            set_status(defender, "blind", ZABANIYA_DURATION_S, chance=ZABANIYA_BLIND_CHANCE)
            self._blind_clones(defender)
        battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "ZABANIYA!", Hassasin_VIOLET])
        battle.log = f"{attacker.name} plunges the arena into Zabaniya — darkness falls!"
        battle.flash_timer = max(battle.flash_timer, 0.45)
        battle.add_screen_shake(20, 0.3)
        battle.add_ring(attacker.pos, 200, 0.8, Hassasin_VIOLET, width=6)
        emit_dark(battle.fx, attacker.pos, count=50, radius=90)

    def _blind_clones(self, defender):
        """Zabaniya's blackout doesn't spare `defender`'s own clones/
        illusions — every living one of them (Phantom Lancer's illusions,
        Chaos Knight's Phantasm, Sukuna's shadows, ...) goes blind for the
        same duration/chance as the real fighter, so a clone army that
        auto-attacks (can_attack — see core/clone_army.py) can whiff its own
        swings too instead of fighting on unaffected while the arena is
        pitch dark. Only ever set on an army that actually ticks statuses
        back down (has_statuses=True) — an army without it (Leonidas' own
        Spartans) never expires a status once set, so it's skipped there
        rather than leaving them blind for the rest of the fight. Vampire's
        own Crimson Doppelganger (battle.clone) is left out on purpose: it
        never attacks on its own, only stands in as a redirect target, so
        blinding it would do nothing."""
        defender_plugin = self.battle.plugin_for(defender)
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        if army is None or not army.has_statuses:
            return
        for clone in army.clones:
            set_status(clone, "blind", ZABANIYA_DURATION_S, chance=ZABANIYA_BLIND_CHANCE)

    def on_status_expire(self, fighter, name, data):
        if fighter is not self.fighter or name != "death_ultimate":
            return
        self.battle.log = f"{fighter.name}'s Zabaniya fades — the arena's darkness lifts."

    # ---- per-frame simulation ------------------------------------------------
    def ambient_tick(self, dt):
        if "death_ultimate" not in self.fighter.statuses:
            self._death_particle_cd = 0.0
            return
        self._death_particle_cd -= dt
        if self._death_particle_cd <= 0:
            emit_dark(self.battle.fx, self.fighter.pos, count=3, radius=60)
            self._death_particle_cd = 0.12

    # ---- presentation ---------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_dark(self.battle.fx, pos, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is not self.fighter:
            return False
        if battle.motion == "swarm":
            # Twin Fangs' own ranged mode — each knife drawn at its own
            # live, independently-tracked position/heading (see
            # resolve_special/spawn_swarm_projectiles), not a single shared
            # point — they're genuinely flying in different directions, not
            # a fanned-out illusion around one shot.
            for proj in battle.swarm_projectiles:
                if not proj["alive"] or proj["delay"] > 0:
                    continue
                self._draw_one_knife(screen, proj["pos"], proj["vel"])
            return True
        return False

    @staticmethod
    def _draw_one_knife(screen, pos, direction):
        if direction.length_squared() == 0:
            direction = pygame.Vector2(1, 0)
        d = direction.normalize()
        perp = pygame.Vector2(-d.y, d.x)
        length, width = 22, 5
        tip = pos + d * length * 0.6
        base = pos - d * length * 0.4
        pygame.draw.polygon(screen, _KNIFE_BLADE_COLOR, [tip, base + perp * width, base - perp * width])
        pygame.draw.line(screen, _KNIFE_HILT_COLOR, base, base - d * 8, width=3)

    def draw_fx(self, screen, shake_x):
        self._draw_slash(screen, shake_x)
        self._draw_ability_fx(screen, shake_x)

    def _draw_slash(self, screen, shake_x):
        """Twin Fangs' own melee mode — a bare-handed dual-dagger cross-cut
        appearing directly on the target, no dash/travel (same "instant"
        no-windup-travel shape as Sukuna's Hachi — see characters/sukuna/
        plugin.py's own draw_fx). While Death is up, every one of
        _death_hit_points (the real opponent plus every clone Twin Fangs
        actually connected with this swing — see resolve_special/
        _resolve_death_swing) gets its own full-size death-slash cut (see
        _draw_death_slash), all drawn on the same frame — genuinely one
        instant-slash swing landing on each body at once, not a single
        shared blast standing in for all of them."""
        battle, f = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is f and battle.motion == "instant"
                and battle.ability.name == "Twin Fangs"):
            return
        phase, t = battle.current_phase, battle.phase_t
        if phase != "impact":
            return
        shake = pygame.Vector2(shake_x, 0)
        if "death_ultimate" in f.statuses:
            for point in self._death_hit_points:
                direction = point - f.pos
                direction = direction.normalize() if direction.length_squared() else battle.atk_dir
                self._draw_death_slash(screen, point + shake, direction, t)
            return
        center = pygame.Vector2(battle.defender_start) + shake
        draw_slash_fx(screen, center, battle.atk_dir, t, size=100)
        draw_starburst(screen, center, WHITE, size=24, fade=1 - t)

    @staticmethod
    def _draw_death_slash(screen, target, direction, t):
        """Death's own version of Twin Fangs' cut — bare-handed, appearing
        directly on the target with no travel (same shape as Sukuna's own
        Hachi/Kai — see characters/sukuna/plugin.py's own draw_fx), never a
        beam/line connecting it back to Before-Hassasin's own position (that
        read as a laser, not a cut). Just bigger and fanned across more
        cuts than the plain close-range version above, since this same
        "instant" swing now lands regardless of how far away the target is.
        Called once per point in _death_hit_points (see _draw_slash), so a
        Death swing that connects with several bodies at once draws this
        same cut, independently, on every one of them."""
        draw_slash_fx(screen, target, direction, t, size=170)
        draw_starburst(screen, target, WHITE, size=46, fade=1 - t)
        draw_expanding_ring(screen, target, 90 * t, Hassasin_VIOLET, width=6)

    def _draw_ability_fx(self, screen, shake_x):
        battle, f = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is f):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t
        shake = pygame.Vector2(shake_x, 0)
        if name in ("Trace of Death", "Zabaniya") and phase in ("windup", "channel"):
            origin = pygame.Vector2(battle.attacker_start) + shake
            draw_expanding_ring(screen, origin, 18 + 50 * t, Hassasin_VIOLET, width=4)
            draw_starburst(screen, origin, Hassasin_VIOLET, size=14 + 16 * t, fade=t)

    def full_screen_overlay(self, screen):
        """Death's own blackout — a fully opaque black wash over the whole
        scene, same hook Vampire's Eternal Night uses (see characters/
        vampire/plugin.py). Unlike Eternal Night's own fade (strongest right
        at cast, thinning out for its entire duration), this stays at full
        strength (alpha 255, pure black — genuinely nothing else on screen
        is visible through it) for the whole blackout and only lifts in the
        last second — "pitch dark" reads better held steady than gradually
        thinning throughout."""
        active = self.fighter.statuses.get("death_ultimate")
        if not active:
            return
        remaining = active["time"]
        alpha = int(255 * min(1.0, remaining)) if remaining < 1.0 else 255
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, alpha))
        screen.blit(overlay, (0, 0))
