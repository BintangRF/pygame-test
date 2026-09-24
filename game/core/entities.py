"""
Game entities — Character (a fighter), Zone (an arena effect area),
Clone (Vampire's decoy), plus small helpers shared by them.
"""

import math

import pygame

from .constants import ARENA_RECT, AVATAR_R, CHARACTER_HITBOX_R, CLONE_BASE_ARMOR
from .status_library import BLOCKS_MOVE


def format_cd(seconds):
    return "READY" if seconds <= 0 else f"{seconds:.1f}s"


def in_cone(pos, origin, direction, spread_deg, reach):
    """Whether `pos` lies inside a cone/fan swept from `origin` along
    `direction` (spread_deg total, half on each side) out to `reach` — the
    one geometry test for "is this body in the area", shared by every
    caller that needs it (combat_resolution.do_damage for the ability's own
    resolved target, clone_army.splash_cone for a defender's clones) so a
    cone-shaped ability treats any enemy body the same way, none exempted
    by what kind of body it is."""
    if direction.length_squared() == 0 or reach <= 0:
        return False
    to_pos = pos - origin
    dist = to_pos.length()
    if dist < 1e-6 or dist > reach:
        return False
    d = direction.normalize()
    cos_angle = max(-1.0, min(1.0, d.dot(to_pos / dist)))
    return math.acos(cos_angle) <= math.radians(spread_deg) / 2


def melee_size_offset(a, b):
    """How much farther apart (center to center) `a` and `b` sit at the
    same edge-to-edge gap than two default-sized bodies would. Every
    melee_range/attack_range in the roster was tuned back when every body
    shared CHARACTER_HITBOX_R, i.e. as a center distance between two
    default-sized bodies — adding this offset turns that same number into
    the matching center distance for these two actual bodies, so reach is
    effectively measured edge to edge. Without it, a big target (the
    practice Dummy's 2x sprite) holds every short-reach melee fighter
    outside its own melee_range through collision alone. Same
    hitbox_r-or-AVATAR_R radius convention as bounce_move and
    resolve_character_collision below."""
    return (
        getattr(a, "hitbox_r", AVATAR_R) - CHARACTER_HITBOX_R
        + getattr(b, "hitbox_r", AVATAR_R) - CHARACTER_HITBOX_R
    )


def melee_distance(a, b):
    """Center distance between `a` and `b`, minus melee_size_offset — the
    number to compare against a melee_range/attack_range."""
    return (a.pos - b.pos).length() - melee_size_offset(a, b)


def set_status(character, name, time_s, **kwargs):
    """Apply or refresh a timed status effect (shield, vulnerability, curse, ...)."""
    s = character.statuses.get(name, {})
    s["time"] = time_s
    s.update(kwargs)
    character.statuses[name] = s


def bounce_move(obj, dt, speed_mult=1.0):
    """Move obj by its velocity, bouncing off the arena bounds like a DVD
    logo. The bounce margin is obj's own hitbox_r (a Character's actual
    on-screen radius — see Character.__init__/assets.make_character) when
    it has one, falling back to the flat AVATAR_R for a bouncing body that
    doesn't (e.g. Vampire's Clone, always drawn at the default size anyway).
    Without reading obj's own radius here, a fighter drawn bigger than the
    default sprite — the practice Dummy, at 2x every other fighter's
    diameter — would bounce off the wall with half its own sprite already
    poking through it, instead of bouncing at its actual drawn edge."""
    dt = dt * speed_mult
    obj.pos += obj.vel * dt
    r = getattr(obj, "hitbox_r", AVATAR_R)
    left, right = ARENA_RECT.left + r, ARENA_RECT.right - r
    top, bottom = ARENA_RECT.top + r, ARENA_RECT.bottom - r
    if obj.pos.x < left:
        obj.pos.x = left
        obj.vel.x *= -1
    elif obj.pos.x > right:
        obj.pos.x = right
        obj.vel.x *= -1
    if obj.pos.y < top:
        obj.pos.y = top
        obj.vel.y *= -1
    elif obj.pos.y > bottom:
        obj.pos.y = bottom
        obj.vel.y *= -1


