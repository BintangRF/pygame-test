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
        onto a decoy standing in for this plugin's own fighter (see
        StatusLibraryMixin.taunt_redirect) — resolve the decoy's fate and
        return True to stop do_damage() from running its usual resolution."""
        return False

    def basic_attack_decoys(self):
        """Extra targets (Phantom Lancer's illusion clones — anything with a
        .pos, usable with CloneArmy.damage_clone) this plugin's own fighter
        wants thrown into the pool an eligible incoming attack might land on
        instead — see taunt_redirect for exactly which attacks are eligible
        (gated by each ability's own explicit ignore_clone flag — see
        abilities.Ability — not by whether it's a basic, skill, or ultimate,
        despite this method's name). By default, see decoy_redirect_weight,
        an equal-odds pool alongside the real fighter itself (unlike a
        taunting decoy, which is a guaranteed 100% redirect while its status
        is up); empty by default."""
        return []

    def decoy_redirect_weight(self):
        """How many "slots" each entry from basic_attack_decoys() gets in
        taunt_redirect's pool, relative to a single slot for the real
        fighter itself — 1 would be a plain equal-odds pool. Defers to this
        plugin's own clone_army() (see CloneArmy.decoy_weight) when it has
        one, since any character's illusions should skew incoming eligible
        attacks toward themselves the same way, not just Phantom Lancer's;
        falls back to 1 (no skew) for a plugin with no CloneArmy at all."""
        army = self.clone_army()
        return army.decoy_weight if army is not None else 1

    def clone_army(self):
        """This plugin's own core/clone_army.py CloneArmy, if it has one —
        None by default. Read generically by combat_resolution.py
        (splash_aoe_to_clones) so an AoE-flavored ability (Ability.aoe_radius/
        aoe_cone_deg) automatically also damages the defender's own clone
        army, whichever character it belongs to — a character with a
        CloneArmy gets this for free, no per-character on_damage_dealt
        wiring needed."""
        return None

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

    def extra_colliders(self):
        """Extra roaming bodies (anything with .pos/.vel, like a Character)
        this plugin wants included in the fighter-vs-fighter bounce
        collision (see resolve_collisions) on top of f1/f2/the Vampire's
        clone — Phantom Lancer's illusion army is the only source right
        now. Aggregated from every plugin each frame, so returning a fresh
        list each call is fine."""
        return []

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
