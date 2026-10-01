"""
Per-shadow visual effects for Sukuna's Ten Shadows, so each shadow reads as
its own thing instead of every one sharing the same crimson ring and puff.
All textures are from the Kenney Particle Pack (CC0, assets/fx/kenney) —
white-on-black premultiplied art, so it is tinted by a color multiply and
added onto the screen (BLEND_RGBA_ADD), fading by darkening the tint.

Each shadow gets up to three layers:
- an aura drawn under its sprite every frame (draw_auras): Round Deer's
  healing rune, Tiger Funeral's taunt sigil, Mahoraga's golden wheel;
- a trail emitted while it moves (tick): Divine Dog's shadow wisps, Nue's
  static crackle, Great Serpent's venom bubbles, Piercing Ox's charge streak;
- a hit effect when its basic attack lands (on_hit): claw rake, lightning
  strike, constricting coil, tongue lash, ...

plus one-off moments (on_summon, on_rabbit_split, on_ox_impact,
on_toad_land, on_mahoraga_adapt, on_elephant_wave). Purely cosmetic: none
of it reads or writes combat state.
"""

import math
import random

import pygame

from ...core.asset_loading import load_sprite
from ...core.glow import glow_line

KENNEY_DIR = "fx/kenney"

DOG_COLOR = (150, 130, 230)
NUE_COLOR = (120, 210, 255)
NUE_HOT = (255, 245, 150)
SERPENT_COLOR = (120, 235, 90)
TOAD_TONGUE = (255, 110, 170)
TOAD_WATER = (100, 210, 190)
RABBIT_COLOR = (235, 240, 255)
ELEPHANT_COLOR = (80, 170, 220)
OX_COLOR = (240, 150, 70)
DEER_COLOR = (130, 255, 170)
TIGER_COLOR = (255, 80, 50)
MAHORAGA_COLOR = (255, 205, 90)
SUMMON_COLOR = {
    "divine_dog": DOG_COLOR, "nue": NUE_COLOR, "great_serpent": SERPENT_COLOR, "toad": TOAD_WATER,
    "rabbit": RABBIT_COLOR, "max_elephant": ELEPHANT_COLOR, "piercing_ox": OX_COLOR,
    "round_deer": DEER_COLOR, "tiger_funeral": TIGER_COLOR, "mahoraga": MAHORAGA_COLOR,
}

#: Seconds between trail puffs per shadow key (see ShadowFX.tick).
TRAIL_INTERVAL = {"divine_dog": 0.05, "nue": 0.12, "great_serpent": 0.18, "round_deer": 0.22}

# Tinted textures are cached per (name, size, color); size is rounded to
# SIZE_STEP px and fade to ALPHA_STEPS levels so the cache stays small even
# though every burst grows and fades continuously.
SIZE_STEP = 4
ALPHA_STEPS = 12
_CACHE = {}


def _scale(color, k):
    return tuple(max(0, min(255, int(c * k))) for c in color[:3])


def _texture(name, size, color, fade):
    size = max(SIZE_STEP, int(round(size / SIZE_STEP)) * SIZE_STEP)
    level = max(0, min(ALPHA_STEPS, round(fade * ALPHA_STEPS)))
    key = (name, size, tuple(color[:3]), level)
    img = _CACHE.get(key)
    if img is None:
        img = load_sprite(f"{KENNEY_DIR}/{name}.png", size).copy()
        tint = _scale(color, level / ALPHA_STEPS)
        img.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
        _CACHE[key] = img
    return img


def _blit_add(screen, img, center, angle=0.0, stretch=None):
    if stretch is not None:
        w, h = img.get_size()
        img = pygame.transform.smoothscale(img, (max(1, int(w * stretch[0])), max(1, int(h * stretch[1]))))
    if angle:
        img = pygame.transform.rotate(img, angle)
    screen.blit(img, img.get_rect(center=(round(center[0]), round(center[1]))),
                special_flags=pygame.BLEND_RGBA_ADD)


def _deg(direction):
    """pygame.transform.rotate angle that turns a texture drawn pointing
    up (+y screen up) to face `direction`."""
    return -math.degrees(math.atan2(direction.y, direction.x)) - 90


