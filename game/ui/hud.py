"""HUD/overlay drawing: the match title, each fighter's status panel
(HP bar, cooldowns, meter), floating damage/heal numbers, the battle log
line, full-screen tints (Berserker Rage / Eternal Night / hit-flash), the
win banner, and the debug readout. None of this touches gameplay state —
it only reads it.
"""

import pygame

from ..core.constants import (
    GOLD, GRAY, GREEN, HEIGHT, METER_COLOR, NAIL_SILVER, POISON_COLOR, RED, SHIELD_COLOR, STUN_COLOR, WHITE, WIDTH,
)
from ..core.effects import draw_icon_glyph
from ..core.entities import format_cd
from ..core.status_library import RING_COLOR as STATUS_RING_COLOR
from ..core.status_library import STATUS_ICON

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
    "Static Link": "Link",
    "Tusk Act 2": "Act2",
    "Tusk Act 3": "Act3",
    "Twin Fangs": "Fangs",
    "Death Scent": "Scent",
    "Trace of Death": "Trace",
    "Zabaniya": "Zaba",
}

# short labels for the buff/debuff readout below the meter — falls back to a
# truncated, title-cased status name for anything not listed here.
STATUS_ABBREV = {
    "stunned": "Stun", "frozen": "Frozen", "rooted": "Root", "silenced": "Silence",
    "disarmed": "Disarm", "slowed": "Slow", "feared": "Fear", "asleep": "Sleep",
    "curse": "Curse", "bleed": "Bleed", "poison": "Poison", "burn": "Burn",
    "corruption": "Corrupt", "armor_break": "ArmBrk", "vulnerability": "Vuln",
    "attack_down": "AtkDn", "attack_speed_down": "SpdDn", "blind": "Blind",
    "cooldown_increase": "CDUp", "regen": "Regen", "shield": "Shield",
    "damage_reduction": "DmgRed", "attack_up": "AtkUp", "attack_speed_up": "SpdUp",
    "move_speed_up": "MSpdUp", "lifesteal": "Lifestl", "invulnerable": "Invuln",
    "reflect": "Reflect", "static": "Static", "untargetable": "Untarg",
    "armor_up": "ArmUp", "death_ultimate": "Dark", "bh_lethal_mark": "Lethal",
    "spin_charge": "Spin",
}

# Reuses the same per-status ring color render.py draws around the fighter
# (STATUS_RING_COLOR for the generic status_library.py effects), plus the
# handful of statuses that keep their own hand-tuned ring color in render.py
# instead of a STATUS_RING_COLOR entry (see its own docstring note).
STATUS_COLOR = dict(STATUS_RING_COLOR)
STATUS_COLOR.update({
    "shield": SHIELD_COLOR,
    "bleed": RED,
    "poison": POISON_COLOR,
    "rooted": NAIL_SILVER,
    "stunned": STUN_COLOR,
})
# Statuses that read as a positive buff when a character's own bespoke
# status (e.g. Raiju's "static") isn't in STATUS_COLOR at all — everything
# else defaults to a negative/debuff color instead.
BUFF_STATUS_NAMES = {
    "regen", "shield", "damage_reduction", "attack_up", "attack_speed_up",
    "move_speed_up", "lifesteal", "invulnerable", "reflect",
    "armor_up", "death_ultimate", "bh_lethal_mark", "spin_charge",
}
# Caps the buff/debuff readout so a heavily-stacked target can't push the
# panel past the battle log line at the bottom of the screen.
MAX_STATUS_ROWS = 4

# draw_floaters' settle-in: how small a floater has shrunk to by the time
# it's fully faded out (1.0 = no shrink at all).
FLOATER_MIN_SCALE = 0.55


# Compact icon glyph drawn just before each Basic/Skill/Ultimate row and
# each active-status row (see draw_status_panel/draw_status_effects below) —
# SKILL_ABBREV/STATUS_ABBREV alone read fine to someone who already has them
# memorized, but a quick recognizable shape (circle/diamond/star by ability
# kind, or the same per-status icon already drawn as a ring around the
# fighter) gives everyone else something to spot at a glance instead of just
# more abbreviated text.
ICON_R = 4
ICON_GAP = 4


def _blit_icon_row(screen, panel_x, left_side, y, shape, color, text_surf):
    icon_cy = y + text_surf.get_height() / 2
    if left_side:
        icon_cx = panel_x + ICON_R
        text_x = panel_x + ICON_R * 2 + ICON_GAP
    else:
        icon_cx = panel_x - ICON_R
        text_x = panel_x - ICON_R * 2 - ICON_GAP - text_surf.get_width()
    draw_icon_glyph(screen, shape, (icon_cx, icon_cy), ICON_R, color)
    screen.blit(text_surf, (text_x, y))


