"""
Game entities — Character (a fighter), Zone (an arena effect area),
Clone (Vampire's decoy), plus small helpers shared by them.
"""

import pygame

from .constants import AVATAR_R, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, CLONE_BASE_ARMOR, CLONE_BASE_HP


def format_cd(ms):
    return "READY" if ms <= 0 else f"{ms / 1000:.1f}s"


def set_status(character, name, time_ms, **kwargs):
    """Apply or refresh a timed status effect (shield, vulnerability, curse, ...)."""
    s = character.statuses.get(name, {})
    s["time"] = time_ms
    s.update(kwargs)
    character.statuses[name] = s


def squash(obj, axis):
    """Squash & stretch on a wall bounce: compress along the impact axis,
    stretch along the other, like the DVD-logo bounce landing on its edge.
    Caller (battle_loop.py) eases scale_x/scale_y back to 1.0 each frame."""
    if axis == "x":
        obj.scale_x, obj.scale_y = 0.82, 1.18
    else:
        obj.scale_x, obj.scale_y = 1.18, 0.82


def bounce_move(obj, dt_ms, speed_mult=1.0):
    """Move obj by its velocity, bouncing off the arena bounds like a DVD logo."""
    dt = (dt_ms / 1000) * speed_mult
    obj.pos += obj.vel * dt
    if obj.pos.x < BOUND_LEFT:
        obj.pos.x = BOUND_LEFT
        obj.vel.x *= -1
        squash(obj, "x")
    elif obj.pos.x > BOUND_RIGHT:
        obj.pos.x = BOUND_RIGHT
        obj.vel.x *= -1
        squash(obj, "x")
    if obj.pos.y < BOUND_TOP:
        obj.pos.y = BOUND_TOP
        obj.vel.y *= -1
        squash(obj, "y")
    elif obj.pos.y > BOUND_BOTTOM:
        obj.pos.y = BOUND_BOTTOM
        obj.vel.y *= -1
        squash(obj, "y")


def resolve_character_collision(a, b):
    """Bump two roaming bodies (the two fighters, and/or Vampire's clone)
    apart when they overlap, bouncing them off each other like the DVD-logo
    wall bounce in bounce_move — same treat-as-a-circle-of-radius-AVATAR_R
    convention the arena bounds already use (see BOUND_* above), just
    against one another instead of the arena edge. Equal-mass elastic
    collision: the velocity component along the impact normal is swapped
    between the two, leaving the tangential component untouched."""
    delta = a.pos - b.pos
    dist = delta.length()
    min_dist = AVATAR_R * 2
    if dist >= min_dist:
        return
    normal = delta / dist if dist > 1e-4 else pygame.Vector2(1, 0)

    # Push both out of overlap, split evenly, then clamp back inside the
    # arena so the separation itself can never shove someone through a wall.
    overlap = min_dist - dist
    a.pos += normal * (overlap / 2)
    b.pos -= normal * (overlap / 2)
    for obj in (a, b):
        obj.pos.x = max(BOUND_LEFT, min(BOUND_RIGHT, obj.pos.x))
        obj.pos.y = max(BOUND_TOP, min(BOUND_BOTTOM, obj.pos.y))

    a_n = a.vel.dot(normal)
    b_n = b.vel.dot(normal)
    a.vel += normal * (b_n - a_n)
    b.vel += normal * (a_n - b_n)

    axis = "x" if abs(normal.x) >= abs(normal.y) else "y"
    squash(a, axis)
    squash(b, axis)


