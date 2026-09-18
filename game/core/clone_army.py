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
via the same bounce_move DVD-logo physics real fighters use by default —
see CharacterPlugin.clone_move_step for how a character swaps that in for
its own bespoke per-clone movement (Sukuna's Ten Shadows: a stationary
healer, a shadow that flies straight through the arena walls instead of
bouncing, one that orbits its own owner, ...) instead of every clone in
every army roaming identically.

Capabilities are independent flags, mixed and matched per CloneArmy
instance — none of them requires any of the others:
  can_attack     - each clone auto-attacks on its own cooldown/range with a
                   basic-attack-alike (no skills of its own), scaled off the
                   owner's own basic ability — whichever's nearer once in
                   range, the current opponent itself or one of the
                   opponent's own clones (see _pick_attack_target), so two
                   clone-owning fighters' illusions actually brawl each
                   other instead of only ever swinging at the real fighters.
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
                   With can_attack also on, Blind is one of those: a clone
                   carrying it rolls the same roll_blind_miss chance a real
                   fighter's own swing does (see _clone_attack/
                   _clone_attack_clone) and can whiff its own attack too —
                   e.g. Before-Hassasin's Zabaniya blacking out every one of
                   the opponent's own bodies, clones included, not just the
                   real fighter (see BeforeHassasinPlugin._blind_clones).
                   Never set on a clone whose own army has has_statuses=
                   False (Leonidas' Spartans) — nothing ever ticks it back
                   down there, so it would just stay blind forever instead
                   of expiring on schedule.

Regardless of which (if any) of the above are enabled, every clone is
always: a real physical body (see extra_colliders — bounces off fighters/
other clones same as a real one), and vulnerable to area damage (see
splash_aoe for an enemy's Ability.aoe_radius landing nearby, splash_cone for
an Ability.aoe_cone_deg fan, zone_tick for standing inside an enemy-owned
Zone) — a clone that "can't attack" still isn't invincible. Area damage is
never a matter of being picked as a target either: an area ability sweeps
every clone its own shape actually covers, each judged purely on where it
stands, whatever happened to the owner itself (see combat_resolution.
splash_aoe_to_clones). Separately, an eligible SINGLE-TARGET attack aimed at
the owner can land on a clone instead of the owner — but only a clone
genuinely standing within decoy_redirect_reach() of the owner when the
attack lands, never a random pick off however many are out on the field
however far away (see redirect_pool and status_library.taunt_redirect for
exactly which attacks are eligible: any single-target ability whose own
moves.py doesn't set ignore_clone=True — see abilities.Ability — regardless
of whether it's a basic, skill, or ultimate).
"""

import math
import random

import pygame

from .constants import ARENA_RECT, AVATAR_R, CLONE_BASE_ARMOR, GRAY, RED, WHITE
from .effects import draw_status_rings, scale_sprite
from .entities import in_cone
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
        # Flat/near-zero by design (see CloneArmy.clone_armor) — armor stays
        # a flimsy illusion's, even though max_hp (see CloneArmy.spawn) now
        # scales off the owner's own current max_hp. Present unconditionally
        # (harmless on a decoy that never takes damage) so generic code
        # (bounce_move/squash, and CloneArmy's own damage/status helpers)
        # never needs an attribute-existence check.
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


class CloneArmy:
    def __init__(
        self, plugin, cap, stat_pct, duration,
        can_attack=False, can_use_skill=False, has_statuses=False,
        attack_cooldown=0.9, attack_range=140, attack_anim=0.26,
        spawn_speed=(60, 100), dot_mirror_radius=100,
        clone_hp_pct=0.15, clone_armor=CLONE_BASE_ARMOR,
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
        # A clone's own max_hp is never flat — it's this pct of whichever
        # fighter owns it (its own current max_hp, read fresh at spawn time
        # in spawn() below, not cached here), same "scaled off its owner"
        # model Vampire's Crimson Doppelganger uses (see
        # characters/vampire/plugin.py's own CLONE_HP_PCT).
        self.clone_hp_pct = clone_hp_pct
        self.clone_armor = clone_armor
        self.clones = []

    @property
    def battle(self):
        return self.plugin.battle

    @property
    def owner(self):
        return self.plugin.fighter

    # ---- lifecycle -----------------------------------------------------------
    def spawn(self, near=None, cap=None, stat_pct=None, duration=None, hp_pct=None,
              attack_cooldown=None, attack_range=None):
        """Conjure one clone near `near` (the owner's own position when
        omitted), evicting the oldest once the cap is already full. `cap`/
        `stat_pct`/`duration`/`hp_pct` override this army's own defaults for
        just this spawn — e.g. Phantom Lancer's Juxtapose ultimate
        temporarily raises all four. `stat_pct` only ever scales atk (and,
        via the owner's own move_speed_mult below, roam speed); `hp_pct`
        scales max_hp, read fresh off the owner's own CURRENT max_hp every
        spawn (never cached), so a clone's durability tracks whatever the
        owner's own max_hp is at cast time — armor always stays this army's
        own flat clone_armor regardless.

        `attack_cooldown`/`attack_range`, when given, are pinned onto this
        one clone (see _pick_attack_target/tick's own getattr fallback to
        this army's shared defaults) instead of the whole army sharing one
        value — needed the moment an army can hold more than one clone at
        once with genuinely different combat stats (Sukuna's Ten Shadows:
        cap > 1, and a Toad summoned while a Divine Dog is still out must
        keep the Dog's own faster attack pace, not silently inherit the
        Toad's slower one). A plugin whose clones are all identical (Phantom
        Lancer, Vampire) just never passes these and every clone keeps
        reading the army's own shared attack_cooldown/attack_range, exactly
        as before this pair of kwargs existed."""
        owner = self.owner
        if near is None:
            near = owner.pos
        cap = self.cap if cap is None else cap
        stat_pct = self.stat_pct if stat_pct is None else stat_pct
        duration = self.duration if duration is None else duration
        hp_pct = self.clone_hp_pct if hp_pct is None else hp_pct

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
        clone = CloneUnit(pos, vel, duration, owner.atk * stat_pct, round(owner.max_hp * hp_pct), self.clone_armor)
        if attack_cooldown is not None:
            clone.attack_cooldown = attack_cooldown
        if attack_range is not None:
            clone.attack_range = attack_range
        clone.attack_cd = random.uniform(0.15, attack_cooldown if attack_cooldown is not None else self.attack_cooldown)
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
        # The opponent's own CloneArmy, if it has one (None for a plugin
        # with no clone_army() at all) — read fresh each tick since a clone
        # army's own population changes constantly (spawns, expiries, other
        # attacks) and this one's own attack loop below needs the live list.
        enemy_plugin = battle.plugin_for(opponent)
        enemy_army = enemy_plugin.clone_army() if enemy_plugin is not None else None
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
            self.plugin.clone_move_step(clone, dt, speed_mult)
            clone.scale_x += (1.0 - clone.scale_x) * min(1.0, dt / 0.14)
            clone.scale_y += (1.0 - clone.scale_y) * min(1.0, dt / 0.14)
            clone.hit_flash = max(0.0, clone.hit_flash - dt)
            clone.visual_recoil *= 0.8
            if self.can_attack:
                clone.attack_anim_t = max(0.0, clone.attack_anim_t - dt)
                clone.attack_cd -= dt
                if clone.attack_cd <= 0:
                    target = self._pick_attack_target(clone, opponent, enemy_army)
                    if target is not None:
                        if isinstance(target, CloneUnit):
                            self._clone_attack_clone(clone, target, enemy_army)
                        else:
                            self._clone_attack(clone, target)
                        clone.attack_cd = getattr(clone, "attack_cooldown", self.attack_cooldown)
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
    def _pick_attack_target(self, clone, opponent, enemy_army):
        """Whichever eligible target is nearest `clone` and within
        attack_range: the real opponent fighter, or one of the opponent's
        own living clones (enemy_army may be None — a plugin with no
        clone_army() at all). Nearest-wins rather than a fixed preference,
        so a clone standing next to an enemy illusion fights it instead of
        always reaching past it for the real fighter farther away. Reads
        `clone`'s own attack_range when spawn() pinned one (see spawn's own
        docstring), falling back to this army's shared default otherwise."""
        best, best_dist = None, getattr(clone, "attack_range", self.attack_range)
        if opponent.is_alive():
            dist = (clone.pos - opponent.pos).length()
            if dist <= best_dist:
                best, best_dist = opponent, dist
        if enemy_army is not None:
            for enemy_clone in enemy_army.clones:
                dist = (clone.pos - enemy_clone.pos).length()
                if dist <= best_dist:
                    best, best_dist = enemy_clone, dist
        return best

    def _clone_attack_clone(self, clone, enemy_clone, enemy_army):
        """Same swing as _clone_attack, but the target is an enemy illusion
        instead of the real opposing fighter — routed through the enemy
        army's own damage_clone (flat, armor-less, no shield/reflect) rather
        than the full deal_damage pipeline, same as a redirected basic
        attack or an AoE splash landing on a clone."""
        clone.attack_dir = self._face(clone, enemy_clone.pos)
        clone.attack_anim_t = self.attack_anim
        if self.battle.roll_blind_miss(clone):
            return
        basic_mult = self.owner.abilities["basic"].dmg_mult
        dmg = round(clone.atk * basic_mult)
        enemy_army.damage_clone(enemy_clone, dmg, knock_dir=clone.attack_dir)

    @staticmethod
    def _face(clone, target_pos):
        direction = target_pos - clone.pos
        return direction.normalize() if direction.length_squared() else pygame.Vector2(1, 0)

    def _clone_attack(self, clone, opponent):
        """A clone's own basic-attack-alike — no skills, ever (that's
        can_use_skill's job, see on_owner_skill_landed). Routed through the
        shared deal_damage() pipeline (armor/shields/reflect/on_damage_taken
        all still apply) with the owner itself as the nominal attacker,
        just skipping the full ability animation/state machine (so it never
        goes through outgoing_damage/on_damage_dealt — see
        clone_basic_attack_roll/clone_basic_attack_landed for a character
        whose own basic-attack passive still wants a look at a clone's
        swing, e.g. Chaos Knight's Chaos Strike). The swing always plays,
        even on a blocked/0-damage hit — same as a real fighter's own basic
        attack still animating on a miss.

        reflect_target=clone: a Reflect on `opponent` punishes whoever
        physically threw the hit, which is this clone, not the owner
        standing somewhere else on the field — deal_damage's own
        reflect_target note has the full reasoning."""
        battle, owner = self.battle, self.owner
        clone.attack_dir = self._face(clone, opponent.pos)
        clone.attack_anim_t = self.attack_anim
        if battle.roll_blind_miss(clone):
            battle.floaters.append([clone.pos.x, clone.pos.y - 30, -0.5, 210, "Blinded!", GRAY])
            return

        basic_mult = owner.abilities["basic"].dmg_mult
        dmg = round(clone.atk * basic_mult)
        dmg, crit = self.plugin.clone_basic_attack_roll(clone, dmg)
        guard = self.plugin
        guard._clone_army_resolving = True
        actual = battle.deal_damage(owner, opponent, dmg, reflect_target=clone)
        guard._clone_army_resolving = False
        if actual <= 0:
            return
        opponent.hit_flash = opponent.hit_flash_max = 0.09
        opponent.hit_flash_heavy = False
        opponent.visual_recoil += clone.attack_dir * 6
        battle.floaters.append([opponent.pos.x, opponent.pos.y - 30, -0.5, 210, f"-{actual}", owner.color])
        emit_spark_burst(battle.fx, opponent.pos, owner.color, count=8)
        self.plugin.clone_basic_attack_landed(clone, opponent, actual, crit)

    # ---- combat: mirroring the owner's own skill (can_use_skill) -------------
    def on_owner_skill_landed(self, ability, defender):
        """Call from the owning plugin whenever the owner's own skill just
        landed on `defender` (e.g. from on_damage_dealt, guarded on
        `ability.kind == "skill"`) — every living clone replays that same
        skill's damage against the same target at its own (reduced) atk, no
        cooldown of its own; it only ever fires in lockstep with the
        owner's own cast. No-op unless can_use_skill is enabled.

        reflect_target=clone, same reasoning as _clone_attack above — each
        clone's own mirrored swing is what a Reflect on `defender` bounces
        back onto, not the owner."""
        if not self.can_use_skill or not self.clones:
            return
        battle, owner = self.battle, self.owner
        guard = self.plugin
        for clone in list(self.clones):
            dmg = round(clone.atk * ability.dmg_mult)
            guard._clone_army_resolving = True
            actual = battle.deal_damage(owner, defender, dmg, reflect_target=clone)
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
        """Chip `dmg` off `clone`'s own hp, doubled — a clone always takes
        2x whatever raw damage a real fighter would've taken from the same
        hit, on top of its already-flimsy hp pool (see CloneArmy.spawn's own
        clone_hp_pct) — a hit floater/spark for a discrete hit (an area
        attack landing, or a redirected basic attack — see
        status_library.taunt_redirect/basic_attack_decoys), silent for a
        continuous tick (zone chip damage would otherwise spam a floater
        every frame). A clone with no hp left is destroyed outright, with
        its own beat. Returns the doubled amount actually applied (clones
        have no armor/shield of their own to mitigate it further), for a
        caller that wants it for its own follow-up math (meter gain,
        lifesteal, ...).

        `show_floater=True` also doubles as "this was a real landed hit,
        not a silent tick" — the same white/red flash, squash, and
        knockback nudge ImpactFXMixin.apply_impact gives a real fighter,
        sized off `ability`'s own impact tier (see BattleAnimation.
        impact_tier) when the caller has one (a redirected basic attack, an
        AoE splash), falling back to the flimsy "basic" tier otherwise.
        `knock_dir` is the direction to nudge the clone away from — the
        attacker's own atk_dir for a redirected hit, the blast/cone origin
        for splash; a zero/omitted direction just skips the nudge.

        This is the one choke point every source of clone damage in the
        game already funnels through (a redirected hit, an AoE/cone splash,
        Raiju's own bespoke Volt Fang, this army's own _clone_attack_clone),
        so it's also the one place a clone carrying the generic
        "invulnerable" status (see status_library.py — a character can set
        it on its own clones the same way Berserker Rage sets it on a real
        fighter) needs to be checked, unlike a real fighter's own
        apply_damage which already does this generically."""
        if dmg <= 0 or clone.statuses.get("invulnerable"):
            return 0
        dmg = round(dmg * 2)
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
        a candidate stand-in for the real fighter against an incoming
        eligible attack, though only one actually standing within
        decoy_redirect_reach() when the attack lands is ever eligible (see
        status_library.taunt_redirect for which attacks are eligible in the
        first place). A copy, since callers may mutate self.clones (a clone
        dying) while iterating the pool they got back."""
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
        `reach` — any clone anywhere in that wedge takes `dmg` too, checked
        by the exact same entities.in_cone test combat_resolution.do_damage
        runs against the ability's own resolved target, so a clone and the
        real fighter it belongs to are held to one identical hit-or-miss
        rule instead of two diverging ones."""
        if not self.clones or direction.length_squared() == 0 or reach <= 0:
            return
        d = direction.normalize()
        for clone in list(self.clones):
            if in_cone(clone.pos, origin, direction, spread_deg, reach):
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
    def draw(self, screen, shake_x, sprite_alpha=255, ring_color=None, draw_weapon=None, sprite_for=None,
              ring_radius_for=None):
        """Generic clone rendering: a sprite, faded, plus a color ring — the
        same hit-flash tint/squash/knockback and status-effect rings a real
        fighter gets (see draw_fighter in render.py) on top, since a clone
        can now take a real landed hit (damage_clone) and carry the same
        statuses (has_statuses) a real fighter can. Pass
        `draw_weapon(screen, clone, pos)` for a character-specific weapon
        prop/animation (kept out of this shared module on purpose — art is
        each character's own call). Pass `sprite_for(clone)` for a character
        whose own clones shouldn't all just be a faded copy of its own
        sprite — Sukuna's Ten Shadows returns one of ten distinct shadow
        sprites depending on clone.shadow_key (see characters/sukuna/
        shadows_sprite.py) instead of ten copies of Sukuna's own orb; omitted,
        every clone falls back to the owner's own image, same as before this
        hook existed (Phantom Lancer's illusions, still just faded copies of
        Phantom Lancer himself). Pass `ring_radius_for(clone)` when a clone's
        drawn ring should shrink along with a shrunk sprite (Rabbit Escape —
        see SukunaPlugin._ring_radius) — purely cosmetic, the clone's actual
        hitbox stays the flat AVATAR_R every clone uses regardless; omitted,
        every clone keeps the original fixed AVATAR_R + 6 ring."""
        owner = self.owner
        color = ring_color or owner.color
        battle = self.battle
        for clone in self.clones:
            base = sprite_for(clone) if sprite_for is not None else owner.image
            img = base.copy()
            if clone.hit_flash > 0:
                img = battle.hit_flash_sprite(img, clone)
            img = scale_sprite(img, clone.scale_x, clone.scale_y)
            img.set_alpha(sprite_alpha)
            pos = clone.pos + clone.visual_recoil + pygame.Vector2(shake_x, 0)
            screen.blit(img, img.get_rect(center=(int(pos.x), int(pos.y))))
            radius = ring_radius_for(clone) if ring_radius_for is not None else AVATAR_R + 6
            pygame.draw.circle(screen, color, (int(pos.x), int(pos.y)), radius, width=3)
            draw_status_rings(screen, pos, clone.statuses, font=battle.font_small)
            if draw_weapon is not None:
                draw_weapon(screen, clone, pos)