class _Burst:
    """One textured sprite that lives `life` seconds: size lerps size0 ->
    size1, brightness fade0 -> fade1 (eased), rotating at `spin` deg/s.
    `stretch` squashes the texture (w, h multipliers) before rotating, for
    streaks and bolts. `follow` pins it to a moving object's pos."""

    __slots__ = ("name", "pos", "size0", "size1", "color", "life", "t", "angle", "spin",
                 "fade0", "fade1", "stretch", "vel", "follow")

    def __init__(self, name, pos, size0, size1, color, life, angle=0.0, spin=0.0,
                 fade0=1.0, fade1=0.0, stretch=None, vel=None, follow=None):
        self.name, self.pos, self.color, self.life = name, pygame.Vector2(pos), color, life
        self.size0, self.size1, self.angle, self.spin = size0, size1, angle, spin
        self.fade0, self.fade1, self.stretch, self.follow = fade0, fade1, stretch, follow
        self.vel = pygame.Vector2(vel) if vel is not None else None
        self.t = 0.0


class _Line:
    """A glowing segment between two points (Toad's tongue), optionally
    tracking moving endpoints."""

    __slots__ = ("a", "b", "color", "width", "life", "t", "follow_a", "follow_b")

    def __init__(self, a, b, color, width, life, follow_a=None, follow_b=None):
        self.a, self.b = pygame.Vector2(a), pygame.Vector2(b)
        self.color, self.width, self.life, self.t = color, width, life, 0.0
        self.follow_a, self.follow_b = follow_a, follow_b


