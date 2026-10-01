"""
Reusable particle system for battle impact/status effects.

Ambient background particles (the drifting arena dust in BattleAnimation)
stay as they are — this module is for short-lived combat effects: hit
sparks, blood, holy light, debris, embers, static, etc. Everything routes
through one ParticleSystem instance and a handful of `emit_*` presets so
effects are never hand-rolled per attack.
"""

import math
import random

import pygame

from .glow import add_dot, lighten, mix

MAX_PARTICLES = 900


def _lerp_color(bg, color, ratio):
    ratio = max(0.0, min(1.0, ratio))
    return (
        int(bg[0] + (color[0] - bg[0]) * ratio),
        int(bg[1] + (color[1] - bg[1]) * ratio),
        int(bg[2] + (color[2] - bg[2]) * ratio),
    )


class Particle:
    def __init__(self, pos, velocity, lifetime, radius, color, alpha=255,
                 gravity=0.0, drag=1.0, kind="circle", rotation=0.0,
                 rotation_speed=0.0, scale=1.0):
        self.pos = pygame.Vector2(pos)
        self.velocity = pygame.Vector2(velocity)
        self.lifetime = lifetime
        self.max_lifetime = max(1, lifetime)
        self.radius = radius
        self.color = color
        self.alpha = alpha
        self.gravity = gravity
        self.drag = drag
        self.kind = kind
        self.rotation = rotation
        self.rotation_speed = rotation_speed
        self.scale = scale

    def update(self, dt):
        self.velocity *= self.drag
        self.velocity.y += self.gravity * dt
        self.pos += self.velocity * dt
        self.rotation += self.rotation_speed * dt
        self.lifetime -= dt
        life_ratio = max(0.0, self.lifetime / self.max_lifetime)
        self.alpha = int(255 * life_ratio)
        return self.lifetime > 0

    def draw(self, screen, bg_color, offset=(0, 0)):
        """Energy kinds (circle, holy, spark, slash, star, bolt, square) are
        drawn as light: a soft additive glow (glow.add_dot) under a small
        anti-aliased core, fading in brightness. Matter kinds (dust, smoke,
        blood, bat, debris) stay solid shapes fading into the floor."""
        life_ratio = max(0.0, min(1.0, self.lifetime / self.max_lifetime))
        color = _lerp_color(bg_color, self.color, life_ratio)
        x = self.pos.x + offset[0]
        y = self.pos.y + offset[1]
        r = max(1.0, self.radius * self.scale)

        if self.kind in ("circle", "holy"):
            add_dot(screen, (x, y), r * 2.6, self.color, 0.75 * life_ratio)
            add_dot(screen, (x, y), r * 0.9, lighten(self.color, 0.55), life_ratio)

        elif self.kind in ("dust", "blood"):
            pygame.draw.circle(screen, color, (x, y), r)

        elif self.kind == "bat":
            self._draw_bat(screen, x, y, r, color)

        elif self.kind == "smoke":
            pygame.draw.circle(screen, color, (x, y), r * (1.4 - life_ratio * 0.4))

        elif self.kind in ("spark", "slash"):
            # a tapered streak: dim tail, bright head, glow around the head
            length = max(3, self.radius * 3.4 * self.scale)
            d = self._heading()
            head = (x + d.x * length * 0.5, y + d.y * length * 0.5)
            tail = (x - d.x * length * 0.5, y - d.y * length * 0.5)
            mid = (x, y)
            core = _lerp_color(bg_color, lighten(self.color, 0.5), life_ratio)
            pygame.draw.aaline(screen, color, tail, mid)
            pygame.draw.line(screen, core, mid, head, max(1, int(self.radius * 0.7)))
            pygame.draw.aaline(screen, core, mid, head)
            add_dot(screen, head, r * 1.8, self.color, 0.6 * life_ratio)

        elif self.kind == "square":
            pts = []
            for dx, dy in ((-1, -0.55), (1, -0.55), (1, 0.55), (-1, 0.55)):
                lx, ly = dx * r, dy * r
                pts.append((x + lx * math.cos(self.rotation) - ly * math.sin(self.rotation),
                            y + lx * math.sin(self.rotation) + ly * math.cos(self.rotation)))
            add_dot(screen, (x, y), r * 2.4, self.color, 0.55 * life_ratio)
            pygame.draw.polygon(screen, _lerp_color(bg_color, lighten(self.color, 0.35), life_ratio), pts)

        elif self.kind == "debris":
            pts = []
            for dx, dy in ((-1, -1), (1, -0.7), (0.8, 1), (-0.9, 0.8)):
                lx, ly = dx * r, dy * r
                pts.append((x + lx * math.cos(self.rotation) - ly * math.sin(self.rotation),
                            y + lx * math.sin(self.rotation) + ly * math.cos(self.rotation)))
            pygame.draw.polygon(screen, color, pts)

        elif self.kind == "star":
            add_dot(screen, (x, y), r * 2.2, self.color, 0.7 * life_ratio)
            core = _lerp_color(bg_color, lighten(self.color, 0.6), life_ratio)
            for i in range(2):
                ang = self.rotation + i * (math.pi / 2)
                dx, dy = math.cos(ang) * r * 1.6, math.sin(ang) * r * 1.6
                pygame.draw.aaline(screen, core, (x - dx, y - dy), (x + dx, y + dy))

        elif self.kind == "bolt":
            # A short jagged shard — two kinked segments radiating outward,
            # unlike "spark"'s single straight line — Raiju's own lightning
            # hit effect (see emit_lightning_spark). The kink direction
            # (left/right of travel) is fixed per-particle via
            # rotation_speed's sign, set once at emit time, so it doesn't
            # flicker between sides frame to frame.
            length = max(3, self.radius * 3.4 * self.scale)
            d = self._heading()
            perp = pygame.Vector2(-d.y, d.x)
            side = 1 if self.rotation_speed >= 0 else -1
            kink = perp * length * 0.24 * side
            p0 = (x - d.x * length * 0.5, y - d.y * length * 0.5)
            mid = (x + kink.x, y + kink.y)
            p2 = (x + d.x * length * 0.5, y + d.y * length * 0.5)
            add_dot(screen, mid, length * 0.6, self.color, 0.5 * life_ratio)
            core = _lerp_color(bg_color, lighten(self.color, 0.6), life_ratio)
            pygame.draw.aalines(screen, core, False, (p0, mid, p2))

    def _heading(self):
        if self.velocity.length_squared() > 1:
            return self.velocity.normalize()
        return pygame.Vector2(math.cos(self.rotation), math.sin(self.rotation))

    def _draw_bat(self, screen, x, y, r, color):
        if self.velocity.length_squared() > 1:
            d = self.velocity.normalize()
        else:
            d = pygame.Vector2(1, 0)
        perp = pygame.Vector2(-d.y, d.x)
        wing = perp * r * 1.6
        pygame.draw.polygon(screen, color, [
            (x, y), (x + wing.x - d.x * r, y + wing.y - d.y * r), (x - d.x * r * 0.4, y - d.y * r * 0.4),
        ])
        pygame.draw.polygon(screen, color, [
            (x, y), (x - wing.x - d.x * r, y - wing.y - d.y * r), (x - d.x * r * 0.4, y - d.y * r * 0.4),
        ])