class Character:
    def __init__(self, key, name, era, hp, atk, color, abilities, meter_max, meter_gain, meter_name,
                 armor=0.0, move_speed_mult=1.0, nail_bullets_max=0):
        self.key = key  # "paladin" | "vampire" | "berserker" — identifies which special-case logic applies
        self.name = name
        self.era = era
        self.hp = hp
        self.max_hp = hp
        self.atk = atk
        self.color = color
        self.abilities = abilities  # {"basic":Ability, "skills":[Ability,...], "ultimate":Ability}
        self.armor = armor  # damage-reduction points on a 0-100 scale (30 = 30% less damage taken)
        self.move_speed_mult = move_speed_mult  # baseline roam-speed multiplier (on top of status effects)
        # Johnny's Nail Bullet ammo pool — every other fighter leaves this at
        # 0 (unused); basic attack and every skill cost 1 (see
        # johnny_ammo_ready/johnny_consume_nail_bullet in characters/johnny/ability.py)
        self.nail_bullets_max = nail_bullets_max
        self.nail_bullets = nail_bullets_max

        self.meter = 0
        self.meter_max = meter_max
        self.meter_gain = meter_gain
        self.meter_name = meter_name

        self.statuses = {}
        self.radiant_energy = 0.0

        self.image = None
        self.pos = pygame.Vector2()
        self.vel = pygame.Vector2()
        self.display_hp = float(hp)
        self.shake = 0.0
        self.spin_angle = 0.0

        # Visual-only knockback offset from being hit — decays each frame.
        # Never affects gameplay position/collision, only where it's drawn.
        self.visual_recoil = pygame.Vector2()

        # Damage-taken sprite flash: hit_flash counts down from hit_flash_max
        # (set by ImpactFXMixin.apply_impact); heavy/ultimate hits go
        # white->red instead of a plain white->normal fade (see render.py).
        self.hit_flash = 0.0
        self.hit_flash_max = 0.0
        self.hit_flash_heavy = False

        # Squash & stretch — set by entities.squash() on a wall bounce and by
        # ImpactFXMixin.apply_impact on a landed hit; eased back to 1.0 each
        # frame in battle_loop.py.
        self.scale_x = 1.0
        self.scale_y = 1.0

        # Visual-only fade for the "vanished" status (Phantom Lancer's
        # Doppelganger) — eased toward fully transparent (0) while vanished
        # and back to full otherwise in battle_loop.py's update(), so
        # appearing/disappearing reads as a genuine transition instead of an
        # instant alpha snap. Movement is untouched either way — this only
        # ever affects render.py's draw_fighter, never gameplay.
        self.vanish_alpha = 255.0

    def is_alive(self):
        return self.hp > 0


class Zone:
    """A circular area effect left in the arena (Sacred Ground / Blood Pool)."""

    def __init__(self, kind, center, radius, time_left, owner):
        self.kind = kind
        self.center = center
        self.radius = radius
        self.time_left = time_left
        self.owner = owner


class Clone:
    """Vampire's Crimson Doppelganger decoy — bounces around like a fighter.
    `owner` is whoever it's standing in for (see StatusLibraryMixin.
    taunt_redirect in core/status_library.py: an attack aimed at `owner`
    gets forced onto this clone instead, as long as it carries the generic
    "taunt" status).

    Carries the same flat hp/armor/statuses shape as a real Character (see
    CLONE_BASE_HP/CLONE_BASE_ARMOR) so it's a full participant in the
    generic status-library/zone pipeline (battle.tick_statuses/
    tick_library_effects, an enemy zone's own zone_tick) instead of being
    invisible to it — a Vampire decoy standing in an enemy's Blood
    Pool/Sacred Ground/Static Field takes the exact same effect a real
    fighter would, same as Phantom Lancer's own CloneUnit already does."""

    def __init__(self, image, color, pos, vel, time_left, owner):
        self.image = image
        self.color = color
        self.pos = pos
        self.vel = vel
        self.time_left = time_left
        self.owner = owner
        self.statuses = {}
        self.shake = 0.0
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.hp = CLONE_BASE_HP
        self.max_hp = CLONE_BASE_HP
        self.armor = CLONE_BASE_ARMOR
        # A landed tag effect's own log line (Sukuna's Hachi, Raiju's Fang
        # Flicker, ...) reads `defender.name` unconditionally when the hit
        # actually took effect — this decoy can now be that `defender` (see
        # status_effects.apply_ability_tag_effects), so it needs a name of
        # its own instead of crashing that f-string.
        self.name = f"{owner.name}'s decoy"

    def is_alive(self):
        return self.hp > 0
