"""
BattleAnimation — the state machine and renderer that ties everything
together: roaming/bouncing movement, picking and animating abilities,
status effects, zones, the clone, and drawing every frame.

The actual logic is split into focused mixins, one per concern, combined
below into a single class (all mixins share one instance, so `self.x` set
in one file is visible to methods defined in any other):

    core/plugin.py             — the CharacterPlugin interface every fighter's
                                  own module implements (see below)
    core/impact_fx.py          — shared hit-feedback (shake, hit-stop, rings, impact particles)
    core/combat_resolution.py  — the generic damage/heal pipeline + roam/attack sequencing
    core/status_effects.py     — dispatches tag effects/status-expiry/zone-ticks to plugins
    core/battle_loop.py        — the per-frame update tick + motion-phase math
    core/render.py             — the draw() orchestrator + arena/fighter/projectile rendering
    ui/hud.py                  — title, status panels, floaters, log, overlays

Every character-specific number, side effect, and animation lives in that
character's own characters/<name>/plugin.py, discovered generically through
core/assets.py's CHARACTERS registry — this file only wires the two fighters
actually in the match to their plugins and owns construction (__init__).
Adding a new fighter never touches this file (or any other file listed
above): write characters/<name>/plugin.py and register it in CHARACTERS.
"""

import random

import pygame

from .core.assets import CHARACTERS
from .core.attack_state import ATTACK_STATE_FIELDS
from .core.battle_loop import BattleLoopMixin
from .core.camera import CameraShake
from .core.combat_resolution import CombatResolutionMixin
from .core.constants import ARENA_RECT
from .core.impact_fx import ImpactFXMixin
from .core.particles import ParticleSystem
from .core.render import RenderMixin
from .core.status_effects import StatusEffectsMixin
from .core.status_library import StatusLibraryMixin
from .ui.hud import HUDMixin


def _attack_state_property(name):
    """self.<name> reads/writes through whichever AttackState is currently
    bound as self._current — see BattleAnimation.attacks/_current below.
    Every combat_resolution.py/battle_loop.py/render.py reference to (say)
    self.ability, and every character plugin's battle.ability, keeps
    working unchanged: it now means "the attack currently being processed"
    rather than "the one attack the whole match can ever have in flight"."""
    def getter(self):
        return getattr(self._current, name)

    def setter(self, value):
        setattr(self._current, name, value)

    return property(getter, setter)


class BattleAnimation(
    CombatResolutionMixin, StatusEffectsMixin, StatusLibraryMixin, ImpactFXMixin, BattleLoopMixin, RenderMixin,
    HUDMixin,
):
    def __init__(self, f1, f2):
        self.f1, self.f2 = f1, f2
        # One CharacterPlugin instance per fighter actually in this match —
        # in CHARACTERS registry order, so presentation layering (weapon fx,
        # impact particles) matches a fixed, deterministic priority
        # regardless of which fighter is f1 vs f2. Every other file in this
        # list talks to fighters only through this list/plugin_for(), never
        # by name — that's what lets a new character slot in with zero
        # edits outside characters/<name>/.
        self.plugins = [
            CHARACTERS[key]["plugin_cls"](self, f)
            for key in CHARACTERS
            for f in (f1, f2)
            if f.key == key
        ]
        self.weapons = {}
        for plugin in self.plugins:
            self.weapons.update(plugin.weapons())
        self.font_big = pygame.font.SysFont("consolas", 28, bold=True)
        self.font_mid = pygame.font.SysFont("consolas", 17, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 12, bold=True)

        self.log = "Battle begins!"
        self.winner = None
        self.floaters = []  # [x, y, vy, alpha, text, color]

        self.zones = []
        self.clone = None
        self.flash_timer = 0

        # Visual-feel state: camera shake, hit-stop, particles, rings and
        # afterimages are pure presentation and never read by gameplay logic.
        self.camera_shake = CameraShake()
        self.hit_stop_timer = 0
        # Ultimate impacts dip below 1.0 and ease back over TIME_SCALE_RECOVER_S —
        # unlike hit-stop's full freeze, the attack animation keeps moving, just slowed.
        self.time_scale = 1.0
        # Camera punch-in on a heavy/ultimate impact, eased back to 1.0 (see render.py draw()).
        self.zoom = 1.0
        self.afterimages = []  # [{"image", "pos", "alpha"}]
        self.afterimage_cd = 0

        self.fx = ParticleSystem()  # impact sparks, blood, holy light, debris...
        self.rings = []  # [{"pos","radius","max_radius","start_radius","color","elapsed","duration"}]
        self.debug = False

        # Each fighter's own in-flight ability, if any — see
        # core/attack_state.py. At most one entry per fighter (keyed by the
        # attacker), so up to 2 at once: this (plus self._current, the
        # AttackState whichever combat_resolution.py/battle_loop.py/
        # render.py call currently in progress is operating on) is what
        # lets both fighters cast independently instead of the whole match
        # sharing one global "current attack". self.attacker/self.ability/
        # etc. below all read/write through self._current, so every
        # existing reference to them (including every character plugin's
        # battle.attacker/battle.ability/...) keeps meaning exactly what it
        # already did, just scoped to whichever attack is bound right now.
        self.attacks = {}
        self._current = None

        self.weapon_trail = []

        self.particles = [
            {
                "pos": pygame.Vector2(
                    random.uniform(ARENA_RECT.left, ARENA_RECT.right),
                    random.uniform(ARENA_RECT.top, ARENA_RECT.bottom),
                ),
                "vel": pygame.Vector2(random.uniform(-6, 6), random.uniform(4, 14)),
                "r": random.uniform(1, 2.4),
                "shade": random.choice([(70, 15, 20), (95, 20, 25), (55, 12, 16)]),
            }
            for _ in range(45)
        ]

    def plugin_for(self, character):
        """The CharacterPlugin instance owning `character` (self.f1's or
        self.f2's plugin), or None — e.g. when `character` is the Vampire's
        clone decoy rather than a real fighter."""
        for plugin in self.plugins:
            if plugin.fighter is character:
                return plugin
        return None

    def defending_state(self, character):
        """The AttackState (if any) whose defender is `character` — used
        wherever code needs to know "is someone else's attack currently
        aimed at this fighter", which self.attacks (keyed by attacker) can't
        answer directly. At most one such state at a time (each fighter can
        only be attacking one target, the other fighter)."""
        for state in self.attacks.values():
            if state.defender is character:
                return state
        return None

    # self.attacker, self.ability, self.seq, self.projectile_pos, ... —
    # every field of whichever AttackState is bound as self._current, set
    # up as properties below the class body once ATTACK_STATE_FIELDS is
    # known (see _attack_state_property above).
    @property
    def mode(self):
        """"gameover" once a winner is set, else "attack" while a specific
        AttackState is bound as self._current (i.e. from inside code
        processing one fighter's own attack), else "roam". Every character
        plugin's battle.mode == "attack" check runs from inside exactly
        that kind of bound call, so this keeps meaning "is the attack I'm
        currently looking at in progress" even though several attacks (one
        per fighter) can now exist at once — see self.attacks/_current."""
        if self.winner is not None:
            return "gameover"
        return "attack" if self._current is not None else "roam"


for _field in ATTACK_STATE_FIELDS:
    setattr(BattleAnimation, _field, _attack_state_property(_field))
del _field
