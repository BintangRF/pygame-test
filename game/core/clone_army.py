"""Reusable illusion/clone-army building block any CharacterPlugin can
compose instead of hand-rolling its own spawn/cap/move/attack/expire logic
(originally built for Phantom Lancer's Juxtapose passive — see
characters/phantom_lancer/plugin.py for the reference user — generalized
here so a future character's own decoy/illusion kit can reuse the same
engine plumbing with different capabilities).

A CloneArmy never touches the engine's real attacker/defender attack-
sequence machinery (core/battle_loop.py/combat_resolution.py) — every
CloneUnit is a lightweight self-contained mover driven entirely from the
owning plugin's own ambient_tick/draw_fx hooks (called every frame
regardless of mode, same as any other character's ambient state), moving
via the same bounce_move DVD-logo physics real fighters use.

Capabilities are independent flags, mixed and matched per CloneArmy
instance — none of them requires any of the others:
  can_attack     - each clone auto-attacks the current opponent on its own
                   cooldown/range with a basic-attack-alike (no skills of
                   its own), scaled off the owner's own basic ability.
  can_use_skill  - each clone also mirrors whatever skill the owner itself
                   just landed, at the same instant — no independent
                   cooldown of its own; call on_owner_skill_landed() from
                   the owning plugin's own on_damage_dealt (or wherever it
                   detects its own skill landed) to trigger it.
  has_statuses   - each clone carries a real .statuses dict and ticks it
                   every frame through the exact same generic
                   status_library.py pipeline (battle.tick_statuses/
                   tick_library_effects) a real fighter uses — a buff/debuff
                   applied to a clone (via entities.set_status) behaves
                   exactly like it would on a real fighter, DoT included.

Regardless of which (if any) of the above are enabled, every clone is
always: a real physical body (see extra_colliders — bounces off fighters/
other clones same as a real one), and vulnerable to area damage (see
splash_aoe for an enemy's Ability.aoe_radius landing nearby, splash_cone for
an Ability.aoe_cone_deg fan, zone_tick for standing inside an enemy-owned
Zone) — a clone that "can't attack" still isn't invincible. An eligible
attack aimed at the owner can also land on a clone instead of the owner —
see redirect_pool and status_library.taunt_redirect for exactly which
attacks are eligible (any ability whose own moves.py doesn't set
ignore_clone=True — see abilities.Ability — regardless of whether it's a
basic, skill, or ultimate) — a pool alongside the owner itself, weighted by
the owning plugin's own decoy_redirect_weight() (1 = plain equal-odds).
"""

import math
import random

import pygame

from .constants import ARENA_RECT, AVATAR_R, CLONE_BASE_ARMOR, CLONE_BASE_HP, RED, WHITE
from .effects import draw_status_rings, scale_sprite
from .entities import bounce_move
from .particles import emit_dark, emit_spark_burst


class CloneUnit:
    """One illusory copy a CloneArmy manages — a mover (pos/vel/scale, same
    shape bounce_move/squash expect) with its own hp/atk, an always-present
    (but only ever populated when the owning army has has_statuses=True)
    statuses dict, and attack-swing state used only when can_attack/
    can_use_skill is enabled. Never a real Character: no abilities of its
    own, and it's never a selectable attacker/defender target the normal
    way — see the module docstring for how it can still take damage."""

    def __init__(self, pos, vel, time_left, atk, max_hp, armor=0.0):
        self.pos = pos
        self.vel = vel
        self.time_left = time_left
        self.atk = atk
        self.max_hp = max_hp
        self.hp = max_hp
        # Flat/near-zero by design (see CloneArmy.clone_hp/clone_armor) — a
        # clone is a flimsy illusion, not a scaled-down copy of the owner's
        # own durability. Present unconditionally (harmless on a decoy that
        # never takes damage) so generic code (bounce_move/squash, and
        # CloneArmy's own damage/status helpers) never needs an
        # attribute-existence check.
        self.armor = armor
        self.statuses = {}
        # Same landed-hit feedback a real Character gets from ImpactFXMixin.
        # apply_impact (see damage_clone) — a white/red sprite tint plus a
        # brief squash/knockback — so a clone taking a redirected hit or an
        # AoE splash reads exactly like a real fighter getting hit, not just
        # a silent hp tick with a floater.
        self.hit_flash = 0.0
        self.hit_flash_max = 0.0
        self.hit_flash_heavy = False
        self.visual_recoil = pygame.Vector2()
        # A landed tag effect's own log line (Sukuna's Hachi, Raiju's Fang
        # Flicker, ...) reads `defender.name` unconditionally when the hit
        # actually took effect — a clone can now be that `defender` (see
        # status_effects.apply_ability_tag_effects), so it needs a name of
        # its own instead of crashing that f-string.
        self.name = "the illusion"
        self.scale_x = 1.0
        self.scale_y = 1.0
        # Staggered by the caller so a whole batch spawned at once doesn't
        # all swing on the same frame.
        self.attack_cd = 0.0
        # Counts down once a swing starts — draw callers read it to play a
        # one-shot animation instead of an idle pose; attack_dir is the
        # swing direction frozen at the moment of the swing.
        self.attack_anim_t = 0.0
        self.attack_dir = pygame.Vector2(1, 0)

    def is_alive(self):
        return self.hp > 0