class ParticleSystem:
    def __init__(self, max_particles=MAX_PARTICLES):
        self.particles = []
        self.max_particles = max_particles

    def emit(self, particle):
        self.particles.append(particle)
        overflow = len(self.particles) - self.max_particles
        if overflow > 0:
            del self.particles[0:overflow]

    def update(self, dt):
        self.particles = [p for p in self.particles if p.update(dt)]

    def draw(self, screen, bg_color=(10, 10, 12), offset=(0, 0)):
        for p in self.particles:
            p.draw(screen, bg_color, offset)

    def clear(self):
        self.particles.clear()

    def __len__(self):
        return len(self.particles)


# ---- presets -----------------------------------------------------------------
# Every preset appends directly to a ParticleSystem — randomized but bounded
# (angle/speed/size/lifetime jitter only) so attacks stay readable.

def emit_hit_spark(ps, pos, color, count=18, speed=(130, 340), lifetime=(0.14, 0.32)):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        ps.emit(Particle(pos, vel, random.uniform(*lifetime), random.uniform(2.0, 4.0),
                          color, drag=0.88, kind="spark"))


def emit_dust(ps, pos, count=14, spread=40):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(15, 70)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        vel.y -= random.uniform(0, 15)
        ps.emit(Particle(pos + pygame.Vector2(random.uniform(-6, 6), random.uniform(-6, 6)),
                          vel, random.uniform(0.3, 0.56), random.uniform(2.5, 5.5),
                          (150, 130, 100), gravity=30, drag=0.95, kind="dust"))


