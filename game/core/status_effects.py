"""Generic status/zone engine. None of the actual per-character behavior
lives here — every tag effect, status-expiry reaction, and zone tick is
defined in that character's own characters/<name>/plugin.py (see
core/plugin.py for the hook contract); this file only dispatches to
self.plugins and owns the timed-status/zone bookkeeping shared by all of
them — the shared timer/expiry-hook plumbing that core/status_library.py's
own effect taxonomy (bleed/poison chip damage, stun, and everything else) is
layered on top of. Ability selection/damage math lives in
combat_resolution.py.

To land a generic effect from a character's own plugin hook, just call
entities.set_status() with one of the names below — no new plumbing
needed:
    set_status(defender, "bleed", 3000, dps=12)     # or "poison"
    set_status(defender, "stunned", 1500)
"""


class StatusEffectsMixin:
    def apply_ability_tag_effects(self):
        """Runs once a landed (non-missed) ability resolves — each plugin's
        hook is a no-op unless `self.attacker` is that plugin's fighter."""
        if self._miss:
            return
        ability, attacker, defender = self.ability, self.attacker, self.defender
        for plugin in self.plugins:
            plugin.apply_tag_effects(ability, attacker, defender)

    # ---- status / zone tick ----------------------------------------------------
    def tick_statuses(self, f, dt_ms):
        for name in list(f.statuses.keys()):
            s = f.statuses[name]
            s["time"] -= dt_ms
            if s["time"] <= 0:
                data = f.statuses.pop(name)
                self.on_status_expire(f, name, data)

    def on_status_expire(self, f, name, data):
        for plugin in self.plugins:
            plugin.on_status_expire(f, name, data)

    def update_zones(self, dt_ms):
        for z in list(self.zones):
            z.time_left -= dt_ms
            owner_plugin = self.plugin_for(z.owner)
            if owner_plugin is not None:
                owner_plugin.zone_recenter(z)
                for f in (self.f1, self.f2):
                    if f.is_alive() and (f.pos - z.center).length() <= z.radius:
                        owner_plugin.zone_tick(f, z, dt_ms / 1000)
            if z.time_left <= 0:
                self.zones.remove(z)
