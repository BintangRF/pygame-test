"""Arjuna move list: Gandiva (basic), Aindrastra, Sammohana, Devadatta,
Pashupatastra — every name pulled straight from the Sanskrit Mahabharata
itself, not the Javanese wayang retelling (see plugin.py's own docstring for
where each one comes from in the text).

Reworked to actually hit like the epic's own greatest archer instead of
poking for chip damage — every number below still traces back to something
the text itself says about that weapon, not an arbitrary buff:
  - Savyasachi (passive): his own epithet literally means "ambidextrous" —
    he draws and looses with either hand at once. Here that's not just
    moves_while_active anymore, it's Gandiva firing as a genuine two-arrow
    release every time (see ArjunaPlugin.resolve_special) — full damage
    twice, not a partial multi-hit.
  - Aindrastra: a named weapon of Indra himself, so it now hits like one —
    raised damage and a longer stun than a plain skill.
  - Sammohana: in the Virata Parva it didn't just make one soldier drowsy,
    it put a whole army to sleep, defenseless, at once — the follow-up here
    is a Vulnerability debuff for the same duration, so whatever lands while
    the target is out cold actually punishes that helplessness.
  - Devadatta: the epic describes conches sounded before battle as
    shattering enemy morale, not just startling them — Fear now comes with
    a real Attack Down alongside it.
  - Pashupatastra: Shiva's own absolute weapon, capable (per the text) of
    destroying the three worlds — raised damage and, since a weapon like
    that should cripple whatever it doesn't outright kill, a stun on impact.

Passive (Savyasachi) still means Gandiva/Aindrastra/Sammohana all carry
moves_while_active below too — Arjuna never has to plant his feet to loose
an arrow, the same freedom Johnny's own Nail Bullet has (see
core/motions.py's own note on that flag). Devadatta and Pashupatastra are
the exception: sounding a conch and calling down Shiva's own weapon are
deliberate, planted moments, not quick shots.
"""

from ...core.abilities import Ability


def make_arjuna_abilities():
    return {
        # A plain ranged shot — no melee_range at all, Arjuna never needs to
        # close distance, and moves_while_active means he never needs to
        # stop moving for it either. tag="gandiva_shot" is what
        # ArjunaPlugin.resolve_special keys off to fire it as Savyasachi's
        # own two-handed double release instead of a single hit.
        "basic": Ability("Gandiva", "basic", "bolt", 1.0, 0.75, tag="gandiva_shot", moves_while_active=True),
        "skills": [
            # Indra's own weapon, taught to Arjuna during his stay in
            # Amaravati (Indralokabhigamana Parva) — a homing shot
            # (ignore_clone=True: always finds the real target) that stuns
            # on impact. Damage/stun both raised — a named weapon of the
            # king of the gods shouldn't hit like a plain skill.
            Ability("Aindrastra", "skill", "homing_bolt", 4.0, 1.8, tag="aindrastra",
                    ignore_clone=True, moves_while_active=True),
            # The illusion-astra Chitrasena the Gandharva taught Arjuna
            # during his exile — in the Virata Parva cattle raid it put a
            # whole company of soldiers to sleep at once, utterly
            # defenseless. Still puts the target to sleep (the generic
            # "asleep" status — any hit landing on a sleeping target wakes
            # it with its own bonus burst automatically), now paired with
            # Vulnerability for the same window so a follow-up hit actually
            # punishes that helplessness.
            Ability("Sammohana", "skill", "homing_bolt", 6.0, 1.1, tag="sammohana",
                    ignore_clone=True, moves_while_active=True),
            # Arjuna's own conch, also a gift from Indra — the epic
            # describes conches blown before battle as breaking the
            # opposing army's morale outright, not just startling them, so
            # this carries a real Attack Down alongside Fear, not damage of
            # its own. cast_target="enemy": it detonates on the defender.
            Ability("Devadatta", "skill", "cast", 6.0, 0.0, tag="devadatta",
                    aoe_radius=130, cast_target="enemy"),
        ],
        # Shiva's own absolute weapon, earned through Arjuna's own penance in
        # the Kirātārjunīya — described in the text as capable of destroying
        # the three worlds, so this is the hardest-hitting move in the kit
        # and now stuns on landing too. A rain of arrows called down onto
        # the target from directly above, the same "summoned from the sky"
        # shape as Thunder God's Descent (see core/motions.py's "sky_strike").
        "ultimate": Ability("Pashupatastra", "ultimate", "sky_strike", 12.0, 3.0,
                             big=True, tag="pashupatastra", aoe_radius=140),
    }
