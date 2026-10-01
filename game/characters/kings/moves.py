"""Kings's move list: Throw Card, Play Hand, Fold, Three Card Spread. The
numbers/tags here drive the generic combat pipeline (core/
combat_resolution.py); the behavior behind each tag lives in plugin.py next
to this file.

Passive (Arcana Deck, see KingsPlugin): Kings fights out of a deck of the 21
Major Arcana, holding a hand of 5, each card upright or reversed. Throw Card
spends the card he wants least and draws a new one; Play Hand fires every
card in the hand and scores it by its longest Sequence of running numerals
(a Link, a Triad, ... a Grand Arcana). An empty deck is reshuffled from the
discards, and that costs him a moment standing still."""

from ...core.abilities import Ability


def make_kings_abilities():
    return {
        # One card flicked at the target, the one his hand wants least,
        # hitting a little harder the higher its numeral. Draws a replacement.
        "basic": Ability("Throw Card", "basic", "bolt", 1.0, 0.8, tag="kings_throw"),
        "skills": [
            # The whole hand at once: every card's effect, then one hit per
            # card in its longest Sequence. He holds a loose hand for a while
            # before giving up and playing it anyway. dmg_mult only marks it
            # as a damaging attack; the hits are KingsPlugin.resolve_special's.
            # A "cast" (big, for the longer beats): the windup gathers the
            # fan, the channel is the volley in flight, the hits land on release.
            Ability("Play Hand", "skill", "cast", 4.5, 1.0, big=True, tag="kings_play", cast_target="enemy"),
            # Only with a loose, mostly reversed hand: throw it in, draw 5
            # fresh, and slip out of reach for a beat while shuffling.
            Ability("Fold", "skill", "cast", 8.0, 0.0, tag="kings_fold", cast_target="self"),
        ],
        # Past, Present, Future: three cards turned up, all upright. The Past
        # turns his hp back, the Present acts now, the Future is planted
        # where the target stands and detonates later.
        "ultimate": Ability("Three Card Spread", "ultimate", "cast", 12, 0.0, big=True, tag="kings_spread",
                            cast_target="self"),
    }
