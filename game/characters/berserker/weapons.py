"""The Berserker's weapon prop (see fx.py for how it's animated)."""

from ...core.asset_loading import load_weapon


def load_berserker_weapons():
    return {"axe": load_weapon("axe.png", 100)}
