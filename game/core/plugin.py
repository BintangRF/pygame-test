"""The `CharacterPlugin` extension point every fighter's own module plugs
into. This is the one interface the whole engine (battle.py, and every
core/*.py file) talks to instead of naming characters directly — adding a
new fighter means writing a new characters/<name>/plugin.py subclass and
registering it in core/assets.py's CHARACTERS dict, never touching engine
code.

One instance is constructed per fighter *actually in the match* (never all
six at once) as `PluginCls(battle, fighter)`, so every hook already knows
which of self.battle.f1/self.battle.f2 it owns via self.fighter — no more
`is self.paladin`-style identity checks scattered through shared files.

Every hook below has a no-op default, so a character only needs to override
the handful it actually uses. Hooks come in three flavors:
  - "chain" hooks (outgoing_damage, incoming_defense, heal_bonus, the two
    speed multipliers, melee_range_bonus, cooldown_bonus): called on every
    plugin in turn, threading the return value through — harmless for a
    plugin uninvolved in the current fighter/attack since its default just
    returns the input unchanged.
  - "handled?" hooks (impact_particles, draw_projectile, resolve_special,
    on_attack_redirected): called until one plugin returns truthy, which
    stops the shared fallback/further dispatch. (Whether an attack gets
    redirected onto a taunting decoy in the first place is generic now —
    see StatusLibraryMixin.taunt_redirect in core/status_library.py — so
    on_attack_redirected is the only hook left here for reacting to it.)
  - "notify" hooks (everything else): called on every plugin unconditionally;
    each guards internally on `attacker/defender/fighter is self.fighter`
    (or on status/tag names only it ever applies) so it's a no-op elsewhere.
"""


class CharacterPlugin:
    def __init__(self, battle, fighter):
        self.battle = battle
        self.fighter = fighter

    # ---- construction / loadout --------------------------------------------
    def weapons(self):
        """Extra weapon-prop images this character needs, merged into
        battle.weapons — see core/assets.py's load_weapon()."""
        return {}

    # ---- ability gating (combat_resolution.choose_ability/start_attack) ---
    def melee_range_bonus(self, attacker, melee_range):
        return melee_range

    def cooldown_bonus(self, attacker, ability, cooldown):
        return cooldown

    def ammo_ready(self, attacker, ability):
        return True

    def consume_ammo(self, attacker, ability):
        pass

    # ---- damage pipeline (combat_resolution.deal_damage/do_damage) --------
    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        return dmg, note

    def incoming_defense(self, attacker, defender, dmg):
        return dmg

    def pre_damage(self, target, dmg):
        """Called from apply_damage() with the fully-mitigated damage about
        to be subtracted. May perform a side effect (a passive that reacts
        to being hit hard) and/or return an actual-damage value to
        short-circuit the normal HP subtraction (a death-save); returning
        None leaves normal resolution to apply_damage()."""
        return None

    def on_damage_taken(self, defender, actual):
        pass

    def on_damage_dealt(self, attacker, defender, actual):
        pass

    def heal_bonus(self, attacker, heal_mult):
        return heal_mult

    def on_attack_redirected(self):
        """Called instead of the normal hit when this attack got forced
        onto a taunting decoy (see StatusLibraryMixin.taunt_redirect) —
        resolve the decoy's fate and return True to stop do_damage() from
        running its usual resolution."""
        return False

    def resolve_special(self):
        """For abilities whose damage doesn't go through the normal
        do_damage() formula at all (multi-hit flurries, swarm strikes) —
        return True once this plugin has fully resolved the ability itself."""
        return False

    # ---- status / zone dispatch (status_effects.py) ------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        pass

    def on_status_expire(self, fighter, name, data):
        pass

    def on_shield_broken(self, fighter, attacker, data):
        """Called once when `fighter`'s own "shield" status has its absorb
        pool fully consumed by status_library.apply_shield_absorb (the
        generic Shield mechanic) — `attacker` is whoever's hit popped it,
        `data` the status dict it was removed with. Override for a
        break-triggered payoff (Paladin's Holy Nova retaliation); the
        absorb/mitigation itself already happened generically before this
        fires, no default behavior needed here."""
        pass

    def zone_tick(self, fighter, zone, dt):
        """Called once per frame per fighter standing in a zone this
        character owns (dispatched by the zone's owner, not its kind)."""
        pass

    def zone_recenter(self, zone):
        """Called once per frame for each zone this character owns, before
        zone_tick — override to have the zone follow its owner around the
        arena (Sacred Ground) instead of staying fixed at its cast site."""
        pass

    def zone_slow_multiplier(self, zone):
        return 0.5

    def zone_style(self, zone):
        """(color, label) used to draw a zone this character owns."""
        return (240, 240, 240), zone.kind.title()

    def zone_decorate(self, screen, zone):
        """Extra per-frame flourish drawn on top of a zone this character
        owns (Static Field's crackling arcs), after its base circle."""
        pass

    # ---- per-frame simulation (battle_loop.py) -----------------------------
    def attack_speed_multiplier(self, fighter):
        return 1.0

    def roam_speed_multiplier(self, fighter, dt_ms):
        return 1.0

    def ambient_tick(self, dt_ms):
        """Ambient, gameplay-inert particles/state tied to an ongoing buff
        (Rage embers, Eternal Night motes) — called every frame regardless
        of mode."""
        pass

    # ---- presentation (impact_fx.py / render.py / hud.py) -------------------
    def impact_particles(self, pos, count):
        """True once this plugin has spawned this attacker's flavor of hit
        particles — stops the generic-spark fallback from also firing."""
        return False

    def draw_fx(self, screen, shake_x):
        """Weapon/technique animation, drawn every frame regardless of mode
        (most characters only draw anything while self.battle.attacker is
        self.fighter, but idle weapon props may draw whenever alive)."""
        pass

    def draw_projectile(self, screen):
        """True once this plugin has drawn the in-flight projectile for the
        current attack — stops the generic dot-and-line fallback."""
        return False

    def full_screen_overlay(self, screen):
        """A full-screen tint tied to this character's own buff/timer
        (Berserker Rage's red wash, Eternal Night's purple wash)."""
        pass
