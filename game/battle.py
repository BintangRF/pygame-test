"""
BattleAnimation — the state machine and renderer that ties everything
together: roaming/bouncing movement, picking and animating abilities,
status effects, zones, the clone, Eternal Night, and drawing every frame.

The actual logic is split into focused mixins, one per concern, combined
below into a single class (all mixins share one instance, so `self.x` set
in one file is visible to methods defined in any other):

    core/impact_fx.py         — shared hit-feedback (shake, hit-stop, rings, impact particles)
    core/combat_resolution.py — the generic damage/heal pipeline + roam/attack sequencing
    core/status_effects.py    — dispatches tag effects/status-expiry/zone-ticks to characters/*/ability.py
    core/battle_loop.py       — the per-frame update tick + motion-phase math
    core/render.py            — the draw() orchestrator + arena/fighter/projectile rendering
    ui/hud.py                 — title, status panels, floaters, log, overlays
    characters/paladin/ability.py     — Paladin's ability logic (shield, radiant energy, mark, sacred ground)
    characters/vampire/ability.py     — Vampire's ability logic (clone, curse, blood pool, eternal night)
    characters/berserker/ability.py   — Berserker's ability logic (rage, fury passive, last stand)
    characters/sukuna/ability.py      — Sukuna's ability logic (bleed, Kai flurry, Kamino)
    characters/raiju/ability.py       — Raiju's ability logic (ambush, static stacks, overcharge)
    characters/johnny/ability.py      — Johnny's ability logic (Nail Bullet ammo, crit/bleed, wall teleport, pin)
    characters/paladin/fx.py          — Paladin's weapon animation
    characters/berserker/fx.py        — Berserker's axe animation
    characters/sukuna/fx.py           — Sukuna's curse-technique animation
    characters/raiju/fx.py            — Raiju's lightning/teleport animation
    characters/johnny/fx.py           — Johnny's nail/teleport animation

This file only wires those together and owns construction (__init__).
"""

import random

import pygame

from .characters.berserker.ability import BerserkerAbilityMixin
from .characters.berserker.fx import BerserkerFXMixin
from .characters.berserker.weapons import load_berserker_weapons
from .characters.johnny.ability import JohnnyAbilityMixin
from .characters.johnny.fx import JohnnyFXMixin
from .characters.paladin.ability import PaladinAbilityMixin
from .characters.paladin.fx import PaladinFXMixin
from .characters.paladin.weapons import load_paladin_weapons
from .characters.raiju.ability import RaijuAbilityMixin
from .characters.raiju.fx import RaijuFXMixin
from .characters.sukuna.ability import SukunaAbilityMixin
from .characters.sukuna.fx import SukunaFXMixin
from .characters.vampire.ability import VampireAbilityMixin
from .core.battle_loop import BattleLoopMixin
from .core.camera import CameraShake
from .core.combat_resolution import CombatResolutionMixin
from .core.constants import ARENA_RECT
from .core.impact_fx import ImpactFXMixin
from .core.particles import ParticleSystem
from .core.render import RenderMixin
from .core.status_effects import StatusEffectsMixin
from .ui.hud import HUDMixin


def find_by_key(f1, f2, key):
    """Return whichever of f1/f2 is the given character type, or None if
    neither is — lets character-specific mechanics degrade cleanly in any
    matchup instead of assuming a fixed pair of fighters."""
    if f1.key == key:
        return f1
    if f2.key == key:
        return f2
    return None


class BattleAnimation(
    CombatResolutionMixin, StatusEffectsMixin, ImpactFXMixin, BattleLoopMixin,
    RenderMixin, HUDMixin, PaladinFXMixin, BerserkerFXMixin, SukunaFXMixin, RaijuFXMixin, JohnnyFXMixin,
    PaladinAbilityMixin, VampireAbilityMixin, BerserkerAbilityMixin, SukunaAbilityMixin, RaijuAbilityMixin,
    JohnnyAbilityMixin,
):
    def __init__(self, f1, f2):
        self.f1, self.f2 = f1, f2
        # character-specific mechanics key off these — None when that
        # character isn't in this matchup, so their special-case branches
        # (checked via `is self.paladin` etc.) simply never fire
        self.paladin = find_by_key(f1, f2, "paladin")
        self.vampire = find_by_key(f1, f2, "vampire")
        self.berserker = find_by_key(f1, f2, "berserker")
        self.sukuna = find_by_key(f1, f2, "sukuna")
        self.raiju = find_by_key(f1, f2, "raiju")
        self.johnny = find_by_key(f1, f2, "johnny")
        self._kai_hits = self.KAI_BASE_HITS  # updated each time Kai resolves; read by draw_sukuna_effects
        self.johnny_reload_cd = JohnnyAbilityMixin.RELOAD_MS  # ms until Johnny's next Nail Bullet reloads
        self.weapons = {**load_paladin_weapons(), **load_berserker_weapons()}
        self.font_big = pygame.font.SysFont("consolas", 28, bold=True)
        self.font_mid = pygame.font.SysFont("consolas", 17, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 12, bold=True)

        self.log = "Battle begins!"
        self.winner = None
        self.floaters = []  # [x, y, vy, alpha, text, color]

        self.zones = []
        self.clone = None
        self.night_timer = 0
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
        self.night_afterimage_cd = 0
        self.night_particle_cd = 0
        self.rage_particle_cd = 0

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