class ShadowFX:
    def __init__(self):
        self.bursts = []
        self.lines = []
        self.time = 0.0

    # ---- generic ---------------------------------------------------------------
    def burst(self, name, pos, size0, size1, color, life, **kw):
        self.bursts.append(_Burst(name, pos, size0, size1, color, life, **kw))

    def tick(self, dt, clones):
        """Ages every burst/line and emits each living shadow's movement
        trail. Called once per frame from SukunaPlugin.ambient_tick."""
        self.time += dt
        alive = []
        for b in self.bursts:
            b.t += dt
            if b.t >= b.life:
                continue
            if b.vel is not None:
                b.pos += b.vel * dt
            if b.follow is not None:
                b.pos = pygame.Vector2(b.follow.pos)
            b.angle += b.spin * dt
            alive.append(b)
        self.bursts = alive
        lines = []
        for ln in self.lines:
            ln.t += dt
            if ln.t < ln.life:
                lines.append(ln)
        self.lines = lines
        for clone in clones:
            self._emit_trail(clone, dt)

    def _emit_trail(self, clone, dt):
        key = getattr(clone, "shadow_key", None)
        if key == "piercing_ox":
            if getattr(clone, "pierce_state", None) == "charge" and clone.vel.length_squared() > 0:
                d = clone.vel.normalize()
                self.burst("muzzle_02", clone.pos - d * 30, 120, 80, OX_COLOR, 0.22,
                           angle=_deg(-d), stretch=(0.6, 1.4))
                self.burst("smoke_03", clone.pos + pygame.Vector2(random.uniform(-14, 14), random.uniform(-14, 14)),
                           50, 90, _scale(OX_COLOR, 0.55), 0.45, angle=random.uniform(0, 360), spin=60)
            return
        interval = TRAIL_INTERVAL.get(key)
        if interval is None:
            return
        clone.fx_cd = getattr(clone, "fx_cd", 0.0) - dt
        if clone.fx_cd > 0:
            return
        clone.fx_cd = interval
        jitter = pygame.Vector2(random.uniform(-16, 16), random.uniform(-16, 16))
        if key == "divine_dog":
            self.burst("smoke_05", clone.pos + jitter, 40, 75, _scale(DOG_COLOR, 0.55), 0.5,
                       angle=random.uniform(0, 360), spin=random.uniform(-90, 90))
        elif key == "nue":
            self.burst("spark_04", clone.pos + jitter * 1.6, 70, 80, NUE_COLOR, 0.14,
                       angle=random.uniform(0, 360))
        elif key == "great_serpent":
            self.burst("circle_05", clone.pos + jitter, 14, 26, SERPENT_COLOR, 0.8,
                       vel=(random.uniform(-8, 8), -35), fade0=0.9)
        elif key == "round_deer":
            self.burst("star_04", clone.pos + jitter * 1.8, 34, 20, DEER_COLOR, 0.9,
                       vel=(0, -45), angle=random.uniform(0, 45))

    # ---- auras (under the sprite) ----------------------------------------------
    def draw_auras(self, screen, shake_x, clones):
        t = self.time
        for clone in clones:
            key = getattr(clone, "shadow_key", None)
            pos = clone.pos + pygame.Vector2(shake_x, 0)
            if key == "round_deer":
                pulse = 0.75 + 0.25 * math.sin(t * 3)
                _blit_add(screen, _texture("magic_02", 130, DEER_COLOR, 0.8 * pulse), pos, angle=t * 40)
                _blit_add(screen, _texture("light_01", 110, DEER_COLOR, 0.35 * pulse), pos)
            elif key == "tiger_funeral":
                pulse = 0.7 + 0.3 * math.sin(t * 5)
                _blit_add(screen, _texture("magic_01", 130, TIGER_COLOR, 0.9 * pulse), pos, angle=-t * 60)
                _blit_add(screen, _texture("circle_03", 100, TIGER_COLOR, 0.4 * pulse), pos)
            elif key == "mahoraga":
                size = clone_draw_size(clone) * 1.5
                _blit_add(screen, _texture("magic_03", size, MAHORAGA_COLOR, 0.45), pos, angle=t * 25)
                _blit_add(screen, _texture("light_03", size * 0.9, MAHORAGA_COLOR, 0.15), pos)
            elif key == "nue":
                flicker = 0.5 + 0.5 * random.random()
                _blit_add(screen, _texture("circle_05", 90, NUE_COLOR, 0.35 * flicker), pos)
            elif key == "divine_dog":
                _blit_add(screen, _texture("smoke_07", 95, DOG_COLOR, 0.35), pos, angle=t * 30)

    # ---- bursts/lines (over the sprite) ----------------------------------------
    def draw(self, screen, shake_x):
        off = pygame.Vector2(shake_x, 0)
        for ln in self.lines:
            a = (ln.follow_a.pos if ln.follow_a is not None else ln.a) + off
            b = (ln.follow_b.pos if ln.follow_b is not None else ln.b) + off
            k = ln.t / ln.life
            # Shoots out over the first half, retracts over the second.
            reach = min(1.0, k * 2) if k < 0.5 else max(0.0, 2 - k * 2)
            tip = a.lerp(b, reach)
            glow_line(screen, a, tip, ln.color, width=ln.width)
            _blit_add(screen, _texture("circle_05", 22, ln.color, 1.0), tip)
        for b in self.bursts:
            k = b.t / b.life
            size = b.size0 + (b.size1 - b.size0) * (1 - (1 - k) ** 2)
            fade = b.fade0 + (b.fade1 - b.fade0) * k * k
            if fade <= 0.02:
                continue
            _blit_add(screen, _texture(b.name, size, b.color, fade), b.pos + off, angle=b.angle, stretch=b.stretch)

    # ---- moments ---------------------------------------------------------------
    def on_summon(self, key, pos):
        color = SUMMON_COLOR.get(key, (220, 60, 60))
        self.burst("light_01", pos, 60, 170, color, 0.45)
        self.burst("smoke_09", pos, 70, 150, _scale(color, 0.6), 0.6, angle=random.uniform(0, 360), spin=90)
        self.burst("star_08", pos, 120, 60, color, 0.3)

    def on_hit(self, key, clone, target):
        """`clone` landed a basic attack on `target` (a fighter or a decoy)."""
        src, dst = pygame.Vector2(clone.pos), pygame.Vector2(target.pos)
        d = dst - src
        d = d.normalize() if d.length_squared() > 0 else pygame.Vector2(1, 0)
        if key == "divine_dog":
            # Three parallel claw rakes across the target, then a pale flash.
            perp = pygame.Vector2(-d.y, d.x)
            for i in (-1, 0, 1):
                self.burst("slash_03", dst + perp * i * 14, 90, 100, DOG_COLOR, 0.22,
                           angle=_deg(d) + 90, stretch=(0.35, 1.0))
            self.burst("scratch_01", dst, 110, 120, (255, 255, 255), 0.18, angle=_deg(d) + 45)
            self.burst("star_08", dst, 70, 30, DOG_COLOR, 0.2)
        elif key == "nue":
            # A bolt dropping out of the sky onto the target.
            self.burst("spark_05", dst - pygame.Vector2(0, 90), 210, 210, NUE_HOT, 0.2, stretch=(0.7, 1.0))
            self.burst("spark_02", dst, 120, 150, NUE_COLOR, 0.25, angle=random.uniform(0, 360))
            self.burst("flare_01", dst, 160, 60, NUE_HOT, 0.25)
        elif key == "great_serpent":
            # A coil tightening around the target, plus a venom puff.
            self.burst("twirl_03", dst, 150, 60, SERPENT_COLOR, 0.45, spin=-540)
            self.burst("twirl_03", dst, 120, 40, SERPENT_COLOR, 0.45, angle=180, spin=-540)
            self.burst("smoke_06", dst, 60, 110, _scale(SERPENT_COLOR, 0.7), 0.6, angle=random.uniform(0, 360))
        elif key == "toad":
            self.lines.append(_Line(src, dst, TOAD_TONGUE, 6, 0.24, follow_a=clone, follow_b=target))
            self.burst("dirt_02", dst, 70, 120, TOAD_WATER, 0.35, angle=random.uniform(0, 360))
        elif key == "max_elephant":
            self.burst("dirt_03", src, 80, 180, ELEPHANT_COLOR, 0.5, angle=random.uniform(0, 360))
            self.burst("light_02", src, 60, 160, ELEPHANT_COLOR, 0.45)
        elif key == "piercing_ox":
            self.burst("star_09", dst, 130, 70, OX_COLOR, 0.25)
            self.burst("dirt_01", dst, 60, 130, OX_COLOR, 0.4, angle=_deg(d))
        elif key == "rabbit":
            self.burst("star_04", dst, 50, 20, RABBIT_COLOR, 0.2)
        elif key == "mahoraga":
            self.burst("light_03", dst, 80, 170, MAHORAGA_COLOR, 0.35)

    def on_rabbit_split(self, pos):
        self.burst("smoke_06", pos, 30, 70, RABBIT_COLOR, 0.4, angle=random.uniform(0, 360), fade0=0.7)
        for _ in range(3):
            v = pygame.Vector2(random.uniform(40, 90), 0).rotate(random.uniform(0, 360))
            self.burst("star_04", pos, 26, 10, RABBIT_COLOR, 0.45, vel=v, angle=random.uniform(0, 45))

    def on_ox_impact(self, pos, direction):
        self.burst("dirt_03", pos, 90, 200, OX_COLOR, 0.5, angle=_deg(-direction))
        self.burst("smoke_09", pos, 80, 200, _scale(OX_COLOR, 0.6), 0.6, spin=120)
        self.burst("star_09", pos, 150, 60, (255, 230, 180), 0.2)

    def on_toad_land(self, pos):
        self.burst("circle_02", pos, 30, 90, TOAD_WATER, 0.35, fade0=0.8)

    def on_mahoraga_adapt(self, clone):
        self.burst("magic_03", clone.pos, clone_draw_size(clone) * 1.2, clone_draw_size(clone) * 2.2,
                   MAHORAGA_COLOR, 0.5, spin=360, follow=clone)
        self.burst("light_03", clone.pos, 100, 260, MAHORAGA_COLOR, 0.4, follow=clone)

    def draw_elephant_wave(self, screen, pos, radius, k):
        """Max Elephant's growing pulse: a soft water ring texture scaled to
        `radius`, fading as it reaches full size (k = 0..1)."""
        if radius < 4:
            return
        _blit_add(screen, _texture("light_02", radius * 2.3, ELEPHANT_COLOR, 0.8 * (1 - k)), pos)


def clone_draw_size(clone):
    """Rough on-screen diameter for sizing an aura to a clone — Mahoraga's
    own sprite is scaled up (see SukunaPlugin._shadow_sprite), so its aura
    reads the scale it was spawned with when available."""
    return getattr(clone, "fx_size", 90)
