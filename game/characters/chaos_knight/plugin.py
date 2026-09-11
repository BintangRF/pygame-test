"""Chaos Knight plugin: the Chaos Strike passive (a flat chance for Mace
Slash to land as a critical hit and lifesteal off it), Chaos Bolt's homing
stun (a random duration between 0.5s and 1.5s), Reality Rift's melee-range
teleport + root (staying planted at the landing spot and always following up
with a guaranteed Mace Slash — see forced_ability), the Phantasm ultimate's
full-power illusions (which also cast every skill Chaos Knight itself casts,
in lockstep and with no cooldown of their own — see _mirror_skill and
core/clone_army.py), and the mace-swing/rift/portal animation."""

import math
import random

import pygame

from ...core.clone_army import CloneArmy
from ...core.constants import AVATAR_R, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, CHAOS_EMBER, WHITE
from ...core.effects import (
    draw_comet,
    draw_expanding_ring,
    draw_rotated,
    draw_slash,
    draw_slash_arc,
    draw_starburst,
    weapon_angle,
)
from ...core.entities import set_status
from ...core.motions import ease_in, ease_out
from ...core.particles import emit_dark, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .weapons import load_chaos_knight_weapons

# Passive: Chaos Strike — every Mace Slash has this flat chance to land as a
# critical hit (flat multiplier, not the RNG-stacking-with-armor kind) and
# lifesteal the *entire* damage it actually dealt back as healing — the
# generic "lifesteal" status (see StatusLibraryMixin.lifesteal_pct) is a flat
# 100% system-wide now, no per-character pct of its own to tune here anymore.
CHAOS_STRIKE_CHANCE = 0.4
CHAOS_STRIKE_CRIT_MULT = 1.3

# Chaos Bolt: a random stun window each cast, not one fixed duration.
CHAOS_BOLT_STUN_MIN = 0.5
CHAOS_BOLT_STUN_MAX = 1.5

# Reality Rift: how long the root lasts, and the distance Chaos Knight
# blinks to when its own basic attack somehow carries no melee_range at all
# (never happens today — Mace Slash always sets one — just a safe fallback).
# Long enough to actually guarantee a follow-up Mace Slash lands on the
# rooted target instead of just being a "during the blink itself" flicker.
REALITY_RIFT_ROOT_S = 2.5

# Phantasm: up to 3 illusions at full (100%) atk, fighting and casting
# alongside Chaos Knight for the rest of its duration (see CloneArmy's own
# `cap` below) — "100% stats" means atk, the one stat stat_pct scales; hp is
# its own separate pct of Chaos Knight's own current max_hp (see
# PHANTASM_CLONE_HP_PCT), armor stays CloneArmy's own flat clone_armor. Every
# other clone combat stat (attack_cooldown/attack_range below) is read
# straight off Chaos Knight's own Mace Slash (see __init__) rather than
# duplicated here as a separate literal, so a clone's swing always stays in
# lockstep with whatever Mace Slash's own cooldown/melee_range actually are
# — only hp_pct/armor are deliberately its own, weaker, clone-only numbers.
PHANTASM_DURATION_S = 10
PHANTASM_STAT_PCT = 1.0
PHANTASM_CLONE_HP_PCT = 0.35
# Purely the simplified one-shot swing's own visual duration (a clone has no
# windup/slash1/slash2 phase machine of its own — see _draw_clone_mace) —
# not a combat stat, so unlike attack_cooldown/attack_range this one has no
# real Mace Slash counterpart to read from.
CLONE_ATTACK_ANIM_S = 0.261
CLONE_SPAWN_SPEED = (60, 100)  # matches core/assets.py's own spawn()

# Idle resting pose for the mace prop — held low and angled back, same
# convention as Phantom Lancer's own resting lance (see IDLE_ANGLE/
# IDLE_OFFSET in characters/phantom_lancer/plugin.py).
IDLE_ANGLE = 200
IDLE_OFFSET = pygame.Vector2(-10, 16)


class ChaosKnightPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        basic = fighter.abilities["basic"]
        self.army = CloneArmy(
            self, cap=2, stat_pct=PHANTASM_STAT_PCT, duration=PHANTASM_DURATION_S,
            can_attack=True, can_use_skill=True, has_statuses=True,
            # Read straight off Mace Slash itself (basic.cooldown/melee_range)
            # rather than duplicated as separate literals — see the module
            # constants above.
            attack_cooldown=basic.cooldown, attack_range=basic.melee_range,
            attack_anim=CLONE_ATTACK_ANIM_S, spawn_speed=CLONE_SPAWN_SPEED,
            clone_hp_pct=PHANTASM_CLONE_HP_PCT,
        )
        # Set by CloneArmy's own _clone_attack/on_owner_skill_landed while a
        # clone's own mirrored hit resolves through deal_damage — unread by
        # this plugin (Chaos Strike's crit/lifesteal no longer needs to
        # guard against it, see outgoing_damage below), but CloneArmy sets
        # it unconditionally on every plugin it drives, same as Phantom
        # Lancer's own copy of this same flag.
        self._clone_army_resolving = False
        # Set by apply_tag_effects the instant Reality Rift lands, read (and
        # cleared) by forced_ability on the very next start_attack() call —
        # guarantees the blink-in is always followed by a real Mace Slash on
        # the same (rooted) target instead of just going back to whatever
        # choose_ability's own random pool happens to pick next.
        self._forced_basic = None

    def weapons(self):
        return load_chaos_knight_weapons()

    def clone_army(self):
        return self.army

    # ---- passive: Chaos Strike -------------------------------------------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is not self.fighter:
            return dmg, note
        if ability.kind == "basic" and random.random() < CHAOS_STRIKE_CHANCE:
            # Status: lifesteal (generic, flat 100% — see
            # StatusLibraryMixin.lifesteal_pct in core/status_library.py, no
            # pct kwarg to pass anymore) instead of a bespoke heal computed
            # by hand here — deal_damage() itself (called moments later in
            # this very same do_damage()) reads this the instant `actual`
            # (the real, already armor/shield-mitigated damage that lands on
            # the defender) is known, and applies `round(actual * heal_mult)`
            # (see combat_resolution.apply_lifesteal). A near-instant
            # duration: it only ever needs to survive from here to that one
            # read, nothing decrements it in between (tick_statuses only
            # ever runs between frames, never mid-do_damage()).
            set_status(attacker, "lifesteal", 0.15)
            return round(dmg * CHAOS_STRIKE_CRIT_MULT), note + " [CHAOS STRIKE]"
        return dmg, note

    # ---- passive: Chaos Strike, mirrored onto Phantasm clones ---------------
    def clone_basic_attack_roll(self, clone, dmg):
        """A Phantasm clone's own basic-attack-alike (CloneArmy._clone_attack)
        is dealt through battle.deal_damage() directly with the owner as the
        nominal attacker — and deal_damage() now applies the generic
        lifesteal status generically too (see
        combat_resolution.apply_lifesteal), so setting the same status here
        is all a clone's own Chaos Strike crit needs: Chaos Knight heals for
        the clone's own landed hit exactly the same way it would for its own
        Mace Slash (see outgoing_damage above), no separate bespoke heal of
        its own anymore."""
        if random.random() < CHAOS_STRIKE_CHANCE:
            set_status(self.fighter, "lifesteal", 0.15)
            return round(dmg * CHAOS_STRIKE_CRIT_MULT), True
        return dmg, False

    # ---- Reality Rift: guaranteed Mace Slash follow-up ---------------------
    def forced_ability(self, attacker):
        if attacker is not self.fighter or self._forced_basic is None:
            return None
        ability = self._forced_basic
        self._forced_basic = None
        if not self.battle.can_basic_attack(attacker):
            return None  # CK got disarmed/silenced/stunned in the meantime — skip, don't force through real CC
        return ability

    # ---- Reality Rift: blink to melee range --------------------------------
    def strike_point_override(self, attacker, ability):
        if attacker is not self.fighter or ability.tag != "reality_rift":
            return None
        battle = self.battle
        basic_range = self.fighter.abilities["basic"].melee_range
        # atk_dir points attacker -> defender; landing `basic_range` back
        # off the defender's own position puts Chaos Knight exactly at Mace
        # Slash's own reach once it arrives, same distance a normal dash-in
        # basic attack would need to already be in range.
        dest = battle.defender_start - battle.atk_dir * basic_range
        dest.x = max(BOUND_LEFT, min(BOUND_RIGHT, dest.x))
        dest.y = max(BOUND_TOP, min(BOUND_BOTTOM, dest.y))
        return dest

    def _mirror_reality_rift(self, defender):
        """Reality Rift's own clone-mirror payoff (see _mirror_skill below) —
        every living Phantasm clone blinks to the defender's melee range too
        and roots them right along with Chaos Knight's own cast (a plain
        re-apply of the same fixed REALITY_RIFT_ROOT_S — harmless, unlike
        Chaos Bolt's random stun roll, which _mirror_skill deliberately
        leaves alone so it doesn't quietly overwrite Chaos Knight's own
        already-floated duration). CloneArmy's generic skill-mirror
        (on_owner_skill_landed) only replays a *damage* proc — Reality Rift
        carries none (dmg_mult 0, see moves.py) — so this teleport+root
        mirror is Chaos Knight's own bespoke follow-up instead. Only moves
        the clones (and guarantees their own follow-up swing — see the
        attack_cd reset below) — the portal flourish itself is drawn in
        _draw_ability_fx, in lockstep with Chaos Knight's own reappear/
        strike phases, not a separate one-shot effect here."""
        if not self.army.clones:
            return
        basic_range = self.fighter.abilities["basic"].melee_range
        for clone in self.army.clones:
            direction = clone.pos - defender.pos
            if direction.length_squared() == 0:
                direction = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
            direction = direction.normalize()
            dest = defender.pos + direction * basic_range
            dest.x = max(BOUND_LEFT, min(BOUND_RIGHT, dest.x))
            dest.y = max(BOUND_TOP, min(BOUND_BOTTOM, dest.y))
            clone.pos = dest
            # Guaranteed follow-up swing, same idea as Chaos Knight's own
            # forced_ability Mace Slash — calls CloneArmy's own can_attack
            # swing (_clone_attack, same code/animation a normal in-range
            # auto-attack uses) directly instead of just zeroing attack_cd
            # and hoping the passive range check (clone.pos vs
            # CLONE_ATTACK_RANGE) passes next tick: the arena-bounds clamp
            # above can nudge `dest` a few px past CLONE_ATTACK_RANGE at the
            # edge of the arena, which would otherwise silently skip this
            # "guaranteed" hit.
            self.army._clone_attack(clone, defender)
            clone.attack_cd = self.army.attack_cooldown
            emit_dark(self.battle.fx, dest, count=14, radius=30)
        set_status(defender, "rooted", REALITY_RIFT_ROOT_S)

    def _mirror_skill(self, ability, defender):
        """Every living Phantasm clone performs this same skill too, the
        instant Chaos Knight's own cast resolves — called from the tail of
        apply_tag_effects below for any ability.kind == "skill", so it's
        keyed purely off Chaos Knight *activating* the skill (any resolved,
        non-missed cast — apply_ability_tag_effects already skips this
        entirely on a genuine miss/evade), not off actual damage landing.
        No cooldown of its own; it only ever fires in lockstep with Chaos
        Knight's own cast, at most once per cast, same as
        CloneArmy.on_owner_skill_landed's own no-cooldown design."""
        if not self.army.clones or defender is None:
            return
        if ability.tag == "chaos_bolt":
            # The visible cast itself (a comet at each clone, during Chaos
            # Knight's own "chase" phase) is drawn in _draw_ability_fx,
            # piggybacking on Chaos Knight's own animation clock instead of
            # a separate one here — this only resolves the mechanical hit.
            self.army.on_owner_skill_landed(ability, defender)
            emit_spark_burst(self.battle.fx, defender.pos, CHAOS_EMBER, count=10)
        elif ability.tag == "reality_rift":
            self._mirror_reality_rift(defender)

    # ---- tag effects --------------------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "chaos_bolt" and defender is not None and battle.damage_applied:
            # Status: stunned — a fresh random duration every cast, not one
            # fixed number (see CHAOS_BOLT_STUN_MIN/MAX).
            stun_s = random.uniform(CHAOS_BOLT_STUN_MIN, CHAOS_BOLT_STUN_MAX)
            set_status(defender, "stunned", stun_s)
            battle.floaters.append(
                [defender.pos.x, defender.pos.y - 55, -0.5, 255, f"Stun {stun_s:.1f}s!", CHAOS_EMBER]
            )
            battle.log = f"{attacker.name}'s Chaos Bolt stuns {defender.name} for {stun_s:.1f}s!"
            emit_spark_burst(battle.fx, defender.pos, CHAOS_EMBER, count=18)
        elif tag == "reality_rift" and defender is not None:
            # Status: rooted (hard CC — movement only, can still fight back)
            set_status(defender, "rooted", REALITY_RIFT_ROOT_S)
            # Stay planted at the rift's landing spot instead of drifting
            # back to where Chaos Knight started — flicker_slash's own
            # "return" phase, and the engine's end-of-sequence snap-back,
            # both read attacker_start/attack_final_pos (see
            # battle_loop.apply_motion_frame's "flicker_slash" branch and
            # update_attack's own end-of-sequence snap); overwriting both to
            # the landing spot makes "return" a no-op hold instead of a walk
            # back out, so the guaranteed Mace Slash below actually lands
            # right where Chaos Knight blinked to.
            battle.attacker_start = pygame.Vector2(battle.strike_point)
            battle.attack_final_pos = pygame.Vector2(battle.strike_point)
            self._forced_basic = self.fighter.abilities["basic"]
            battle.floaters.append([defender.pos.x, defender.pos.y - 55, -0.5, 255, "Rooted!", CHAOS_EMBER])
            battle.log = f"{attacker.name} rips open a Reality Rift beside {defender.name}!"
            battle.add_ring(attacker.pos, 70, 0.4, CHAOS_EMBER, width=4)
            emit_dark(battle.fx, attacker.pos, count=26, radius=45)
        elif tag == "phantasm":
            # Status: none — Phantasm has no timed buff of its own; the
            # clone army (see __init__/clone_army()) tracks its own duration.
            self.army.spawn(near=attacker.pos)
            self.army.spawn(near=attacker.pos)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "PHANTASM!", CHAOS_EMBER])
            battle.log = f"{attacker.name} tears open a Phantasm — a full-power illusion joins the fight!"
            battle.flash_timer = max(battle.flash_timer, 0.42)
            battle.add_screen_shake(18, 0.28)
            battle.add_ring(attacker.pos, 160, 0.7, CHAOS_EMBER, width=6)
            emit_dark(battle.fx, attacker.pos, count=40, radius=80)

        if ability.kind == "skill":
            self._mirror_skill(ability, defender)

    # ---- per-frame simulation ---------------------------------------------------
    def ambient_tick(self, dt):
        self.army.tick(dt)

    def extra_colliders(self):
        return self.army.extra_colliders()

    def basic_attack_decoys(self):
        return self.army.redirect_pool()

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_spark_burst(self.battle.fx, pos, CHAOS_EMBER, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos and battle.ability.name == "Chaos Bolt"):
            return False
        draw_comet(screen, battle.projectile_pos, battle.atk_dir, CHAOS_EMBER,
                   size=1.1 if battle.ability.big else 1.0)
        return True

    def draw_fx(self, screen, shake_x):
        self._draw_mace(screen, shake_x)
        self._draw_ability_fx(screen, shake_x)
        self.army.draw(screen, shake_x, ring_color=CHAOS_EMBER, draw_weapon=self._draw_clone_mace)

    def _draw_mace(self, screen, shake_x):
        """The mace: rested low when idle, a double bludgeoning swing for
        Mace Slash — mirrors Berserker's own "slash" motion structure exactly
        (windup/slash1/slash2/return — see MOTIONS["slash"] in
        core/motions.py and Reckless Cleave's draw_fx), same crossing-diagonal
        draw_slash_arc sweep + ghost-image weapon_trail Reckless Cleave uses
        to actually sell the swing (rather than just a self-rotating prop),
        just a heavier crushing arc instead of a claw rake."""
        battle, ck = self.battle, self.fighter
        if not ck.is_alive():
            return
        # Hidden in lockstep with the fighter's own sprite during Reality
        # Rift's teleport (see render.py's is_flicker_hidden) — no floating
        # weapon left behind while Chaos Knight itself is invisible.
        hidden = (
            battle.mode == "attack" and battle.attacker is ck
            and battle.motion == "flicker_slash" and battle.current_phase in ("vanish", "reappear")
        )
        if hidden:
            return

        img = battle.weapons["mace"]
        p = ck.pos + pygame.Vector2(shake_x, 0)

        active = battle.mode == "attack" and battle.attacker is ck and battle.ability.name == "Mace Slash"
        if not active:
            battle.weapon_trail.clear()
            draw_rotated(screen, img, p + IDLE_OFFSET, IDLE_ANGLE)
            return

        phase, t = battle.current_phase, battle.phase_t
        tip_reach = AVATAR_R + 14
        if phase == "windup":
            reach, extra = 10, -60 * ease_out(t)
        elif phase == "slash1":
            reach = tip_reach
            extra = -60 + 120 * ease_in(t)
            swing_dir = battle.atk_dir.rotate(-35)
            draw_slash_arc(screen, p, swing_dir, radius=48 + 10 * t, spread_deg=95,
                            color=CHAOS_EMBER, width=7, fade=1 - t)
            if t > 0.55:
                strike_pos = p + battle.atk_dir * reach
                draw_slash(screen, strike_pos, swing_dir, WHITE, length=32, width=5)
                draw_starburst(screen, strike_pos, WHITE, size=26, fade=(1 - t) / 0.45)
                draw_expanding_ring(screen, strike_pos, 34 * t, CHAOS_EMBER, width=4)
        elif phase == "slash2":
            reach = tip_reach
            extra = 60 - 120 * ease_in(t)
            swing_dir = battle.atk_dir.rotate(35)
            draw_slash_arc(screen, p, swing_dir, radius=52 + 12 * t, spread_deg=105,
                            color=CHAOS_EMBER, width=8, fade=1 - t)
            if t > 0.55:
                strike_pos = p + battle.atk_dir * reach
                draw_slash(screen, strike_pos, swing_dir, WHITE, length=36, width=6)
                draw_starburst(screen, strike_pos, WHITE, size=30, fade=(1 - t) / 0.45)
                draw_expanding_ring(screen, strike_pos, 38 * t, CHAOS_EMBER, width=4)
        else:  # return
            reach = tip_reach - (tip_reach - 6) * ease_out(t)
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

    def _draw_ability_fx(self, screen, shake_x):
        """Reality Rift's own portal flourish (windup/vanish/reappear are
        already covered by render.py's is_flicker_hidden + the vanish/
        reappear ring/particles fired from apply_tag_effects above), and
        Chaos Bolt/Phantasm's charge-up telegraphs — plus, for Reality
        Rift/Chaos Bolt, every living Phantasm clone's own mirrored version
        of the same flourish, drawn off this exact same phase/phase_t clock
        instead of a separate one of its own (see _mirror_skill/
        _mirror_reality_rift, which only move the clone / resolve the hit,
        never animate anything themselves) — so a clone's "cast" is always
        in lockstep with Chaos Knight's own, never a second, independently
        timed effect."""
        battle, ck = self.battle, self.fighter
        if not (battle.mode == "attack" and battle.attacker is ck):
            return
        name = battle.ability.name
        phase, t = battle.current_phase, battle.phase_t
        shake = pygame.Vector2(shake_x, 0)
        if name == "Reality Rift" and phase in ("reappear", "strike"):
            pos = pygame.Vector2(battle.strike_point) + shake
            draw_expanding_ring(screen, pos, 50 * (t if phase == "reappear" else max(0.0, 1 - t)),
                                CHAOS_EMBER, width=5)
            draw_starburst(screen, pos, CHAOS_EMBER, size=30, fade=t if phase == "reappear" else max(0.0, 1 - t))
            for clone in self.army.clones:
                cpos = clone.pos + shake
                draw_expanding_ring(screen, cpos, 32 * (t if phase == "reappear" else max(0.0, 1 - t)),
                                    CHAOS_EMBER, width=3)
                draw_starburst(screen, cpos, CHAOS_EMBER, size=18,
                               fade=t if phase == "reappear" else max(0.0, 1 - t))
        elif name == "Chaos Bolt" and phase == "windup":
            origin = pygame.Vector2(battle.attacker_start) + shake
            draw_starburst(screen, origin, CHAOS_EMBER, size=10 + 14 * t, fade=t)
        elif name == "Chaos Bolt" and phase == "chase":
            # Same lerp/ease_in(t) formula battle_loop.py's own "chase"
            # branch uses for Chaos Knight's real projectile_pos (t is
            # battle.phase_t, not a separate clock) — without actually
            # travelling toward the target this way, the comet just sits on
            # top of the clone's own position the whole phase and gets
            # painted over by army.draw()'s clone sprite right after.
            target = pygame.Vector2(battle.defender.pos if battle.defender is not None else battle.defender_start)
            for clone in self.army.clones:
                start = pygame.Vector2(clone.pos)
                pos = start.lerp(target, ease_in(t)) + shake
                draw_comet(screen, pos, target - start, CHAOS_EMBER, size=0.9)
        elif name == "Phantasm" and phase in ("windup", "channel"):
            origin = pygame.Vector2(battle.attacker_start) + shake
            draw_expanding_ring(screen, origin, 20 + 60 * t, CHAOS_EMBER, width=5)
            draw_starburst(screen, origin, CHAOS_EMBER, size=16 + 18 * t, fade=t)

    def _draw_clone_mace(self, screen, clone, pos):
        """Rested low when idle, one continuous swing-out-and-back when
        clone.attack_anim_t is counting down — passed to CloneArmy.draw() as
        its draw_weapon callback, same shape as Phantom Lancer's own
        _draw_clone_lance. Full-size, same prop image the real Chaos Knight
        holds — no scaled-down clone-only copy."""
        img = self.battle.weapons["mace"]
        if clone.attack_anim_t > 0:
            t = 1 - clone.attack_anim_t / CLONE_ATTACK_ANIM_S
            reach = 8 + (AVATAR_R + 18) * math.sin(math.pi * t)
            angle = weapon_angle(clone.attack_dir, 0)
            weapon_pos = pos + clone.attack_dir * reach
            # Same impact starburst/ring the real Mace Slash fires at the tip
            # of its swing (see _draw_mace's slash2 branch above) — a single
            # hit here instead of two, timed to the reach's own peak (t=0.5)
            # rather than a fixed phase_t threshold, since a clone has no
            # windup/slash1/slash2 phase machine of its own.
            if 0.4 < t < 0.6:
                fade = 1 - abs(t - 0.5) / 0.2
                draw_starburst(screen, weapon_pos, WHITE, size=30, fade=fade)
                draw_expanding_ring(screen, weapon_pos, 38 * fade, CHAOS_EMBER, width=4)
        else:
            weapon_pos = pos + IDLE_OFFSET * 0.8
            angle = IDLE_ANGLE
        draw_rotated(screen, img, weapon_pos, angle)