def emit_blood(ps, pos, direction=None, count=24, speed=(90, 300)):
    for _ in range(count):
        if direction is not None and direction.length_squared() > 0 and random.random() < 0.6:
            base = math.atan2(direction.y, direction.x)
            ang = base + random.uniform(-0.9, 0.9)
        else:
            ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        shade = random.choice([(150, 15, 25), (180, 25, 35), (110, 10, 18)])
        ps.emit(Particle(pos, vel, random.uniform(0.26, 0.5), random.uniform(2.0, 4.5),
                          shade, gravity=160, drag=0.9, kind="blood"))


def _shades(color, default):
    """Three tones of `color` (deep, base, light) for a preset that mixes
    shades, or the preset's own `default` trio when no color is given."""
    if color is None:
        return default
    return [mix(color, (0, 0, 0), 0.35), tuple(color[:3]), lighten(color, 0.45)]


def emit_holy(ps, pos, count=24, radius=60, color=None):
    """Motes of light drawn inward to `pos`, tinted from `color` (the
    caster's own signature color) or warm gold by default."""
    shades = _shades(color, [(250, 225, 140), (255, 245, 200), (240, 200, 60)])
    if color is not None:
        shades[0] = tuple(color[:3])  # light never goes dark
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        r = random.uniform(4, radius)
        spawn = pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * r
        vel = (pos - spawn) * random.uniform(0.6, 1.4)
        shade = random.choice(shades)
        ps.emit(Particle(spawn, vel, random.uniform(0.36, 0.64), random.uniform(2.0, 4.0),
                          shade, drag=0.94, kind="holy"))


def emit_dark(ps, pos, count=24, radius=55, color=None):
    """A burst of dark energy motes and bat shapes, in shades of `color`
    (the caster's own signature color) or shadow purple by default."""
    shades = _shades(color, [(90, 20, 120), (60, 10, 90), (130, 30, 150)])
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(30, 130)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        shade = random.choice(shades)
        if random.random() < 0.35:
            ps.emit(Particle(pos, vel * 0.6, random.uniform(0.32, 0.56), random.uniform(2.5, 4.0),
                              shade, drag=0.92, kind="bat", rotation_speed=random.uniform(-4, 4)))
        else:
            ps.emit(Particle(pos, vel, random.uniform(0.28, 0.5), random.uniform(2.0, 3.8),
                              shade, drag=0.93, kind="circle"))


def emit_debris(ps, pos, count=14, speed=(80, 220)):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        vel.y -= random.uniform(30, 90)
        shade = random.choice([(110, 90, 70), (140, 110, 80), (90, 70, 55)])
        ps.emit(Particle(pos, vel, random.uniform(0.32, 0.54), random.uniform(2.5, 5.0),
                          shade, gravity=260, drag=0.94, kind="debris",
                          rotation=random.uniform(0, math.tau), rotation_speed=random.uniform(-8, 8)))


def emit_spark_burst(ps, pos, color, count=22, speed=(160, 360)):
    """Electric burst — Raiju's static/lightning flavor."""
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        ps.emit(Particle(pos, vel, random.uniform(0.12, 0.28), random.uniform(1.5, 3.0),
                          color, drag=0.82, kind="spark"))
        if random.random() < 0.5:
            ps.emit(Particle(pos, vel * 0.5, random.uniform(0.18, 0.32), random.uniform(2.0, 3.2),
                              (235, 255, 255), drag=0.85, kind="star", rotation=ang))


def emit_lightning_spark(ps, pos, color, count=20, speed=(150, 380)):
    """Raiju's own hit effect: a burst of jagged little lightning shards
    ("bolt" kind, above) radiating outward, plus a handful of tight white
    flash motes at the core — reads as a genuine electric discharge at the
    point of impact, distinct from the plain circular spark/star mix
    emit_spark_burst gives every other electric-flavored hit in the game."""
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        ps.emit(Particle(pos, vel, random.uniform(0.14, 0.3), random.uniform(2.0, 4.0),
                          color, drag=0.8, kind="bolt", rotation=ang,
                          rotation_speed=random.choice((-1.0, 1.0))))
    for _ in range(max(4, count // 4)):
        ang = random.uniform(0, math.tau)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * random.uniform(40, 120)
        ps.emit(Particle(pos, vel, random.uniform(0.1, 0.2), random.uniform(2.0, 3.4),
                          (235, 255, 255), drag=0.8, kind="circle"))


def emit_explosion(ps, pos, color, count=48, speed=(110, 340)):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        kind = random.choice(["circle", "spark", "debris"])
        ps.emit(Particle(pos, vel, random.uniform(0.26, 0.6), random.uniform(2.0, 5.0),
                          color, gravity=70 if kind == "debris" else 0, drag=0.9, kind=kind,
                          rotation=random.uniform(0, math.tau), rotation_speed=random.uniform(-6, 6)))
