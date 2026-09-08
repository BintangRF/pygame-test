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
    set_status(defender, "bleed", 3, dps=12)     # or "poison"
    set_status(defender, "stunned", 1.5)
"""


class StatusEffectsMixin:
    def apply_ability_tag_effects(self):
        """Runs once a landed (non-missed) ability resolves — each plugin's
        hook is a no-op unless `self.attacker` is that plugin's fighter.
        Reads back whichever target actually took the hit: redirect_target
        (a taunting decoy, or one of Phantom Lancer's illusions — see
        StatusLibraryMixin.taunt_redirect) when the attack got redirected,
        the real defender otherwise — so a tag effect (Sukuna's Hachi
        bleed, Raiju's Fang Flicker static stack, ...) lands on whichever
        of the two actually got struck, same as the damage itself already
        does, instead of always landing on the real fighter regardless of
        who was actually hit."""
        if self._miss:
            return
        ability, attacker = self.ability, self.attacker
        defender = self.redirect_target if self.redirect_target is not None else self.defender
        for plugin in self.plugins:
            plugin.apply_tag_effects(ability, attacker, defender)

    # ---- status / zone tick ----------------------------------------------------
    def tick_statuses(self, f, dt):
        for name in list(f.statuses.keys()):
            s = f.statuses[name]
            s["time"] -= dt
            if s["time"] <= 0:
                data = f.statuses.pop(name)
                self.on_status_expire(f, name, data)

    def on_status_expire(self, f, name, data):
        for plugin in self.plugins:
            plugin.on_status_expire(f, name, data)

    def update_zones(self, dt):
        for z in list(self.zones):
            z.time_left -= dt
            owner_plugin = self.plugin_for(z.owner)
            if owner_plugin is not None:
                owner_plugin.zone_recenter(z)
                targets = [self.f1, self.f2]
                # Vampire's own decoy Clone is a full participant in zone
                # effects too (see entities.Clone) — except a zone owned by
                # its own owner, exactly like Phantom Lancer's own
                # CloneArmy.zone_tick skips those, so a Vampire's decoy
                # standing in the Vampire's own Blood Pool doesn't get
                # poisoned by its own side's zone.
                if self.clone is not None and z.owner is not self.clone.owner:
                    targets.append(self.clone)
                for f in targets:
                    if f.is_alive() and (f.pos - z.center).length() <= z.radius:
                        owner_plugin.zone_tick(f, z, dt)
            if z.time_left <= 0:
                self.zones.remove(z)
