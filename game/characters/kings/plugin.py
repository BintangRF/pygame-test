"""Kings plugin: the Arcana Deck passive (the 21 Major Arcana of cards.png as
one deck, a hand of 5, the discard pile and the reshuffle), the scoring of
Play Hand, every card's effect upright and reversed, the Arcana Combos, Fold,
the Three Card Spread ultimate, and all of Kings's presentation: his mask
picked per moment (sprite.compose), his hand orbiting him, the fan, the
volleys and falling cards, the combo cut-in and the spread.

Passive: Arcana Deck. Every card is drawn upright or, REVERSED_CHANCE of the
time, reversed (and drawn upside down). Play Hand fires every card in the
hand, and scores the hand by its longest Sequence: cards whose numerals run
on from each other (VII, VIII, IX is a Triad). The longer the Sequence, the
more cards fly and the harder each one hits (SEQUENCES); a hand with not one
reversed card is Clear and hits harder still. The order of a play:
  - first the hand-shapers bend the hand: The Magician turns cards over,
    Wheel of Fortune deals the rest of the hand again, Strength sets the
    multiplier;
  - then every other card lands, and then every Arcana Combo in the hand
    (COMBOS: two named cards played together, either way up, each pair
    unlocking a move of its own: Eclipse, Hellfire, Resurrection, ...);
  - then the hits, and last The Tower and The Chariot.
The Fool upright is wild: it fills whichever gap makes the Sequence longest.
A Grand Arcana (all 5 in Sequence) turns every reversed card in it upright.

Throw Card is his discard: the card the hand wants least (a reversed card
first, then whatever is furthest from the rest; never half of a combo) is
flicked at the target and replaced. Play Hand waits for at least a Link,
three upright cards or a combo, but only for HOLD_MAX_S; Fold is only ever
an option holding a hand of loose, mostly reversed cards. The deck is only
21 cards, so it runs dry often; the reshuffle costs him RESHUFFLE_S standing
still.

Presentation: the hand orbits him on a tilted ring, the far half drawn
under his mask (from an invisible zone's zone_decorate, the same trick
Pac-Man's pellets use) and the near half over it. Play Hand gathers the
hand into a fan in front of him, turns every card face up, then fires them
one after another on curving paths (a Sequence linked by a golden chain).
A combo plays a cut-in: its two cards slam together across the arena."""

import itertools
import math
import random

import pygame

from ...core.anime_fx import draw_cast_circle, draw_glow_texture, draw_speed_lines
from ...core.constants import (
    ARENA_RECT, AVATAR_R, BOUND_BOTTOM, BOUND_LEFT, BOUND_RIGHT, BOUND_TOP, GOLD, GRAY, GREEN, HEIGHT,
    KINGS_EMERALD, RED, WHITE, WIDTH,
)
from ...core.entities import Zone, set_status
from ...core.glow import add_dot, glow_polyline, glow_ring
from ...core.motions import ease_in, ease_in_out, ease_out
from ...core.particles import emit_dark, emit_spark_burst
from ...core.plugin import CharacterPlugin
from ...core.status_library import CLEANSABLE, apply_knockback, cleanse, heal
from .sprite import card_image, compose

# ---- the deck ---------------------------------------------------------------------
# (numeral, part name, title) in cards.png's own order and numbering.
MAJORS = (
    (0, "fool", "The Fool"), (1, "magician", "The Magician"), (2, "priestess", "The High Priestess"),
    (3, "empress", "The Empress"), (4, "emperor", "The Emperor"), (5, "hierophant", "The Hierophant"),
    (6, "lovers", "The Lovers"), (7, "chariot", "The Chariot"), (8, "strength", "Strength"),
    (9, "hermit", "The Hermit"), (10, "fortune", "Wheel of Fortune"), (11, "justice", "Justice"),
    (12, "hanged_man", "The Hanged Man"), (13, "death", "Death"), (14, "temperance", "Temperance"),
    (15, "devil", "The Devil"), (16, "tower", "The Tower"), (17, "world", "The World"),
    (18, "moon", "The Moon"), (19, "sun", "The Sun"), (20, "judgment", "Judgement"),
)
HAND_SIZE = 5
REVERSED_CHANCE = 0.3
RESHUFFLE_S = 0.5
# Cards that act on the hand itself before it's scored, and the two that
# land after the hits instead of before.
SHAPERS = ("magician", "fortune", "strength")
AFTER_HITS = ("tower", "chariot")

# ---- Sequences ----------------------------------------------------------------------
# run length -> (name, hits, dmg mult per hit)
SEQUENCES = {
    1: ("Lone Arcana", 1, 1.3),
    2: ("Link", 2, 1.0),
    3: ("Triad", 3, 1.05),
    4: ("Procession", 4, 1.15),
    5: ("Grand Arcana", 5, 1.5),
}
CLEAR_MULT = 1.2
TRIAD_STUN_S = 0.4
PROCESSION_ARMOR_BREAK = 15
GRAND_STUN_S = 1.0

# ---- Arcana Combos ------------------------------------------------------------------
# Two named cards played in the same hand (either way up) unlock a move of
# their own on top of the Sequence: (name, the two cards, cut-in color).
COMBOS = (
    ("Eclipse", ("sun", "moon"), (255, 200, 90)),
    ("Hellfire", ("tower", "devil"), (255, 110, 40)),
    ("Resurrection", ("death", "judgment"), (235, 235, 255)),
    ("Juggernaut", ("chariot", "strength"), (230, 170, 70)),
    ("Hidden Truth", ("hermit", "priestess"), (150, 200, 255)),
    ("Royal Decree", ("emperor", "empress"), (255, 215, 100)),
    ("Verdict", ("justice", "hanged_man"), (210, 220, 240)),
    ("Journey's End", ("fool", "world"), (120, 230, 170)),
    ("Jackpot", ("fortune", "magician"), (255, 230, 60)),
    ("Absolution", ("temperance", "hierophant"), (180, 240, 255)),
    ("Heartbreak", ("lovers", "death"), (240, 90, 130)),
)
ECLIPSE_S = 4.0
ECLIPSE_TINT_S = 1.5
HELLFIRE_CARDS = 6
HELLFIRE_MULT = 0.8
HELLFIRE_SPREAD_PX = 34
RESURRECT_STATUS = "kings_resurrect"
RESURRECT_S = 8.0
RESURRECT_HP = 0.25
JUGGERNAUT_MULT = 1.6
JUGGERNAUT_KNOCK_PX = 100
HIDDEN_TRUTH_S = 2.0
DECREE_S = 5.0
VERDICT_DELAY_S = 1.4
VERDICT_MISSING_HP = 0.3
JACKPOT_ROLLS = (1, 2, 2, 3, 3, 5)
ABSOLUTION_HEAL = 0.08
HEARTBREAK_S = 4.0
# A falling card strike: how long it's visibly dropping (locked onto its
# landing spot) before it hits, and the radius it hits within.
STRIKE_FALL_S = 0.35
VERDICT_FALL_S = 0.8
STRIKE_R = 34

# Play Hand waits this long for a hand worth playing, then plays it anyway.
HOLD_MAX_S = 3.0
THROW_NUMERAL_BONUS = 0.6
FOLD_UNTARGETABLE_S = 0.6

# ---- ultimate: Three Card Spread ----------------------------------------------------
PAST_S = 3.0
PRESENT_MULT = 1.8
FUTURE_DELAY_S = 4.0
FUTURE_R = 80
FUTURE_MULT = 2.6
SPREAD_TINT_ALPHA = 60

# ---- presentation -------------------------------------------------------------------
# The hand's orbit: a ring tilted toward the camera, its far half under him.
ORBIT_RX, ORBIT_RY = 50, 24
ORBIT_DY = 2
ORBIT_SPEED = 0.9
ORBIT_W, ORBIT_H = 16, 32
DEAL_S = 0.25
THROWN_W, THROWN_H = 16, 32
FAN_W, FAN_H = 24, 48
FAN_STEP = 24
SPREAD_W, SPREAD_H = 34, 68
SPREAD_GAP = 58
FUTURE_W, FUTURE_H = 22, 44
CUTIN_W, CUTIN_H = 64, 128
CUTIN_S = 1.1
CUTIN_CLASH = 0.28
FUTURE_FLIGHT_S = 0.33
SCATTER_S = 0.5
OMEN_S = 0.7
IDLE_BOB_PX = 2
IDLE_BOB_SPEED = 2.6
OMEN_COLOR = (200, 120, 230)
HELLFIRE_COLOR = (255, 110, 40)
COMBO_GLOW = (240, 90, 220)