def _move_dmg_label(ability):
    """Compact move-stat readout: the move's damage as a percentage of ATK,
    or UTIL for a 0-damage utility move (shield/mark/zone/curse/...)."""
    if ability.dmg_mult <= 0:
        return "UTIL"
    return f"{round(ability.dmg_mult * 100)}%"


class HUDMixin:
    def draw_debug(self, screen):
        # Up to two fighters can each have their own AttackState in flight
        # at once now (see self.attacks) — list each one directly rather
        # than a single Motion/Phase line, since there's no longer exactly
        # one "current" attack for the whole match.
        lines = [f"Mode: {self.mode}"]
        for f in (self.f1, self.f2):
            state = self.attacks.get(f)
            if state is None:
                lines.append(f"{f.name}: roaming")
            else:
                lines.append(f"{f.name}: {state.motion}/{state.current_phase} t={state.phase_t:.2f}")
        lines += [
            f"Particles: {len(self.fx)}  Rings: {len(self.rings)}",
            f"Afterimages: {len(self.afterimages)}  Floaters: {len(self.floaters)}",
            f"Shake: {self.camera_shake.strength:.1f}  Zoom: {self.zoom:.2f}",
        ]
        panel = pygame.Surface((190, 14 * len(lines) + 8), pygame.SRCALPHA)
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
        alpha = int(180 * (self.flash_timer / 0.4))
        overlay.fill((255, 240, 180, alpha))
        screen.blit(overlay, (0, 0))

    def draw_status_panel(self, screen, f, left_side):
        panel_x = 18 if left_side else WIDTH - 18
        y = 496

        def blit_ra(surf, yy):
            xx = panel_x if left_side else panel_x - surf.get_width()
            screen.blit(surf, (xx, yy))

        blit_ra(self.font_small.render(f.name.upper(), True, f.color), y)

        bar_w, bar_h = 140, 7
        bar_x = panel_x if left_side else panel_x - bar_w
        pygame.draw.rect(screen, GRAY, (bar_x, y + 15, bar_w, bar_h))
        ratio = max(0.0, f.hp / f.max_hp)
        pygame.draw.rect(screen, GREEN if ratio > 0.3 else RED, (bar_x, y + 15, bar_w * ratio, bar_h))

        # status_outgoing_multiplier (status_library.py) folds Attack Up/Down
        # in live, same "current/base" treatment effective_armor already gets
        # right below — otherwise a landed Attack Up buff would show no
        # visible change here even though it's genuinely boosting every hit.
        eff_atk = round(f.atk * self.status_outgoing_multiplier(f))
        atk_txt = f"ATK {eff_atk}" if eff_atk >= f.atk else f"ATK {eff_atk}/{f.atk}"
        if f.nail_bullets_max > 0:
            atk_txt += f"  NAIL {f.nail_bullets}/{f.nail_bullets_max}"
        # Paladin's own Radiant Energy (characters/paladin/plugin.py) — every
        # hit taken banks a pct of it here as flat bonus damage, unloaded
        # whole on the Paladin's own next attack (outgoing_damage) — shown
        # only once something's actually banked, same "only when relevant"
        # convention the NAIL readout above already uses for Johnny.
        if f.radiant_energy > 0:
            atk_txt += f"  RAD +{round(f.radiant_energy)}"
        blit_ra(self.font_small.render(atk_txt, True, WHITE if eff_atk >= f.atk else RED), y + 26)

        # effective_armor (status_library.py) folds Armor Break/Vulnerability
        # in live, so this reads as "current/base" the moment either debuff
        # is chewing on it instead of always showing the static base value.
        armor = self.effective_armor(f)
        armor_txt = f"ARM {armor:.0f}" if armor >= f.armor else f"ARM {armor:.0f}/{f.armor:.0f}"
        blit_ra(self.font_small.render(armor_txt, True, WHITE if armor >= f.armor else RED), y + 38)

        basic = f.abilities["basic"]
        basic_ready = basic.timer <= 0
        basic_color = GREEN if basic_ready else GRAY
        _blit_icon_row(
            screen, panel_x, left_side, y + 50, "circle", basic_color,
            self.font_small.render(
                f"Basic {_move_dmg_label(basic)} {format_cd(basic.timer)}", True, basic_color,
            ),
        )

        row_y = y + 62
        for s in f.abilities["skills"]:
            label = SKILL_ABBREV.get(s.name, s.name[:4])
            ready = s.timer <= 0
            skill_color = GREEN if ready else WHITE
            _blit_icon_row(
                screen, panel_x, left_side, row_y, "diamond", skill_color,
                self.font_small.render(
                    f"{label} {_move_dmg_label(s)} {format_cd(s.timer)}", True, skill_color,
                ),
            )
            row_y += 12

        ult = f.abilities["ultimate"]
        ult_dmg = _move_dmg_label(ult)
        if ult.hp_threshold is not None:
            hp_ratio = f.hp / f.max_hp
            ult_ready = not ult.used and ult.timer <= 0 and hp_ratio < ult.hp_threshold
            if ult.used:
                ult_label = f"ULT {ult_dmg}: USED"
            elif ult_ready:
                ult_label = f"ULT {ult_dmg}: READY"
            elif ult.timer > 0:
                ult_label = f"ULT {ult_dmg}: {format_cd(ult.timer)}"
            else:
                ult_label = f"ULT {ult_dmg}: HP<{int(ult.hp_threshold * 100)}%"
            ult_color = GOLD if ult_ready else GRAY
            _blit_icon_row(
                screen, panel_x, left_side, row_y, "star", ult_color,
                self.font_small.render(ult_label, True, ult_color),
            )
            row_y += 12
        else:
            ult_ready = ult.timer <= 0 and f.meter >= f.meter_max
            ult_label = f"ULT {ult_dmg}: " + (
                "READY" if ult_ready else (format_cd(ult.timer) if ult.timer > 0 else "charging")
            )
            ult_color = GOLD if ult_ready else GRAY
            _blit_icon_row(
                screen, panel_x, left_side, row_y, "star", ult_color,
                self.font_small.render(ult_label, True, ult_color),
            )
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
            row_y += 21

        row_y = self.draw_passive_gauge(screen, f, blit_ra, panel_x, left_side, row_y)
        self.draw_status_effects(screen, f, blit_ra, panel_x, left_side, row_y)

    def draw_passive_gauge(self, screen, f, blit_ra, panel_x, left_side, row_y):
        """A character's own bespoke passive resource (see
        CharacterPlugin.passive_gauge) — None for every character without
        one, so this is a no-op for the whole roster except whoever opts in."""
        plugin = self.plugin_for(f)
        gauge = plugin.passive_gauge(f) if plugin is not None else None
        if gauge is None:
            return row_y
        ratio, label, color = gauge
        ratio = max(0.0, min(1.0, ratio))
        bar_w, bar_h = 140, 6
        bar_x = panel_x if left_side else panel_x - bar_w
        pygame.draw.rect(screen, GRAY, (bar_x, row_y, bar_w, bar_h))
        pygame.draw.rect(screen, color, (bar_x, row_y, bar_w * ratio, bar_h))
        blit_ra(self.font_small.render(label, True, color), row_y + 8)
        return row_y + 21

    def draw_status_effects(self, screen, f, blit_ra, panel_x, left_side, row_y):
        """Active buff/debuff readout: one status per row (icon + name + time
        left), colored the same as that status's ring around the fighter.
        The icon reuses the exact (shape, ring) pair status_library.
        STATUS_ICON already assigns that status for its own ring around the
        fighter (falls back to a plain circle for the handful of statuses —
        bleed, poison, static, spin_charge, rooted, stunned, shield — that
        draw their own bespoke ring instead of using that generic table), so
        a row here always reads as the same effect as the ring on the
        character instead of just more abbreviated text. Capped at
        MAX_STATUS_ROWS with a "+N more" line so a heavily-stacked target
        can't push the panel into the battle log line below it."""
        names = sorted(f.statuses.keys())
        shown, extra = names[:MAX_STATUS_ROWS], names[MAX_STATUS_ROWS:]
        for name in shown:
            data = f.statuses[name]
            label = STATUS_ABBREV.get(name, name.replace("_", " ").title()[:8])
            secs = data.get("time", 0)
            color = STATUS_COLOR.get(name, GREEN if name in BUFF_STATUS_NAMES else RED)
            icon = STATUS_ICON.get(name)
            shape = icon["shape"] if icon else "circle"
            _blit_icon_row(
                screen, panel_x, left_side, row_y, shape, color,
                self.font_small.render(f"{label} {secs:.1f}s", True, color),
            )
            row_y += 12
        if extra:
            blit_ra(self.font_small.render(f"+{len(extra)} more", True, GRAY), row_y)

    def draw_floaters(self, screen):
        for fl in self.floaters:
            x, y, _vy, alpha, text, color = fl[:6]
            # fl[6] (spawn alpha) only exists once battle_loop's per-frame
            # tick has lazily added it — before that (the very first frame a
            # floater exists) life_ratio just defaults to "brand new", which
            # also degrades cleanly to the old plain fade-only look if it's
            # ever missing.
            spawn_alpha = fl[6] if len(fl) > 6 else alpha
            life_ratio = max(0.0, min(1.0, alpha / spawn_alpha)) if spawn_alpha else 0.0
            emphasize = "ULT!" in text or "EXECUTE" in text or "CRIT!" in text
            font = self.font_big if emphasize else self.font_mid
            surf = font.render(text, True, color)
            scale = FLOATER_MIN_SCALE + (1 - FLOATER_MIN_SCALE) * life_ratio
            if scale < 0.98:
                w, h = surf.get_width(), surf.get_height()
                surf = pygame.transform.smoothscale(surf, (max(1, round(w * scale)), max(1, round(h * scale))))
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
