"""
Fighter Arena — animated arena battle (Python + Pygame).

This file is just the entry point: create the window, run the character
select -> battle -> series-result flow. The actual game logic lives in the
`game/` package:

    game/core/               — engine layer, shared by every character:
                                abilities.py (the Ability data bundle),
                                plugin.py (the CharacterPlugin extension point —
                                see its docstring for the full hook contract),
                                entities.py (Character/Zone/Clone), constants.py,
                                motions.py, combat_resolution.py, status_effects.py,
                                battle_loop.py, render.py, assets.py (the CHARACTERS
                                registry), asset_loading.py, impact_fx.py, camera.py,
                                particles.py
    game/characters/<name>/  — one folder per fighter (paladin, vampire, berserker,
                                sukuna, raiju, johnny), each with its own moves.py
                                (move list) and plugin.py (a CharacterPlugin
                                subclass: gameplay logic + animation). Adding a new
                                fighter means writing this folder and one entry in
                                CHARACTERS — no engine file needs to change.
    game/ui/                 — menu.py (character-select and best-of-N screens),
                                hud.py (status panels, floaters, log, overlays)
    game/battle.py           — BattleAnimation: the state machine and renderer

Run:
    python battle_animation.py
"""

import pygame

from game.battle import BattleAnimation
from game.core.assets import make_fighters
from game.core.constants import FPS, HEIGHT, WIDTH
from game.core.display import VirtualDisplay
from game.ui.menu import CharacterSelect, PauseMenu, SeriesTracker, draw_series_result


def main():
    pygame.init()
    display = VirtualDisplay(WIDTH, HEIGHT, "Fighter Arena")
    screen = display.canvas
    clock = pygame.time.Clock()

    font_big = pygame.font.SysFont("consolas", 28, bold=True)
    font_mid = pygame.font.SysFont("consolas", 17, bold=True)
    font_small = pygame.font.SysFont("consolas", 12, bold=True)

    state = "select"  # "select" | "battle" | "series_result"
    select = CharacterSelect()
    pause_menu = PauseMenu()
    tracker = None
    battle = None
    paused = False  # only ever true while state == "battle"

    def resume_battle():
        nonlocal paused
        paused = False

    def quit_battle():
        # Back to character select, abandoning the current series entirely
        # — not the same as quitting the whole app (Esc/window close still
        # do that), just this fight.
        nonlocal state, select, tracker, battle, paused
        paused = False
        state = "select"
        select = CharacterSelect()
        tracker = None
        battle = None

    running = True
    while running:
        dt = clock.tick(FPS) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if state == "battle":
                    # Toggles both ways: opens the pause overlay, and (since
                    # this fires again the next time Esc is pressed while
                    # already paused) closes it back to resume, same as the
                    # overlay's own "Esc: Resume" hint.
                    paused = not paused
                else:
                    running = False
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_F3 and battle is not None:
                battle.toggle_debug()
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                display.toggle_fullscreen()
                continue

            # Resizes the real window on VIDEORESIZE and rewrites any mouse
            # position on the event from real window pixels into canvas
            # space, so select.handle_event/pause_menu.handle_event below
            # can keep reading event.pos as if the window were always drawn
            # 1:1.
            display.handle_event(event)

            if state == "battle" and paused:
                pause_menu.handle_event(event, resume_battle, quit_battle)
                continue

            if state == "select":
                select.handle_event(event)
            elif state == "series_result" and event.type == pygame.KEYDOWN:
                decided = tracker.series_winner() is not None
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    if decided:
                        # Rematch: same two fighters, no trip back through
                        # character select — just reset the score and go.
                        tracker.reset()
                    else:
                        tracker.next_round()
                    battle = BattleAnimation(*make_fighters(tracker.key1, tracker.key2))
                    state = "battle"
                elif decided and event.key == pygame.K_n:
                    state = "select"
                    select = CharacterSelect()
                    tracker = None

        if state == "select" and select.done:
            key1, key2, best_of = select.result
            tracker = SeriesTracker(key1, key2, best_of)
            battle = BattleAnimation(*make_fighters(key1, key2))
            state = "battle"

        if state == "select":
            select.draw(screen, mouse_pos=display.mouse_pos())
        elif state == "battle":
            if not paused:
                battle.update(dt)
                if battle.mode == "gameover":
                    tracker.record(battle.winner.key)
                    state = "series_result"
            battle.draw(screen, show_winner=False)
            if paused:
                pause_menu.draw(screen, font_big, font_mid, font_small)
        elif state == "series_result":
            battle.draw(screen, show_winner=False)
            draw_series_result(screen, tracker, font_big, font_mid, font_small)

        display.present()

    pygame.quit()


if __name__ == "__main__":
    main()