class Card:
    __slots__ = ("numeral", "name", "title", "reversed")

    def __init__(self, numeral, name, title):
        self.numeral, self.name, self.title = numeral, name, title
        self.reversed = False

    def label(self):
        return self.title + (" (R)" if self.reversed else "")


class HandResult:
    __slots__ = ("length", "run", "clear")

    def __init__(self, length, run, clear):
        self.length, self.run, self.clear = length, run, clear

    @property
    def name(self):
        return SEQUENCES[self.length][0] + (" (Clear)" if self.clear else "")

    def order(self):
        return self.length, self.clear


def _longest_run(cards):
    """The longest stretch of cards whose numerals run on from each other."""
    by_num = {c.numeral: c for c in cards}
    best = []
    for n in sorted(by_num):
        if n - 1 in by_num:
            continue
        run = []
        while n in by_num:
            run.append(by_num[n])
            n += 1
        if len(run) > len(best):
            best = run
    return best


def evaluate(cards):
    """Score a hand by its longest Sequence, an upright Fool tried in every
    gap it could fill (the longest wins)."""
    if not cards:
        return HandResult(1, [], False)
    fool = next((c for c in cards if c.name == "fool" and not c.reversed), None)
    best = _longest_run(cards)
    if fool is not None:
        rest = [c for c in cards if c is not fool]
        taken = {c.numeral for c in rest}
        for n in range(21):
            if n in taken:
                continue
            stand_in = Card(n, "fool", fool.title)
            run = _longest_run(rest + [stand_in])
            if len(run) > len(best):
                best = [fool if c is stand_in else c for c in run]
    return HandResult(max(1, len(best)), best, not any(c.reversed for c in cards))


def combos_in(cards):
    names = {c.name for c in cards}
    return [combo for combo in COMBOS if set(combo[1]) <= names]


def _clamp_point(p, margin=0):
    return pygame.Vector2(
        max(BOUND_LEFT + margin, min(BOUND_RIGHT - margin, p.x)),
        max(BOUND_TOP + margin, min(BOUND_BOTTOM - margin, p.y)),
    )


def _bezier(a, c, b, t):
    return a * (1 - t) ** 2 + c * (2 * t * (1 - t)) + b * t * t


def _blit_card(screen, img, pos, angle=0.0, scale=1.0, alpha=255, sx=1.0):
    """One card image at `pos`: squeezed to `sx` of its width (a card
    turning over), then rotated/scaled, faded to `alpha`."""
    if sx < 1.0:
        w, h = img.get_size()
        img = pygame.transform.smoothscale(img, (max(1, round(w * max(0.04, sx))), h))
    if angle or scale != 1.0:
        img = pygame.transform.rotozoom(img, angle, scale)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(max(0, round(alpha)))
    screen.blit(img, img.get_rect(center=(round(pos.x), round(pos.y))))


