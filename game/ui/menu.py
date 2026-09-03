"""
Pre-battle menus: pick fighter 1, pick fighter 2, then pick the match's
best-of-N length. Needed once there are more than two selectable characters
— the old code always just booted Paladin vs Vampire.
"""

import pygame

from ..core.assets import CHARACTERS
from ..core.constants import GOLD, GRAY, GREEN, HEIGHT, ORANGE, WHITE, WIDTH

BO_OPTIONS = [1, 3, 5, 7]  # best-of-N choices offered (minimum 1)
CARD_ASPECT = 150 / 118  # height/width ratio a card's contents were designed around
CARD_W_BOUNDS = (80, 130)  # card never gets narrower/wider than this, however many there are
CARD_GAP = 16
CARD_ROW_GAP = 14
CARD_MARGIN = 20  # side padding the card grid must stay within
GRID_Y0 = 148
GRID_BOTTOM = HEIGHT - 50  # leaves room for the footer line below the grid


def _card_grid(n):
    """Pick a (cols, card_w, card_h) grid sized entirely from `n` and the
    available screen area — never a fixed card count or size — so the grid
    keeps fitting the window as characters are added or removed.

    For every possible column count, the card size is capped by whichever
    dimension is tighter: available width / cols, or available height / rows
    (converted through CARD_ASPECT so cards keep their designed proportions).
    The column count that lets cards be biggest wins; ties prefer more
    columns (a wider, shorter grid reads better than a tall narrow one)."""
    avail_w = WIDTH - 2 * CARD_MARGIN
    avail_h = GRID_BOTTOM - GRID_Y0
    min_w, max_w = CARD_W_BOUNDS

    best = None  # (card_w, cols)
    for cols in range(n, 0, -1):
        rows = -(-n // cols)  # ceil division
        w_from_width = (avail_w - (cols - 1) * CARD_GAP) / cols
        h_from_height = (avail_h - (rows - 1) * CARD_ROW_GAP) / rows
        w_from_height = h_from_height / CARD_ASPECT
        card_w = max(min_w, min(max_w, w_from_width, w_from_height))
        if best is None or card_w > best[0]:
            best = (card_w, cols)

    card_w, cols = best
    card_h = card_w * CARD_ASPECT
    return cols, card_w, card_h


def _card_rects(n):
    """Lay `n` cards out as a centered grid, sized and wrapped automatically
    by _card_grid so a row never overflows the window."""
    cols, card_w, card_h = _card_grid(n)
    rows = -(-n // cols)

    rects = []
    for i in range(n):
        row, col = divmod(i, cols)
        cols_in_row = cols if (row < rows - 1 or n % cols == 0) else n % cols
        row_w = cols_in_row * card_w + (cols_in_row - 1) * CARD_GAP
        x0 = (WIDTH - row_w) / 2
        y = GRID_Y0 + row * (card_h + CARD_ROW_GAP)
        x = x0 + col * (card_w + CARD_GAP)
        rects.append(pygame.Rect(round(x), round(y), round(card_w), round(card_h)))
    return rects


class CharacterSelect:
    """Two-stage character picker followed by a best-of-N picker.

    Drive it from the main loop: feed it events via handle_event(), draw it
    every frame via draw(), and check `.done` — once true, `.result` holds
    (key1, key2, best_of).
    """

    def __init__(self):
        self.keys = list(CHARACTERS.keys())
        self.stage = "p1"  # "p1" -> "p2" -> "bo" -> done
        self.p1_key = None
        self.p2_key = None
        self.bo_index = 1  # BO_OPTIONS[1] == 3, a reasonable default
        self.done = False
        self.result = None

        self.font_big = pygame.font.SysFont("consolas", 26, bold=True)
        self.font_mid = pygame.font.SysFont("consolas", 16, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 12, bold=True)

        self._card_rects = _card_rects(len(self.keys))
        self._bo_rects = []
        self._confirm_rect = None

    # ---- input -----------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_click(event.pos)
        elif event.type == pygame.KEYDOWN:
            self._handle_key(event.key)

    def _handle_click(self, pos):
        if self.stage in ("p1", "p2"):
            available = [k for k in self.keys if k != self.p1_key] if self.stage == "p2" else self.keys
            rects = _card_rects(len(available))
            for key, rect in zip(available, rects):
                if rect.collidepoint(pos):
                    self._pick(key)
                    return
        elif self.stage == "bo":
            for i, rect in self._bo_rects:
                if rect.collidepoint(pos):
                    self.bo_index = i
                    return
            if self._confirm_rect and self._confirm_rect.collidepoint(pos):
                self._confirm()

    def _handle_key(self, key):
        if self.stage in ("p1", "p2"):
            available = [k for k in self.keys if k != self.p1_key] if self.stage == "p2" else self.keys
            if key in (pygame.K_1, pygame.K_KP1) and len(available) >= 1:
                self._pick(available[0])
            elif key in (pygame.K_2, pygame.K_KP2) and len(available) >= 2:
                self._pick(available[1])
            elif key in (pygame.K_3, pygame.K_KP3) and len(available) >= 3:
                self._pick(available[2])
            elif key in (pygame.K_4, pygame.K_KP4) and len(available) >= 4:
                self._pick(available[3])
            elif key == pygame.K_BACKSPACE and self.stage == "p2":
                self.stage, self.p1_key = "p1", None
        elif self.stage == "bo":
            if key in (pygame.K_LEFT, pygame.K_a):
                self.bo_index = (self.bo_index - 1) % len(BO_OPTIONS)
            elif key in (pygame.K_RIGHT, pygame.K_d):
                self.bo_index = (self.bo_index + 1) % len(BO_OPTIONS)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._confirm()
            elif key == pygame.K_BACKSPACE:
                self.stage, self.p2_key = "p2", None

    def _pick(self, key):
        if self.stage == "p1":
            self.p1_key = key
            self.stage = "p2"
        elif self.stage == "p2":
            self.p2_key = key
            self.stage = "bo"

    def _confirm(self):
        self.done = True
        self.result = (self.p1_key, self.p2_key, BO_OPTIONS[self.bo_index])

    # ---- drawing -----------------------------------------------------------
    def draw(self, screen):
        screen.fill((10, 10, 12))
        if self.stage == "p1":
            self._draw_character_stage(screen, "CHOOSE YOUR FIRST FIGHTER", self.keys)
        elif self.stage == "p2":
            available = [k for k in self.keys if k != self.p1_key]
            self._draw_character_stage(screen, "CHOOSE YOUR SECOND FIGHTER", available)
        else:
            self._draw_bo_stage(screen)

    def _draw_character_stage(self, screen, title, available):
        title_surf = self.font_big.render(title, True, WHITE)
        screen.blit(title_surf, ((WIDTH - title_surf.get_width()) // 2, 60))

        key_hint = "/".join(str(i + 1) for i in range(len(available)))
        hint = self.font_small.render(f"Click a card, or press {key_hint}", True, GRAY)
        screen.blit(hint, ((WIDTH - hint.get_width()) // 2, 100))

        rects = _card_rects(len(available))
        self._card_rects = rects
        mouse_pos = pygame.mouse.get_pos()
        for i, (key, rect) in enumerate(zip(available, rects)):
            spec = CHARACTERS[key]
            hovered = rect.collidepoint(mouse_pos)
            self._draw_card(screen, rect, spec, hovered, index=i + 1)

        if self.p1_key is not None and self.stage == "p2":
            p1_spec = CHARACTERS[self.p1_key]
            chosen = self.font_small.render(
                f"Fighter 1: {p1_spec['label']}  (Backspace to change)", True, GOLD
            )
            screen.blit(chosen, ((WIDTH - chosen.get_width()) // 2, HEIGHT - 30))

    # vertical anchor points as a fraction of card height, taken from the
    # original 118x150 card design — keeps the layout proportional however
    # big or small `_card_grid` ends up sizing the cards
    IMG_Y_FRAC = 44 / 150
    LABEL_Y_FRAC = 84 / 150
    ERA_Y_FRAC = 104 / 150
    THUMB_FRAC = 64 / 118  # thumbnail size relative to card width

    def _draw_card(self, screen, rect, spec, hovered, index):
        border = GOLD if hovered else GRAY
        pygame.draw.rect(screen, (25, 25, 28), rect, border_radius=8)
        pygame.draw.rect(screen, border, rect, width=2, border_radius=8)

        thumb_size = round(rect.width * self.THUMB_FRAC)
        cache = spec.setdefault("_thumb_cache", {})
        img = cache.get(thumb_size)
        if img is None:
            from ..core.assets import character_sprite
            img = character_sprite(spec, thumb_size)
            cache[thumb_size] = img
        img_rect = img.get_rect(center=(rect.centerx, rect.y + rect.height * self.IMG_Y_FRAC))
        screen.blit(img, img_rect)

        label = self.font_mid.render(spec["label"], True, spec["color"])
        screen.blit(label, (rect.centerx - label.get_width() // 2, rect.y + rect.height * self.LABEL_Y_FRAC))

        era = self.font_small.render(spec["era"], True, GRAY)
        screen.blit(era, (rect.centerx - era.get_width() // 2, rect.y + rect.height * self.ERA_Y_FRAC))

        num = self.font_small.render(f"[{index}]", True, GRAY)
        screen.blit(num, (rect.x + 6, rect.y + 6))

    def _draw_bo_stage(self, screen):
        title_surf = self.font_big.render("MATCH LENGTH", True, WHITE)
        screen.blit(title_surf, ((WIDTH - title_surf.get_width()) // 2, 60))

        p1 = CHARACTERS[self.p1_key]
        p2 = CHARACTERS[self.p2_key]
        vs = self.font_mid.render(f"{p1['label']} vs {p2['label']}", True, WHITE)
        screen.blit(vs, ((WIDTH - vs.get_width()) // 2, 105))

        hint = self.font_small.render("Left/Right to choose, Enter to start", True, GRAY)
        screen.blit(hint, ((WIDTH - hint.get_width()) // 2, 135))

        n = len(BO_OPTIONS)
        total_w = n * 70 + (n - 1) * 12
        x0 = (WIDTH - total_w) // 2
        y0 = 190
        self._bo_rects = []
        for i, bo in enumerate(BO_OPTIONS):
            rect = pygame.Rect(x0 + i * (70 + 12), y0, 70, 70)
            selected = i == self.bo_index
            pygame.draw.rect(screen, (25, 25, 28), rect, border_radius=8)
            pygame.draw.rect(screen, GOLD if selected else GRAY, rect,
                              width=3 if selected else 2, border_radius=8)
            label = self.font_big.render(str(bo), True, GOLD if selected else WHITE)
            screen.blit(label, (rect.centerx - label.get_width() // 2, rect.centery - 16))
            self._bo_rects.append((i, rect))

        sub = self.font_small.render("games", True, GRAY)
        screen.blit(sub, ((WIDTH - sub.get_width()) // 2, y0 + 78))

        needed = BO_OPTIONS[self.bo_index] // 2 + 1
        need_txt = self.font_small.render(f"First to {needed} wins takes the match", True, GRAY)
        screen.blit(need_txt, ((WIDTH - need_txt.get_width()) // 2, y0 + 100))

        self._confirm_rect = pygame.Rect(WIDTH // 2 - 70, y0 + 130, 140, 40)
        pygame.draw.rect(screen, GREEN, self._confirm_rect, border_radius=6)
        start_label = self.font_mid.render("START", True, (10, 10, 12))
        screen.blit(start_label, (self._confirm_rect.centerx - start_label.get_width() // 2,
                                   self._confirm_rect.centery - start_label.get_height() // 2))


class SeriesTracker:
    """Tracks wins across a best-of-N series between two fixed fighters."""

    def __init__(self, key1, key2, best_of):
        self.key1, self.key2 = key1, key2
        self.best_of = best_of
        self.needed = best_of // 2 + 1
        self.wins = {key1: 0, key2: 0}
        self.round_no = 1

    def record(self, winner_key):
        self.wins[winner_key] += 1

    def series_winner(self):
        for key, w in self.wins.items():
            if w >= self.needed:
                return key
        return None

    def next_round(self):
        self.round_no += 1

    def reset(self):
        """Start a fresh series between the same two fighters — the rematch
        path, which skips character select entirely."""
        self.wins = {self.key1: 0, self.key2: 0}
        self.round_no = 1


def draw_series_result(screen, tracker, font_big, font_mid, font_small):
    """Overlay shown after a single game ends: score so far, and whether the
    whole series is decided or another round is coming."""
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 190))
    screen.blit(overlay, (0, 0))

    p1_label = CHARACTERS[tracker.key1]["label"]
    p2_label = CHARACTERS[tracker.key2]["label"]
    score = f"{p1_label} {tracker.wins[tracker.key1]} - {tracker.wins[tracker.key2]} {p2_label}"
    score_surf = font_mid.render(score, True, WHITE)
    screen.blit(score_surf, ((WIDTH - score_surf.get_width()) // 2, HEIGHT // 2 - 60))

    winner_key = tracker.series_winner()
    if winner_key is not None:
        label = CHARACTERS[winner_key]["label"]
        text = f"{label} WINS THE MATCH!"
        color = GOLD
        hint = "Enter: Rematch    N: New Fighters    Esc: Quit"
    else:
        text = f"ROUND {tracker.round_no} — GET READY"
        color = ORANGE
        hint = "Press Enter to continue"

    text_surf = font_big.render(text, True, color)
    screen.blit(text_surf, ((WIDTH - text_surf.get_width()) // 2, HEIGHT // 2 - 20))

    hint_surf = font_small.render(hint, True, WHITE)
    screen.blit(hint_surf, ((WIDTH - hint_surf.get_width()) // 2, HEIGHT // 2 + 30))
