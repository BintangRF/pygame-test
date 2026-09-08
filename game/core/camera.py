"""Reusable camera shake — a single decaying trauma value that offsets
drawing each frame. Battle-balance values (which tier hits for how much)
stay in battle.py; this module only owns the decay math."""

import random

import pygame

SHAKE_SMALL = 3
SHAKE_MEDIUM = 6
SHAKE_HEAVY = 10
SHAKE_ULTIMATE = 16

SHAKE_DURATION_SMALL = 0.08
SHAKE_DURATION_MEDIUM = 0.12
SHAKE_DURATION_HEAVY = 0.18
SHAKE_DURATION_ULTIMATE = 0.25


class CameraShake:
    def __init__(self):
        self.timer = 0
        self.duration = 0
        self.strength = 0.0

    def add(self, strength, duration):
        # a new shake only overrides the current one if it's at least as
        # strong — a small tremor shouldn't cut a heavy hit's shake short
        if strength >= self.strength or self.timer <= 0:
            self.strength = strength
        self.duration = max(self.duration, duration)
        self.timer = max(self.timer, duration)

    def update(self, dt):
        if self.timer > 0:
            self.timer = max(0, self.timer - dt)
        if self.timer <= 0:
            self.strength = 0.0
            self.duration = 0

    def offset(self):
        if self.timer <= 0 or self.duration <= 0:
            return pygame.Vector2(0, 0)
        progress = self.timer / self.duration
        current = self.strength * progress
        return pygame.Vector2(random.uniform(-1, 1) * current, random.uniform(-1, 1) * current)
