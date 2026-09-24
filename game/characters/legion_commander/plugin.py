"""Legion Commander plugin: the Unyielding Resolve passive (Attack Up +
Armor Up kept live only while the opponent's hp is ahead of her own),
Overwhelming Odds' radial flame-arrow barrage (armor-chipping + burn on
every arrow that connects), Press the Attack's self-cleanse/heal/speed
burst, Moment of Courage's lifesteal window, Duel's blink-lock (mutual
root+silence, a self-only Reflect while it lasts, and a permanent Attack Up
once it ends), and the scepter/flame-arrow animation."""

import pygame

from ...core.constants import AVATAR_R, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GOLD, GRAY, LEGION_CRIMSON, WHITE
from ...core.effects import draw_expanding_ring, draw_rotated, draw_slash_fx, draw_starburst, rotate_to_dir, weapon_angle
from ...core.entities import melee_size_offset, set_status
from ...core.motions import ease_in, ease_out
from ...core.particles import emit_explosion, emit_spark_burst
from ...core.plugin import CharacterPlugin
from ...core.status_library import cleanse, heal
from .weapons import flame_arrow_sprite, load_legion_commander_weapons

# Passive: Unyielding Resolve — while the opponent's hp is strictly ahead of
# Legion Commander's own, she carries a flat Attack Up + Armor Up buff,
# refreshed every frame she still qualifies (see ambient_tick) and dropped
# immediately once the opponent's hp falls back to or below hers again.
PASSIVE_ATK_PCT = 0.65
PASSIVE_ARMOR_AMOUNT = 16
# Refreshed every ambient_tick call — comfortably above one frame so it never
# actually lapses while the condition keeps holding, short enough that
# dropping it (see ambient_tick's else branch, which pops it immediately
# anyway) never leaves a stale buff hanging around either.
PASSIVE_REFRESH_S = 0.25

# Overwhelming Odds: every arrow that actually lands chips a flat amount of
# armor and leaves the target burning — refreshed (not stacked) by each
# fresh hit, same "flat, non-stacking" shape Chain Bolt/Thunder God's
# Descent use for their own burn.
OO_ARMOR_BREAK_AMOUNT = 10
OO_ARMOR_BREAK_DURATION_S = 5
OO_BURN_DURATION_S = 6

# Press the Attack: an instant heal (pct of Legion Commander's own max hp)
# plus a short move-speed burst, on top of the cleanse.
PRESS_HEAL_PCT = 0.35
PRESS_SPEED_PCT = 3
PRESS_SPEED_DURATION_S = 5

# Moment of Courage: how long the generic "lifesteal" status stays up.
MOC_LIFESTEAL_DURATION_S = 8

# Duel: how long the mutual root+silence lockdown and Legion Commander's own
# Reflect window last, how much of the opponent's own damage Reflect bounces
# back while it's up, and the flat Attack Up she keeps for the rest of the
# match once the duel ends. Neither fighter has anything else to do while
# it's up (basic attack is the only action root+silence leaves either of
# them), so DUEL_BASIC_COOLDOWN_S also crushes both fighters' basic-attack
# cooldown down to a rapid trade for the whole window (see cooldown_bonus) —
# a real slugfest instead of waiting out each side's normal, much longer
# cooldown.
DUEL_DURATION_S = 2
DUEL_REFLECT_PCT = 1.3
DUEL_ATK_BONUS = 5
DUEL_BASIC_COOLDOWN_S = 0.5
# Landed a hair inside the shorter fighter's own melee_range instead of
# exactly on it — see _duel_basic_range's own comment for why sitting
# exactly on that boundary is unsafe.
DUEL_RANGE_MARGIN = 2.0

# Idle resting pose for the scepter prop — held low and angled back, same
# convention every other character's weapon prop uses (see IDLE_ANGLE/
# IDLE_OFFSET in characters/berserker/plugin.py and
# characters/chaos_knight/plugin.py).
IDLE_ANGLE = 205
IDLE_OFFSET = pygame.Vector2(-12, 18)


class LegionCommanderPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        # Set by apply_tag_effects the instant Duel lands, read (and
        # cleared) by forced_ability on the very next try_start_attack() call —
        # guarantees the blink-in always follows up with a real Scepter
        # Strike, same trick Chaos Knight's Reality Rift uses (see
        # ChaosKnightPlugin._forced_basic).
        self._forced_basic = None
        # Counts down from DUEL_DURATION_S once Duel lands (see
        # apply_tag_effects); the instant it crosses 0 (ambient_tick),
        # Legion Commander keeps DUEL_ATK_BONUS permanently. Kept as a plain
        # timer here rather than a status on the fighter so it never shows
        # up in the HUD's status readout as a debuff-colored line, and can
        # never be stripped by a cleanse.
        self._duel_timer = 0.0

    def weapons(self):
        return load_legion_commander_weapons()

    def _opponent(self):
        battle = self.battle
        return battle.f2 if battle.f1 is self.fighter else battle.f1

    # ---- passive: Unyielding Resolve, plus Duel's permanent payoff --------
    def ambient_tick(self, dt):
        lc = self.fighter
        if lc.is_alive():
            enemy = self._opponent()
            if enemy.is_alive() and enemy.hp > lc.hp:
                set_status(lc, "attack_up", PASSIVE_REFRESH_S, pct=PASSIVE_ATK_PCT)
                set_status(lc, "armor_up", PASSIVE_REFRESH_S, amount=PASSIVE_ARMOR_AMOUNT)
            else:
                lc.statuses.pop("attack_up", None)
                lc.statuses.pop("armor_up", None)

        if self._duel_timer > 0:
            self._duel_timer -= dt
            if self._duel_timer <= 0:
                self._duel_timer = 0.0
                lc.atk += DUEL_ATK_BONUS
                self.battle.floaters.append(
                    [lc.pos.x, lc.pos.y - 60, -0.6, 255, "DUEL WON!", LEGION_CRIMSON]
                )
                self.battle.log = f"{lc.name}'s resolve hardens — Duel's Attack Up is permanent now!"

    # ---- Overwhelming Odds: swarm setup + per-hit debuff -------------------
    def resolve_special(self):
        """Overwhelming Odds hands off to the generic swarm engine (see
        spawn_swarm_projectiles/update_swarm_projectiles in
        core/battle_loop.py), same as Vampire's own Bat Swarm — this only
        does the one-time cast setup right as the barrage begins; the actual
        per-arrow armor/burn payoff is on_damage_dealt below, fired once per
        connecting arrow by the generic engine itself."""
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.ability.tag == "overwhelming_odds"):
            return False
        attacker = battle.attacker
        if battle.roll_blind_miss(attacker):
            battle.swarm_projectiles = []
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 50, -0.5, 255, "Blinded!", GRAY])
            battle.log = f"{attacker.name}'s Overwhelming Odds fizzles out — blinded!"
            return True
        battle.spawn_swarm_projectiles()
        battle.add_ring(attacker.pos, 130, 0.5, LEGION_CRIMSON, width=5)
        emit_explosion(battle.fx, attacker.pos, LEGION_CRIMSON, count=26)
        battle.log = f"{attacker.name} rains down Overwhelming Odds!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def on_damage_dealt(self, attacker, defender, actual):
        if (attacker is not self.fighter or defender is None or actual <= 0
                or self.battle.ability is None or self.battle.ability.tag != "overwhelming_odds"):
            return
        set_status(defender, "armor_break", OO_ARMOR_BREAK_DURATION_S, amount=OO_ARMOR_BREAK_AMOUNT)
        set_status(defender, "burn", OO_BURN_DURATION_S)

    # ---- Duel: blink to melee range, guaranteed Scepter Strike follow-up --
    def _duel_basic_range(self, defender):
        """The SHORTER of Legion Commander's own basic_range and
        `defender`'s own (each still run through melee_range_bonus, same
        chain choose_ability itself reads) — both fighters sit rooted at
        this exact distance for the whole DUEL_DURATION_S window (neither
        can roam back into range), so picking Legion Commander's own range
        alone would strand a shorter-ranged opponent (e.g. Chaos Knight/
        Phantom Lancer's 100 vs her own 110) permanently out of its own
        melee_range — never "ready" in choose_ability (see combat_
        resolution.py's basic_ready check), a one-sided beatdown instead of
        the mutual slugfest this ultimate promises. A ranged opponent
        (melee_range=None) has no such ceiling, so Legion Commander's own
        range wins by default."""
        battle = self.battle
        lc_range = self.fighter.abilities["basic"].melee_range
        for plugin in battle.plugins:
            lc_range = plugin.melee_range_bonus(self.fighter, lc_range)
        opp_range = defender.abilities["basic"].melee_range
        for plugin in battle.plugins:
            opp_range = plugin.melee_range_bonus(defender, opp_range)
        shortest = min(r for r in (lc_range, opp_range) if r is not None)
        # Landing at EXACTLY the shorter side's own max range sits right on
        # that fighter's own basic_ready boundary (combat_resolution.py's
        # `distance <= melee_range`) — a hair of float rounding from the two
        # normalize()/subtract chains between here and the final blink
        # position is enough to land the real distance a few ULPs *past*
        # melee_range, permanently failing <= for that one fighter for the
        # rest of the rooted lockdown (it can never roam closer to fix it)
        # even though every number involved was "meant" to be exactly equal.
        # A tiny inward margin costs nothing visually and guarantees both
        # sides read as in range regardless of which way the rounding falls.
        # Returned as a center distance: melee_range is measured edge to
        # edge (see entities.melee_size_offset), so the two bodies' own size
        # is added back on for the actual blink position.
        return max(0.0, shortest - DUEL_RANGE_MARGIN) + melee_size_offset(self.fighter, defender)

    def strike_point_override(self, attacker, ability):
        if attacker is not self.fighter or ability.tag != "duel":
            return None
        battle = self.battle
        defender = self._opponent()
        # Only a first approximation for the teleport's own vanish/reappear
        # animation (still using the pre-cast atk_dir/defender_start
        # snapshot from try_start_attack) — defender isn't rooted yet at this
        # point (that only happens once apply_tag_effects itself fires, at
        # the "strike" phase further into this same cast), so it's free to
        # keep roaming for the ~0.2s of "vanish"+"reappear" still ahead.
        # apply_tag_effects re-snaps Legion Commander to defender's actual
        # live position right as the lockdown lands, overriding whatever
        # guess lands here — see its own comment for why that final snap is
        # the one that actually has to be exact.
        basic_range = self._duel_basic_range(defender)
        dest = battle.defender_start - battle.atk_dir * basic_range
        dest.x = max(BOUND_LEFT, min(BOUND_RIGHT, dest.x))
        dest.y = max(BOUND_TOP, min(BOUND_BOTTOM, dest.y))
        return dest

    def forced_ability(self, attacker):
        if attacker is not self.fighter or self._forced_basic is None:
            return None
        ability = self._forced_basic
        self._forced_basic = None
        if not self.battle.can_basic_attack(attacker):
            return None  # LC got stunned/disarmed in the meantime — skip, don't force through real CC
        return ability

    def cooldown_bonus(self, attacker, ability, cooldown):
        """While Duel is up, crush *either* fighter's basic-attack cooldown
        down to DUEL_BASIC_COOLDOWN_S — called for both attacker and
        defender's own basics since cooldown_bonus is a chain hook run on
        every plugin regardless of whose ability just fired (see
        combat_resolution.try_start_attack). Never raises it: a character whose
        own basic cooldown is already under 0.5s keeps its own faster pace."""
        if ability.kind == "basic" and self._duel_timer > 0:
            return min(cooldown, DUEL_BASIC_COOLDOWN_S)
        return cooldown

    # ---- tag effects --------------------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "press_the_attack":
            # Status: none directly for the cleanse/heal (both one-shot
            # actions, see status_library.cleanse/heal) — move_speed_up is
            # the only timed status this leaves behind.
            cleanse(attacker)
            healed = heal(attacker, PRESS_HEAL_PCT)
            set_status(attacker, "move_speed_up", PRESS_SPEED_DURATION_S, pct=PRESS_SPEED_PCT)
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, f"+{round(healed)}", GOLD])
            battle.log = f"{attacker.name} presses the attack — cleansed, healed, and faster!"
            battle.add_ring(attacker.pos, 90, 0.45, LEGION_CRIMSON, width=4)
            emit_spark_burst(battle.fx, attacker.pos, GOLD, count=18)
        elif tag == "moment_of_courage":
            # Status: lifesteal (generic, flat 100% of whatever damage
            # actually lands — see core/status_library.py)
            set_status(attacker, "lifesteal", MOC_LIFESTEAL_DURATION_S)
            attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 60, -0.6, 255, "COURAGE!", LEGION_CRIMSON])
            battle.log = f"{attacker.name} finds a Moment of Courage!"
            battle.add_ring(attacker.pos, 80, 0.4, LEGION_CRIMSON, width=4)
            emit_spark_burst(battle.fx, attacker.pos, LEGION_CRIMSON, count=16)
        elif tag == "duel":
            # Re-snap to defender's actual LIVE position right here, the
            # last possible instant before rooted (below) makes it
            # permanent for the whole DUEL_DURATION_S window: defender was
            # still free to roam through the "vanish"/"reappear" phases
            # this cast just played out (strike_point_override's own guess
            # ran before any of that, off a stale snapshot), so a fast
            # mover (Phantom Lancer/Vampire, ...) drifting well past the
            # intended basic_range in that ~0.2s was routine — stranding
            # both fighters out of each other's range for the rest of the
            # lockdown the instant it started, one guaranteed Scepter
            # Strike and then total silence for the remaining ~3s instead
            # of the mutual slugfest this ultimate promises.
            basic_range = self._duel_basic_range(defender)
            direction = defender.pos - attacker.pos
            if direction.length_squared() == 0:
                direction = pygame.Vector2(1, 0)
            atk_dir = direction.normalize()
            dest = defender.pos - atk_dir * basic_range
            dest.x = max(BOUND_LEFT, min(BOUND_RIGHT, dest.x))
            dest.y = max(BOUND_TOP, min(BOUND_BOTTOM, dest.y))
            attacker.pos = pygame.Vector2(dest)
            # apply_motion_frame's own flicker_slash branch re-asserts
            # `a.pos = battle.strike_point` on every remaining frame of this
            # same "strike" phase (it runs unconditionally, every frame,
            # regardless of damage_applied) — without also correcting
            # strike_point itself here, the very next frame would silently
            # snap Legion Commander straight back to the stale guess above.
            battle.strike_point = pygame.Vector2(dest)

            # Status: rooted + silenced on both sides — a straight slugfest
            # of basic attacks only (neither is in BLOCKS_BASIC, see
            # core/status_library.py), guaranteed to open with Legion
            # Commander's own Scepter Strike (see forced_ability) right where
            # she just blinked to.
            set_status(attacker, "rooted", DUEL_DURATION_S)
            set_status(attacker, "silenced", DUEL_DURATION_S)
            set_status(defender, "rooted", DUEL_DURATION_S)
            set_status(defender, "silenced", DUEL_DURATION_S)
            # Status: reflect — self only, for the duel's own duration.
            set_status(attacker, "reflect", DUEL_DURATION_S, pct=DUEL_REFLECT_PCT)
            self._duel_timer = DUEL_DURATION_S
            # Anchor attacker_start to the (re-snapped) landing spot — both
            # fighters are rooted for the whole duel window (above), so
            # neither actually moves from here regardless, and the
            # guaranteed Scepter Strike below dashes in from exactly this
            # spot once it fires next frame.
            battle.attacker_start = pygame.Vector2(dest)
            self._forced_basic = self.fighter.abilities["basic"]
            # Meter reset is generic now — see try_start_attack() in
            # core/combat_resolution.py.
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "DUEL!", LEGION_CRIMSON])
            battle.log = f"{attacker.name} challenges {defender.name} to a Duel!"
            battle.flash_timer = max(battle.flash_timer, 0.4)
            battle.add_screen_shake(18, 0.28)
            battle.add_ring(defender.pos, 150, 0.6, LEGION_CRIMSON, width=6)
            emit_spark_burst(battle.fx, defender.pos, LEGION_CRIMSON, count=24)

    # ---- presentation -------------------------------------------------------
    def impact_particles(self, pos, count):
        emit_explosion(self.battle.fx, pos, LEGION_CRIMSON, count=count)
        return True

    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.motion == "swarm"):
            return False
        sprite = flame_arrow_sprite(battle.ability.swarm_size)
        for proj in battle.swarm_projectiles:
            if not proj["alive"] or proj["delay"] > 0:
                continue  # not yet armed — stays invisible until launched
            img = rotate_to_dir(sprite, proj["vel"])
            screen.blit(img, img.get_rect(center=(round(proj["pos"].x), round(proj["pos"].y))))
        return True

    def draw_fx(self, screen, shake_x):
        """The scepter: rested low when idle, swung for Scepter Strike
        (whether picked normally or forced as Duel's guaranteed follow-up —
        both are the exact same ability/animation), hidden in lockstep with
        Legion Commander's own sprite during Duel's teleport (see
        render.py's is_flicker_hidden)."""
        battle, lc = self.battle, self.fighter
        if not lc.is_alive():
            return

        hidden = (
            battle.mode == "attack" and battle.attacker is lc
            and battle.motion == "flicker_slash" and battle.current_phase in ("vanish", "reappear")
        )
        if hidden:
            return

        img = battle.weapons["scepter"]
        p = lc.pos + pygame.Vector2(shake_x, 0)

        active = battle.mode == "attack" and battle.attacker is lc and battle.ability.name == "Scepter Strike"
        if not active:
            battle.weapon_trail.clear()
            draw_rotated(screen, img, p + IDLE_OFFSET, IDLE_ANGLE)
            return

        phase, t = battle.current_phase, battle.phase_t
        tip_reach = AVATAR_R + 16
        # "slash" motion's own phase names (windup/slash1/slash2/return —
        # see MOTIONS["slash"] in core/motions.py), not "strike"/"impact" —
        # those never fire, since RESOLVE_PHASE only ever calls this
        # "slash2".
        if phase == "windup":
            reach, extra = 12, -40 * ease_out(t)
        elif phase == "slash1":
            reach = tip_reach
            extra = -40 + 40 * ease_in(t)
        elif phase == "slash2":
            reach = tip_reach
            extra = 0
        else:  # return
            reach = tip_reach - (tip_reach - 10) * ease_out(t)
            extra = 0
        angle = weapon_angle(battle.atk_dir, extra)
        pos = p + battle.atk_dir * reach

        if phase in ("slash1", "slash2"):
            battle.weapon_trail.append((img, pygame.Vector2(pos), angle))
            if len(battle.weapon_trail) > 6:
                battle.weapon_trail.pop(0)
            for i, (t_img, t_pos, t_angle) in enumerate(battle.weapon_trail[:-1]):
                fade = int(90 * (i + 1) / len(battle.weapon_trail))
                draw_rotated(screen, t_img, t_pos, t_angle, alpha=fade)
        else:
            battle.weapon_trail.clear()

        draw_rotated(screen, img, pos, angle)

        # The painted slash flipbook + impact pop, drawn on top of the
        # scepter itself (same tip position) — the actual connecting hit
        # only ever lands on slash2 (RESOLVE_PHASE["slash"] == "slash2").
        if phase == "slash2":
            draw_slash_fx(screen, pos, battle.atk_dir, t, size=100)
            draw_starburst(screen, pos, WHITE, size=28, fade=1 - t)
            draw_expanding_ring(screen, pos, 36 * t, LEGION_CRIMSON, width=4)
