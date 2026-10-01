"""Berserker plugin: Berserker Rage (activation, its tag-cast side effects,
and the forced last-stand that fires instead of a killing blow), the Fury
passive that permanently stacks on any big hit landed, Rage's melee-range/
damage/speed bonuses, and the axe/Axe-Throw weapon animation."""

import math

import pygame

from ...core.constants import AVATAR_R, HEIGHT, BERSERKER_RED, WHITE, WIDTH
from ...core.effects import (
    draw_expanding_ring,
    draw_fan,
    draw_rotated,
    draw_slash_fx,
    draw_starburst,
    weapon_angle,
)
from ...core.entities import set_status
from ...core.glow import glow_polyline
from ...core.motions import ease_in, ease_out
from ...core.particles import emit_debris, emit_explosion
from ...core.plugin import CharacterPlugin
from ...core.status_library import cleanse
from .weapons import load_berserker_weapons

# Berserker Rage widens the basic attack's melee reach while it's active
RAGE_RANGE_BONUS = 40
# ...and hits harder / swings faster, so the immunity window is also a real damage spike
RAGE_DMG_MULT = 0.7
RAGE_ATTACK_SPEED = 0.1
RAGE_MOVE_SPEED = 0.7
RAGE_DURATION_S = 6
# ...and cuts Axe Throw's own cooldown by 70% while active (this is the cut
# itself, not what's left — higher = more cut = shorter cooldown)
RAGE_AXE_THROW_COOLDOWN_CUT_PCT = 0.5
# ...and Whirling Axes' own cooldown the same way (same "cut, not what's
# left" convention)
RAGE_WHIRLING_AXES_COOLDOWN_CUT_PCT = 0.5

# forced last-stand: the hp the Berserker is left at instead of dying
LAST_STAND_HP = 1

# Rage's own permanent payoff, on top of its timed buff bundle — armor is a
# direct, permanent stat bump (same "mutate the base stat, no expiry" shape
# Fury already uses below), lifesteal rides the generic "lifesteal" status
# (see StatusLibraryMixin.lifesteal_pct — flat 100% the instant it's up) at
# a duration long enough to outlast any real match, so it never lapses once
# Rage has fired. Rage itself only ever fires once per match (one_shot
# ultimate, or the death-save last stand — both flip ultimate.used), so this
# never needs a guard against re-applying.
RAGE_PERMANENT_ARMOR_BONUS = 6
RAGE_PERMANENT_ATTACK_BONUS = 3
RAGE_PERMANENT_LIFESTEAL_DURATION_S = 999999

# passive: any single hit that deals at least this much damage permanently
# toughens the Berserker up — stacks without limit, for the rest of the match
FURY_THRESHOLD = 4
FURY_ARMOR_GAIN = 0.7  # armor is on a 0-100 scale, so this is +0.5%
FURY_ATK_GAIN = 0.7
FURY_SPEED_GAIN = 0.7

#: Reckless Cleave's own splash reach, granted from the moment Berserker
#: Rage's own timed buff window actually ends (see on_status_expire/
#: _unlock_basic_splash below) — not present from the start. A blast
#: centered on the defender (no aoe_cone_deg, so combat_resolution.
#: do_damage's in_cone gate never applies to the main hit; it's just a
#: plain radius passed straight to CloneArmy.splash_aoe/
#: splash_aoe_to_clones). Once unlocked, every landed basic also chips any
#: of the defender's own clones standing this close to them — the generic
#: answer to Phantom Lancer's Juxtapose swarm (and Chaos Knight's Phantasm,
#: Vampire's Doppelganger, ...) parking a pile of illusions right on top of
#: their owner: once Rage's own burst of power fades, Berserker's fast,
#: frequent basic keeps something to show for landing through a crowd of
#: them, instead of only ever touching the one real fighter underneath. As
#: a side effect, marking the basic as an area ability also pulls it out of
#: taunt_redirect's decoy pool entirely (see status_library.taunt_redirect)
#: — it can no longer be swapped onto a single decoy clone in place of the
#: real target either.
BASIC_SPLASH_RADIUS = 120

AXE_THROW_SPREAD_START = 20

