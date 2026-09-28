"""Phantom Lancer plugin: the Juxtapose passive (every landed Spear Slash/
Spirit Lance conjures an illusory clone that roams and auto-attacks on its
own, capped at 5 at once — 7 while the Juxtapose ultimate is active, with
richer stats/duration — and, on top of that, every clone currently alive
also feeds Phantom Lancer's own outgoing damage and armor, a flat % of his
own attack plus a flat armor amount per clone, rising and falling with the
live army headcount every frame — see CLONE_ATK_BUFF_PCT_PER_CLONE/
CLONE_ARMOR_BUFF_PER_CLONE/_clone_stat_buff_tick below), Doppelganger's
brief both-direction damage immunity
(the generic "vanished" status — see core/status_library.py), Phantom
Rush's move-speed burst, and the spear weapon/clone animation.

The clone army itself is the generic core/clone_army.py building block
(CloneArmy), configured here with can_attack=True (a basic-attack-alike, no
skills) and has_statuses=True — a nearby clone stands in an enemy zone
(Blood Pool/Sacred Ground/Static Field) just like a real fighter would, and
also mirrors whatever DoT status (bleed/poison/burn/curse/corruption/
frozen) is actively ticking on Phantom Lancer itself, through the exact
same generic status_library.py formula, so a Sukuna bleed or a Vampire
poison hurts the illusions standing next to it too. An AoE-tagged ability
(Ability.aoe_radius/aoe_cone_deg — Axe Throw's fan, an ultimate's blast,
...) landing anywhere near Phantom Lancer automatically also damages every
illusion of this army its own shape covers — see combat_resolution.
splash_aoe_to_clones, which reads this army back through clone_army()
below; no bespoke per-ability wiring needed here at all, and no redirect
involved either (an area ability is never redirected onto one body — it
damages each of them where they stand, whatever happened to Phantom Lancer
itself). Any eligible SINGLE-TARGET attack aimed at Phantom Lancer (any
such ability whose own moves.py doesn't set ignore_clone=True — see
abilities.Ability and status_library.taunt_redirect — regardless of
basic/skill/ultimate) can instead land on one of its clones in place of
Phantom Lancer — but only a clone actually standing close enough to Phantom
Lancer when the attack lands (see basic_attack_decoys/
status_library.taunt_redirect/CharacterPlugin.decoy_redirect_reach), never
a random pick off however many clones are out roaming elsewhere on the
field. See core/clone_army.py for the full menu of capabilities
(attack-less decoys, skill-mirroring, ...) any future character's own kit
can opt into instead. This file only owns Phantom Lancer's own numbers
(cap/stat%/duration, the Juxtapose buff swapping in richer ones) and its
own presentation (the spear weapon prop, both on Phantom Lancer itself and
on each clone)."""

import math
import random

import pygame

from ...core.clone_army import CloneArmy
from ...core.constants import AVATAR_R, GOLD, WHITE
from ...core.effects import draw_bolt_fx, draw_expanding_ring, draw_rotated, draw_slash_fx, draw_starburst, weapon_angle
from ...core.entities import set_status
from ...core.motions import ease_in, ease_out
from ...core.particles import Particle, emit_dark, emit_spark_burst
from ...core.plugin import CharacterPlugin
from .weapons import load_phantom_lancer_weapons

# Juxtapose passive: base cap/atk%/duration for a clone spawned off a
# landed Spear Slash/Spirit Lance, and the richer numbers used instead while
# the Juxtapose ultimate's own buff window is active (see _clone_spawn_params).
# stat_pct only ever scales atk — hp scales separately off CLONE_HP_PCT/
# JUXTAPOSE_CLONE_HP_PCT below (a pct of Phantom Lancer's own current
# max_hp, not atk), armor always stays CloneArmy's own flat clone_armor.
# Cut by another 30% (0.5/0.65 -> 0.35/0.45) — a full clone army was landing
# too much extra damage on top of Phantom Lancer's own hits.
BASE_CLONE_CAP = 5
BASE_CLONE_STAT_PCT = 0.65
BASE_CLONE_DURATION_S = 10
BASE_CLONE_HP_PCT = 0.1

