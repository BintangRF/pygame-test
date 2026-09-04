"""HUD/overlay drawing: the match title, each fighter's status panel
(HP bar, cooldowns, meter), floating damage/heal numbers, the battle log
line, full-screen tints (Berserker Rage / Eternal Night / hit-flash), the
win banner, and the debug readout. None of this touches gameplay state —
it only reads it.
"""

import pygame

from ..core.constants import GOLD, GRAY, GREEN, HEIGHT, METER_COLOR, RED, WHITE, WIDTH
from ..core.entities import format_cd

# short labels for the per-skill cooldown readout in the status panel
SKILL_ABBREV = {
    "Judgment Mark": "Mark",
    "Divine Shield": "Shld",
    "Sacred Ground": "Grnd",
    "Blood Bolt": "Bolt",
    "Blood Hex": "Hex",
    "Bat Swarm": "Swrm",
    "Blood Pool": "Pool",
    "Crimson Doppelganger": "Clon",
    "Axe Throw": "AxeT",
    "Chain Bolt": "Cbolt",
    "Static Field": "Stat",
    "Blink Strike": "Blnk",
    "Tusk Act 2": "Act2",
    "Tusk Act 3": "Act3",
}


class HUDMixin:
    def draw_debug(self, screen):
        lines = [
            f"Motion: {self.motion}",
            f"Phase: {self.current_phase}  t={self.phase_t:.2f}",
            f"Mode: {self.mode}",
            f"Particles: {len(self.fx)}  Rings: {len(self.rings)}",
            f"Afterimages: {len(self.afterimages)}  Floaters: {len(self.floaters)}",
            f"HitStop: {self.hit_stop_timer:.0f}ms  Shake: {self.camera_shake.strength:.1f}",
            f"TimeScale: {self.time_scale:.2f}  Zoom: {self.zoom:.2f}",
        ]
        panel = pygame.Surface((150, 14 * len(lines) + 8), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 160))
        screen.blit(panel, (4, 90))
        for i, line in enumerate(lines):
            screen.blit(self.font_small.render(line, True, GREEN), (8, 94 + i * 14))

    def draw_title(self, screen):
        vs_gap = 14
        name1 = self.font_big.render(self.f1.name.upper(), True, GOLD)
        vs = self.font_big.render("VS", True, WHITE)
        name2 = self.font_big.render(self.f2.name.upper(), True, RED)
        total_w = name1.get_width() + vs.get_width() + name2.get_width() + vs_gap * 2
        x = (WIDTH - total_w) // 2
        y = 18
        screen.blit(name1, (x, y))
        x += name1.get_width() + vs_gap
        screen.blit(vs, (x, y))
        x += vs.get_width() + vs_gap
        screen.blit(name2, (x, y))

        who = self.font_mid.render("WHO WILL WIN?", True, WHITE)
        screen.blit(who, ((WIDTH - who.get_width()) // 2, 64))

    def draw_flash(self, screen):
        if self.flash_timer <= 0:
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        alpha = int(180 * (self.flash_timer / 400))
        overlay.fill((255, 240, 180, alpha))
        screen.blit(overlay, (0, 0))

    def draw_status_panel(self, screen, f, left_side):
        panel_x = 18 if left_side else WIDTH - 18
        y = 416

        def blit_ra(surf, yy):
            xx = panel_x if left_side else panel_x - surf.get_width()
            screen.blit(surf, (xx, yy))

        blit_ra(self.font_small.render(f.name.upper(), True, f.color), y)

        bar_w, bar_h = 140, 7
        bar_x = panel_x if left_side else panel_x - bar_w
        pygame.draw.rect(screen, GRAY, (bar_x, y + 15, bar_w, bar_h))
        ratio = max(0.0, f.hp / f.max_hp)
        pygame.draw.rect(screen, GREEN if ratio > 0.3 else RED, (bar_x, y + 15, bar_w * ratio, bar_h))

        atk_txt = f"ATK {f.atk}"
        if f.nail_bullets_max > 0:
            atk_txt += f"  NAIL {f.nail_bullets}/{f.nail_bullets_max}"
        blit_ra(self.font_small.render(atk_txt, True, WHITE), y + 26)

        basic = f.abilities["basic"]
        basic_ready = basic.timer <= 0
        blit_ra(
            self.font_small.render(f"Basic {format_cd(basic.timer)}", True,
                                    GREEN if basic_ready else GRAY),
            y + 39,
        )

        row_y = y + 51
        skills = f.abilities["skills"]
        for i in range(0, len(skills), 2):
            parts = []
            for s in skills[i:i + 2]:
                label = SKILL_ABBREV.get(s.name, s.name[:4])
                parts.append(f"{label} {format_cd(s.timer)}")
            blit_ra(self.font_small.render("  ".join(parts), True, WHITE), row_y)
            row_y += 11

        ult = f.abilities["ultimate"]
        if ult.hp_threshold is not None:
            hp_ratio = f.hp / f.max_hp
            ult_ready = not ult.used and ult.timer <= 0 and hp_ratio < ult.hp_threshold
            if ult.used:
                ult_label = "ULT: USED"
            elif ult_ready:
                ult_label = "ULT: READY"
            elif ult.timer > 0:
                ult_label = f"ULT: {format_cd(ult.timer)}"
            else:
                ult_label = f"ULT: HP<{int(ult.hp_threshold * 100)}%"
            blit_ra(self.font_small.render(ult_label, True, GOLD if ult_ready else GRAY), row_y)
            return

        ult_ready = ult.timer <= 0 and f.meter >= f.meter_max
        ult_label = "ULT: READY" if ult_ready else (
            f"ULT: {format_cd(ult.timer)}" if ult.timer > 0 else "ULT: charging"
        )
        blit_ra(self.font_small.render(ult_label, True, GOLD if ult_ready else GRAY), row_y)
        row_y += 13

        meter_w, meter_h = 140, 6
        meter_x = panel_x if left_side else panel_x - meter_w
        pygame.draw.rect(screen, GRAY, (meter_x, row_y, meter_w, meter_h))
        m_ratio = f.meter / f.meter_max
        pygame.draw.rect(screen, METER_COLOR, (meter_x, row_y, meter_w * m_ratio, meter_h))
        blit_ra(
            self.font_small.render(f"{f.meter_name} {round(f.meter)}/{f.meter_max}", True, WHITE),
            row_y + 8,
        )

    def draw_floaters(self, screen):
        for x, y, _vy, alpha, text, color in self.floaters:
            emphasize = "ULT!" in text or "EXECUTE" in text
            font = self.font_big if emphasize else self.font_mid
            surf = font.render(text, True, color)
            surf.set_alpha(max(0, int(alpha)))
            screen.blit(surf, (x - surf.get_width() / 2, y))

    def draw_log(self, screen):
        surf = self.font_small.render(self.log, True, WHITE)
        screen.blit(surf, ((WIDTH - surf.get_width()) // 2, HEIGHT - 20))

    def draw_winner(self, screen):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        text = f"{self.winner.name} WINS!"
        surf = self.font_big.render(text, True, GOLD)
        screen.blit(surf, ((WIDTH - surf.get_width()) // 2, HEIGHT // 2 - 20))
        hint = self.font_small.render("Press R to restart, Esc to quit", True, WHITE)
        screen.blit(hint, ((WIDTH - hint.get_width()) // 2, HEIGHT // 2 + 30))