def resolve_character_collision(a, b):
    """Bump two roaming bodies (the two fighters, and/or Vampire's clone)
    apart when they overlap, bouncing them off each other like the DVD-logo
    wall bounce in bounce_move — same treat-body-as-a-circle-of-its-own-
    hitbox_r convention bounce_move uses (falling back to AVATAR_R for a
    body without one, e.g. Vampire's Clone), just against one another
    instead of the arena edge, so e.g. the practice Dummy (drawn at 2x
    every other fighter's diameter) bumps and gets bumped at its own actual
    drawn edge instead of the flat default radius every other fighter
    happens to share. Equal-mass elastic collision: the velocity component
    along the impact normal is swapped between the two, leaving the
    tangential component untouched.

    A body currently pinned in place (BLOCKS_MOVE — stunned/frozen/rooted/
    asleep) never gets pushed by this: without that check, a Phantom Lancer
    illusion (or any other roaming extra_collider, see
    CharacterPlugin.extra_colliders) wandering into a rooted fighter would
    shove it off the exact spot its own root promised — most visibly Legion
    Commander's Duel, whose whole mutual-basic-attack lock depends on both
    fighters staying at the exact distance they were pinned at (see
    LegionCommanderPlugin.strike_point_override); one stray bump used to be
    enough to knock them both permanently out of each other's melee_range
    for the rest of the window. The other, still-movable side simply eats
    the full overlap instead of splitting it — normal 50/50 push once
    neither side is pinned.

    Returns whether the two actually overlapped this call — battle_loop's
    resolve_collisions uses that to fire CharacterPlugin.on_collision only
    on a real bump, not every pair it checks (most aren't overlapping most
    frames)."""
    delta = a.pos - b.pos
    dist = delta.length()
    min_dist = getattr(a, "hitbox_r", AVATAR_R) + getattr(b, "hitbox_r", AVATAR_R)
    if dist >= min_dist:
        return False
    normal = delta / dist if dist > 1e-4 else pygame.Vector2(1, 0)

    # Push both out of overlap (split evenly, unless one side is pinned —
    # see the docstring above), then clamp back inside the arena so the
    # separation itself can never shove someone through a wall.
    overlap = min_dist - dist
    a_pinned = bool(a.statuses.keys() & BLOCKS_MOVE)
    b_pinned = bool(b.statuses.keys() & BLOCKS_MOVE)
    if a_pinned and b_pinned:
        return True
    elif a_pinned:
        b.pos -= normal * overlap
    elif b_pinned:
        a.pos += normal * overlap
    else:
        a.pos += normal * (overlap / 2)
        b.pos -= normal * (overlap / 2)
    for obj in (a, b):
        r = getattr(obj, "hitbox_r", AVATAR_R)
        obj.pos.x = max(ARENA_RECT.left + r, min(ARENA_RECT.right - r, obj.pos.x))
        obj.pos.y = max(ARENA_RECT.top + r, min(ARENA_RECT.bottom - r, obj.pos.y))

    a_n = a.vel.dot(normal)
    b_n = b.vel.dot(normal)
    a.vel += normal * (b_n - a_n)
    b.vel += normal * (a_n - b_n)
    return True


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
        # This fighter's own collision/bounce radius — defaults to the flat
        # CHARACTER_HITBOX_R, but assets.make_character overwrites it with
        # half the visible (non-transparent) width of that fighter's own
        # sprite (assets.sprite_hitbox_r), so every fighter's hitbox/bounce
        # point matches its own silhouette instead of one shared radius
        # (see bounce_move and resolve_character_collision above, and
        # CHARACTER_HITBOX_R's own docstring in core/constants.py).
        self.hitbox_r = CHARACTER_HITBOX_R
        self.pos = pygame.Vector2()
        self.vel = pygame.Vector2()
        # The fixed roam-cruising speed assets.spawn() actually gives this
        # fighter's own vel (wall bounces only ever flip one component's
        # sign afterward, never its magnitude) — ImpactFXMixin.
        # decay_launch_speed reads this as the speed a landed hit's own
        # knock_back launch eases back down to, so a knocked-back fighter
        # settles back into its own normal pace instead of stopping dead or
        # overshooting it.
        self.base_speed = 0.0
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
        # A critical hit's own flash tint (see ImpactFXMixin.apply_impact's
        # "critical" tier) — WHITE->CRIT_COLOR instead of hit_flash_heavy's
        # WHITE->RED, so a crit reads as its own distinct flourish rather
        # than just another heavy hit (see hit_flash_sprite in render.py).
        self.hit_flash_crit = False

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

    Carries the same hp/armor/statuses shape as a real Character (armor
    flat off CLONE_BASE_ARMOR, hp a pct of `owner`'s own max_hp — see
    `max_hp`, computed by the caller, VampirePlugin.spawn_clone) so it's a
    full participant in the generic status-library/zone pipeline
    (battle.tick_statuses/tick_library_effects, an enemy zone's own
    zone_tick) instead of being invisible to it — a Vampire decoy standing
    in an enemy's Blood Pool/Sacred Ground/Static Field takes the exact
    same effect a real fighter would, same as Phantom Lancer's own
    CloneUnit already does."""

    def __init__(self, image, color, pos, vel, time_left, owner, max_hp):
        self.image = image
        self.color = color
        self.pos = pos
        self.vel = vel
        self.time_left = time_left
        self.owner = owner
        self.statuses = {}
        self.shake = 0.0
        self.hp = max_hp
        self.max_hp = max_hp
        self.armor = CLONE_BASE_ARMOR
        # A landed tag effect's own log line (Sukuna's Hachi, Raiju's Fang
        # Flicker, ...) reads `defender.name` unconditionally when the hit
        # actually took effect — this decoy can now be that `defender` (see
        # status_effects.apply_ability_tag_effects), so it needs a name of
        # its own instead of crashing that f-string.
        self.name = f"{owner.name}'s decoy"

    def is_alive(self):
        return self.hp > 0