JUXTAPOSE_DURATION_S = 15
JUXTAPOSE_CLONE_CAP = 8
JUXTAPOSE_CLONE_STAT_PCT = 0.85
JUXTAPOSE_CLONE_DURATION_S = 15
JUXTAPOSE_CLONE_HP_PCT = 0.15

# Juxtapose's other half: every clone currently alive also feeds Phantom
# Lancer's own outgoing damage and armor — CLONE_ATK_BUFF_PCT_PER_CLONE more
# of his own attack, plus CLONE_ARMOR_BUFF_PER_CLONE flat armor, per clone —
# recomputed every ambient_tick straight off the live army headcount (see
# _clone_stat_buff_tick) into self-refreshing "attack_up"/"armor_up"
# (status_library.py), the same live-condition-refresh pattern Legion
# Commander's Unyielding Resolve uses (see legion_commander/plugin.py's own
# ambient_tick) — never a stacked counter of its own to decay independently,
# so both rise with a fresh spawn and fall the instant a clone expires/dies/
# gets destroyed, in lockstep with the army itself. Read off the army's own
# len(), not stat_pct/cap, so it scales identically whether a clone came
# from a base spawn or a richer Juxtapose-ultimate one. 0.10 (not a smaller
# number) so even the 2 clones one landed hit spawns nudges the HUD's
# rounded ATK/ARM readout — a subtler pct here would round away invisibly at
# low clone counts and read as "doing nothing".
CLONE_ATK_BUFF_PCT_PER_CLONE = 0.15
CLONE_ARMOR_BUFF_PER_CLONE = 2.2
CLONE_ATK_BUFF_REFRESH_S = 0.25

# How often, and from how far away, each clone auto-attacks the opponent.
CLONE_ATTACK_COOLDOWN_S = 1
CLONE_ATTACK_RANGE = 100
CLONE_SPAWN_SPEED = (60, 100)  # matches core/assets.py's own spawn()
# How long a clone's own lance-thrust swing plays for — see
# CloneUnit.attack_anim_t / _draw_clone_lance.
CLONE_ATTACK_ANIM_S = 0.26

DOPPELGANGER_VANISH_S = 1
PHANTOM_RUSH_DURATION_S = 5
PHANTOM_RUSH_PCT = 2  # +100% move speed for the burst

# Idle resting pose for the lance prop (see _draw_lance) — held low and
# angled back, like a real lancer resting the shaft against a shoulder.
IDLE_ANGLE = 200
IDLE_OFFSET = pygame.Vector2(-10, 16)

# Clone glass-shatter transitions: an illusion is a reflection, so it
# arrives and leaves like one: a pane of blue glass. CloneArmy (core, not
# ours to edit) adds/removes clones from several paths (spawn, cap eviction,
# expiry, a lethal hit, a zone tick, the match ending), so rather than hook
# each one, draw_fx diffs the army's live clone list against last frame's
# (see _sync_clone_shatters) and starts a transition for every clone that
# appeared or vanished, whatever the cause. Leaving ("out"): a spiderweb of
# cracks over where it stood fades across SHATTER_OUT_S while
# SHATTER_OUT_SHARDS shards burst outward and fall. Arriving ("in"):
# SHATTER_IN_SHARDS shards fly inward from SHATTER_IN_REACH px out and meet
# at the clone as the same crack web flashes up and dissolves over
# SHATTER_IN_S, while the clone's own sprite fades in over that window
# (see _clone_sprite). SHATTER_RADIUS matches CloneArmy.draw's own ring.
GLASS_BLUE = (150, 210, 255)
GLASS_PALE = (220, 242, 255)
SHATTER_OUT_S = 0.36
SHATTER_IN_S = 0.26
SHATTER_OUT_SHARDS = 8
SHATTER_IN_SHARDS = 5
SHATTER_IN_REACH = (48, 72)
SHATTER_RADIUS = AVATAR_R + 6
SHATTER_CRACK_RAYS = 5
SHATTER_MAX_WEBS = 2


