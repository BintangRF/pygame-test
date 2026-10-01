"""Pac-Man plugin: the Waka Waka passive (a maze floor of pellets he eats —
never refilled — and the power-up for clearing every last one: a frightened
opponent and the 200 -> 400 -> 800 -> 1600 bite chain), every tag's effect
(Bonus Fruit bouncing round the maze, the Ghost Gang's scatter-then-chase
hunt, the Game Over? fake-out, Warp Tunnel's wrap-around, Super Pac-Man's
giant hunt), and all of his presentation — every sprite cut from the arcade
sheet (sprite.py): his mouth frames, his death animation, the giant
intermission Pac-Man, all four ghosts, their eyes, Blinky's torn and patched
cloak from the intermissions, the bonus fruits and the score numbers.
Pellets are plain dots drawn under the fighters (via an invisible zone's
zone_decorate).

Passive: Waka Waka — one maze of PELLET_SPACING-spaced pellets per match,
never refilled. He moves like every other fighter (the plain bounce roam —
nothing steers him); pellets within PELLET_MAGNET_R of him slide toward him
instead (RUSH_MAGNET_R during Waka Rush), and he eats whatever reaches him.
Every PELLETS_PER_POWER pellets add one POWER (the ultimate's meter) and heal
PELLET_HEAL_PCT; each of the four bigger corner Power Pellets is worth a
POWER on its own.

Clearing the maze — every last pellet — powers him up, once per match
(MAZE CLEAR): the opponent is frightened (the generic "feared" status, plus
"slowed" — frightened ghosts are slow, so he can catch it), and for
CLEAR_POWER_S he's faster, casts only Chomp, Chomp reaches farther, and
each bite chains bigger (CHAIN_MULT, CHAIN_SCORES). He hunts through his
attacks' own dash, never by bending his roam."""

import math
import random

import pygame

from ...core.constants import (
    BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GREEN, PACMAN_YELLOW, WHITE,
)
from ...core.entities import Zone, set_status
from ...core.glow import add_dot
from ...core.particles import emit_dark, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .sprite import big_pac, death, direction_name, eyes, fright, fruit, ghost, intermission, pac, score

# ---- passive: Waka Waka -----------------------------------------------------
PELLET_COLOR = (255, 190, 175)
PELLET_SPACING = 50
PELLET_REACH = 0.8  # share of his hitbox radius a pellet must be within to be eaten
# Pellets this close slide toward him (he never steers toward them himself).
PELLET_MAGNET_R = 120
RUSH_MAGNET_R = 170
PELLET_MAGNET_SPEED = 260
PELLETS_PER_POWER = 3
PELLET_HEAL_PCT = 0.02
# Powered up, Chomp reaches this much farther (its melee_dash closes the gap).
POWER_REACH_BONUS = 60
# Maze clear: the once-a-match power-up for eating every pellet.
CLEAR_POWER_S = 8.0
CLEAR_FEAR_S = 2.0
POWER_SPEED = 0.4
FRIGHT_SLOW = 0.5
# Bites while powered (Chomp, Super Pac-Man's bites): each one in a row hits
# harder and scores higher, like eating ghost after ghost.
CHAIN_MULT = (1.25, 1.5, 1.75, 2.0)
CHAIN_SCORES = (200, 400, 800, 1600)

# ---- Bonus Fruit --------------------------------------------------------------------
# (fruit, score, damage mult, effect) — every cast moves one fruit along.
FRUITS = (
    ("cherry", 100, 1.4, None),
    ("strawberry", 300, 1.5, "heal"),
    ("orange", 500, 1.6, "slow"),
    ("apple", 700, 1.7, "weaken"),
    ("melon", 1000, 1.9, "poison"),
    ("galaxian", 2000, 2.2, "stun"),
    ("bell", 3000, 2.5, "silence"),
    ("key", 5000, 3.0, "armor_break"),
)
FRUIT_SPEED = 230
FRUIT_LIFE_S = 8.0
FRUIT_BLINK_S = 1.2
# Pac-Man can't snap up his own fruit the instant it's thrown.
FRUIT_GRACE_S = 0.6
FRUIT_EAT_HEAL_PCT = 0.06
FRUIT_SCALE = 1.5

