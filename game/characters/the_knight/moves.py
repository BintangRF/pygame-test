"""The Knight's move list: Nail Slash, Dash Slash, Crystal Heart, Dream
Nail, Shade Hunt, Vengeful Spirit, Focus, Abyss Shriek. The numbers/tags
here drive the generic combat pipeline (core/combat_resolution.py); the
behavior behind each tag lives in plugin.py next to this file.

Passives (see KnightPlugin): Soul Vessel — nail hits fill SOUL, and the two
spells (Vengeful Spirit, Focus) spend it — and Mantis Claw — every arena
wall he bounces off is a wall jump: a burst of speed and an empowered next
nail strike. Every skill is a different verb: blink into a corner and
dash back through the target (Dash Slash), charge and rocket across the
arena (Crystal Heart), steal its
thoughts and Soul (Dream Nail), set his own Shade loose on it (Shade Hunt),
shoot (Vengeful Spirit), heal (Focus)."""

from ...core.abilities import Ability


def make_the_knight_abilities():
    return {
        "basic": Ability("Nail Slash", "basic", "slash", 0.7, 1.0, melee_range=105, tag="knight_nail"),
        "skills": [
            # Melt into shadow and blink into the arena corner farthest from
            # the target, cling there a beat (hittable), kick off it — a
            # Mantis Claw wall jump that empowers the strike — and dash
            # straight through the target. Its hit is KnightPlugin's own;
            # the generic "cast" motion only supplies the timing.
            Ability("Dash Slash", "skill", "cast", 6, 0.0, tag="knight_dashslash", cast_target="enemy",
                    ignore_clone=True, ignore_taunt=True),
            # Crouch and charge crystal, then rocket in a straight line across
            # the whole arena — a hit only if the target is on that line when
            # he launches — and wall-jump off the far wall.
            Ability("Crystal Heart", "skill", "cast", 7, 0.0, tag="knight_crystal", cast_target="enemy",
                    ignore_clone=True, ignore_taunt=True),
            # A slow dream-slash: weak, but steals SOUL, silences, and reads
            # the target's thoughts.
            Ability("Dream Nail", "skill", "cast", 8, 0.6, tag="knight_dream", cast_target="enemy"),
            # His Shade tears loose and hunts the target on its own for a few
            # seconds — a few void slashes, each handing SOUL back — while
            # the Knight keeps fighting.
            Ability("Shade Hunt", "skill", "cast", 9, 0.0, tag="knight_shade", cast_target="enemy"),
            # Spell: a screaming ghost-skull that shoves the target back.
            Ability("Vengeful Spirit", "skill", "bolt", 2.5, 2.0, tag="knight_spirit"),
            # Spell: channel Soul into a heal — lost if he's hit mid-channel.
            Ability("Focus", "skill", "cast", 5, 0.0, tag="knight_focus", cast_target="self"),
        ],
        # Void wraiths pour out of the Knight and tear into the target,
        # sending it fleeing in terror — and refill every SOUL.
        "ultimate": Ability("Abyss Shriek", "ultimate", "sky_strike", 11, 3.0, big=True, tag="knight_shriek"),
    }
