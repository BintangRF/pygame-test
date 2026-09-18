"""Phantom Lancer's weapon prop (see plugin.py for how it's animated)."""

from ...core.asset_loading import load_weapon


def load_phantom_lancer_weapons():
    return {"lancer": load_weapon("phantom_lancer/lancer.png", 120)}