# ---- Ghost Gang ----------------------------------------------------------------------
GHOSTS = ("blinky", "pinky", "inky", "clyde")
# Arcade scatter corners: Blinky top-right, Pinky top-left, Inky bottom-right,
# Clyde bottom-left.
SCATTER_CORNER = {
    "blinky": (BOUND_RIGHT, BOUND_TOP), "pinky": (BOUND_LEFT, BOUND_TOP),
    "inky": (BOUND_RIGHT, BOUND_BOTTOM), "clyde": (BOUND_LEFT, BOUND_BOTTOM),
}
GANG_SCATTER_S = 0.9
GANG_LIFE_S = 6.0
GHOST_SPEED = 210
GHOST_EYES_SPEED = 380
GHOST_HITS = 2
GHOST_HIT_CD_S = 0.6
GHOST_MULT = {"blinky": 0.9, "pinky": 0.7, "inky": 0.7, "clyde": 0.7}
GHOST_COLOR = {"blinky": (255, 60, 60), "pinky": (255, 170, 230), "inky": (60, 230, 255), "clyde": (255, 175, 70)}
# Blinky's exit is the intermission gag: his cloak snags on a nail and tears,
# and he crawls home naked dragging it — patched up for every later release.
SNAG_S = 0.45
NAKED_SPEED = 120
NAKED_MAX_S = 3.0
GHOST_SCALE = 1.5

# ---- Game Over? --------------------------------------------------------------------
# He "dies" (the death animation, untargetable), then pops up behind the
# opponent and chomps it for AMBUSH_MULT.
AMBUSH_BEHIND_PX = 55
AMBUSH_MULT = 1.8

# ---- Warp Tunnel -------------------------------------------------------------------
WARP_SPEED = 0.5
WARP_SPEED_S = 1.2

# ---- ultimate: Super Pac-Man ---------------------------------------------------------
SUPER_S = 4.0
SUPER_FEAR_S = 2.0
SUPER_SPEED = 0.6
SUPER_DR = 0.3
SUPER_BITE_MULT = 1.0
SUPER_BITE_CD_S = 0.8
SUPER_SCALE = 1.25
# Super Pac-Man's Chomp lunges from farther (its normal cooldown still applies).
SUPER_REACH_BONUS = 100

# ---- presentation -----------------------------------------------------------------------
CHOMP_HZ = 12
MOUTH_CYCLE = ("open", "half", "closed", "half")
POPUP_S = 0.9
DEATH_FRAME_S = 0.11


def _clamp_point(p):
    return pygame.Vector2(max(BOUND_LEFT, min(BOUND_RIGHT, p.x)), max(BOUND_TOP, min(BOUND_BOTTOM, p.y)))


def _nearest_wall(p):
    """(point on the nearest arena wall, the matching point on the opposite
    wall, the direction into that nearest wall — which is also the way he
    keeps going once he wraps out of the opposite one)."""
    walls = [
        (p.x - BOUND_LEFT, pygame.Vector2(BOUND_LEFT, p.y), pygame.Vector2(BOUND_RIGHT, p.y), pygame.Vector2(-1, 0)),
        (BOUND_RIGHT - p.x, pygame.Vector2(BOUND_RIGHT, p.y), pygame.Vector2(BOUND_LEFT, p.y), pygame.Vector2(1, 0)),
        (p.y - BOUND_TOP, pygame.Vector2(p.x, BOUND_TOP), pygame.Vector2(p.x, BOUND_BOTTOM), pygame.Vector2(0, -1)),
        (BOUND_BOTTOM - p.y, pygame.Vector2(p.x, BOUND_BOTTOM), pygame.Vector2(p.x, BOUND_TOP), pygame.Vector2(0, 1)),
    ]
    _, near, far, outward = min(walls, key=lambda w: w[0])
    return near, far, outward


