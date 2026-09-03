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

    def update(self, dt_ms):
        dt = dt_ms / 1000
        self.velocity *= self.drag
        self.velocity.y += self.gravity * dt
        self.pos += self.velocity * dt
        self.rotation += self.rotation_speed * dt
        self.lifetime -= dt_ms
        life_ratio = max(0.0, self.lifetime / self.max_lifetime)
        self.alpha = int(255 * life_ratio)
        return self.lifetime > 0

    def draw(self, screen, bg_color, offset=(0, 0)):
        life_ratio = max(0.0, min(1.0, self.lifetime / self.max_lifetime))
        color = _lerp_color(bg_color, self.color, life_ratio)
        x = self.pos.x + offset[0]
        y = self.pos.y + offset[1]

        if self.kind in ("circle", "dust", "blood", "holy", "bat"):
            r = max(1, self.radius * self.scale)
            if self.kind == "bat":
                self._draw_bat(screen, x, y, r, color)
            else:
                pygame.draw.circle(screen, color, (int(x), int(y)), max(1, int(r)))

        elif self.kind == "smoke":
            r = max(1, self.radius * self.scale * (1.4 - life_ratio * 0.4))
            pygame.draw.circle(screen, color, (int(x), int(y)), max(1, int(r)))

        elif self.kind in ("spark", "slash"):
            length = max(2, self.radius * 3 * self.scale)
            if self.velocity.length_squared() > 1:
                d = self.velocity.normalize()
            else:
                d = pygame.Vector2(math.cos(self.rotation), math.sin(self.rotation))
            p1 = (x - d.x * length / 2, y - d.y * length / 2)
            p2 = (x + d.x * length / 2, y + d.y * length / 2)
            pygame.draw.line(screen, color, p1, p2, max(1, int(self.radius)))

        elif self.kind in ("square", "debris"):
            r = max(1, self.radius * self.scale)
            pts = []
            for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                ang = self.rotation
                lx, ly = dx * r, dy * r
                pts.append((
                    x + lx * math.cos(ang) - ly * math.sin(ang),
                    y + lx * math.sin(ang) + ly * math.cos(ang),
                ))
            pygame.draw.polygon(screen, color, pts)

        elif self.kind == "star":
            r = max(1, self.radius * self.scale)
            for i in range(4):
                ang = self.rotation + i * (math.pi / 2)
                x2 = x + math.cos(ang) * r
                y2 = y + math.sin(ang) * r
                pygame.draw.line(screen, color, (x, y), (x2, y2), 2)

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

    def update(self, dt_ms):
        self.particles = [p for p in self.particles if p.update(dt_ms)]

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

def emit_hit_spark(ps, pos, color, count=18, speed=(130, 340), lifetime=(140, 320)):
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
                          vel, random.uniform(300, 560), random.uniform(2.5, 5.5),
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
        ps.emit(Particle(pos, vel, random.uniform(260, 500), random.uniform(2.0, 4.5),
                          shade, gravity=160, drag=0.9, kind="blood"))


def emit_holy(ps, pos, count=24, radius=60):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        r = random.uniform(4, radius)
        spawn = pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * r
        vel = (pos - spawn) * random.uniform(0.6, 1.4)
        shade = random.choice([(250, 225, 140), (255, 245, 200), (240, 200, 60)])
        ps.emit(Particle(spawn, vel, random.uniform(360, 640), random.uniform(2.0, 4.0),
                          shade, drag=0.94, kind="holy"))


def emit_dark(ps, pos, count=24, radius=55):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(30, 130)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        shade = random.choice([(90, 20, 120), (60, 10, 90), (130, 30, 150)])
        if random.random() < 0.35:
            ps.emit(Particle(pos, vel * 0.6, random.uniform(320, 560), random.uniform(2.5, 4.0),
                              shade, drag=0.92, kind="bat", rotation_speed=random.uniform(-4, 4)))
        else:
            ps.emit(Particle(pos, vel, random.uniform(280, 500), random.uniform(2.0, 3.8),
                              shade, drag=0.93, kind="circle"))


def emit_debris(ps, pos, count=14, speed=(80, 220)):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        vel.y -= random.uniform(30, 90)
        shade = random.choice([(110, 90, 70), (140, 110, 80), (90, 70, 55)])
        ps.emit(Particle(pos, vel, random.uniform(320, 540), random.uniform(2.5, 5.0),
                          shade, gravity=260, drag=0.94, kind="debris",
                          rotation=random.uniform(0, math.tau), rotation_speed=random.uniform(-8, 8)))


def emit_spark_burst(ps, pos, color, count=22, speed=(160, 360)):
    """Electric burst — Raiju's static/lightning flavor."""
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        ps.emit(Particle(pos, vel, random.uniform(120, 280), random.uniform(1.5, 3.0),
                          color, drag=0.82, kind="spark"))
        if random.random() < 0.5:
            ps.emit(Particle(pos, vel * 0.5, random.uniform(180, 320), random.uniform(2.0, 3.2),
                              (235, 255, 255), drag=0.85, kind="star", rotation=ang))


def emit_explosion(ps, pos, color, count=48, speed=(110, 340)):
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(*speed)
        vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
        kind = random.choice(["circle", "spark", "debris"])
        ps.emit(Particle(pos, vel, random.uniform(260, 600), random.uniform(2.0, 5.0),
                          color, gravity=70 if kind == "debris" else 0, drag=0.9, kind=kind,
                          rotation=random.uniform(0, math.tau), rotation_speed=random.uniform(-6, 6)))