#: Status names tick_library_effects actually deals damage-over-time for
#: (see status_library.py's own DoT taxonomy) — the only ones _mirror_owner_
#: dots bothers copying onto a nearby clone. Buffs/hard-CC/other debuffs on
#: the owner are deliberately not mirrored (a clone is a damage sponge, not
#: a second copy of every one of the owner's statuses).
_MIRRORED_DOT_NAMES = ("bleed", "poison", "burn", "curse", "corruption", "frozen")


# Default "slots" each living clone gets in taunt_redirect's pool, relative
# to 1 for the real fighter itself (see CharacterPlugin.decoy_redirect_weight)
# — above a plain 1-for-1 equal-odds split, since an illusion existing at
# all is more interesting when it actually tends to soak the hit meant for
# the real fighter standing behind it.
DEFAULT_DECOY_WEIGHT = 3


class CloneArmy:
    def __init__(
        self, plugin, cap, stat_pct, duration,
        can_attack=False, can_use_skill=False, has_statuses=False,
        attack_cooldown=0.9, attack_range=140, attack_anim=0.26,
        spawn_speed=(60, 100), dot_mirror_radius=100,
        clone_hp=CLONE_BASE_HP, clone_armor=CLONE_BASE_ARMOR,
        decoy_weight=DEFAULT_DECOY_WEIGHT,
    ):
        self.plugin = plugin
        self.cap = cap
        self.stat_pct = stat_pct
        self.duration = duration
        self.can_attack = can_attack
        self.can_use_skill = can_use_skill
        self.has_statuses = has_statuses
        self.attack_cooldown = attack_cooldown
        self.attack_range = attack_range
        self.attack_anim = attack_anim
        self.spawn_speed = spawn_speed
        self.dot_mirror_radius = dot_mirror_radius
        self.clone_hp = clone_hp
        self.clone_armor = clone_armor
        # Read generically by CharacterPlugin.decoy_redirect_weight — how
        # many "slots" each living clone gets in taunt_redirect's pool
        # relative to a single slot for the real fighter itself. Any
        # character's illusions skew incoming basic attacks toward
        # themselves the same way by default, not just Phantom Lancer's;
        # pass a different value here for a character that wants a plainer
        # (or steeper) split.
        self.decoy_weight = decoy_weight
        self.clones = []

    @property
    def battle(self):
        return self.plugin.battle

    @property
    def owner(self):
        return self.plugin.fighter

    # ---- lifecycle -----------------------------------------------------------
    def spawn(self, near=None, cap=None, stat_pct=None, duration=None):
        """Conjure one clone near `near` (the owner's own position when
        omitted), evicting the oldest once the cap is already full. `cap`/
        `stat_pct`/`duration` override this army's own defaults for just
        this spawn — e.g. Phantom Lancer's Juxtapose ultimate temporarily
        raises all three. `stat_pct` only ever scales atk (and, via the
        owner's own move_speed_mult below, roam speed) — hp/armor always
        come from this army's own flat clone_hp/clone_armor, never scaled
        off the owner's own max_hp, so a clone stays just as flimsy
        regardless of which fighter (or which buffed spawn) it came from."""
        owner = self.owner
        if near is None:
            near = owner.pos
        cap = self.cap if cap is None else cap
        stat_pct = self.stat_pct if stat_pct is None else stat_pct
        duration = self.duration if duration is None else duration

        if len(self.clones) >= cap:
            self.clones.pop(0)  # oldest replaced first

        offset = pygame.Vector2(random.uniform(-40, 40), random.uniform(-40, 40))
        pos = pygame.Vector2(near) + offset
        pos.x = max(ARENA_RECT.left + AVATAR_R, min(ARENA_RECT.right - AVATAR_R, pos.x))
        pos.y = max(ARENA_RECT.top + AVATAR_R, min(ARENA_RECT.bottom - AVATAR_R, pos.y))
        angle = random.uniform(0, math.tau)
        # Roam speed scales with the owner's own move_speed_mult (a Berserker's
        # clones dart around faster than a Paladin's), same intrinsic stat
        # real fighters spawn with (see core/assets.py's own spawn()) — on
        # top of that, tick() applies whatever temporary speed buff/slow the
        # owner is currently under, every frame.
        speed = random.uniform(*self.spawn_speed) * owner.move_speed_mult
        vel = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
        clone = CloneUnit(pos, vel, duration, owner.atk * stat_pct, self.clone_hp, self.clone_armor)
        clone.attack_cd = random.uniform(0.15, self.attack_cooldown)
        self.clones.append(clone)
        return clone

    def tick(self, dt):
        """Call once per frame from the owning plugin's own ambient_tick."""
        battle, owner = self.battle, self.owner
        self.zone_tick(dt)
        if not self.clones:
            return
        if battle.winner is not None or not owner.is_alive():
            self.clones = []
            return
        opponent = battle.f2 if battle.f1 is owner else battle.f1
        # Illusions, not independent movers — they mirror whatever
        # move-speed state the owner itself is in right now (a speed buff,
        # a slow, ...), same multiplier real fighters' own roam_step reads.
        speed_mult = battle.status_move_speed_multiplier(owner)

        alive = []
        for clone in self.clones:
            clone.time_left -= dt
            if clone.time_left <= 0:
                continue
            if self.has_statuses:
                if (clone.pos - owner.pos).length() <= self.dot_mirror_radius:
                    self._mirror_owner_dots(clone)
                battle.tick_library_effects(clone, dt)
                battle.tick_statuses(clone, dt)
                if not clone.is_alive():
                    continue
            bounce_move(clone, dt, speed_mult)
            clone.scale_x += (1.0 - clone.scale_x) * min(1.0, dt / 0.14)
            clone.scale_y += (1.0 - clone.scale_y) * min(1.0, dt / 0.14)
            clone.hit_flash = max(0.0, clone.hit_flash - dt)
            clone.visual_recoil *= 0.8
            if self.can_attack:
                clone.attack_anim_t = max(0.0, clone.attack_anim_t - dt)
                clone.attack_cd -= dt
                if (
                    opponent.is_alive() and clone.attack_cd <= 0
                    and (clone.pos - opponent.pos).length() <= self.attack_range
                ):
                    self._clone_attack(clone, opponent)
                    clone.attack_cd = self.attack_cooldown
            alive.append(clone)
        self.clones = alive

    def extra_colliders(self):
        """Feed CharacterPlugin.extra_colliders() from the owning plugin —
        clones are physical bodies too, bounced off fighters/each other by
        battle_loop.resolve_collisions same as any real one."""
        return self.clones

    def _mirror_owner_dots(self, clone):
        """Copy every currently-active DoT status (bleed/poison/burn/curse/
        corruption/frozen) from the owner onto `clone`, refreshed every
        frame it's within dot_mirror_radius — so whatever poison/bleed/etc.
        is actively ticking on the owner also ticks on a clone standing
        close enough to it, through the exact same generic status_library.py
        formula (tick_library_effects, called right after this in tick())
        rather than a hand-rolled damage estimate. A DoT the owner no longer
        carries is dropped from the clone too, instead of lingering on its
        own borrowed copy."""
        owner = self.owner
        for name in _MIRRORED_DOT_NAMES:
            src = owner.statuses.get(name)
            if src is None:
                clone.statuses.pop(name, None)
            else:
                clone.statuses[name] = dict(src)

    # ---- combat: clone's own basic-attack-alike (can_attack) -----------------
    def _clone_attack(self, clone, opponent):
        """A clone's own basic-attack-alike — no skills, ever (that's
        can_use_skill's job, see on_owner_skill_landed). Routed through the
        shared deal_damage() pipeline (armor/shields/reflect/on_damage_taken
        all still apply) with the owner itself as the nominal attacker,
        just skipping the full ability animation/state machine. The swing
        always plays, even on a blocked/0-damage hit — same as a real
        fighter's own basic attack still animating on a miss."""
        battle, owner = self.battle, self.owner
        direction = opponent.pos - clone.pos
        clone.attack_dir = direction.normalize() if direction.length_squared() else pygame.Vector2(1, 0)
        clone.attack_anim_t = self.attack_anim

        basic_mult = owner.abilities["basic"].dmg_mult
        dmg = round(clone.atk * basic_mult)
        guard = self.plugin
        guard._clone_army_resolving = True
        actual = battle.deal_damage(owner, opponent, dmg)
        guard._clone_army_resolving = False
        if actual <= 0:
            return
        opponent.hit_flash = opponent.hit_flash_max = 0.09
        opponent.hit_flash_heavy = False
        opponent.visual_recoil += clone.attack_dir * 6
        battle.floaters.append([opponent.pos.x, opponent.pos.y - 30, -0.5, 210, f"-{actual}", owner.color])
        emit_spark_burst(battle.fx, opponent.pos, owner.color, count=8)

    # ---- combat: mirroring the owner's own skill (can_use_skill) -------------
    def on_owner_skill_landed(self, ability, defender):
        """Call from the owning plugin whenever the owner's own skill just
        landed on `defender` (e.g. from on_damage_dealt, guarded on
        `ability.kind == "skill"`) — every living clone replays that same
        skill's damage against the same target at its own (reduced) atk, no
        cooldown of its own; it only ever fires in lockstep with the
        owner's own cast. No-op unless can_use_skill is enabled."""
        if not self.can_use_skill or not self.clones:
            return
        battle, owner = self.battle, self.owner
        guard = self.plugin
        for clone in list(self.clones):
            dmg = round(clone.atk * ability.dmg_mult)
            guard._clone_army_resolving = True
            actual = battle.deal_damage(owner, defender, dmg)
            guard._clone_army_resolving = False
            if actual <= 0:
                continue
            battle.floaters.append([defender.pos.x, defender.pos.y - 30, -0.5, 210, f"-{actual}", owner.color])
            emit_spark_burst(battle.fx, defender.pos, owner.color, count=8)

    # ---- vulnerability: area damage / redirected hits (any capability) -------
    def _destroy_clone(self, clone):
        """Remove `clone` outright with its own destroyed beat — shared by
        every path that can kill one (a discrete hit dropping its hp to 0
        in damage_clone, or an enemy zone's own real effect doing it via
        zone_tick below)."""
        battle = self.battle
        self.clones.remove(clone)
        battle.floaters.append([clone.pos.x, clone.pos.y - 45, -0.6, 220, "Destroyed!", WHITE])
        emit_dark(battle.fx, clone.pos, count=14, radius=30)

    def damage_clone(self, clone, dmg, show_floater=True, ability=None, knock_dir=None):
        """Chip `dmg` off `clone`'s own hp — a hit floater/spark for a
        discrete hit (an area attack landing, or a redirected basic attack —
        see status_library.taunt_redirect/basic_attack_decoys), silent for a
        continuous tick (zone chip damage would otherwise spam a floater
        every frame). A clone with no hp left is destroyed outright, with
        its own beat. Returns `dmg` unchanged (clones have no armor/shield
        of their own to mitigate it), for a caller that wants it for its own
        follow-up math (meter gain, lifesteal, ...).

        `show_floater=True` also doubles as "this was a real landed hit,
        not a silent tick" — the same white/red flash, squash, and
        knockback nudge ImpactFXMixin.apply_impact gives a real fighter,
        sized off `ability`'s own impact tier (see BattleAnimation.
        impact_tier) when the caller has one (a redirected basic attack, an
        AoE splash), falling back to the flimsy "basic" tier otherwise.
        `knock_dir` is the direction to nudge the clone away from — the
        attacker's own atk_dir for a redirected hit, the blast/cone origin
        for splash; a zero/omitted direction just skips the nudge."""
        if dmg <= 0:
            return 0
        battle = self.battle
        clone.hp -= dmg
        if show_floater:
            battle.floaters.append([clone.pos.x, clone.pos.y - 30, -0.5, 200, f"-{round(dmg)}", RED])
            emit_spark_burst(battle.fx, clone.pos, self.owner.color, count=6)
            tier = battle.impact_tier(ability) if ability is not None else "basic"
            clone.hit_flash = clone.hit_flash_max = battle.TIER_FLASH[tier]
            clone.hit_flash_heavy = tier in ("heavy", "ultimate")
            clone.scale_x, clone.scale_y = battle.TIER_SQUASH[tier]
            if knock_dir is not None and knock_dir.length_squared():
                clone.visual_recoil += knock_dir.normalize() * battle.TIER_KNOCKBACK[tier]
        if clone.hp <= 0 and clone in self.clones:
            self._destroy_clone(clone)
        return dmg

    def redirect_pool(self):
        """This army's own contribution to a defending fighter's
        basic_attack_decoys() (see core/plugin.py) — every living clone, as
        an alternative to the real fighter itself for an incoming eligible
        attack (weighted per decoy_redirect_weight() — see
        status_library.taunt_redirect for which attacks are eligible). A
        copy, since callers may mutate self.clones (a clone dying) while
        iterating the pool they got back."""
        return list(self.clones)

    def splash_aoe(self, center, radius, dmg, ability=None):
        """An enemy's area-flavored attack (Ability.aoe_radius, no
        aoe_cone_deg) detonating AT `center` (the defender's own impact
        point — Bat Swarm, Kamino, Heaven's Verdict, Thunder God's Descent
        all genuinely blast the target's own position) — any clone within
        `radius` of it takes `dmg` too. Called generically by
        combat_resolution.splash_aoe_to_clones whenever such an ability
        lands on this army's own owner — no per-character wiring needed,
        just expose this army via CharacterPlugin.clone_army()."""
        if not self.clones:
            return
        for clone in list(self.clones):
            offset = clone.pos - center
            if offset.length() <= radius:
                self.damage_clone(clone, dmg, ability=ability, knock_dir=offset)

    def splash_cone(self, origin, direction, spread_deg, reach, dmg, ability=None):
        """An enemy's cone/fan-shaped attack (Ability.aoe_cone_deg — Axe
        Throw's fan, see draw_fan/_draw_axe_fan in characters/berserker/
        plugin.py) swept from `origin` (the ATTACKER's own position, not the
        defender's — the fan originates there and sweeps outward) along
        `direction`, spanning `spread_deg` total (half on each side) out to
        `reach` — any clone anywhere in that wedge takes `dmg` too,
        regardless of how close it is to wherever the defender happens to
        be standing; the fan doesn't stop just because it already reached
        its one resolved target, since visually/thematically it really does
        cover that whole swept area."""
        if not self.clones or direction.length_squared() == 0 or reach <= 0:
            return
        d = direction.normalize()
        half = math.radians(spread_deg) / 2
        for clone in list(self.clones):
            to_clone = clone.pos - origin
            dist = to_clone.length()
            if dist < 1e-6 or dist > reach:
                continue
            cos_angle = max(-1.0, min(1.0, d.dot(to_clone / dist)))
            if math.acos(cos_angle) <= half:
                self.damage_clone(clone, dmg, ability=ability, knock_dir=d)

    def zone_tick(self, dt):
        """An enemy-owned Zone (Blood Pool/Sacred Ground/Static Field, ...)
        affects any clone standing in it exactly like it would a real
        fighter — delegated to that zone's own owner's own zone_tick (the
        same poison+disarm Blood Pool applies, the same corruption+chip
        Sacred Ground applies, ...) instead of a hand-rolled flat
        approximation, so a clone standing in it takes the exact same
        effect a real fighter would, tag-effect statuses included (any
        poison/corruption/etc. this sets on the clone still ticks through
        the normal has_statuses pipeline in tick() above)."""
        battle, owner = self.battle, self.owner
        if not self.clones or not battle.zones:
            return
        for zone in battle.zones:
            if zone.owner is owner:
                continue
            owner_plugin = battle.plugin_for(zone.owner)
            if owner_plugin is None:
                continue
            for clone in list(self.clones):
                if (clone.pos - zone.center).length() <= zone.radius:
                    owner_plugin.zone_tick(clone, zone, dt)
                    if not clone.is_alive() and clone in self.clones:
                        self._destroy_clone(clone)

    # ---- presentation ----------------------------------------------------------
    def draw(self, screen, shake_x, sprite_alpha=150, ring_color=None, draw_weapon=None):
        """Generic clone rendering: the owner's own sprite, faded, plus a
        color ring — the same hit-flash tint/squash/knockback and
        status-effect rings a real fighter gets (see draw_fighter in
        render.py) on top, since a clone can now take a real landed hit
        (damage_clone) and carry the same statuses (has_statuses) a real
        fighter can. Pass `draw_weapon(screen, clone, pos)` for a
        character-specific weapon prop/animation (kept out of this shared
        module on purpose — art is each character's own call)."""
        owner = self.owner
        color = ring_color or owner.color
        battle = self.battle
        for clone in self.clones:
            img = owner.image.copy()
            if clone.hit_flash > 0:
                img = battle.hit_flash_sprite(img, clone)
            img = scale_sprite(img, clone.scale_x, clone.scale_y)
            img.set_alpha(sprite_alpha)
            pos = clone.pos + clone.visual_recoil + pygame.Vector2(shake_x, 0)
            screen.blit(img, img.get_rect(center=(int(pos.x), int(pos.y))))
            pygame.draw.circle(screen, color, (int(pos.x), int(pos.y)), AVATAR_R + 3, width=2)
            draw_status_rings(screen, pos, clone.statuses, font=battle.font_small)
            if draw_weapon is not None:
                draw_weapon(screen, clone, pos)