def _centred_line(lo, hi):
    """Evenly spaced PELLET_SPACING points spanning lo..hi, centred."""
    n = int((hi - lo) // PELLET_SPACING) + 1
    start = (lo + hi) / 2 - (n - 1) * PELLET_SPACING / 2
    return [round(start + i * PELLET_SPACING) for i in range(n)]


def _cast_progress(phase, t):
    """0-1 progress through a "cast" motion's windup + channel."""
    return t * 0.33 if phase == "windup" else 0.33 + t * 0.67


class PacmanPlugin(CharacterPlugin):
    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self._clock = 0.0
        self._zone = None
        self.pellets = []
        # a grid centred in the arena, PELLET_SPACING apart
        xs = _centred_line(BOUND_LEFT, BOUND_RIGHT)
        ys = _centred_line(BOUND_TOP, BOUND_BOTTOM)
        corners = {(xs[0], ys[0]), (xs[-1], ys[0]), (xs[0], ys[-1]), (xs[-1], ys[-1])}
        for x in xs:
            for y in ys:
                self.pellets.append({"pos": pygame.Vector2(x, y), "power": (x, y) in corners, "eaten": None})
        self._dots = 0
        self._cleared = False
        self._power_t = 0.0
        self._super_t = 0.0
        self._bite_cd = 0.0
        self._chain = 0
        self._fright_until = -1.0
        self._fruit_level = 0
        self._fruits = []
        self._ghosts = []
        self._blinky_patched = False
        self._popups = []
        self._warp = None
        self._fake = None
        self._ambush = False
        self._ambush_strike = False
        self._dead_at = None

    def _opponent(self):
        b = self.battle
        return b.f2 if self.fighter is b.f1 else b.f1

    def _powered(self):
        return self._power_t > 0 or self._super_t > 0

    def _popup(self, value, pos):
        self._popups.append({"img": score(value, 1.5), "pos": pygame.Vector2(pos), "born": self._clock})

    def _heal(self, pct):
        p = self.fighter
        before = p.hp
        p.hp = min(p.max_hp, p.hp + p.max_hp * pct)
        if p.hp - before >= 1:
            self.battle.floaters.append([p.pos.x, p.pos.y - 40, -0.5, 230, f"+{round(p.hp - before)}", GREEN])

    def _frighten(self, seconds):
        battle, p = self.battle, self.fighter
        enemy = self._opponent()
        if enemy.is_alive() and not battle.is_invulnerable(enemy):
            set_status(enemy, "feared", seconds, source=pygame.Vector2(p.pos))
            # frightened ghosts are slow — so he can actually catch it
            set_status(enemy, "slowed", seconds, pct=FRIGHT_SLOW)
            self._fright_until = self._clock + seconds

    def _can_hit(self, target):
        b = self.battle
        return (target is not None and target.is_alive() and not b.is_invulnerable(target)
                and not b.is_vanished(target) and not b.is_untargetable(target))

    def _strike(self, target, mult, color, knock_dir):
        battle, p = self.battle, self.fighter
        dmg = round(p.atk * mult * battle.status_outgoing_multiplier(p))
        actual = battle.deal_damage(p, target, dmg)
        target.hit_flash = target.hit_flash_max = 0.1
        target.hit_flash_color, target.hit_flash_heavy, target.hit_flash_crit = WHITE, False, False
        target.visual_recoil += knock_dir * 5
        target.shake = max(target.shake, 10)
        battle.floaters.append([target.pos.x + random.uniform(-8, 8), target.pos.y - 40, -0.6, 255,
                                f"-{actual}", color])
        for pl in battle.plugins:
            pl.on_damage_dealt(p, target, actual)
        return actual

    def _chain_bonus(self, pos):
        """The next link of the powered-up bite chain: its damage multiplier
        (and its score popping up over `pos`)."""
        i = self._chain
        self._chain = min(len(CHAIN_MULT) - 1, self._chain + 1)
        self._popup(CHAIN_SCORES[i], pos)
        return CHAIN_MULT[i]

    # ---- passive: Waka Waka -----------------------------------------------------
    def _eat_pellets(self, dt):
        battle, p = self.battle, self.fighter
        reach = p.hitbox_r * PELLET_REACH
        state = battle.attacks.get(p)
        magnet = RUSH_MAGNET_R if state is not None and state.ability.tag == "pac_rush" else PELLET_MAGNET_R
        for pel in self.pellets:
            if pel["eaten"] is not None:
                continue
            pull = p.pos - pel["pos"]
            dist = pull.length()
            if reach < dist <= magnet:
                pel["pos"] += pull / dist * min(dist, PELLET_MAGNET_SPEED * dt)
                dist = (p.pos - pel["pos"]).length()
            if dist > reach:
                continue
            pel["eaten"] = self._clock
            if pel["power"]:
                p.meter = min(p.meter_max, p.meter + p.meter_gain)
                battle.add_ring(p.pos, 50, 0.3, PACMAN_YELLOW, width=2)
            else:
                self._dots += 1
                if self._dots >= PELLETS_PER_POWER:
                    self._dots = 0
                    p.meter = min(p.meter_max, p.meter + p.meter_gain)
                    self._heal(PELLET_HEAL_PCT)
        if not self._cleared and all(pel["eaten"] is not None for pel in self.pellets):
            self._maze_clear()

    def _maze_clear(self):
        """Every pellet's gone: the once-a-match power-up."""
        battle, p = self.battle, self.fighter
        self._cleared = True
        self._power_t = CLEAR_POWER_S
        self._chain = 0
        set_status(p, "move_speed_up", CLEAR_POWER_S, pct=POWER_SPEED)
        self._frighten(CLEAR_FEAR_S)
        battle.add_ring(p.pos, 140, 0.6, PACMAN_YELLOW, width=5)
        battle.flash_timer = max(battle.flash_timer, 0.15)
        battle.floaters.append([p.pos.x, p.pos.y - 55, -0.5, 255, "MAZE CLEAR!", PACMAN_YELLOW])
        battle.log = f"{p.name} clears the maze — POWER UP! {self._opponent().name} is frightened!"

    def ammo_ready(self, attacker, ability):
        """Powered up he only hunts: the maze-clear power-up or Super Pac-Man
        leaves him nothing but Chomp."""
        if attacker is not self.fighter or not self._powered():
            return True
        return ability.tag == "pac_chomp"

    def melee_range_bonus(self, attacker, melee_range):
        if attacker is not self.fighter or melee_range is None:
            return melee_range
        if self._super_t > 0:
            return melee_range + SUPER_REACH_BONUS
        if self._power_t > 0:
            return melee_range + POWER_REACH_BONUS
        return melee_range

    def forced_ability(self, attacker):
        """Game Over?'s ambush: the instant he pops back up, Chomp."""
        if attacker is not self.fighter or not self._ambush:
            return None
        self._ambush = False
        if not self.battle.can_basic_attack(attacker):
            return None
        self._ambush_strike = True
        return attacker.abilities["basic"]

    def zone_style(self, zone):
        return PACMAN_YELLOW, "Maze"

    def zone_decorate(self, screen, zone):
        """The pellets, drawn under the fighters (this plugin's own maze
        zone is an invisible zero-radius one parked off-screen — it's only
        here for this draw hook)."""
        blink = int(self._clock * 4) % 2 == 0
        for pel in self.pellets:
            if pel["eaten"] is not None:
                continue
            x, y = round(pel["pos"].x), round(pel["pos"].y)
            if pel["power"]:
                if blink:
                    pygame.draw.circle(screen, PELLET_COLOR, (x, y), 7)
            else:
                pygame.draw.rect(screen, PELLET_COLOR, (x - 2, y - 2, 4, 4))

    def passive_gauge(self, fighter):
        if fighter is not self.fighter:
            return None
        left = sum(1 for pel in self.pellets if pel["eaten"] is None)
        if self._super_t > 0:
            return self._super_t / SUPER_S, "SUPER PAC-MAN!", PACMAN_YELLOW
        if self._power_t > 0:
            return self._power_t / CLEAR_POWER_S, "POWER!", PACMAN_YELLOW
        if self._cleared:
            return 1.0, "MAZE CLEARED", PACMAN_YELLOW
        return 1 - left / len(self.pellets), f"MAZE {left} left", PACMAN_YELLOW

    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is not self.fighter or ability.tag != "pac_chomp":
            return dmg, note
        if self._ambush_strike:
            self._ambush_strike = False
            dmg = round(dmg * AMBUSH_MULT)
            note += " [SURPRISE]"
            self._popup(1600, defender.pos)
        if self._powered():
            mult = self._chain_bonus(defender.pos) * (SUPER_BITE_MULT if self._super_t > 0 else 1.0)
            dmg = round(dmg * mult)
            note += " [SUPER]" if self._super_t > 0 else " [POWER]"
        return dmg, note

    # ---- skills -----------------------------------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag, p = self.battle, ability.tag, self.fighter
        if tag == "pac_fruit":
            self._throw_fruit()
        elif tag == "pac_ghost":
            self._release_gang()
        elif tag == "pac_warp":
            p.meter = min(p.meter_max, p.meter + p.meter_gain)
        elif tag == "pac_super":
            self._super_t = SUPER_S
            self._chain = 0
            set_status(p, "move_speed_up", SUPER_S, pct=SUPER_SPEED)
            set_status(p, "damage_reduction", SUPER_S, pct=SUPER_DR)
            self._frighten(SUPER_FEAR_S)
            battle.add_ring(p.pos, 160, 0.6, PACMAN_YELLOW, width=6)
            battle.flash_timer = max(battle.flash_timer, 0.15)
            battle.floaters.append([p.pos.x, p.pos.y - 60, -0.5, 255, "SUPER PAC-MAN!", PACMAN_YELLOW])
            battle.log = f"{p.name} turns into Super Pac-Man — {defender.name} runs for its life!"

    # -- Bonus Fruit --
    def _throw_fruit(self):
        """Bonus Fruit: this level's fruit bounces off round the maze, Ms.
        Pac-Man style — bonking the opponent if it runs into it, or eaten
        by Pac-Man himself for a heal and a POWER if he gets there first.
        Every cast moves the fruit one level along (cherry ... key)."""
        battle, p = self.battle, self.fighter
        name, value, mult, effect = FRUITS[self._fruit_level]
        self._fruit_level = min(len(FRUITS) - 1, self._fruit_level + 1)
        ang = random.uniform(0, math.tau)
        self._fruits.append({"name": name, "value": value, "mult": mult, "effect": effect, "t": 0.0,
                             "pos": pygame.Vector2(p.pos),
                             "vel": pygame.Vector2(math.cos(ang), math.sin(ang)) * FRUIT_SPEED})
        battle.log = f"A {name} bounces into the maze!"

    def _tick_fruits(self, dt):
        battle, p = self.battle, self.fighter
        enemy = self._opponent()
        keep = []
        for fr in self._fruits:
            fr["t"] += dt
            if fr["t"] >= FRUIT_LIFE_S:
                continue
            fr["pos"] += fr["vel"] * dt
            if not BOUND_LEFT <= fr["pos"].x <= BOUND_RIGHT:
                fr["vel"].x *= -1
            if not BOUND_TOP <= fr["pos"].y <= BOUND_BOTTOM:
                fr["vel"].y *= -1
            fr["pos"] = _clamp_point(fr["pos"])
            if (enemy.pos - fr["pos"]).length() <= enemy.hitbox_r + 12 and self._can_hit(enemy):
                self._strike(enemy, fr["mult"], PACMAN_YELLOW, fr["vel"].normalize())
                self._fruit_effect(enemy, fr["effect"])
                self._popup(fr["value"], enemy.pos)
                emit_spark_burst(battle.fx, enemy.pos, PACMAN_YELLOW, count=10)
                battle.log = f"{enemy.name} runs into a {fr['name']} — {fr['value']} points!"
                continue
            if fr["t"] >= FRUIT_GRACE_S and p.is_alive() and (p.pos - fr["pos"]).length() <= p.hitbox_r:
                self._heal(FRUIT_EAT_HEAL_PCT)
                p.meter = min(p.meter_max, p.meter + p.meter_gain)
                self._popup(fr["value"], p.pos)
                battle.log = f"{p.name} eats the {fr['name']} — {fr['value']} points!"
                continue
            keep.append(fr)
        self._fruits = keep

    def _fruit_effect(self, target, effect):
        if effect == "heal":
            self._heal(0.05)
        elif effect == "slow":
            set_status(target, "slowed", 2.0, pct=0.35)
        elif effect == "weaken":
            set_status(target, "attack_down", 3.0, pct=0.25)
        elif effect == "poison":
            set_status(target, "poison", 3.0)
        elif effect == "stun":
            set_status(target, "stunned", 0.6)
        elif effect == "silence":
            set_status(target, "silenced", 1.5)
        elif effect == "armor_break":
            set_status(target, "armor_break", 4.0, amount=10)

    # -- Ghost Gang --
    def _release_gang(self):
        battle, p = self.battle, self.fighter
        for name in GHOSTS:
            corner = pygame.Vector2(SCATTER_CORNER[name])
            self._ghosts.append({"name": name, "pos": pygame.Vector2(p.pos), "vel": pygame.Vector2(0, -1),
                                 "t": 0.0, "hits": 0, "cd": 0.0, "mode": "scatter", "mode_t": 0.0,
                                 "corner": corner, "wobble": random.uniform(0, 6)})
        emit_spark_burst(battle.fx, p.pos, WHITE, count=16)
        p.meter = min(p.meter_max, p.meter + p.meter_gain)
        battle.log = f"{p.name} lets the whole Ghost Gang out of the pen!"

    def _ghost_goal(self, g, enemy):
        """Where each ghost's own arcade chase logic sends it."""
        p, name = self.fighter, g["name"]
        if name == "blinky":
            return enemy.pos
        if name == "pinky":
            ahead = enemy.vel.normalize() if enemy.vel.length_squared() > 0 else pygame.Vector2(0, 0)
            return enemy.pos + ahead * 70
        if name == "inky":
            off = enemy.pos - p.pos
            off = off.normalize() if off.length_squared() > 0 else pygame.Vector2(1, 0)
            return enemy.pos + off.rotate(math.degrees(math.sin(g["t"] * 3 + g["wobble"]))) * 50
        # clyde: shy — closes in, then backs off to his corner once he's close
        return enemy.pos if (enemy.pos - g["pos"]).length() > 90 else g["corner"]

    def _tick_ghosts(self, dt):
        """The Ghost Gang: all four scatter to their own corners first, then
        switch to chase, each with its arcade logic (see _ghost_goal), biting
        up to GHOST_HITS times; then the eyes fly home — except Blinky, whose
        cloak snags on a nail and tears, leaving him to crawl home naked."""
        p = self.fighter
        enemy = self._opponent()
        keep = []
        for g in self._ghosts:
            g["t"] += dt
            g["mode_t"] += dt
            g["cd"] -= dt
            mode = g["mode"]
            done = g["hits"] >= GHOST_HITS or g["t"] >= GANG_LIFE_S or not enemy.is_alive()
            if mode in ("scatter", "chase") and done:
                mode = "snag" if g["name"] == "blinky" and not self._blinky_patched else "eyes"
                g["mode"], g["mode_t"] = mode, 0.0
            elif mode == "scatter" and g["mode_t"] >= GANG_SCATTER_S:
                g["mode"], g["mode_t"] = "chase", 0.0
                mode = "chase"
            if mode == "snag":
                if g["mode_t"] >= SNAG_S:
                    g["mode"], g["mode_t"] = "naked", 0.0
                    self._blinky_patched = True
                keep.append(g)
                continue
            if mode == "scatter":
                goal, speed = g["corner"], GHOST_SPEED
            elif mode == "chase":
                goal, speed = self._ghost_goal(g, enemy), GHOST_SPEED
            elif mode == "naked":
                goal, speed = p.pos, NAKED_SPEED
            else:  # eyes
                goal, speed = p.pos, GHOST_EYES_SPEED
            step = goal - g["pos"]
            if mode in ("eyes", "naked") and (step.length() < 16 or g["mode_t"] > NAKED_MAX_S):
                continue
            if step.length_squared() > 0:
                g["vel"] = step.normalize()
                g["pos"] += g["vel"] * min(step.length(), speed * dt)
            if (mode in ("scatter", "chase") and g["cd"] <= 0
                    and (enemy.pos - g["pos"]).length() <= enemy.hitbox_r + 14 and self._can_hit(enemy)):
                g["cd"] = GHOST_HIT_CD_S
                g["hits"] += 1
                self._ghost_hit(g, enemy)
            keep.append(g)
        self._ghosts = keep

    def _ghost_hit(self, g, enemy):
        name = g["name"]
        self._strike(enemy, GHOST_MULT[name], GHOST_COLOR[name], g["vel"])
        if name == "pinky":
            set_status(enemy, "slowed", 1.5, pct=0.35)
        elif name == "inky":
            set_status(enemy, "blind", 2.0, chance=0.3)
        elif name == "clyde":
            set_status(enemy, "attack_speed_down", 2.0, pct=0.25)
        emit_spark_burst(self.battle.fx, enemy.pos, GHOST_COLOR[name], count=8)

    # -- per-frame cast paths --
    def attack_frame(self, attacker, ability, phase, t):
        if attacker is not self.fighter:
            return
        state = self.battle._current
        if ability.tag == "pac_warp":
            self._warp_frame(state, phase, t)
        elif ability.tag == "pac_fake":
            self._fake_frame(state, phase, t)

    def _fake_frame(self, state, phase, t):
        """Game Over?: play dead (the death animation, untargetable — his
        opponent's attacks find nothing), then pop back up right behind the
        opponent and chomp it (see forced_ability/outgoing_damage)."""
        battle, p = self.battle, self.fighter
        if self._fake is None or self._fake["state"] is not state:
            self._fake = {"state": state, "popped": False}
            battle.floaters.append([p.pos.x, p.pos.y - 55, -0.4, 255, "GAME OVER?", WHITE])
        set_status(p, "untargetable", 0.08)
        if phase == "release" and not self._fake["popped"]:
            self._fake["popped"] = True
            enemy = state.defender if state.defender is not None else self._opponent()
            away = enemy.pos - p.pos
            away = away.normalize() if away.length_squared() > 0 else pygame.Vector2(1, 0)
            dest = _clamp_point(enemy.pos + away * AMBUSH_BEHIND_PX)
            p.pos = pygame.Vector2(dest)
            battle.attacker_start = pygame.Vector2(dest)
            emit_spark_burst(battle.fx, dest, PACMAN_YELLOW, count=14)
            self._ambush = True
            battle.log = f"{p.name} was only pretending — SURPRISE!"

    def _warp_frame(self, state, phase, t):
        """Warp Tunnel, written over the planted "cast" position: slide into
        the nearest wall, shrinking away, then pop out of the opposite wall
        and run on into the arena."""
        battle, p = self.battle, self.fighter
        if self._warp is None or self._warp["state"] is not state:
            near, far, outward = _nearest_wall(state.attacker_start)
            self._warp = {"state": state, "near": near, "far": far, "out": outward, "exited": False, "scale": 1.0}
        w = self._warp
        if phase in ("channel", "release"):
            set_status(p, "untargetable", 0.08)
        if phase == "windup":
            p.pos = state.attacker_start.lerp(w["near"], t * 0.5)
        elif phase == "channel":
            p.pos = state.attacker_start.lerp(w["near"], 0.5 + 0.5 * t)
            w["scale"] = 1.0 - 0.75 * t
        elif phase == "release":
            if not w["exited"]:
                w["exited"] = True
                emit_dark(battle.fx, w["near"], count=12, radius=18, color=PACMAN_YELLOW)
                emit_dark(battle.fx, w["far"], count=12, radius=18, color=PACMAN_YELLOW)
                set_status(p, "move_speed_up", WARP_SPEED_S, pct=WARP_SPEED)
                p.vel = w["out"] * max(p.vel.length(), 120)
                battle.log = f"{p.name} takes the warp tunnel!"
            p.pos = _clamp_point(w["far"] + w["out"] * 30 * t)
            w["scale"] = 0.25 + 0.75 * t

    # ---- per-frame ------------------------------------------------------------------
    def ambient_tick(self, dt):
        battle, p = self.battle, self.fighter
        self._clock += dt
        if self._zone is None:
            self._zone = Zone("maze", pygame.Vector2(-500, -500), 0, 1e9, p)
            battle.zones.append(self._zone)
        live = set(battle.attacks.values())
        if self._warp is not None and self._warp["state"] not in live:
            self._warp = None
        if self._fake is not None and self._fake["state"] not in live:
            self._fake = None
        self._power_t = max(0.0, self._power_t - dt)
        self._super_t = max(0.0, self._super_t - dt)
        self._bite_cd = max(0.0, self._bite_cd - dt)
        if p.is_alive():
            self._eat_pellets(dt)
            self._super_bite()
        self._tick_fruits(dt)
        self._tick_ghosts(dt)
        self._popups = [pp for pp in self._popups if self._clock - pp["born"] < POPUP_S]
        p.image = self._pose()

    def _super_bite(self):
        battle, p = self.battle, self.fighter
        enemy = self._opponent()
        if self._super_t <= 0 or self._bite_cd > 0 or p in battle.attacks:
            return
        if (enemy.pos - p.pos).length() > p.hitbox_r * SUPER_SCALE + enemy.hitbox_r + 12 or not self._can_hit(enemy):
            return
        self._bite_cd = SUPER_BITE_CD_S
        aim = enemy.pos - p.pos
        aim = aim.normalize() if aim.length_squared() > 0 else pygame.Vector2(1, 0)
        self._strike(enemy, SUPER_BITE_MULT * self._chain_bonus(enemy.pos), PACMAN_YELLOW, aim)
        battle.add_screen_shake(4, 0.1)

    # ---- presentation: sprite ----------------------------------------------------------
    def _pose(self):
        battle, p = self.battle, self.fighter
        p.ring_scale = 1.0  # the outer ring follows his size; only the grown/shrunk poses below change it
        if not p.is_alive():
            if self._dead_at is None:
                self._dead_at = self._clock
            i = int((self._clock - self._dead_at) / DEATH_FRAME_S)
            if i < 10:
                return death(i)
            if i < 13:
                return death("spark")
            return pygame.Surface((1, 1), pygame.SRCALPHA)
        state = battle.attacks.get(p)
        heading = state.atk_dir if state is not None else p.vel
        facing = direction_name(heading)
        if state is not None and state.ability.tag == "pac_fake":
            if state.current_phase in ("windup", "channel"):
                return death(min(9, int(_cast_progress(state.current_phase, state.phase_t) * 10)))
            if state.phase_t < 0.4:
                return death("spark")
        if any(n in p.statuses for n in ("stunned", "frozen", "asleep", "rooted", "curse")):
            return pac(facing, "closed")
        hz = CHOMP_HZ * (1.6 if state is not None or self._powered() else 1.0)
        mouth = MOUTH_CYCLE[int(self._clock * hz) % 4] if p.vel.length_squared() > 1 or state else "half"
        if self._super_t > 0:
            img = big_pac(facing, mouth, SUPER_SCALE)
            p.ring_scale = img.get_bounding_rect().height / pac(facing, "half").get_bounding_rect().height
            return img
        if self._warp is not None and state is not None and state.ability.tag == "pac_warp":
            scale = round(self._warp["scale"] * 10) / 10
            p.ring_scale = scale
            return pac(facing, mouth, scale=scale)
        return pac(facing, mouth)

    # ---- presentation: fx -------------------------------------------------------------
    def draw_fx(self, screen, shake_x):
        p = self.fighter
        offset = pygame.Vector2(shake_x, 0)
        frame = int(self._clock * 8) % 2
        if self._powered() and p.is_alive():
            add_dot(screen, p.pos + offset, 46 if self._super_t > 0 else 34, PACMAN_YELLOW,
                    0.35 + 0.15 * math.sin(self._clock * 12))
        for fr in self._fruits:
            if fr["t"] > FRUIT_LIFE_S - FRUIT_BLINK_S and int(self._clock * 10) % 2:
                continue  # blinking out
            img = fruit(fr["name"], FRUIT_SCALE)
            pos = fr["pos"] + offset
            screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))
        for g in self._ghosts:
            self._draw_ghost(screen, g, frame, offset)
        enemy = self._opponent()
        left = self._fright_until - self._clock
        if left > 0 and "feared" in enemy.statuses and enemy.is_alive():
            white = left < 0.6 and int(self._clock * 8) % 2 == 0
            img = fright(white, frame)
            pos = enemy.pos + offset - pygame.Vector2(0, enemy.hitbox_r + 30)
            screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))
        for pp in self._popups:
            age = (self._clock - pp["born"]) / POPUP_S
            img = pp["img"].copy()
            img.set_alpha(round(255 * (1 - age)))
            pos = pp["pos"] + offset - pygame.Vector2(0, 30 + 30 * age)
            screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))

    def _draw_ghost(self, screen, g, frame, offset):
        pos = g["pos"] + offset
        mode, d = g["mode"], direction_name(g["vel"])
        if mode == "eyes":
            img = eyes(d)
        elif mode == "snag":
            # the nail he caught his cloak on, the cloak tearing, a scrap flying off
            nail = intermission("nail", 3)
            screen.blit(nail, nail.get_rect(center=(round(pos.x) - 26, round(pos.y))))
            img = intermission(f"blinky_torn_{int(g['mode_t'] * 8) % 2}", GHOST_SCALE)
            scrap = intermission("torn_piece", GHOST_SCALE)
            fly = pos + pygame.Vector2(-20 - 60 * g["mode_t"], -40 * g["mode_t"])
            screen.blit(scrap, scrap.get_rect(center=(round(fly.x), round(fly.y))))
        elif mode == "naked":
            img = intermission(f"blinky_naked_{frame}", GHOST_SCALE)
            if g["vel"].x < 0:
                img = pygame.transform.flip(img, True, False)
        elif g["name"] == "blinky" and self._blinky_patched:
            img = intermission(f"blinky_patched_{frame}", GHOST_SCALE)
            if g["vel"].x > 0:
                img = pygame.transform.flip(img, True, False)
        else:
            img = ghost(g["name"], d, frame)
        screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))
