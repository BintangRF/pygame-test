"""Window/display wrapper: every screen still renders onto a fixed
WIDTH x HEIGHT canvas exactly as before (see constants.py) — VirtualDisplay
just scales that canvas up to fill however big the real OS window happens to
be, uniformly (never stretched) and letterboxed/pillarboxed to keep the
logical aspect ratio intact, whether the window is freely resized or made
fullscreen. Only battle_animation.py's main loop needs to know the real
window can now be a different size than the canvas it draws on.
"""

import pygame


class VirtualDisplay:
    def __init__(self, width, height, caption):
        self.width = width
        self.height = height
        self.window = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption(caption)
        # Every draw() call in the game still targets this — same size it
        # always was, so no other module needs to change.
        self.canvas = pygame.Surface((width, height))
        self.fullscreen = False
        self._windowed_size = (width, height)

    def handle_event(self, event):
        """Feed every pygame event through here before anything else reads
        it. Two jobs: actually resize the real window's own surface on
        VIDEORESIZE (SDL2 needs an explicit set_mode call to grow/shrink it
        — the event alone doesn't do that), and rewrite any mouse position
        on the event in place from real window pixels into this display's
        own canvas space, so every caller (menu click handling, etc.) can
        keep reading event.pos exactly as if the window were never resized
        or letterboxed at all."""
        if event.type == pygame.VIDEORESIZE and not self.fullscreen:
            self._windowed_size = (event.w, event.h)
            self.window = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
        if hasattr(event, "pos"):
            event.pos = self.to_canvas(event.pos)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self._windowed_size = self.window.get_size()
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.window = pygame.display.set_mode(self._windowed_size, pygame.RESIZABLE)

    def _viewport(self):
        """(scale, offset_x, offset_y, out_w, out_h) placing the canvas as
        large as possible inside the real window without distorting its
        aspect ratio — whatever gap is left on the sides/top-bottom stays
        plain black (letterbox/pillarbox)."""
        win_w, win_h = self.window.get_size()
        scale = min(win_w / self.width, win_h / self.height)
        scale = max(scale, 0.01)
        out_w, out_h = max(1, round(self.width * scale)), max(1, round(self.height * scale))
        return scale, (win_w - out_w) // 2, (win_h - out_h) // 2, out_w, out_h

    def to_canvas(self, pos):
        """Real-window pixel coordinates -> this display's own WIDTH x
        HEIGHT canvas coordinates, undoing the letterbox offset/scale
        present() draws the canvas with — e.g. for a mouse click's own
        event.pos, so menu hit-testing never has to know the window isn't
        drawn 1:1 any more."""
        scale, off_x, off_y, _out_w, _out_h = self._viewport()
        return ((pos[0] - off_x) / scale, (pos[1] - off_y) / scale)

    def mouse_pos(self):
        """pygame.mouse.get_pos(), translated the same way to_canvas
        translates an event's own position — for hover checks that poll the
        mouse directly every frame instead of reacting to an event."""
        return self.to_canvas(pygame.mouse.get_pos())

    def present(self):
        """Scale the finished canvas into the real window and flip it —
        call once per frame, after this frame's draw() calls are done."""
        scale, off_x, off_y, out_w, out_h = self._viewport()
        self.window.fill((0, 0, 0))
        if abs(scale - 1.0) < 1e-6 and (off_x, off_y) == (0, 0):
            self.window.blit(self.canvas, (0, 0))
        else:
            scaled = pygame.transform.smoothscale(self.canvas, (out_w, out_h))
            self.window.blit(scaled, (off_x, off_y))
        pygame.display.flip()