class PhantomLancerPlugin(CharacterPlugin):
    #: Ground crack this fighter's big hits leave (anime_fx.DECAL_STYLES):
    #: a lance-straight fan with illusion echoes.
    GROUND_DECAL = "phantom"
    #: Hit-flash flare (anime_fx.build_impact_burst_frames): a spectral four-point glint.
    BURST_TEXTURE = "magic_04"

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.army = CloneArmy(
            self, cap=BASE_CLONE_CAP, stat_pct=BASE_CLONE_STAT_PCT, duration=BASE_CLONE_DURATION_S,
            can_attack=True, has_statuses=True,
            attack_cooldown=CLONE_ATTACK_COOLDOWN_S, attack_range=CLONE_ATTACK_RANGE,
            attack_anim=CLONE_ATTACK_ANIM_S, spawn_speed=CLONE_SPAWN_SPEED,
            clone_hp_pct=BASE_CLONE_HP_PCT,
        )
        # Set/read by CloneArmy's own _clone_attack — guards on_damage_dealt
        # below from re-triggering the passive off a clone's own attack
        # (which also routes through deal_damage/attacker is self.fighter)
        # — only Phantom Lancer's own landed hit spawns a new clone, never a
        # clone spawning another clone.
        self._clone_army_resolving = False
        self.vanish_particle_cd = 0
        # Glass-shatter bookkeeping (see GLASS_BLUE above): last frame's
        # clones keyed by id() (holding the objects keeps those ids from
        # being reused), the live transitions, and which clones are still
        # materializing (id -> its "in" transition, read by _clone_sprite).
        self._known_clones = {}
        self._shatters = []
        self._materializing = {}

    def weapons(self):
        return load_phantom_lancer_weapons()

    def clone_army(self):
        """Read generically by combat_resolution.splash_aoe_to_clones — an
        AoE-tagged ability landing on Phantom Lancer automatically also
        damages whichever of these clones it actually catches, no bespoke
        wiring needed here at all."""
        return self.army

    # ---- Juxtapose passive: spawn-on-hit --------------------------------------
    def on_damage_dealt(self, attacker, defender, actual):
        if attacker is not self.fighter or actual <= 0 or self._clone_army_resolving:
            return
        battle = self.battle
        # Spirit Lance is a ranged shot landing out by the enemy — its
        # clone conjures in next to them there instead of back at Phantom
        # Lancer's own position (every other trigger — Spear Slash,
        # Juxtapose's own direct spawns — still conjures at Phantom
        # Lancer's feet).
        near = defender.pos if battle.ability is not None and battle.ability.tag == "spirit_lance" else None
        self.spawn_clone(near)
        self.spawn_clone(near)

    def _clone_spawn_params(self):
        """Juxtapose's own buff (a bespoke marker status, not a generic
        status_library.py effect — same pattern as Raiju's "static" stack
        counter) swaps in a higher cap and richer stats/duration/hp for
        every spawn while it's up."""
        if "juxtapose" in self.fighter.statuses:
            return JUXTAPOSE_CLONE_CAP, JUXTAPOSE_CLONE_STAT_PCT, JUXTAPOSE_CLONE_DURATION_S, JUXTAPOSE_CLONE_HP_PCT
        return BASE_CLONE_CAP, BASE_CLONE_STAT_PCT, BASE_CLONE_DURATION_S, BASE_CLONE_HP_PCT

    def spawn_clone(self, near=None):
        cap, stat_pct, duration, hp_pct = self._clone_spawn_params()
        return self.army.spawn(near, cap=cap, stat_pct=stat_pct, duration=duration, hp_pct=hp_pct)

    # ---- clone army: movement + auto-attack (ambient, every frame) -----------
    def ambient_tick(self, dt):
        self._vanish_shimmer_tick(dt)
        self.army.tick(dt)
        self._clone_stat_buff_tick()
        self._age_shatters(dt)

    def _age_shatters(self, dt):
        """Advance every glass-shatter transition on the simulation clock
        (so a frozen match freezes them too) and drop finished ones."""
        for s in self._shatters:
            s["elapsed"] += dt
        self._shatters = [s for s in self._shatters if s["elapsed"] < s["duration"]]
        self._materializing = {
            cid: s for cid, s in self._materializing.items() if s["elapsed"] < s["duration"]
        }

    def _clone_stat_buff_tick(self):
        """See CLONE_ATK_BUFF_PCT_PER_CLONE/CLONE_ARMOR_BUFF_PER_CLONE
        above — Phantom Lancer's own attack_up/armor_up track the live
        clone count every frame, no stack counter of its own to fall out of
        sync with clones dying/expiring elsewhere."""
        pl = self.fighter
        stacks = len(self.army.clones)
        if stacks > 0:
            set_status(pl, "attack_up", CLONE_ATK_BUFF_REFRESH_S, pct=stacks * CLONE_ATK_BUFF_PCT_PER_CLONE)
            set_status(pl, "armor_up", CLONE_ATK_BUFF_REFRESH_S, amount=stacks * CLONE_ARMOR_BUFF_PER_CLONE)
        else:
            pl.statuses.pop("attack_up", None)
            pl.statuses.pop("armor_up", None)

    def extra_colliders(self):
        """Illusions are physical bodies too — this lets battle_loop's
        generic resolve_collisions bounce them off f1/f2/each other instead
        of drifting straight through."""
        return self.army.extra_colliders()

    def basic_attack_decoys(self):
        """Fed into status_library.taunt_redirect: every living clone is a
        candidate stand-in for Phantom Lancer itself against any incoming
        eligible attack (single-target melee/instant/teleport, bolt,
        ricochet — see taunt_redirect for exactly which — regardless of
        basic/skill/ultimate) — but only whichever clone is actually
        standing within decoy_redirect_reach() of Phantom Lancer when the
        attack lands ever takes it instead, never guaranteed and never a
        blind lottery among clones roaming elsewhere on the field (unlike
        Vampire's taunting decoy, which is a guaranteed redirect). An area
        ability never draws from this pool at all: it has no one target to
        swap out, it simply damages every illusion standing in its own area
        (see combat_resolution.splash_aoe_to_clones)."""
        return self.army.redirect_pool()

    def on_attack_redirected(self):
        """An eligible single-target attack aimed at Phantom Lancer got
        redirected onto one of its own clones instead (see
        basic_attack_decoys/status_library.taunt_redirect) — resolve the hit
        against that clone's own hp (armor-less, no shield/reflect — a plain
        illusion, not a full pipeline target) instead of Phantom Lancer
        taking it. Never reached by an area ability, which is excluded from
        redirect entirely: returning True here resolves the whole cast
        against this one clone and stops do_damage(), which for an area
        ability would leave every other body inside its area untouched."""
        battle = self.battle
        clone = battle.redirect_target
        if clone is None or clone not in self.army.clones:
            return False
        attacker, ability = battle.attacker, battle.ability
        dmg = round(attacker.atk * ability.dmg_mult)
        dmg = round(dmg * battle.status_outgoing_multiplier(attacker))
        # ability/knock_dir let damage_clone give this clone the same
        # tiered hit-flash/knockback ImpactFXMixin.apply_impact would
        # give the real Phantom Lancer for this same ability (see
        # CloneArmy.damage_clone) — pushed back along the attacker's own
        # swing direction, same as a real fighter's own knockback.
        actual = self.army.damage_clone(clone, dmg, ability=ability, knock_dir=battle.atk_dir)
        battle.damage_applied = True
        # _miss deliberately left False — the illusion really did get hit,
        # so apply_ability_tag_effects still runs right after this and
        # lands the attack's own tag effect (Sukuna's bleed, Raiju's static
        # stack, ...) on it (redirect_target, read back generically by
        # status_effects.apply_ability_tag_effects) instead of on the real
        # Phantom Lancer, who was never actually touched.
        battle.log = f"{attacker.name}'s {ability.name} strikes one of {self.fighter.name}'s illusions for {actual}!"
        attacker.meter = min(attacker.meter_max, attacker.meter + attacker.meter_gain)
        return True

    def _vanish_shimmer_tick(self, dt):
        """A faint, continuous ghost-mote trail for as long as Doppelganger's
        "vanished" status is up — on top of the fade in render.py (driven by
        f.vanish_alpha) and the vanish/reappear puffs below, so the whole
        window reads as an ongoing effect instead of just two one-off pops."""
        pl = self.fighter
        if "vanished" not in pl.statuses:
            self.vanish_particle_cd = 0
            return
        self.vanish_particle_cd -= dt
        if self.vanish_particle_cd <= 0:
            emit_dark(self.battle.fx, pl.pos, count=3, radius=30)
            self.vanish_particle_cd = 0.06

    def on_status_expire(self, fighter, name, data):
        """Doppelganger's reappear beat — the mirror of the vanish puff in
        apply_tag_effects below, so stepping back into phase gets its own
        visual moment instead of just the alpha fade-in finishing quietly.
        Also its own payoff: reappearing conjures one more clone right next
        to Phantom Lancer, on top of whatever Spear Slash/Spirit Lance
        already spawned during the vanish window."""
        if fighter is not self.fighter or name != "vanished":
            return
        battle = self.battle
        battle.add_ring(fighter.pos, 55, 0.32, fighter.color, width=3)
        emit_dark(battle.fx, fighter.pos, count=18, radius=40)
        self.spawn_clone()
        self.spawn_clone()
        self.spawn_clone()

    # ---- Doppelganger / Phantom Rush / Juxtapose ------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        battle, tag = self.battle, ability.tag
        if tag == "doppelganger":
            # Status: vanished (both-direction damage immunity, see
            # core/status_library.py) — movement is untouched, so Phantom
            # Lancer just keeps drifting on its current DVD-logo heading.
            set_status(attacker, "vanished", DOPPELGANGER_VANISH_S)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 55, -0.5, 255, "Vanished!", WHITE])
            battle.log = f"{attacker.name} slips out of phase — Doppelganger!"
            battle.add_ring(attacker.pos, 70, 0.4, attacker.color, width=4)
            emit_dark(battle.fx, attacker.pos, count=26, radius=50)
        elif tag == "phantom_rush":
            # Status: move_speed_up (the generic movement buff)
            set_status(attacker, "move_speed_up", PHANTOM_RUSH_DURATION_S, pct=PHANTOM_RUSH_PCT)
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 55, -0.5, 255, "Phantom Rush!", attacker.color])
            battle.log = f"{attacker.name} surges forward — Phantom Rush!"
            battle.add_ring(attacker.pos, 60, 0.35, attacker.color, width=3)
            emit_spark_burst(battle.fx, attacker.pos, attacker.color, count=18)
        elif tag == "juxtapose":
            # Status: juxtapose — see _clone_spawn_params. The ultimate's
            # own payoff is two clones conjured immediately at those
            # boosted numbers (set_status runs first, so spawn_clone()
            # already sees it active).
            set_status(attacker, "juxtapose", JUXTAPOSE_DURATION_S)
            self.spawn_clone()
            self.spawn_clone()
            self.spawn_clone()
            battle.floaters.append([attacker.pos.x, attacker.pos.y - 70, -0.6, 255, "JUXTAPOSE!", attacker.color])
            battle.log = f"{attacker.name} calls forth an army of illusions — Juxtapose!"
            battle.flash_timer = max(battle.flash_timer, 0.42)
            battle.add_screen_shake(18, 0.28)
            battle.add_ring(attacker.pos, 160, 0.7, attacker.color, width=6)
            emit_dark(battle.fx, attacker.pos, count=40, radius=80)

    # ---- presentation ----------------------------------------------------------
    def draw_projectile(self, screen):
        battle = self.battle
        if not (battle.attacker is self.fighter and battle.projectile_pos and battle.ability.name == "Spirit Lance"):
            return False
        draw_bolt_fx(screen, battle.projectile_pos, battle.atk_dir, GOLD, size=1.1 if battle.ability.big else 1.0)
        return True

    def draw_fx(self, screen, shake_x):
        self._draw_lance(screen, shake_x)
        self._sync_clone_shatters()
        self.army.draw(screen, shake_x, draw_weapon=self._draw_clone_lance, sprite_for=self._clone_sprite)
        self._draw_shatters(screen, shake_x)

    # ---- clone glass-shatter transitions ----------------------------------------
    def _sync_clone_shatters(self):
        """Diff the army's live clones against last frame's and start a
        glass transition for each arrival/departure (see GLASS_BLUE above).
        Runs from draw_fx rather than ambient_tick because clones also get
        spawned by attack resolution after ambient_tick in the same update,
        which would leave a fresh clone drawn for one frame with no glass."""
        current = {id(c): c for c in self.army.clones}
        for cid, clone in current.items():
            if cid not in self._known_clones:
                self._materializing[cid] = self._start_shatter(clone.pos, "in")
        for cid, clone in self._known_clones.items():
            if cid not in current:
                self._materializing.pop(cid, None)
                self._start_shatter(clone.pos + clone.visual_recoil, "out")
        self._known_clones = current

    def _start_shatter(self, pos, kind):
        """Bake one transition's crack web and emit its shards. Shards are
        rotating "square" particles (a spun square reads as a glass
        diamond), mixed with a few white glints; "out" bursts them outward
        under gravity, "in" launches them from a ring toward `pos`, timed
        to arrive as they fade."""
        pos = pygame.Vector2(pos)
        fx = self.battle.fx
        if kind == "out":
            for _ in range(SHATTER_OUT_SHARDS):
                ang = random.uniform(0, math.tau)
                d = pygame.Vector2(math.cos(ang), math.sin(ang))
                start = pos + d * random.uniform(0, SHATTER_RADIUS * 0.7)
                vel = d * random.uniform(90, 260) + pygame.Vector2(0, -random.uniform(20, 80))
                fx.emit(Particle(start, vel, random.uniform(0.35, 0.6), random.uniform(2.0, 4.2),
                                 random.choice((GLASS_BLUE, GLASS_PALE, self.fighter.color)),
                                 gravity=320, drag=0.95, kind="square",
                                 rotation=random.uniform(0, math.tau),
                                 rotation_speed=random.uniform(-14, 14)))
            for _ in range(3):
                ang = random.uniform(0, math.tau)
                vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * random.uniform(160, 300)
                fx.emit(Particle(pos, vel, random.uniform(0.12, 0.22), 1.5, WHITE, drag=0.85, kind="spark"))
            duration = SHATTER_OUT_S
        else:
            for _ in range(SHATTER_IN_SHARDS):
                ang = random.uniform(0, math.tau)
                d = pygame.Vector2(math.cos(ang), math.sin(ang))
                dist = random.uniform(*SHATTER_IN_REACH)
                life = random.uniform(0.8, 1.0) * SHATTER_IN_S
                fx.emit(Particle(pos + d * dist, -d * (dist / life), life, random.uniform(2.0, 3.6),
                                 random.choice((GLASS_BLUE, GLASS_PALE)), kind="square",
                                 rotation=random.uniform(0, math.tau),
                                 rotation_speed=random.uniform(-10, 10)))
            duration = SHATTER_IN_S
        # Only a breaking clone shows the cracked pane; a spawn-in is just
        # the shards gathering, so a Juxtapose wave isn't a wall of webs.
        # Capped at SHATTER_MAX_WEBS on screen, so a whole wave of clones
        # expiring together breaks into shards, not a wall of webs.
        live_webs = sum(1 for s in self._shatters if s["web"] is not None)
        web = self._bake_crack_web() if kind == "out" and live_webs < SHATTER_MAX_WEBS else None
        shatter = {"pos": pos, "kind": kind, "elapsed": 0.0, "duration": duration, "web": web}
        self._shatters.append(shatter)
        return shatter

    def _bake_crack_web(self):
        """A shattered-pane spiderweb baked onto its own surface once per
        transition: a faint blue disc (the pane), SHATTER_CRACK_RAYS jagged
        rays from an impact point near the center out to the rim, and two
        rings of chords linking neighboring rays, each crack a blue line
        with a pale core."""
        r = SHATTER_RADIUS
        dim = int(r * 2 + 8)
        c = pygame.Vector2(dim / 2, dim / 2)
        surf = pygame.Surface((dim, dim), pygame.SRCALPHA)
        pygame.draw.circle(surf, (*GLASS_BLUE, 46), c, r)
        pygame.draw.circle(surf, (*GLASS_PALE, 200), c, r, width=2)
        base = random.uniform(0, math.tau)
        rays = []
        for i in range(SHATTER_CRACK_RAYS):
            ang = base + i * math.tau / SHATTER_CRACK_RAYS + random.uniform(-0.25, 0.25)
            pts = [c + pygame.Vector2(random.uniform(-2, 2), random.uniform(-2, 2))]
            for step in (0.35, 0.68, 1.0):
                a = ang + random.uniform(-0.18, 0.18)
                pts.append(c + pygame.Vector2(math.cos(a), math.sin(a)) * (r * step))
            rays.append(pts)
        for pts in rays:
            pygame.draw.lines(surf, (*GLASS_BLUE, 230), False, pts, 3)
            pygame.draw.lines(surf, (*GLASS_PALE, 255), False, pts, 1)
        for ring in (1, 2):
            for i in range(len(rays)):
                a, b = rays[i][ring], rays[(i + 1) % len(rays)][ring]
                pygame.draw.line(surf, (*GLASS_BLUE, 200), a, b, 2)
                pygame.draw.line(surf, (*GLASS_PALE, 230), a, b, 1)
        return surf

    def _draw_shatters(self, screen, shake_x):
        """Draw every live transition's crack web, drawn after the clones so
        an arriving clone is seen through its pane. "out" starts fully
        cracked and fades; "in" flashes up then dissolves (sin curve), the
        glass healing into the illusion."""
        for s in self._shatters:
            t = min(1.0, s["elapsed"] / s["duration"])
            fade = (1 - t) if s["kind"] == "out" else math.sin(math.pi * t)
            alpha = round(255 * max(0.0, fade))
            if alpha <= 0:
                continue
            web = s["web"]
            if web is None:
                continue
            web.set_alpha(alpha)
            pos = s["pos"] + pygame.Vector2(shake_x, 0)
            screen.blit(web, web.get_rect(center=(round(pos.x), round(pos.y))))

    def _clone_sprite(self, clone):
        """CloneArmy.draw's sprite_for callback: Phantom Lancer's own image
        (the default look), faded in with its alpha baked into the pixels
        while the clone is still materializing, since CloneArmy.draw resets
        the copy's surface alpha itself every frame."""
        img = self.fighter.image
        s = self._materializing.get(id(clone))
        if s is None:
            return img
        ratio = min(1.0, s["elapsed"] / s["duration"])
        faded = img.copy()
        faded.fill((255, 255, 255, round(255 * ratio)), special_flags=pygame.BLEND_RGBA_MULT)
        return faded

    def _draw_lance(self, screen, shake_x):
        """The lance: rested low when idle, two quick forward jabs for Spear
        Slash. Mirrors Berserker's own "slash" motion structure exactly
        (windup/slash1/slash2/return — see MOTIONS["slash"] in
        core/motions.py and Reckless Cleave's draw_fx) since Spear Slash
        uses that same stationary-double-hit motion, just a straight thrust
        each time instead of a crossing claw-rake."""
        battle, pl = self.battle, self.fighter
        if not pl.is_alive():
            return
        img = battle.weapons["lancer"]
        pos0 = pl.pos + pygame.Vector2(shake_x, 0)
        # Fades in lockstep with the sprite itself (see render.py's
        # draw_fighter) — Vanished (Doppelganger) hides the whole character,
        # weapon included, not just the body.
        weapon_alpha = round(max(0.0, min(255.0, pl.vanish_alpha)))

        active = battle.mode == "attack" and battle.attacker is pl and battle.ability.name == "Spear Slash"
        if not active:
            draw_rotated(screen, img, pos0 + IDLE_OFFSET, IDLE_ANGLE, alpha=weapon_alpha)
            return

        phase, t = battle.current_phase, battle.phase_t
        tip_reach = AVATAR_R + 34
        if phase == "windup":
            reach, extra = 8, -18 * ease_out(t)
        elif phase == "slash1":
            reach = 8 + (tip_reach - 8) * ease_in(t)
            extra = -18 + 18 * ease_in(t)
        elif phase == "slash2":
            # A second, slightly deeper jab — pulled back a touch from
            # slash1's full extension before stabbing out again.
            reach = 14 + (tip_reach - 14) * ease_in(t)
            extra = 0
        else:  # return
            reach = tip_reach - (tip_reach - 12) * ease_out(t)
            extra = 0
        # No +180 here (unlike Berserker's axe): a spear thrust needs the
        # blade tip itself leading along atk_dir, not the butt end.
        angle = weapon_angle(battle.atk_dir, extra)
        pos = pos0 + battle.atk_dir * reach
        draw_rotated(screen, img, pos, angle, alpha=weapon_alpha)

        # The painted slash flipbook rides the whole thrust (drawn on top of
        # the lance, same tip position); the starburst/ring pop only fires
        # right as each jab reaches full extension.
        if phase in ("slash1", "slash2"):
            strike_pos = pos0 + battle.atk_dir * tip_reach
            draw_slash_fx(screen, strike_pos, battle.atk_dir, t, size=85 if phase == "slash1" else 95)
            if t > 0.55:
                size = 22 if phase == "slash1" else 26
                ring = 30 if phase == "slash1" else 34
                draw_starburst(screen, strike_pos, WHITE, size=size, fade=(1 - t) / 0.45)
                draw_expanding_ring(screen, strike_pos, ring * t, pl.color, width=3)

    def _draw_clone_lance(self, screen, clone, pos):
        """Rested low when idle, one continuous thrust-out-and-back when
        clone.attack_anim_t is counting down (see CloneArmy._clone_attack) —
        a single-arc version of Phantom Lancer's own windup/strike/impact/
        return, since a clone has no phase machine of its own to drive it.
        Passed to CloneArmy.draw() as its draw_weapon callback. Full-size,
        same prop image the real Phantom Lancer holds — no scaled-down
        clone-only copy."""
        img = self.battle.weapons["lancer"]
        if clone.attack_anim_t > 0:
            t = 1 - clone.attack_anim_t / CLONE_ATTACK_ANIM_S
            reach = 8 + (AVATAR_R + 18) * math.sin(math.pi * t)
            angle = weapon_angle(clone.attack_dir, 0)
            weapon_pos = pos + clone.attack_dir * reach
            # Same impact starburst/ring the real Spear Slash fires at the
            # tip of its thrust (see _draw_lance's slash2 branch above) — a
            # single hit here instead of two, timed to the reach's own peak
            # (t=0.5) rather than a fixed phase_t threshold, since a clone
            # has no windup/slash1/slash2 phase machine of its own.
            if 0.4 < t < 0.6:
                fade = 1 - abs(t - 0.5) / 0.2
                draw_starburst(screen, weapon_pos, WHITE, size=26, fade=fade)
                draw_expanding_ring(screen, weapon_pos, 34 * fade, self.fighter.color, width=3)
        else:
            weapon_pos = pos + IDLE_OFFSET * 0.8
            angle = IDLE_ANGLE
        draw_rotated(screen, img, weapon_pos, angle)
