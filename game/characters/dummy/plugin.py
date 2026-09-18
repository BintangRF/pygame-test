"""DummyPlugin — a plain punching-bag fighter with no bespoke behavior at
all; every hook stays at CharacterPlugin's own no-op default. Exists so
armor/health tuning (see CHARACTERS["dummy"] in core/assets.py: 999 hp, 0
atk, 1 armor) can be tested against a fighter with zero passive complexity
muddying the numbers."""

from ...core.plugin import CharacterPlugin


class DummyPlugin(CharacterPlugin):
    pass