class KingsPlugin(CharacterPlugin):
    FX_COLOR = GOLD
    BURST_TEXTURE = "star_06"

    def __init__(self, battle, fighter):
        super().__init__(battle, fighter)
        self.deck = [Card(*m) for m in MAJORS]
        self.deck_size = len(self.deck)
        random.shuffle(self.deck)
        self.discard = []
        self.hand = []
        self._eval_key = None
        self._eval = None
        # The card a Throw Card in flight carries / the hand a Play Hand in
        # flight carries ({"cards", "result", "mult", "combos"}), until it resolves.
        self._thrown = None
        self._played = None
        self._hold_t = 0.0
        # The High Priestess upright: the next refill draws 8, keeps the best 5.
        self._scry = False
        # Hidden Truth: the next hand is played with every card upright.
        self._clear_next = False
        self._spread = None
        # The spread as dealt, kept on screen through "release" after it resolves.
        self._spread_view = []
        self._futures = []  # [{"pos", "t", "card"}]
        # Falling card strikes (Hellfire, Verdict):
        # [{"t", "fall", "offset", "pos", "card", "mult", "kind"}].
        self._strikes = []
        self._eclipse_t = 0.0
        self._hp_hist = []  # [(clock, hp)]
        self._omen_t = 0.0
        self._clock = 0.0
        # ---- presentation state
        self._zone = None
        self._slot = {}  # id(card) -> its current angular offset on the orbit
        self._dealt = {}  # id(card) -> clock when it joined the hand
        self._thrown_from = None
        self._fan_from = {}  # id(card) -> where it was on the orbit when the hand was played
        self._flipped = set()
        self._flashes = []  # [{"pos", "t", "dur", "size", "color", "tex"}]
        self._scatter = []  # [{"card", "pos", "vel", "t", "spin"}]
        self._cutin = None  # {"cards", "text", "color", "t", "clashed"}
        self._shuffle_t = 0.0
        self._refill(reshuffle=False)

    def _opponent(self):
        b = self.battle
        return b.f2 if self.fighter is b.f1 else b.f1

    def _floater(self, pos, text, color, dy=-50, vy=-0.5):
        self.battle.floaters.append([pos.x, pos.y + dy, vy, 255, text, color])

    def _flash(self, pos, size, color, delay=0.0, dur=0.3, tex="star_06"):
        self._flashes.append({"pos": pygame.Vector2(pos), "t": -delay, "dur": dur, "size": size,
                              "color": color, "tex": tex})

    # ---- the deck -----------------------------------------------------------------
    def _draw_one(self, reshuffle=True):
        if not self.deck:
            if not (reshuffle and self.discard):
                return None
            self._reshuffle()
        card = self.deck.pop()
        card.reversed = random.random() < REVERSED_CHANCE
        return card

    def _reshuffle(self):
        kings = self.fighter
        self.deck, self.discard = self.discard, []
        random.shuffle(self.deck)
        set_status(kings, "stunned", RESHUFFLE_S)
        self._shuffle_t = RESHUFFLE_S
        self._floater(kings.pos, "Reshuffle!", GOLD, dy=-60)
        self.battle.log = f"{kings.name} reshuffles the deck."

    def _discard(self, card):
        card.reversed = False
        self._slot.pop(id(card), None)
        self._dealt.pop(id(card), None)
        self.discard.append(card)

    def _refill(self, reshuffle=True):
        if self._scry and not self.hand:
            self._scry = False
            pool = [c for c in (self._draw_one(reshuffle) for _ in range(HAND_SIZE + 3)) if c is not None]
            if len(pool) > HAND_SIZE:
                best = max(itertools.combinations(pool, HAND_SIZE), key=self._hand_value)
                for c in pool:
                    if c not in best:
                        c.reversed = False
                        self.deck.insert(0, c)
                pool = list(best)
            self.hand = pool
            for c in pool:
                self._dealt[id(c)] = self._clock
            return
        while len(self.hand) < HAND_SIZE:
            card = self._draw_one(reshuffle)
            if card is None:
                return
            self._dealt[id(card)] = self._clock
            self.hand.append(card)

    def _hand_value(self, cards):
        return (len(combos_in(cards)),) + evaluate(cards).order() + (sum(1 for c in cards if not c.reversed),)

    def current_eval(self):
        key = tuple((c.name, c.reversed) for c in self.hand)
        if key != self._eval_key:
            self._eval_key, self._eval = key, evaluate(self.hand)
        return self._eval

    def _hand_worth_playing(self):
        return (self.current_eval().length >= 2 or bool(combos_in(self.hand))
                or sum(1 for c in self.hand if not c.reversed) >= 3)

    def _least_wanted(self):
        """The card Throw Card spends: a reversed card first, then the one
        furthest from every other numeral in the hand; never half of a combo."""
        res = self.current_eval()
        run = {id(c) for c in res.run} if res.length >= 2 else set()
        partners = {n for _, pair, _ in combos_in(self.hand) for n in pair}

        def keep(c):
            if c.name in partners:
                return 12
            if id(c) in run:
                return 10 + (0 if c.reversed else 1)
            if c.name == "fool" and not c.reversed:
                return 8
            near = sum(1 for o in self.hand if o is not c and abs(o.numeral - c.numeral) <= 2)
            return (0 if c.reversed else 2) + near

        return min(self.hand, key=keep)

    # ---- ability gating -------------------------------------------------------------
    def ammo_ready(self, attacker, ability):
        if attacker is not self.fighter:
            return True
        tag = ability.tag
        if tag == "kings_throw":
            return bool(self.hand)
        if tag == "kings_play":
            return bool(self.hand) and (self._hand_worth_playing() or self._hold_t >= HOLD_MAX_S)
        if tag == "kings_fold":
            return (len(self.hand) == HAND_SIZE and self.current_eval().length == 1
                    and not combos_in(self.hand) and sum(1 for c in self.hand if c.reversed) >= 2)
        return True

    def consume_ammo(self, attacker, ability):
        if attacker is not self.fighter:
            return
        tag = ability.tag
        if tag == "kings_throw":
            self._thrown = self._least_wanted()
            self._thrown_from = self._orbit_pos(self._thrown)
            self.hand.remove(self._thrown)
        elif tag == "kings_play":
            self._fan_from = {id(c): self._orbit_pos(c) for c in self.hand}
            self._flipped = set()
            self._lock_in()
        elif tag == "kings_spread":
            cards = [self._draw_one() for _ in range(3)]
            for c in cards:
                if c is not None:
                    c.reversed = False
            self._spread = cards
            self._spread_view = list(cards)
            self._flipped = set()

    def outgoing_damage(self, attacker, defender, ability, dmg, note):
        if attacker is self.fighter and ability.tag == "kings_throw" and self._thrown is not None:
            dmg += round(attacker.atk * THROW_NUMERAL_BONUS * self._thrown.numeral / 20)
        return dmg, note

    def passive_gauge(self, fighter):
        if fighter is not self.fighter:
            return None
        if self._played is not None:
            name, combos = self._played["result"].name, self._played["combos"]
        else:
            name = self.current_eval().name if self.hand else "-"
            combos = combos_in(self.hand)
        if combos:
            name += " + " + combos[0][0]
        return len(self.deck) / self.deck_size, f"{name.upper()} | DECK {len(self.deck)}", GOLD

    # ---- Play Hand ----------------------------------------------------------------------
    def _lock_in(self):
        """The hand leaves his fingers: the shapers bend it, then the
        Sequence and combos are scored."""
        kings = self.fighter
        cards, self.hand = self.hand, []
        self._hold_t = 0.0
        if self._clear_next:
            self._clear_next = False
            for c in cards:
                c.reversed = False
        mult = 1.0
        for c in [c for c in cards if c.name in SHAPERS]:
            if c not in cards:
                continue
            up = not c.reversed
            if c.name == "magician":
                if up:
                    for o in cards:
                        o.reversed = False
                else:
                    pick = [o for o in cards if o is not c and not o.reversed]
                    if pick:
                        random.choice(pick).reversed = True
            elif c.name == "fortune":
                cards = self._spin_fortune(cards, c, up)
            elif c.name == "strength":
                mult *= 1.4 if up else 0.7
        result = evaluate(cards)
        if result.length == 5:
            for c in cards:
                c.reversed = False
            result.clear = True
        if result.clear:
            mult *= CLEAR_MULT
        if any(c.reversed for c in cards):
            self._omen_t = OMEN_S
        combos = combos_in(cards)
        self._played = {"cards": cards, "result": result, "mult": mult, "combos": combos}
        self._floater(kings.pos, result.name + "!", GOLD, dy=-80, vy=-0.35)

    def _spin_fortune(self, cards, wheel, upright):
        """Wheel of Fortune: deal the rest of the hand again and keep the
        better of the two, or, reversed, the worse."""
        old = [c for c in cards if c is not wheel]
        new = [c for c in (self._draw_one(reshuffle=False) for _ in old) if c is not None]
        if len(new) < len(old):
            for c in new:
                c.reversed = False
                self.deck.append(c)
            return cards
        a, b = [wheel] + old, [wheel] + new
        better = self._hand_value(b) > self._hand_value(a)
        keep, toss = (b, old) if better == upright else (a, new)
        for c in toss:
            self._discard(c)
        self._floater(self.fighter.pos, "The wheel turns!", GOLD if upright else GRAY, dy=-95)
        return keep

    def resolve_special(self):
        battle, kings = self.battle, self.fighter
        if battle.attacker is not kings or battle.ability.tag != "kings_play":
            return False
        played, self._played = self._played, None
        if played is None:
            return True
        try:
            if battle.roll_blind_miss(kings):
                self._floater(kings.pos, "Blinded!", GRAY)
                battle.log = f"{kings.name}'s cards scatter, blinded!"
                return True
            if battle.resolve_redirected_hit():
                battle.log = f"{kings.name} plays his {played['result'].name} into a decoy!"
                return True
            self._play(played, battle.defender)
        finally:
            for c in played["cards"]:
                self._discard(c)
            self._refill()
        return True

    def _play(self, played, enemy):
        battle, kings = self.battle, self.fighter
        result = played["result"]
        cards = played["cards"]
        for c in cards:
            if c.name not in SHAPERS and c.name not in AFTER_HITS:
                self._card_effect(c, enemy, not c.reversed, announce=False)
        if played["combos"]:
            # the cut-in plays as the volley lands, not over the fan and flight
            name, pair, color = played["combos"][0]
            pair_cards = tuple(next(c for c in cards if c.name == n) for n in pair)
            self._cutin = {"cards": pair_cards, "text": " + ".join(c[0] for c in played["combos"]),
                           "color": color, "t": 0.0, "clashed": False}
        for combo in played["combos"]:
            self._combo(combo[0], enemy, played)
        name, hits, mult = SEQUENCES[result.length]
        dealt = 0
        for i in range(hits):
            dealt += self._hit(enemy, mult * played["mult"], spread=i - (hits - 1) / 2)
            self._flash(enemy.pos + pygame.Vector2(random.uniform(-14, 14), random.uniform(-14, 14)),
                        46 + 10 * result.length, GOLD if not result.clear else WHITE, delay=i * 0.06)
        if result.length >= 3:
            self._flash(enemy.pos, 120 + 30 * (result.length - 3), GOLD, delay=hits * 0.06, dur=0.45,
                        tex="flare_01")
        if enemy.is_alive():
            if result.length == 3:
                set_status(enemy, "stunned", TRIAD_STUN_S)
            elif result.length == 4:
                set_status(enemy, "armor_break", 5, amount=PROCESSION_ARMOR_BREAK)
            elif result.length == 5:
                set_status(enemy, "stunned", GRAND_STUN_S)
        for c in cards:
            if c.name in AFTER_HITS:
                self._card_effect(c, enemy, not c.reversed, announce=False)
        if dealt > 0:
            kings.meter = min(kings.meter_max, kings.meter + kings.meter_gain)
            if result.length >= 3:
                battle.apply_impact(enemy, battle.ability)
        combo_txt = "".join(f" + {c[0]}" for c in played["combos"])
        battle.log = f"{kings.name} plays a {result.name}{combo_txt} for {dealt}!"

    def _hit(self, enemy, mult, spread=0.0, label=None):
        """One card connecting: the same direct deal_damage path Sans's
        blasters use, with its own light hit feedback."""
        battle, kings = self.battle, self.fighter
        if enemy is None or not enemy.is_alive() or battle.winner is not None:
            return 0
        if battle.is_invulnerable(enemy) or battle.is_vanished(enemy) or battle.is_untargetable(enemy):
            self._floater(enemy.pos, "Evaded!", WHITE)
            return 0
        dmg = round(kings.atk * mult * battle.status_outgoing_multiplier(kings))
        actual = battle.deal_damage(kings, enemy, dmg)
        enemy.hit_flash = enemy.hit_flash_max = 0.12
        enemy.hit_flash_color = (255, 240, 200)
        enemy.hit_flash_heavy = enemy.hit_flash_crit = False
        enemy.shake = max(enemy.shake, 12)
        emit_spark_burst(battle.fx, enemy.pos, KINGS_EMERALD, count=6)
        text = f"-{round(actual)}" + (f" {label}" if label else "")
        battle.floaters.append([enemy.pos.x + spread * 14, enemy.pos.y - 40 - abs(spread) * 6, -0.6, 255,
                                text, GOLD if label else KINGS_EMERALD])
        for p in battle.plugins:
            p.on_damage_dealt(kings, enemy, actual)
        return actual

    # ---- the cards ------------------------------------------------------------------------
    def _card_effect(self, card, enemy, up, announce=True):
        """One card's effect as it's played (or turned up in the spread):
        the shapers already acted on the hand in _lock_in, so in the spread
        they're a plain Attack Up instead. A played hand's cards are already
        on screen in the fan, so only a spread/Future card names itself."""
        battle, kings = self.battle, self.fighter
        n = card.name
        live = enemy is not None and enemy.is_alive()
        if announce:
            self._floater(kings.pos, card.label(), GOLD if up else OMEN_COLOR, dy=-95, vy=-0.3)
        if n in SHAPERS:
            set_status(kings, "attack_up", 5, pct=0.3)
        elif n == "fool":
            if not up:
                self._floater(kings.pos, "a dead card...", GRAY, dy=-70)
        elif n == "priestess":
            if up:
                self._scry = True
            else:
                set_status(kings, "blind", 2.5, chance=0.4)
        elif n == "empress":
            if up:
                set_status(kings, "regen", 4, pct=0.04)
            elif live:
                set_status(enemy, "regen", 3, pct=0.03)
        elif n == "emperor":
            if up:
                set_status(kings, "armor_up", 5, amount=12)
            else:
                set_status(kings, "attack_down", 4, pct=0.25)
        elif n == "hierophant":
            if up:
                cleanse(kings)
            elif live:
                cleanse(enemy)
        elif n == "lovers":
            if up:
                set_status(kings, "lifesteal", 0.3)
            elif live:
                set_status(enemy, "lifesteal", 3)
        elif n == "chariot":
            if up and live:
                apply_knockback(enemy, kings.pos, 80)
                set_status(enemy, "slowed", 2, pct=0.4)
            elif not up:
                set_status(kings, "rooted", 1.0)
        elif n == "hermit":
            if up:
                set_status(kings, "untargetable", 1.2)
                emit_dark(battle.fx, kings.pos, count=14, radius=26, color=KINGS_EMERALD)
            else:
                set_status(kings, "slowed", 3, pct=0.4)
        elif n == "justice":
            if up and live:
                set_status(enemy, "vulnerability", 0.3, pct=1.0)
            elif live:
                set_status(enemy, "reflect", 3, pct=0.3)
        elif n == "hanged_man":
            if up and live:
                set_status(enemy, "rooted", 1.5)
            elif not up:
                set_status(kings, "rooted", 1.0)
        elif n == "death":
            if up and live:
                set_status(enemy, "vulnerability", 4, pct=0.3)
            elif not up:
                set_status(kings, "vulnerability", 4, pct=0.3)
        elif n == "temperance":
            if live:
                self._temperance(enemy, up)
        elif n == "devil":
            if up and live:
                set_status(enemy, "curse", 1.5, pct=0.3)
            elif not up:
                set_status(kings, "curse", 1.0, pct=0.3)
        elif n == "tower":
            battle.add_screen_shake(8, 0.25)
            if up and live:
                self._hit(enemy, 1.6, label="TOWER")
                if enemy.is_alive():
                    set_status(enemy, "stunned", 0.5)
                battle.add_ring(enemy.pos, 80, 0.4, GOLD, width=4)
                self._flash(enemy.pos, 110, HELLFIRE_COLOR, dur=0.4, tex="flare_01")
            elif not up:
                actual = battle.apply_damage(kings, round(kings.atk * 0.8))
                battle.add_ring(kings.pos, 70, 0.4, OMEN_COLOR, width=4)
                self._flash(kings.pos, 90, OMEN_COLOR, dur=0.4, tex="flare_01")
                self._floater(kings.pos, f"-{round(actual)}", RED, dy=-40, vy=-0.6)
        elif n == "world":
            if up:
                set_status(kings, "shield", 4, absorb=round(0.15 * kings.max_hp))
            else:
                set_status(kings, "armor_break", 4, amount=8)
        elif n == "moon":
            if up and live:
                set_status(enemy, "blind", 3, chance=0.4)
            elif not up:
                set_status(kings, "blind", 2.5, chance=0.4)
        elif n == "sun":
            if up:
                if live:
                    set_status(enemy, "burn", 4)
                set_status(kings, "regen", 3, pct=0.03)
            else:
                set_status(kings, "burn", 2)
        elif n == "judgment":
            if up:
                kings.meter = min(kings.meter_max, kings.meter + 2)
            else:
                kings.meter = max(0, kings.meter - 2)

    def _temperance(self, enemy, up):
        """Upright, the scales tip toward whoever's behind (Kings himself,
        or a plain heal when he's ahead); reversed, they tip away from him."""
        battle, kings = self.battle, self.fighter
        kp, ep = kings.hp / kings.max_hp, enemy.hp / enemy.max_hp
        if up:
            if kp < ep:
                shift = min(0.1, (ep - kp) / 2)
                heal(kings, shift)
                battle.apply_damage(enemy, round(shift * enemy.max_hp), ignore_armor=True)
            else:
                heal(kings, 0.06)
        else:
            loss = min(round(0.03 * kings.max_hp), max(0, round(kings.hp) - 1))
            kings.hp -= loss
            heal(enemy, 0.03)
        battle.add_ring(kings.pos, 60, 0.4, GOLD if up else OMEN_COLOR, width=3)

    # ---- Arcana Combos --------------------------------------------------------------------
    def _combo(self, name, enemy, played):
        battle, kings = self.battle, self.fighter
        live = enemy is not None and enemy.is_alive()
        if name == "Eclipse":
            # The Sun swallowed by the Moon: the target can barely see, and
            # Kings strikes from the dark.
            if live:
                set_status(enemy, "blind", ECLIPSE_S, chance=0.6)
            set_status(kings, "attack_up", ECLIPSE_S, pct=0.3)
            self._eclipse_t = ECLIPSE_TINT_S
        elif name == "Hellfire":
            # The Tower falls and the Devil rains it down: a hail of cards
            # dropping one after another wherever the target is standing.
            for i in range(HELLFIRE_CARDS):
                ang = random.uniform(0, math.tau)
                off = pygame.Vector2(math.cos(ang), math.sin(ang)) * random.uniform(0, HELLFIRE_SPREAD_PX)
                card = next(c for c in played["cards"] if c.name == ("tower", "devil")[i % 2])
                self._strikes.append({"t": 0.45 + 0.22 * i, "fall": STRIKE_FALL_S, "offset": off, "pos": None,
                                      "card": card, "mult": HELLFIRE_MULT, "kind": "hellfire"})
        elif name == "Resurrection":
            # Death and Judgement: the next blow that would kill him only
            # brings him back (see pre_damage).
            set_status(kings, RESURRECT_STATUS, RESURRECT_S)
            battle.add_ring(kings.pos, 70, 0.5, WHITE, width=3)
        elif name == "Juggernaut":
            # The Chariot driven by Strength: straight through the target
            # and out the other side.
            if live:
                start = pygame.Vector2(kings.pos)
                behind = _clamp_point(enemy.pos + battle.atk_dir * 55)
                battle.spawn_afterimage(kings)
                kings.pos = behind
                # "cast" pins him to attacker_start for the rest of the cast
                battle.attacker_start = pygame.Vector2(behind)
                emit_spark_burst(battle.fx, start.lerp(behind, 0.5), GOLD, count=16)
                self._flash(enemy.pos, 100, (230, 170, 70), dur=0.35, tex="flare_01")
                self._hit(enemy, JUGGERNAUT_MULT, label="JUGGERNAUT")
                if enemy.is_alive():
                    apply_knockback(enemy, kings.pos, JUGGERNAUT_KNOCK_PX)
                    set_status(enemy, "stunned", 0.4)
            set_status(kings, "move_speed_up", 4, pct=0.5)
        elif name == "Hidden Truth":
            # The Hermit's lantern and the Priestess's veil: gone from sight,
            # and his next hand dealt with every card upright.
            set_status(kings, "untargetable", HIDDEN_TRUTH_S)
            emit_dark(battle.fx, kings.pos, count=20, radius=30, color=(150, 200, 255))
            self._clear_next = True
        elif name == "Royal Decree":
            # Emperor and Empress: a royal guard for him, a royal order for
            # the target to kneel.
            set_status(kings, "shield", DECREE_S, absorb=round(0.25 * kings.max_hp))
            if live:
                set_status(enemy, "attack_down", DECREE_S, pct=0.3)
        elif name == "Verdict":
            # Justice hangs the target: rooted, then sentenced by however
            # much it's already lost.
            if live:
                set_status(enemy, "rooted", VERDICT_DELAY_S + 0.4)
            card = next(c for c in played["cards"] if c.name == "justice")
            self._strikes.append({"t": VERDICT_DELAY_S, "fall": VERDICT_FALL_S, "offset": pygame.Vector2(),
                                  "pos": None, "card": card, "mult": 0.0, "kind": "verdict"})
        elif name == "Journey's End":
            # From 0 to the World, the whole journey done at once: FATE full
            # and every skill ready again.
            kings.meter = kings.meter_max
            for ab in kings.abilities["skills"]:
                ab.timer = 0
            battle.add_ring(kings.pos, 90, 0.5, (120, 230, 170), width=4)
        elif name == "Jackpot":
            # The Magician spins the Wheel: the whole hand's damage times a roll.
            roll = random.choice(JACKPOT_ROLLS)
            played["mult"] *= roll
            self._floater(kings.pos, f"JACKPOT x{roll}!", (255, 230, 60), dy=-110, vy=-0.3)
        elif name == "Absolution":
            # Every curse on him handed back to whoever laid it.
            moved = [n for n in list(kings.statuses) if n in CLEANSABLE and n != "feared"]
            for n in moved:
                data = kings.statuses.pop(n)
                if live:
                    enemy.statuses[n] = dict(data)
            heal(kings, ABSOLUTION_HEAL)
            self._floater(kings.pos, f"Absolution! ({len(moved)} returned)", (180, 240, 255), dy=-60)
        elif name == "Heartbreak":
            # The Lovers parted by Death: the target's heart is broken.
            # Feared, and every hp it would heal is poisoned instead.
            if live:
                set_status(enemy, "feared", 1.0, source=pygame.Vector2(kings.pos))
                set_status(enemy, "corruption", HEARTBREAK_S, pct=1.0)
                set_status(enemy, "poison", HEARTBREAK_S)

    def pre_damage(self, target, dmg):
        """Resurrection: the blow that would have killed him is spent
        bringing him back instead."""
        kings = self.fighter
        if target is not kings or RESURRECT_STATUS not in kings.statuses or dmg < kings.hp:
            return None
        kings.statuses.pop(RESURRECT_STATUS, None)
        kings.hp = max(1.0, RESURRECT_HP * kings.max_hp)
        battle = self.battle
        battle.add_ring(kings.pos, 100, 0.6, WHITE, width=5)
        emit_spark_burst(battle.fx, kings.pos, WHITE, count=26)
        self._flash(kings.pos, 160, WHITE, dur=0.6, tex="light_01")
        self._floater(kings.pos, "RESURRECTION!", WHITE, dy=-60, vy=-0.4)
        battle.log = f"{kings.name} is judged worthy, and rises again!"
        return 0

    def _tick_strikes(self, dt):
        battle, kings = self.battle, self.fighter
        enemy = self._opponent()
        for st in list(self._strikes):
            st["t"] -= dt
            if st["pos"] is None and st["t"] <= st["fall"]:
                st["pos"] = _clamp_point(enemy.pos + st["offset"])
            if st["t"] > 0:
                continue
            self._strikes.remove(st)
            pos = st["pos"] or pygame.Vector2(enemy.pos)
            verdict = st["kind"] == "verdict"
            battle.add_ring(pos, STRIKE_R + (30 if verdict else 8), 0.35, GOLD, width=4 if verdict else 2)
            battle.add_screen_shake(8 if verdict else 3, 0.15)
            emit_spark_burst(battle.fx, pos, WHITE if verdict else HELLFIRE_COLOR, count=14 if verdict else 6)
            self._flash(pos, 130 if verdict else 60, WHITE if verdict else HELLFIRE_COLOR,
                        dur=0.4 if verdict else 0.25, tex="flare_01" if verdict else "star_06")
            if not enemy.is_alive() or (enemy.pos - pos).length() > STRIKE_R + enemy.hitbox_r:
                continue
            if not verdict:
                self._hit(enemy, st["mult"])
                continue
            if battle.is_invulnerable(enemy) or battle.is_vanished(enemy) or battle.is_untargetable(enemy):
                self._floater(enemy.pos, "Evaded!", WHITE)
                continue
            dmg = max(kings.atk, round(VERDICT_MISSING_HP * (enemy.max_hp - enemy.hp)))
            actual = battle.apply_damage(enemy, dmg, ignore_armor=True)
            enemy.hit_flash = enemy.hit_flash_max = 0.2
            enemy.hit_flash_color = WHITE
            enemy.hit_flash_heavy = enemy.hit_flash_crit = False
            enemy.shake = max(enemy.shake, 20)
            self._floater(enemy.pos, f"-{round(actual)} VERDICT", GOLD, dy=-45, vy=-0.6)
            for p in battle.plugins:
                p.on_damage_dealt(kings, enemy, actual)

    # ---- Throw / Fold / Spread tag effects ----------------------------------------------
    def apply_tag_effects(self, ability, attacker, defender):
        if attacker is not self.fighter:
            return
        if ability.tag == "kings_throw" and defender is not None:
            self._flash(defender.pos, 44, GOLD, dur=0.22)
        elif ability.tag == "kings_fold":
            self._fold()
        elif ability.tag == "kings_spread":
            self._resolve_spread(self._opponent())

    def _fold(self):
        battle, kings = self.battle, self.fighter
        for c in self.hand:
            p = self._orbit_pos(c)
            out = p - kings.pos
            out = out.normalize() if out.length_squared() else pygame.Vector2(1, 0)
            self._scatter.append({"card": c, "pos": p, "vel": out * random.uniform(180, 260), "t": 0.0,
                                  "spin": random.uniform(-720, 720), "reversed": c.reversed})
            self._discard(c)
        self.hand = []
        self._refill()
        set_status(kings, "untargetable", FOLD_UNTARGETABLE_S)
        battle.spawn_afterimage(kings)
        emit_dark(battle.fx, kings.pos, count=16, radius=28, color=KINGS_EMERALD)
        self._floater(kings.pos, "Fold.", WHITE)
        battle.log = f"{kings.name} folds and deals himself a new hand."

    def _resolve_spread(self, enemy):
        battle, kings = self.battle, self.fighter
        past, present, future = ((self._spread or []) + [None, None, None])[:3]
        if past is not None:
            then = next((hp for t, hp in self._hp_hist if t >= self._clock - PAST_S), kings.hp)
            power = 0.5 + 0.5 * past.numeral / 20
            got = heal(kings, max(0.0, then - kings.hp) * power / kings.max_hp)
            self._floater(kings.pos, f"PAST +{round(got)}", GREEN, dy=-45, vy=-0.6)
            self._flash(kings.pos, 120, GREEN, delay=0.25, dur=0.45, tex="light_01")
            self._discard(past)
        if present is not None:
            self._card_effect(present, enemy, True)
            self._hit(enemy, PRESENT_MULT, label="PRESENT")
            self._flash(enemy.pos, 120, GOLD, delay=0.2, dur=0.4, tex="flare_01")
            self._discard(present)
        if future is not None:
            self._futures.append({"pos": pygame.Vector2(enemy.pos), "t": FUTURE_DELAY_S, "card": future})
        self._spread = None
        battle.add_ring(kings.pos, 110, 0.5, GOLD, width=5)
        battle.flash_timer = max(battle.flash_timer, 0.2)
        battle.log = f"{kings.name} reads the spread: Past, Present... and a Future yet to come."

    def _tick_futures(self, dt):
        battle = self.battle
        enemy = self._opponent()
        for fu in list(self._futures):
            fu["t"] -= dt
            if fu["t"] > 0:
                continue
            self._futures.remove(fu)
            card, pos = fu["card"], fu["pos"]
            battle.add_ring(pos, FUTURE_R + 20, 0.5, GOLD, width=5)
            battle.add_screen_shake(9, 0.25)
            emit_spark_burst(battle.fx, pos, GOLD, count=24)
            self._flash(pos, 180, GOLD, dur=0.5, tex="flare_01")
            self._floater(pos, "FUTURE", GOLD, dy=-60, vy=-0.4)
            if enemy.is_alive() and (enemy.pos - pos).length() <= FUTURE_R + enemy.hitbox_r:
                self._hit(enemy, FUTURE_MULT, label="FATE")
                self._card_effect(card, enemy, True)
            self._discard(card)

    # ---- per-frame ----------------------------------------------------------------------
    def ambient_tick(self, dt):
        battle, kings = self.battle, self.fighter
        self._clock += dt
        if self._zone is None:
            # Invisible, off-screen: only here for zone_decorate, which draws
            # under the fighters.
            self._zone = Zone("arcana", pygame.Vector2(-500, -500), 0, 1e9, kings)
            battle.zones.append(self._zone)
        self._hp_hist.append((self._clock, kings.hp))
        while self._hp_hist and self._hp_hist[0][0] < self._clock - PAST_S - 0.5:
            self._hp_hist.pop(0)
        if kings not in battle.attacks:
            # A throw that resolved (or whiffed), a hand or spread cut off mid-cast.
            if self._thrown is not None:
                self._discard(self._thrown)
                self._thrown = None
            if self._played is not None:
                for c in self._played["cards"]:
                    self._discard(c)
                self._played = None
            if self._spread is not None:
                for c in self._spread:
                    if c is not None:
                        self._discard(c)
                self._spread = None
            self._spread_view = []
            if kings.is_alive() and len(self.hand) < HAND_SIZE:
                self._refill()
        play = next(ab for ab in kings.abilities["skills"] if ab.tag == "kings_play")
        if play.timer <= 0 and self.hand and not self._hand_worth_playing():
            self._hold_t += dt
        if battle.winner is None:
            self._tick_futures(dt)
            self._tick_strikes(dt)
        self._tick_presentation(dt)
        kings.image = self._pose()

    def _tick_presentation(self, dt):
        battle = self.battle
        self._eclipse_t = max(0.0, self._eclipse_t - dt)
        self._omen_t = max(0.0, self._omen_t - dt)
        self._shuffle_t = max(0.0, self._shuffle_t - dt)
        # every orbit slot eases toward its even share of the ring
        n = len(self.hand)
        for i, c in enumerate(self.hand):
            goal = i * math.tau / max(1, n)
            cur = self._slot.get(id(c), goal)
            diff = (goal - cur + math.pi) % math.tau - math.pi
            self._slot[id(c)] = cur + diff * min(1.0, dt * 8)
        for f in self._flashes:
            f["t"] += dt
        self._flashes = [f for f in self._flashes if f["t"] < f["dur"]]
        for s in self._scatter:
            s["t"] += dt
            s["pos"] += s["vel"] * dt
            s["vel"] *= max(0.0, 1 - dt * 3)
        self._scatter = [s for s in self._scatter if s["t"] < SCATTER_S]
        if self._cutin is not None:
            self._cutin["t"] += dt
            if not self._cutin["clashed"] and self._cutin["t"] >= CUTIN_CLASH:
                self._cutin["clashed"] = True
                battle.add_screen_shake(6, 0.2)
            if self._cutin["t"] >= CUTIN_S:
                self._cutin = None

    # ---- presentation: sprite -------------------------------------------------------------
    def _pose(self):
        battle, kings = self.battle, self.fighter
        enemy = self._opponent()
        flip = enemy.pos.x < kings.pos.x
        bob = round(IDLE_BOB_PX * math.sin(self._clock * IDLE_BOB_SPEED))
        if not kings.is_alive():
            return compose("reversed", angle=-20, dy=6, gray=True)
        state = battle.attacks.get(kings)
        if state is not None:
            tag, phase, t = state.ability.tag, state.current_phase, state.phase_t
            hop = -round(4 * math.sin(math.pi * t))
            if tag == "kings_spread":
                return compose("ultimate", dy=hop if phase == "windup" else -3, flip=flip)
            if tag == "kings_play":
                lean = (-6 if state.atk_dir.x > 0 else 6) if phase == "channel" else 0
                return compose("cast", angle=lean, dy=hop if phase == "windup" else 0, flip=state.atk_dir.x < 0)
            if tag == "kings_fold":
                return compose("cast", angle=round(10 * math.sin(math.pi * t)), flip=flip)
            if tag == "kings_throw" and phase in ("windup", "fire"):
                lean = -10 if state.atk_dir.x > 0 else 10
                return compose("king", angle=lean if phase == "fire" else -lean // 2, dy=hop, flip=flip)
        if self._omen_t > 0:
            return compose("reversed", dy=bob, flip=flip)
        if "stunned" in kings.statuses:
            return compose("king", angle=round(6 * math.sin(self._clock * 20)), flip=flip)
        tilt = max(-6, min(6, round(-kings.vel.x / 30))) * 2
        return compose("king", angle=tilt, dy=bob, flip=flip)

    # ---- presentation: the orbit ------------------------------------------------------------
    def _orbit_angle(self, card):
        return self._clock * ORBIT_SPEED + self._slot.get(id(card), 0.0)

    def _orbit_pos(self, card, pos=None):
        pos = self.fighter.pos if pos is None else pos
        a = self._orbit_angle(card)
        return pygame.Vector2(pos.x + math.cos(a) * ORBIT_RX, pos.y + ORBIT_DY + math.sin(a) * ORBIT_RY)

    def _draw_orbit(self, screen, pos, front):
        """The near (front=True) or far half of the orbiting hand."""
        kings = self.fighter
        if not self.hand or not kings.is_alive() or self._shuffle_t > 0:
            return
        res = self.current_eval()
        run = {id(c) for c in res.run} if res.length >= 2 else set()
        partners = {n for _, pair, _ in combos_in(self.hand) for n in pair}
        items = []
        for c in self.hand:
            a = self._orbit_angle(c)
            depth = (math.sin(a) + 1) / 2  # 0 far, 1 near
            if (depth >= 0.5) != front:
                continue
            items.append((depth, c, a))
        for depth, c, a in sorted(items, key=lambda x: x[0]):
            deal = min(1.0, (self._clock - self._dealt.get(id(c), -9)) / DEAL_S)
            p = self._orbit_pos(c, pos)
            p.y += math.sin(self._clock * 3 + c.numeral) * 2
            p = pos.lerp(p, ease_out(deal))
            scale = (0.75 + 0.4 * depth) * (0.3 + 0.7 * ease_out(deal))
            alpha = 150 + 105 * depth
            if c.name in partners:
                add_dot(screen, p, 14 * scale, COMBO_GLOW, 0.5 + 0.2 * math.sin(self._clock * 8))
            elif id(c) in run:
                add_dot(screen, p, 13 * scale, GOLD, 0.45)
            angle = -math.cos(a) * 14
            _blit_card(screen, card_image(c, ORBIT_W, ORBIT_H), p, angle=angle, scale=scale, alpha=alpha)

    def zone_decorate(self, screen, zone):
        """Under the fighters: the far half of the orbit, the casting
        circles and the Future's seal."""
        if zone is not self._zone:
            return
        battle, kings = self.battle, self.fighter
        for fu in self._futures:
            if fu["t"] <= FUTURE_DELAY_S - FUTURE_FLIGHT_S:
                k = 1 - fu["t"] / FUTURE_DELAY_S
                draw_cast_circle(screen, (fu["pos"].x, fu["pos"].y + 4), GOLD, FUTURE_R * 1.6,
                                 self._clock * (60 + 240 * k), alpha=120 + 100 * k)
        state = battle.attacks.get(kings)
        if state is not None and state.ability.tag in ("kings_play", "kings_fold") \
                and state.current_phase in ("windup", "channel"):
            fade = min(1.0, state.phase_t * 3 + (1 if state.current_phase == "channel" else 0))
            draw_cast_circle(screen, (kings.pos.x, kings.pos.y + 6), KINGS_EMERALD, AVATAR_R * 3.4,
                             self._clock * 160, alpha=190 * fade)
        self._draw_orbit(screen, kings.pos, front=False)

    def zone_style(self, zone):
        return KINGS_EMERALD, "Arcana"

    # ---- presentation: fx -----------------------------------------------------------------
    def draw_fx(self, screen, shake_x):
        battle, kings = self.battle, self.fighter
        offset = pygame.Vector2(shake_x, 0)
        pos = kings.pos + offset
        for fu in self._futures:
            self._draw_future(screen, fu, offset)
        for st in self._strikes:
            self._draw_strike(screen, st, offset)
        self._draw_orbit(screen, pos, front=True)
        if self._shuffle_t > 0:
            self._draw_shuffle(screen, pos)
        for s in self._scatter:
            k = s["t"] / SCATTER_S
            img = card_image(s["card"], ORBIT_W, ORBIT_H)
            if s["reversed"]:
                img = pygame.transform.rotate(img, 180)
            _blit_card(screen, img, s["pos"] + offset, angle=s["spin"] * k, scale=1 - 0.4 * k,
                       alpha=255 * (1 - k))
        state = battle._current
        if state is not None and state.attacker is kings:
            tag = state.ability.tag
            if tag == "kings_play":
                self._draw_play(screen, state, pos)
            elif tag == "kings_spread":
                self._draw_spread(screen, state, pos)
            elif tag == "kings_throw" and state.current_phase == "windup" and self._thrown is not None:
                hand_pt = pos + state.atk_dir * 22
                start = (self._thrown_from or pos) + offset
                k = ease_out(state.phase_t)
                p = start.lerp(hand_pt, k)
                add_dot(screen, p, 12, GOLD, 0.5 * k)
                _blit_card(screen, card_image(self._thrown, THROWN_W, THROWN_H), p, scale=1 + 0.3 * k)
        for f in self._flashes:
            if f["t"] < 0:
                continue
            k = f["t"] / f["dur"]
            draw_glow_texture(screen, f["tex"], f["pos"] + offset, f["size"] * (0.6 + 0.7 * ease_out(k)),
                              f["color"], fade=1 - k, angle=k * 90)

    def _draw_shuffle(self, screen, pos):
        """The reshuffle: the deck whirled into a riffle around him."""
        k = 1 - self._shuffle_t / RESHUFFLE_S
        cards = self.deck[:8] or self.discard[:8]
        for i, c in enumerate(cards):
            a = self._clock * 14 + i * math.tau / len(cards)
            r = 24 + 10 * math.sin(math.pi * k)
            p = pos + pygame.Vector2(math.cos(a) * r * 1.4, math.sin(a) * r * 0.7 - 6)
            _blit_card(screen, card_image(c, 12, 24, hidden=True), p, angle=math.degrees(-a) % 360)

    def _fan_slots(self, state, pos, n):
        d = state.atk_dir
        side = pygame.Vector2(-d.y, d.x)
        if side.y > 0:
            side = -side  # fan reads left to right
        center = pos + d * 34 + pygame.Vector2(0, -10)
        return [center + side * (k * FAN_STEP) - d * (abs(k) * 7) for k in (i - (n - 1) / 2 for i in range(n))]

    def _draw_play(self, screen, state, pos):
        """Windup: the hand gathers into a fan and turns face up card by
        card. Channel: only the cards that hit (the Sequence) fly, one after
        another on curving paths; the rest flare where they are and fade,
        their effect spent."""
        if self._played is None:
            return
        battle = self.battle
        cards = self._played["cards"]
        n = len(cards)
        slots = self._fan_slots(state, pos, n)
        phase, t = state.current_phase, state.phase_t
        result = self._played["result"]
        run = result.run if result.length >= 3 else []
        hitters = result.run or cards[:1]
        order = {id(c): j for j, c in enumerate(hitters)}
        m = len(hitters)
        enemy = battle.defender.pos if battle.defender is not None else battle.defender_start
        d = state.atk_dir
        side = pygame.Vector2(-d.y, d.x)
        placed = {}
        for i, c in enumerate(cards):
            k = i - (n - 1) / 2
            if phase == "windup":
                start = self._fan_from.get(id(c), pos)
                g = ease_out(min(1.0, t * 1.5))
                p = start.lerp(slots[i], g)
                local = max(0.0, min(1.0, (t - 0.3 - 0.1 * i) / 0.25))
                hidden = local < 0.5
                sx = abs(math.cos(math.pi * local))
                if not hidden and id(c) not in self._flipped:
                    self._flipped.add(id(c))
                    self._flash(p, 40, OMEN_COLOR if c.reversed else GOLD, dur=0.25, tex="light_01")
                    if c.reversed:
                        emit_dark(battle.fx, p, count=8, radius=14, color=OMEN_COLOR)
                angle, scale = -k * 8, 0.75 + 0.25 * g
            elif phase == "channel" and id(c) not in order:
                # not part of the Sequence: its effect flares out in place
                f = min(1.0, t / 0.4)
                p = slots[i] + pygame.Vector2(0, -12 * ease_out(f))
                add_dot(screen, p, 20 * (1 + f), OMEN_COLOR if c.reversed else GOLD, 0.5 * (1 - f))
                _blit_card(screen, card_image(c, FAN_W, FAN_H), p, angle=-k * 8, scale=1 + 0.3 * f,
                           alpha=255 * (1 - f))
                placed[id(c)] = p
                continue
            elif phase == "channel":
                j0 = order[id(c)]
                k = j0 - (m - 1) / 2
                f = max(0.0, min(1.0, (t - 0.09 * j0) / (1 - 0.09 * max(0, m - 1))))
                f = ease_in(f)
                ctrl = slots[i].lerp(enemy, 0.5) + side * (k * 55) + pygame.Vector2(0, -50)
                p = _bezier(slots[i], ctrl, enemy, f)
                # a fading trail of where it just was
                for j, ghost in enumerate((0.07, 0.14, 0.21)):
                    if f - ghost > 0:
                        gp = _bezier(slots[i], ctrl, enemy, f - ghost)
                        _blit_card(screen, card_image(c, THROWN_W, THROWN_H), gp, angle=(f - ghost) * 720 + k * 30,
                                   scale=0.9, alpha=110 - 35 * j)
                hidden, sx = False, 1.0
                angle, scale = -k * 8 + f * 720, 1.0 - 0.2 * f
                if f > 0:
                    add_dot(screen, p, 12, GOLD, 0.4)
            else:
                continue
            placed[id(c)] = p
            img = card_image(c, FAN_W, FAN_H, hidden=hidden)
            if phase == "windup" and not hidden:
                add_dot(screen, p, 18, OMEN_COLOR if c.reversed else GOLD, 0.35)
            _blit_card(screen, img, p, angle=angle, scale=scale, sx=sx)
        if run and len(placed) == n:
            pts = [placed[id(c)] for c in run if id(c) in placed]
            if len(pts) >= 2:
                glow_polyline(screen, pts, GOLD, width=2, intensity=0.9 if phase == "channel" else 0.6 * t)

    def _spread_slots(self, pos):
        y = max(ARENA_RECT.top + SPREAD_H / 2 + 4, pos.y - self.fighter.hitbox_r - SPREAD_H / 2 - 14)
        half = SPREAD_GAP + SPREAD_W / 2 + 10
        cx = max(ARENA_RECT.left + half, min(ARENA_RECT.right - half, pos.x))
        return [pygame.Vector2(cx + (i - 1) * SPREAD_GAP, y + abs(i - 1) * 10) for i in range(3)]

    def _draw_spread(self, screen, state, pos):
        """Windup: three cards rise into an arc. Channel: each turns over in
        turn. Release: Past sinks into him, Present strikes the target, the
        Future flies off to be planted."""
        battle = self.battle
        phase, t = state.current_phase, state.phase_t
        slots = self._spread_slots(pos)
        enemy = battle.defender.pos if battle.defender is not None else pos
        for i, card in enumerate(self._spread_view):
            if card is None:
                continue
            slot = slots[i]
            tilt = (1 - i) * 10
            hidden, sx, scale, alpha = False, 1.0, 1.0, 255
            if phase == "windup":
                local = ease_out(max(0.0, min(1.0, t * 1.6 - i * 0.25)))
                p = pos.lerp(slot, local)
                hidden, scale, tilt = True, 0.4 + 0.6 * local, tilt + (1 - local) * 180
            elif phase == "channel":
                local = max(0.0, min(1.0, t * 3 - i))
                hidden, sx = local < 0.5, abs(math.cos(math.pi * local))
                p = slot + pygame.Vector2(0, -4 * math.sin(math.pi * local))
                if not hidden and id(card) not in self._flipped:
                    self._flipped.add(id(card))
                    self._flash(p, 90, (GREEN, GOLD, OMEN_COLOR)[i], dur=0.35, tex="light_01")
                    battle.add_screen_shake(3, 0.1)
            else:
                k = ease_in(t)
                if i == 0:
                    p, scale, alpha = slot.lerp(pos, k), 1 - 0.7 * k, 255 * (1 - k)
                elif i == 1:
                    p, scale = slot.lerp(enemy, k), 1 + 0.2 * k
                else:
                    dest = self._futures[-1]["pos"] if self._futures else enemy
                    p, scale = slot.lerp(dest, k), 1 - 0.35 * k
                    hidden = k > 0.6
                tilt = tilt * (1 - k) + k * 360 * (i == 1)
            glow = (GREEN, GOLD, OMEN_COLOR)[i]
            if not hidden:
                add_dot(screen, p, SPREAD_W * 0.8 * scale, glow, 0.35)
            _blit_card(screen, card_image(card, SPREAD_W, SPREAD_H, hidden=hidden), p, angle=tilt, scale=scale,
                       alpha=alpha, sx=sx)
            if phase == "channel":
                txt = battle.font_small.render(("PAST", "PRESENT", "FUTURE")[i], True, glow)
                screen.blit(txt, txt.get_rect(midtop=(round(slot.x), round(slot.y + SPREAD_H / 2 + 2))))

    def _draw_strike(self, screen, st, offset):
        """A card dropping onto its locked landing spot, its ring tightening
        under it; Verdict's comes down slowly in a shaft of light."""
        if st["pos"] is None:
            return
        k = 1 - max(0.0, st["t"]) / st["fall"]
        p = st["pos"] + offset
        big = st["kind"] == "verdict"
        glow_ring(screen, p, STRIKE_R * (1.4 - 0.4 * k), GOLD if big else HELLFIRE_COLOR, width=2,
                  intensity=0.3 + 0.7 * k)
        if big:
            draw_glow_texture(screen, "light_01", p + pygame.Vector2(0, -90), 170, WHITE, fade=0.25 + 0.5 * k,
                              stretch=(0.25, 1.6))
            drop = pygame.Vector2(p.x, p.y - 150 * (1 - ease_in_out(k)))
            _blit_card(screen, card_image(st["card"], 30, 60), drop, scale=1.0 + 0.2 * (1 - k))
        else:
            drop = pygame.Vector2(p.x, p.y - 150 * (1 - k) ** 2)
            draw_glow_texture(screen, "fire_01", drop + pygame.Vector2(0, -16), 40, HELLFIRE_COLOR, fade=0.8)
            _blit_card(screen, card_image(st["card"], 16, 32), drop, angle=720 * k)

    def _draw_future(self, screen, fu, offset):
        """The planted Future: hovering face down over its seal, shaking
        harder as it runs out, turned face up in its last moment."""
        if fu["t"] > FUTURE_DELAY_S - FUTURE_FLIGHT_S:
            return
        k = 1 - fu["t"] / FUTURE_DELAY_S
        jitter = 3 * k * k
        p = fu["pos"] + offset + pygame.Vector2(random.uniform(-jitter, jitter),
                                                -20 + 3 * math.sin(self._clock * 4) + random.uniform(-jitter, jitter))
        local = max(0.0, min(1.0, (0.6 - fu["t"]) / 0.3))
        hidden, sx = local < 0.5, abs(math.cos(math.pi * local))
        add_dot(screen, p, 20 + 10 * k, GOLD, 0.3 + 0.4 * (0.5 + 0.5 * math.sin(self._clock * (6 + 14 * k))))
        _blit_card(screen, card_image(fu["card"], FUTURE_W, FUTURE_H, hidden=hidden), p, sx=sx)

    def draw_projectile(self, screen):
        battle = self.battle
        if battle.attacker is not self.fighter or battle.projectile_pos is None:
            return False
        if battle.ability.tag != "kings_throw" or self._thrown is None:
            return False
        state = battle._current
        img = card_image(self._thrown, THROWN_W, THROWN_H)
        t = state.phase_t
        for j, ghost in enumerate((0.12, 0.24, 0.36)):
            if t - ghost > 0:
                gp = battle.attacker_start.lerp(battle.defender_start, t - ghost)
                _blit_card(screen, img, gp, angle=(t - ghost) * 900, scale=0.9, alpha=120 - 35 * j)
        pos = battle.projectile_pos
        add_dot(screen, pos, 12, GOLD, 0.45)
        _blit_card(screen, img, pos, angle=t * 900, scale=1.15)
        return True

    def full_screen_overlay(self, screen):
        """The spread's dim, Eclipse's darkness, and the combo cut-in."""
        state = self.battle.attacks.get(self.fighter)
        alpha = 0
        if state is not None and state.ability.tag == "kings_spread" and state.current_phase != "release":
            alpha = SPREAD_TINT_ALPHA
        if self._eclipse_t > 0:
            alpha = max(alpha, round(120 * min(1.0, self._eclipse_t / 0.5)))
        if alpha:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((20, 0, 30, alpha))
            screen.blit(overlay, (0, 0))
        if self._cutin is not None:
            self._draw_cutin(screen)

    def _draw_cutin(self, screen):
        """The combo's two cards sliding in from either side of the arena
        and slamming together under its name."""
        ci = self._cutin
        t = ci["t"]
        fade = min(1.0, (CUTIN_S - t) / 0.3)
        center = pygame.Vector2(ARENA_RECT.centerx, ARENA_RECT.top + 110)
        band = pygame.Surface((ARENA_RECT.width, 190), pygame.SRCALPHA)
        band.fill((10, 0, 20, round(150 * fade)))
        screen.blit(band, (ARENA_RECT.left, center.y - 95))
        if t < 0.6:
            draw_speed_lines(screen, center, ARENA_RECT, int(self._clock * 20), alpha=round(110 * (1 - t / 0.6)),
                             count=40, clear_radius=80)
        slide = ease_out(min(1.0, t / CUTIN_CLASH))
        for side, card in zip((-1, 1), ci["cards"]):
            far = center + pygame.Vector2(side * (ARENA_RECT.width / 2 + CUTIN_W), 0)
            rest = center + pygame.Vector2(side * (CUTIN_W / 2 + 4), 0)
            recoil = 6 * math.sin(math.pi * min(1.0, max(0.0, t - CUTIN_CLASH) / 0.15)) if t > CUTIN_CLASH else 0
            p = far.lerp(rest, slide) + pygame.Vector2(side * recoil, 0)
            _blit_card(screen, card_image(card, CUTIN_W, CUTIN_H), p, angle=-side * 8 * (1 - slide) + side * 4,
                       alpha=255 * fade)
        if t >= CUTIN_CLASH:
            k = min(1.0, (t - CUTIN_CLASH) / 0.5)
            draw_glow_texture(screen, "flare_01", center, 240, ci["color"], fade=(1 - k) * fade)
            draw_glow_texture(screen, "light_01", center, 150, WHITE, fade=(1 - k) ** 2 * fade)
            img = self.battle.font_mid.render(ci["text"].upper() + "!", True, ci["color"])
            img.set_alpha(round(255 * fade))
            rise = round(10 * ease_out(min(1.0, (t - CUTIN_CLASH) / 0.2)))
            screen.blit(img, img.get_rect(center=(center.x, center.y + CUTIN_H / 2 + 16 - rise)))
