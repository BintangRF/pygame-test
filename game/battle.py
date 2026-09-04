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
        # Ultimate impacts dip below 1.0 and ease back over TIME_SCALE_RECOVER_MS —
        # unlike hit-stop's full freeze, the attack animation keeps moving, just slowed.
        self.time_scale = 1.0
        # Camera punch-in on a heavy/ultimate impact, eased back to 1.0 (see render.py draw()).
        self.zoom = 1.0
        self.afterimages = []  # [{"image", "pos", "alpha"}]
        self.afterimage_cd = 0

        self.fx = ParticleSystem()  # impact sparks, blood, holy light, debris...
        self.rings = []  # [{"pos","radius","max_radius","start_radius","color","elapsed","duration"}]
        self.debug = False

        self.mode = "roam"  # "roam" | "attack" | "gameover"

        self.attacker = None
        self.defender = None
        self.ability = None
        self.motion = None
        self.seq = None
        self.seq_index = 0
        self.phase_elapsed = 0
        self.current_phase = None
        self.damage_applied = False
        self._miss = False

        self.attacker_start = None
        self.defender_start = None
        self.strike_point = None
        self.atk_dir = pygame.Vector2(1, 0)
        self.projectile_pos = None
        # Dodgeable-bolt flight state (Nail Bullet — see is_dodgeable in
        # core/motions.py): where the nail was actually fired from and how
        # long it's been flying, so it can keep sailing past defender_start
        # instead of stopping there. Reset each attack in start_attack().
        self.projectile_origin = None
        self.projectile_travel_ms = 0.0
        # Tusk Act 3's ricocheting nail (see "ricochet" in core/motions.py
        # and ricochet_step in core/battle_loop.py): its own live position,
        # velocity, and how many walls it's bounced off so far. Reset each
        # attack in start_attack().
        self.ricochet_pos = None
        self.ricochet_vel = None
        self.ricochet_bounces = 0
        # True the instant a dodgeable shot's actual flown position (Nail
        # Bullet's straight line, or Tusk Act 3's bouncing one) ever comes
        # within CHARACTER_HITBOX_R of the defender's *live* position (set in
        # apply_motion_frame as it flies) — do_damage() reads this instead of
        # guessing from a single distance snapshot, so a real mid-flight
        # touch always counts as a hit. Reset each attack.
        self.projectile_hit_confirmed = False
        self.attack_final_pos = None
        self.attack_target_clone = False
        self.phase_t = 0.0
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