# Whirling Axes (styled after Troll Warlord's melee Whirling Axes): two
# axes on opposite sides of the orbit, each trailing a glowing swoosh. The
# orbit grows from WHIRL_START_RADIUS to the ability's own aoe_radius across
# windup+whirl, hitting each enemy body once the moment it reaches them
# (see attack_frame). WHIRL_SPIN_SPEED is the orbit speed (deg/ms);
# WHIRL_TUMBLE_MULT is how much faster each axe spins on its own axis.
WHIRL_AXE_COUNT = 2
WHIRL_START_RADIUS = AVATAR_R + 12
WHIRL_SPIN_SPEED = 0.75
WHIRL_TUMBLE_MULT = 2.5
WHIRL_TRAIL_DEG = 120
WHIRL_TRAIL_SEGMENTS = 6
WHIRL_TRAIL_COLOR = (150, 215, 255)

# Idle resting pose for the axe prop — held low and angled back, same
# convention every other character's weapon prop uses (see IDLE_ANGLE/
# IDLE_OFFSET in characters/phantom_lancer/plugin.py and
# characters/chaos_knight/plugin.py).
IDLE_ANGLE = 200
IDLE_OFFSET = pygame.Vector2(-10, 16)


class BerserkerPlugin(CharacterPlugin):
    #: Ground crack this fighter's big hits leave (anime_fx.DECAL_STYLES):
    #: a brutal axe cleft across the swing.
    GROUND_DECAL = "chop"
    #: Hit-flash flare (anime_fx.build_impact_burst_frames): a spray of shrapnel.
    BURST_TEXTURE = "dirt_01"

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.rage_particle_cd = 0
        # The slash phase this swing last launched a cleave wave on, so
        # draw_fx (called every frame) launches exactly one per rake.
        self.cleave_wave_phase = None
        # Bodies (by id) Whirling Axes already hit this cast, so each one
        # takes at most one hit per spin (see attack_frame).
        self.whirl_hit = set()

    def weapons(self):
        return load_berserker_weapons()

    # ---- ability gating -------------------------------------------------------
    def melee_range_bonus(self, attacker, melee_range):
        if melee_range is not None and attacker is self.fighter and self._is_raging(attacker):
            return melee_range + RAGE_RANGE_BONUS
        return melee_range

    def cooldown_bonus(self, attacker, ability, cooldown):
        if attacker is not self.fighter or not self._is_raging(attacker):
            return cooldown
        if ability.tag == "axe_throw":
            return cooldown * (1 - RAGE_AXE_THROW_COOLDOWN_CUT_PCT)
        if ability.tag == "whirling_axes":
            return cooldown * (1 - RAGE_WHIRLING_AXES_COOLDOWN_CUT_PCT)
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
            actual = target.hp - LAST_STAND_HP
            target.hp = LAST_STAND_HP
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
        battle.floaters.append([
            b.pos.x, b.pos.y - 70, -0.6, 255,
            f"FURY +{FURY_ATK_GAIN:g} ATK +{FURY_ARMOR_GAIN:g} ARM +{FURY_SPEED_GAIN:g} SPD", BERSERKER_RED,
        ])
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
        set_status(b, "attack_up", RAGE_DURATION_S, pct=RAGE_DMG_MULT)
        set_status(b, "attack_speed_up", RAGE_DURATION_S, pct=RAGE_ATTACK_SPEED)
        set_status(b, "move_speed_up", RAGE_DURATION_S, pct=RAGE_MOVE_SPEED)
        set_status(b, "invulnerable", RAGE_DURATION_S, death_save=death_save)
        # Permanent payoff, outliving the timed buff bundle above entirely —
        # armor mutated directly (never expires), lifesteal via a duration
        # long enough it never realistically lapses.
        b.armor += RAGE_PERMANENT_ARMOR_BONUS
        b.atk += RAGE_PERMANENT_ATTACK_BONUS
        set_status(b, "lifesteal", RAGE_PERMANENT_LIFESTEAL_DURATION_S)
        # a forced last-stand activation didn't go through the normal
        # attack sequence, so its one-shot flag wouldn't otherwise get set
        b.abilities["ultimate"].used = True
        battle.add_screen_shake(16, 0.28)
        battle.flash_timer = max(battle.flash_timer, 0.38)
        if death_save:
            battle.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "LAST STAND!", BERSERKER_RED])
            battle.log = f"{b.name} refuses to fall — Berserker Rage erupts in a last stand!"
        else:
            battle.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "RAGE!", BERSERKER_RED])
            secs = RAGE_DURATION_S
            battle.log = f"{b.name} flies into a Berserker Rage — unstoppable for {secs}s!"

    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter or ability.tag != "berserker_rage":
            return
        battle = self.battle
        self.start_rage()
        battle.add_ring(self.fighter.pos, 150, 0.6, BERSERKER_RED, width=6)
        emit_debris(battle.fx, self.fighter.pos, count=34, speed=(100, 260))
        emit_explosion(battle.fx, self.fighter.pos, BERSERKER_RED, count=20)

    def resolve_special(self):
        """Whirling Axes resolves at "windup" (see RESOLVE_PHASE in
        core/motions.py): the cleanse fires the instant the cast starts, so
        a Blind/Stun picked up before the spin can't spoil it. The hits
        themselves land continuously afterward, see attack_frame."""
        battle, b = self.battle, self.fighter
        if not (battle.attacker is b and battle.ability.tag == "whirling_axes"):
            return False
        self.whirl_hit = set()
        cleanse(b)
        battle.floaters.append([b.pos.x, b.pos.y - 60, -0.6, 255, "CLEANSE!", WHITE])
        battle.add_screen_shake(6, 0.15)
        emit_debris(battle.fx, b.pos, count=14, speed=(100, 240))
        battle.log = f"{b.name} starts whirling the axes, cleansed!"
        return True

    def attack_frame(self, attacker, ability, phase, t):
        """Whirling Axes' hits, Troll Warlord style: every frame of the spin,
        any enemy body the growing ring currently reaches (its own
        center within the ring's radius plus a body's width, so the axes
        visibly touching someone counts) takes one hit, at most once per
        body per cast. The real defender goes through battle._strike_defender
        (armor, crit, Rage bonus, lifesteal, Fury all apply as usual); its
        clones and Vampire's doppelganger take the same flat hit the generic
        splash_aoe_to_clones would deal, centered on the Berserker here
        instead of on the defender."""
        battle, b = self.battle, self.fighter
        if attacker is not b or ability.tag != "whirling_axes" or phase not in ("windup", "whirl"):
            return
        reach = self._whirl_radius(phase, t, ability.aoe_radius) + AVATAR_R

        defender = battle.defender
        if defender is not None and id(defender) not in self.whirl_hit and (defender.pos - b.pos).length() <= reach:
            self.whirl_hit.add(id(defender))
            battle._strike_defender()

        dmg = round(b.atk * ability.dmg_mult)
        defender_plugin = battle.plugin_for(defender) if defender is not None else None
        army = defender_plugin.clone_army() if defender_plugin is not None else None
        if army is not None:
            for clone in list(army.clones):
                offset = clone.pos - b.pos
                if id(clone) not in self.whirl_hit and offset.length() <= reach:
                    self.whirl_hit.add(id(clone))
                    army.damage_clone(clone, dmg, ability=ability, knock_dir=offset)
        clone = battle.clone
        if (clone is not None and clone.owner is defender and id(clone) not in self.whirl_hit
                and (clone.pos - b.pos).length() <= reach):
            self.whirl_hit.add(id(clone))
            battle._splash_vampire_clone(clone, dmg)

    @staticmethod
    def _whirl_radius(phase, t, full):
        """The orbit's current radius: grows from WHIRL_START_RADIUS to
        `full` (the ability's aoe_radius) over windup+whirl, then holds.
        Shared by the drawing and the hit check so they never disagree."""
        if phase == "windup":
            grow = 0.2 * ease_in(t)
        elif phase == "whirl":
            grow = 0.2 + 0.8 * ease_out(t)
        else:
            grow = 1.0
        return WHIRL_START_RADIUS + (full - WHIRL_START_RADIUS) * grow

    def on_status_expire(self, fighter, name, data):
        if fighter is not self.fighter or name != "invulnerable":
            return
        if not data.get("death_save"):
            # Rage's timed buff bundle ran its full course without ever
            # needing the death-save branch below — its own permanent
            # payoff, on top of the armor/lifesteal start_rage() already
            # granted at cast time.
            self._unlock_basic_splash(fighter)
            return
        battle = self.battle
        if battle.winner is not None:
            return  # match was already decided before the last-stand timer ran out
        fighter.hp = 0
        battle.floaters.append([fighter.pos.x, fighter.pos.y - 40, -0.6, 255, "Rage Fades...", BERSERKER_RED])
        battle.log = f"{fighter.name}'s Berserker Rage fades — the last stand ends."
        # No direct declare_winner(): battle_loop's own death check picks
        # this up next frame, so the last stand's end gets the same KO
        # slow-motion beat as any other fatal blow (see begin_ko_slowmo).

    def _unlock_basic_splash(self, fighter):
        """Reckless Cleave's own splash reach (see BASIC_SPLASH_RADIUS in
        moves.py) — dormant until Berserker Rage's own timed buff window
        actually ends, only ever fired here, since Rage itself is one_shot
        (see start_rage's own note on never needing a re-apply guard)."""
        battle = self.battle
        fighter.abilities["basic"].aoe_radius = BASIC_SPLASH_RADIUS
        battle.floaters.append([fighter.pos.x, fighter.pos.y - 60, -0.6, 255, "CLEAVE UP!", BERSERKER_RED])
        battle.log = f"{fighter.name}'s Rage fades — Reckless Cleave now cleaves everything nearby!"

    # ---- per-frame simulation ---------------------------------------------------
    # attack/move speed while raging come from the generic attack_speed_up/
    # move_speed_up statuses applied in start_rage() — no bespoke multiplier
    # hooks needed here anymore (the engine already reads those generically
    # in battle_loop.py, and duplicating it here would double-apply it).

    def ambient_tick(self, dt):
        if not self._is_raging(self.fighter):
            return
        self.rage_particle_cd -= dt
        if self.rage_particle_cd <= 0:
            emit_debris(self.battle.fx, self.fighter.pos, count=4, speed=(30, 90))
            self.rage_particle_cd = 0.065

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
        alpha = min(110, int(110 * min(1.0, remaining / 8)))
        overlay.fill((160, 30, 10, alpha))
        screen.blit(overlay, (0, 0))

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is self.fighter and battle.ability.name == "Axe Throw":
            self._draw_axe_fan(screen)
            return True
        return False

    def draw_fx(self, screen, shake_x):
        """The Berserker's axe: rested low when idle (same convention as
        every other character's weapon prop — see IDLE_ANGLE/IDLE_OFFSET),
        swung for Reckless Cleave, thrown as the Axe Throw projectile (see
        _draw_axe_fan), and raised overhead during the Berserker Rage roar."""
        battle, b = self.battle, self.fighter
        if not b.is_alive():
            return

        img = battle.weapons["axe"]
        p = b.pos + pygame.Vector2(shake_x, 0)

        name = battle.ability.name if (battle.mode == "attack" and battle.attacker is b) else None
        if name == "Whirling Axes":
            battle.weapon_trail.clear()
            self._draw_whirling_axes(screen, p, img)
            return
        if name not in ("Reckless Cleave", "Berserker Rage"):
            self.cleave_wave_phase = None
            battle.weapon_trail.clear()
            draw_rotated(screen, img, p + IDLE_OFFSET, IDLE_ANGLE)
            return

        phase, t = battle.current_phase, battle.phase_t

        if name == "Berserker Rage":
            lift = 40 + 8 * math.sin(pygame.time.get_ticks() * 0.02)
            pos = p + pygame.Vector2(0, -lift)
            if phase == "channel":
                draw_expanding_ring(screen, p, 20 + 80 * t, BERSERKER_RED, width=5)
                draw_starburst(screen, p, BERSERKER_RED, size=20 + 20 * t, fade=t)
            draw_rotated(screen, img, pos, 0)
            return

        # Two crossing rakes (like a claw swipe), not a dash-in strike: the
        # axe sweeps one diagonal on slash1, the opposite diagonal on
        # slash2, while the body barely moves (see apply_motion_frame). The
        # axe's own position now actually travels along that swing angle
        # (rotating atk_dir by -extra, not just holding a fixed spot along
        # atk_dir and rotating the sprite in place) — that live-tracked
        # position is what feeds the weapon_trail ghosting below, so the
        # trail reads as a real arcing rake through space instead of a
        # fan of afterimages spinning on one point. Each rake also gets the
        # painted slash flipbook (draw_slash_fx) riding along the blade's
        # actual live position/angle for the whole swing, plus a starburst
        # pop right as the axe connects — both drawn *after* the axe prop
        # itself below, or the opaque axe (sharing this same tip position)
        # would just paint straight over them.
        if phase == "windup":
            reach, extra = 10, -68 * ease_out(t)
        elif phase == "slash1":
            reach = AVATAR_R + 14
            extra = -68 + 136 * ease_in(t)
        elif phase == "slash2":
            reach = AVATAR_R + 14
            extra = 68 - 136 * ease_in(t)
        else:  # return
            reach = AVATAR_R + 14 - (AVATAR_R + 4) * ease_out(t)
            extra = -68 + 68 * ease_out(t)
        swing_dir = battle.atk_dir.rotate(-extra)
        angle = weapon_angle(swing_dir, 0)
        pos = p + swing_dir * reach

        if phase in ("slash1", "slash2"):
            battle.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(battle.weapon_trail) > 8:
                battle.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(battle.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(battle.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            battle.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

        if phase == "slash2":
            if self.cleave_wave_phase != phase:
                self.cleave_wave_phase = phase
                self._launch_cleave_wave(phase)
        else:
            self.cleave_wave_phase = None

        if phase == "slash1":
            draw_slash_fx(screen, pos, swing_dir, t, size=90, color=self.fighter.color)
            if t > 0.55:
                draw_starburst(screen, pos, WHITE, size=26, fade=(1 - t) / 0.45)
        elif phase == "slash2":
            draw_slash_fx(screen, pos, swing_dir, t, size=105, color=self.fighter.color)
            if t > 0.55:
                draw_starburst(screen, pos, WHITE, size=30, fade=(1 - t) / 0.45)

    def _draw_whirling_axes(self, screen, center, img):
        """WHIRL_AXE_COUNT axes evenly spaced on an orbit that widens from
        WHIRL_START_RADIUS to the ability's aoe_radius over windup+whirl
        (hits land whenever the ring touches someone, see attack_frame),
        then holds that full radius while fading out on "release"."""
        battle = self.battle
        phase, t = battle.current_phase, battle.phase_t
        full = battle.ability.aoe_radius
        alpha = int(255 * (1 - t)) if phase == "release" else 255
        radius = self._whirl_radius(phase, t, full)

        fade = alpha / 255
        spin = pygame.time.get_ticks() * WHIRL_SPIN_SPEED
        for i in range(WHIRL_AXE_COUNT):
            head = spin + i * 360 / WHIRL_AXE_COUNT
            self._draw_whirl_swoosh(screen, center, radius, head, fade)
            a = math.radians(head)
            pos = center + pygame.Vector2(math.cos(a), math.sin(a)) * radius
            # Each axe also tumbles on its own axis, the same way round it orbits
            # (pygame rotates counter-clockwise, the orbit runs clockwise on screen).
            draw_rotated(screen, img, pos, -(spin * WHIRL_TUMBLE_MULT) % 360, alpha=alpha)

    @staticmethod
    def _draw_whirl_swoosh(screen, center, radius, head_deg, fade):
        """The glowing arc streak trailing one whirling axe: WHIRL_TRAIL_DEG
        of the orbit behind it, split into segments that thin out and dim
        toward the tail so it tapers like a motion blur."""
        n = WHIRL_TRAIL_SEGMENTS
        step = WHIRL_TRAIL_DEG / n
        for s in range(n):
            k = 1 - s / n  # 1 at the axe, towards 0 at the tail
            a0 = math.radians(head_deg - s * step)
            a1 = math.radians(head_deg - (s + 1) * step)
            pts = [
                (center.x + math.cos(a) * radius, center.y + math.sin(a) * radius)
                for a in (a0, (a0 + a1) / 2, a1)
            ]
            glow_polyline(screen, pts, WHIRL_TRAIL_COLOR, width=max(1, round(9 * k)), intensity=0.9 * k * fade)

    def _launch_cleave_wave(self, phase):
        """One crescent shockwave per rake, pushed straight out along
        atk_dir (see ImpactFXMixin.add_cleave_wave). Once Rage has unlocked
        the basic's own splash (see _unlock_basic_splash) the slash2 wave
        is sized to that splash: BASIC_SPLASH_RADIUS wide on each side and
        sweeping clean through the defender to BASIC_SPLASH_RADIUS past
        them, so the area it visibly covers is the area it actually hits.
        slash1's wave is a smaller lead-in. No wave at all before the
        unlock (before or during Rage): the basic is still single-target
        then, and a wave would advertise an area it doesn't have."""
        battle, b = self.battle, self.fighter
        if not battle.ability.aoe_radius:
            return
        origin = b.pos + battle.atk_dir * AVATAR_R
        reach = (battle.defender.pos - origin).length() + BASIC_SPLASH_RADIUS
        size, travel = BASIC_SPLASH_RADIUS * 2, reach
        if phase == "slash1":
            size, travel = size * 0.7, travel * 0.6
        battle.add_cleave_wave(origin, battle.atk_dir, BERSERKER_RED, size, travel, duration=0.5)

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
        # area entities.in_cone checks against (both the resolved defender
        # in combat_resolution.do_damage and its clones via
        # splash_aoe_to_clones) — any enemy body standing inside the drawn
        # fan must always be inside the real one too, no exceptions.
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
