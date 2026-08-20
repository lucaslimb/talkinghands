# -*- coding: utf-8 -*-
"""
Talking Hands — Main Menu (PySide6)

Sidebar-driven launcher. Uses a while-loop + quitOnLastWindowClosed toggle
so the menu and instrument sessions never share a nested event loop.

Entry point: start_menu(resolution_profile, show_trackers, hand_model_complexity)
"""

import sys
import os
import time
import json
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QStackedWidget, QScrollArea, QGridLayout, QProgressBar,
    QLineEdit, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QEventLoop, QTimer, QUrl, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QPoint, QRect
from PySide6.QtGui import QCursor, QFontDatabase, QFont, QDesktopServices

FILE_PATH    = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.instruments.ui_shared import (
    load_custom_font, FONT_FAMILY,
    FONT_SIZE_SM as BASE_FONT_SIZE_SM, FONT_SIZE_MD as BASE_FONT_SIZE_MD,
    FONT_SIZE_LG as BASE_FONT_SIZE_LG, BTN_HEIGHT as BASE_BTN_HEIGHT,
    BORDER_RAD as BASE_BORDER_RAD,
)

# Menu typography is intentionally a little larger than the instrument UI.
FONT_SIZE_SM = round(BASE_FONT_SIZE_SM * 1.18)
FONT_SIZE_MD = round(BASE_FONT_SIZE_MD * 1.18)
FONT_SIZE_LG = round(BASE_FONT_SIZE_LG * 1.18)
BTN_HEIGHT = round(BASE_BTN_HEIGHT * 1.10)
BORDER_RAD = round(BASE_BORDER_RAD * 1.10)
SECTION_FONT_SIZE = 11

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
MENU_BG              = "#F0EDE8"
MENU_SIDEBAR_BG      = "#E9E6E1"
MENU_CARD_BG         = "#FFFFFF"
MENU_CARD_HOVER      = "#F7F5F2"
MENU_CARD_DARK       = "#1E1E1B"
MENU_CARD_DARK_TEXT  = "#FFFFFF"
MENU_CARD_BORDER     = "#E0DDD8"
MENU_SEPARATOR       = "#D5D2CD"
MENU_TEXT_MAIN       = "#1E1E1B"
MENU_TEXT_SUB        = "#8A8A8A"
MENU_ACCENT_GREEN    = "#7ECBA1"
MENU_BTN_START_BG    = "#1E1E1B"
MENU_BTN_START_FG    = "#FFFFFF"

SIDEBAR_W = 215

# Emoji font for labels that contain emoji (Windows: Segoe UI Emoji)
EMOJI_FONT_CSS = "font-family: \'Segoe UI Emoji\', \'Apple Color Emoji\', sans-serif;"

# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------
PIANO_VARIANTS = [
    # Basic pianos & EPs
    "Piano", "Piano 2", "Honky-Tonk", "EP1", "Soft EP", "EP2", "Synth Piano",
    # Organs
    "Drawbar", "Lite Organ", "Rotary Organ",
    # Accordion / Harmonica
    "Accordion",
    # Mallet / Bell
    "Vibraphone", "Celesta", "Glass Hit", "Breath Bells", "Flute Bell",
    # Plucked / Guitar
    "Guitar Chimes", "Acoustic Guitar 1",
    # Bass
    "Acoustic Bass", "Synth Bass", "Fretless 1",
    # Plucked World
    "Oud", "Santur", "Koto LA",
    # Pads & Atmospheres
    "Warm Pad", "Crystal", "Atmosphere", "Metallic Pad", "Ocean Pad",
    "Digital Pad", "Synth Glass", "Silver Pad", "Goblin",
    # Synths & Leads
    "Square", "Polysynth", "Blow Wave",
    # Voices
    "Oohs", "Space Voices", "Warm Voices",
    # Ambient / Cinematic
    "Rain", "Fantasy LA", "Eventide", "Petrichor", "Blue Planet",
    "Ambient Bell", "Bamboo Forest",
]

SOUND_CATEGORIES = {
    "Pianos e teclas": {"Piano", "Piano 2", "Honky-Tonk", "EP1", "Soft EP", "EP2", "Synth Piano"},
    "Órgãos e acordeão": {"Drawbar", "Lite Organ", "Rotary Organ", "Accordion"},
    "Sinos e percussão": {"Vibraphone", "Celesta", "Glass Hit", "Breath Bells", "Flute Bell"},
    "Cordas e mundo": {"Guitar Chimes", "Acoustic Guitar 1", "Oud", "Santur", "Koto LA"},
    "Baixos": {"Acoustic Bass", "Synth Bass", "Fretless 1"},
    "Pads e ambientes": {"Warm Pad", "Crystal", "Atmosphere", "Metallic Pad", "Ocean Pad", "Digital Pad", "Synth Glass", "Silver Pad", "Goblin", "Fantasy LA", "Eventide", "Petrichor", "Blue Planet", "Ambient Bell", "Bamboo Forest"},
    "Synths e vozes": {"Square", "Polysynth", "Blow Wave", "Oohs", "Space Voices", "Warm Voices"},
}

MENU_PREFS_PATH = Path(getattr(settings, "RECORDINGS_ROOT", PROJECT_ROOT)) / ".menu_preferences.json"


def _load_menu_preferences() -> dict:
    try:
        data = json.loads(MENU_PREFS_PATH.read_text(encoding="utf-8"))
        return {"recent": list(data.get("recent", []))}
    except Exception:
        return {"recent": []}


def _save_menu_preferences(data: dict) -> None:
    try:
        MENU_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        MENU_PREFS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ui_log(action: str, **details) -> None:
    """Temporary, intentionally plain stdout diagnostics for menu interactions."""
    suffix = " ".join(f"{key}={value!r}" for key, value in details.items())
    print(f"[menu-ui] {action}{(' ' + suffix) if suffix else ''}", flush=True)


def _sound_category(name: str) -> str:
    for category, names in SOUND_CATEGORIES.items():
        if name in names:
            return category
    return "Outros"
DRUMS_VARIANTS = ["Classic", "Power", "Vintage", "Bright"]

PIANO_TILES_SONGS = [
    "Twinkle Twinkle",
    "Ode to Joy",
    "Happy Birthday",
    "Mary Had a Little Lamb",
    "Jingle Bells (refrao)",
    "Random",
]

PRACTICE_INSTRUMENTS = [
    {
        "id": "piano",   "label": "Piano",   "icon": "🎹",
        "type": "keyboard",  "subtitle": "Toque notas com os dedos",
        "variants": PIANO_VARIANTS,
    },
    {
        "id": "bateria", "label": "Bateria", "icon": "🥁",
        "type": "drums",     "subtitle": "Percussão com as mãos",
        "variants": DRUMS_VARIANTS,
    },
    {
        "id": "maestro", "label": "Maestro", "icon": "🪄",
        "type": "maestro",   "subtitle": "Instrumento gestual expressivo",
        "variants": [],
    },
]

GAME_INSTRUMENTS = [
    {
        "id": "piano_tiles",  "label": "Piano Tiles",  "icon": "⬛",
        "type": "keyboard_game", "subtitle": "Toque as notas na hora certa",
        "default_instrument": "Piano", "songs": PIANO_TILES_SONGS,
    },
    {
        "id": "genius_drums", "label": "Genius Drums", "icon": "🧠",
        "type": "drums_game",    "subtitle": "Repita a sequencia da bateria",
        "default_instrument": "Classic", "songs": [],
    },
]

DIFFICULTIES = [
    ("easy",   "Fácil"),
    ("medium", "Médio"),
    ("hard",   "Difícil"),
]


# ---------------------------------------------------------------------------
# Reusable card widgets
# ---------------------------------------------------------------------------

class ClickableFrame(QFrame):
    """QFrame that emits clicked on mouse press."""
    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class InstrumentCard(ClickableFrame):
    def __init__(self, icon: str, label: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("instrCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._selected = False

        vl = QVBoxLayout(self)
        vl.setContentsMargins(14, 16, 14, 16)
        vl.setSpacing(5)
        vl.setAlignment(Qt.AlignCenter)

        # Icon label - applying emoji font and removing rogue borders
        self._ico = QLabel(icon)
        self._ico.setAlignment(Qt.AlignCenter)
        self._ico.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 32px; border: none;")
        vl.addWidget(self._ico)

        self._lbl = QLabel(label)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet("background: transparent; border: none;")
        vl.addWidget(self._lbl)

        if subtitle:
            self._sub = QLabel(subtitle)
            self._sub.setAlignment(Qt.AlignCenter)
            self._sub.setWordWrap(True)
            self._sub.setStyleSheet("background: transparent; border: none;")
            vl.addWidget(self._sub)
        else:
            self._sub = None

        self._apply(False)

    def _apply(self, sel: bool) -> None:
        if sel:
            self.setStyleSheet(
                f"QFrame#instrCard {{ background-color: {MENU_CARD_DARK};"
                f" border: 1px solid {MENU_CARD_DARK}; border-radius: 10px; }}"
            )
            self._ico.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 32px; color: {MENU_CARD_DARK_TEXT}; border: none;")
            self._lbl.setStyleSheet(
                f"color: {MENU_CARD_DARK_TEXT}; background: transparent; border: none;"
                f" font-size: 18px; font-weight: bold; font-family: {FONT_FAMILY};"
            )
            if self._sub:
                self._sub.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent; border: none; font-size: 13px;")
        else:
            self.setStyleSheet(
                f"QFrame#instrCard {{ background-color: {MENU_CARD_BG};"
                f" border: 1px solid {MENU_CARD_BORDER}; border-radius: 10px; }}"
            )
            self._ico.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 32px; color: {MENU_TEXT_MAIN}; border: none;")
            self._lbl.setStyleSheet(
                f"color: {MENU_TEXT_MAIN}; background: transparent; border: none;"
                f" font-size: 18px; font-weight: bold; font-family: {FONT_FAMILY};"
            )
            if self._sub:
                self._sub.setStyleSheet(f"color: {MENU_TEXT_SUB}; background: transparent; border: none; font-size: 13px;")

    def set_selected(self, v: bool) -> None:
        self._selected = v
        self._apply(v)

    def is_selected(self) -> bool:
        return self._selected


class VariantItem(ClickableFrame):
    preview_requested = Signal(str)

    def __init__(self, text: str, enhanced: bool = False, borderless: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("variantItem")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(round(40 * 1.15))
        self._selected = False
        self._borderless = borderless

        hl = QHBoxLayout(self)
        hl.setContentsMargins(14, 0, 8, 0)
        hl.setSpacing(6)

        self._lbl = QLabel(text)
        hl.addWidget(self._lbl, 1)
        self._preview = QPushButton("Ouvir")
        self._preview.setToolTip("Ouvir prévia")
        self._preview.setFixedSize(58, 31)
        self._preview.setVisible(enhanced)
        self._preview.clicked.connect(lambda: self.preview_requested.emit(text))
        hl.addWidget(self._preview)
        self._apply(False)

    def _apply(self, sel: bool) -> None:
        border = "none" if self._borderless else (f"1px solid {MENU_CARD_DARK}" if sel else f"1px solid {MENU_CARD_BORDER}")
        if sel:
            self.setStyleSheet(
                f"QFrame#variantItem {{ background-color: {MENU_CARD_DARK};"
                f" border: {border}; border-radius: 8px; }}"
            )
            self._lbl.setStyleSheet(f"color: {MENU_CARD_DARK_TEXT}; background: transparent; border: none; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};")
        else:
            self.setStyleSheet(
                f"QFrame#variantItem {{ background-color: {MENU_CARD_BG};"
                f" border: {border}; border-radius: 8px; }}"
            )
            self._lbl.setStyleSheet(f"color: {MENU_TEXT_MAIN}; background: transparent; border: none; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};")

    def set_selected(self, v: bool) -> None:
        self._selected = v
        self._apply(v)

    def is_selected(self) -> bool:
        return self._selected

class ModeCard(ClickableFrame):
    """Home-page mode card."""
    def __init__(self, icon: str, title: str, subtitle: str, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self.setObjectName("modeCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if dark:
            self.setStyleSheet(f"QFrame#modeCard {{ background-color: {MENU_CARD_DARK}; border-radius: 14px; border: none; }}")
        else:
            self.setStyleSheet(f"QFrame#modeCard {{ background-color: {MENU_CARD_BG}; border-radius: 14px; border: 1px solid {MENU_CARD_BORDER}; }}")

        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 18, 20, 18)
        vl.setSpacing(4)

        header = QHBoxLayout()
        em = QLabel(icon)
        em.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 20px;")
        header.addWidget(em)
        header.addStretch()
        arrow = QLabel("->")
        fg_a = MENU_CARD_DARK_TEXT if dark else MENU_TEXT_SUB
        arrow.setStyleSheet(f"background: transparent; font-size: 12px; color: {fg_a};")
        header.addWidget(arrow)
        vl.addLayout(header)
        vl.addStretch()

        fg = MENU_CARD_DARK_TEXT if dark else MENU_TEXT_MAIN
        t = QLabel(title)
        t.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_LG}px; font-weight: bold; color: {fg}; font-family: {FONT_FAMILY};")
        vl.addWidget(t)

        sub_fg = "rgba(255,255,255,0.7)" if dark else MENU_TEXT_SUB
        s = QLabel(subtitle)
        s.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {sub_fg}; font-family: {FONT_FAMILY};")
        vl.addWidget(s)


class StatCard(QFrame):
    def __init__(self, icon: str, label: str, value: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 10px; }}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(12)

        ic = QLabel(icon)
        ic.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 20px;")
        hl.addWidget(ic)

        vl2 = QVBoxLayout()
        vl2.setSpacing(1)
        sub = QLabel(label)
        sub.setStyleSheet(f"background: transparent; font-size: 10px; color: {MENU_TEXT_SUB}; letter-spacing: 1px; font-family: {FONT_FAMILY};")
        vl2.addWidget(sub)
        val = QLabel(value)
        val.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_LG}px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        vl2.addWidget(val)
        hl.addLayout(vl2)
        hl.addStretch()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class SidebarButton(ClickableFrame):
    """Sidebar nav button as a ClickableFrame (icon + text, no QPushButton font conflict)."""
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._active = False

        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(8)

        self._ico = QLabel(icon)
        self._ico.setFixedWidth(24) # Increased slightly to fit emojis cleanly
        self._ico.setAlignment(Qt.AlignCenter)
        hl.addWidget(self._ico)

        self._txt = QLabel(label)
        hl.addWidget(self._txt, 1)

        self._apply(False)

    def set_active(self, v: bool) -> None:
        self._active = v
        self._apply(v)

    def is_active(self) -> bool:
        return self._active

    def _apply(self, v: bool) -> None:
        if v:
            self.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border-radius: 6px; border: none; }}")
            self._ico.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 16px; color: {MENU_TEXT_MAIN};")
            self._txt.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        else:
           self.setStyleSheet(f"QFrame {{ background-color: transparent; border-radius: 6px; border: none; }} QFrame:hover {{ background-color: {MENU_CARD_HOVER}; }}")
           self._ico.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 16px; color: {MENU_TEXT_MAIN};")
           self._txt.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")


class Sidebar(QWidget):
    nav_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        self.setStyleSheet(f"QWidget {{ background-color: {MENU_SIDEBAR_BG}; border-right: 1px solid {MENU_SEPARATOR}; }}")

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Logo row
        logo_w = QWidget()
        logo_w.setStyleSheet(f"background-color: {MENU_SIDEBAR_BG}; border: none;")
        ll = QHBoxLayout(logo_w)
        ll.setContentsMargins(16, 20, 16, 18)
        ll.setSpacing(8)
        logo_icon = QLabel("TH")
        logo_icon.setStyleSheet(
            f"background-color: {MENU_CARD_DARK}; color: {MENU_CARD_DARK_TEXT};"
            f" border-radius: 6px; font-size: 11px; font-weight: bold; padding: 2px 5px;"
        )
        ll.addWidget(logo_icon)
        logo_lbl = QLabel("Talking Hands")
        logo_lbl.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        ll.addWidget(logo_lbl)
        ll.addStretch()
        vl.addWidget(logo_w)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {MENU_SEPARATOR}; border: none;")
        vl.addWidget(sep)

        nav_w = QWidget()
        nav_w.setStyleSheet("background: transparent; border: none;")
        nav_vl = QVBoxLayout(nav_w)
        nav_vl.setContentsMargins(8, 10, 8, 10)
        nav_vl.setSpacing(2)

        self._buttons: dict[str, SidebarButton] = {}

        def _section(text: str):
            lbl2 = QLabel(text)
            lbl2.setContentsMargins(8, 10, 0, 4)
            lbl2.setStyleSheet(f"background: transparent; border: none; font-size: 10px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
            nav_vl.addWidget(lbl2)

        def _btn(page_id: str, icon: str, label: str):
            b = SidebarButton(icon, label)
            b.clicked.connect(lambda pid=page_id: self._on_nav(pid))
            nav_vl.addWidget(b)
            self._buttons[page_id] = b

        _section("MODOS")
        _btn("home",      "🏠", "Home")
        _btn("pratica",   "🎹", "Prática")
        _btn("jogo",      "🎮", "Jogo")
        _section("SISTEMA")
        _btn("gravacoes", "⏺️", "Gravações")

        nav_vl.addStretch()
        vl.addWidget(nav_w, 1)

        self._set_active_visual("home")

    def _on_nav(self, page_id: str) -> None:
        _ui_log("sidebar-navigation", page=page_id)
        self._set_active_visual(page_id)
        self.nav_changed.emit(page_id)

    def _set_active_visual(self, page_id: str) -> None:
        for pid, btn in self._buttons.items():
            btn.set_active(pid == page_id)

    def set_active(self, page_id: str) -> None:
        """Called by MainMenuWindow - visuals only, no signal."""
        self._set_active_visual(page_id)


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

class HomePage(QWidget):
    mode_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {MENU_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(0)

        greet = QLabel("Bem-vindo de volta")
        greet.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
        outer.addWidget(greet)
        outer.addSpacing(6)

        title = QLabel("O que você quer\nexplorar hoje?")
        title.setStyleSheet(f"background: transparent; font-size: 36px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        outer.addWidget(title)
        outer.addSpacing(6)

        sub = QLabel("Transforme gestos no ar em música real.")
        sub.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
        outer.addWidget(sub)
        outer.addSpacing(28)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        def _card(icon, title_, subtitle, page_id, dark=False):
            c = ModeCard(icon, title_, subtitle, dark)
            c.setFixedHeight(180)
            c.clicked.connect(lambda pid=page_id: self.mode_selected.emit(pid))
            cards_row.addWidget(c)

        _card("🎹", "Prática",    "Toque livremente",     "pratica",   dark=True)
        _card("🎮", "Jogo",       "Desafios rítmicos",    "jogo")
        _card("⏺️", "Gravações",  "Ouça suas sessões",    "gravacoes")
        outer.addLayout(cards_row)
        outer.addSpacing(24)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        stats_row.addWidget(StatCard("⏱️", "TEMPO HOJE",      "--"))
        stats_row.addWidget(StatCard("🎯", "PRECISÃO MÉDIA",  "--"))
        stats_row.addWidget(StatCard("🔥", "SEQUENCIA",       "--"))
        outer.addLayout(stats_row)
        outer.addStretch()


# ---------------------------------------------------------------------------
# Shared: instrument selector + variant list
# ---------------------------------------------------------------------------

class InstrumentSelectorPanel(QWidget):
    instrument_changed = Signal(str)
    instrument_double_clicked = Signal(str)

    def __init__(self, instruments: list, stacked: bool = False, allow_double_click: bool = True, section_title: str = "INSTRUMENTO", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._cards: dict[str, InstrumentCard] = {}
        self._card_positions: dict[str, tuple[int, int, int, int]] = {}
        self._instruments = instruments
        self._selected_id = ""
        self._allow_double_click = allow_double_click
        self._grid = None
        self._expand_animation = None

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(10)

        lbl = QLabel(section_title)
        lbl.setStyleSheet(f"background: transparent; border: none; font-size: {SECTION_FONT_SIZE}px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
        vl.addWidget(lbl)

        grid = QGridLayout()
        self._grid = grid
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        if stacked:
            # Each instrument stacks vertically as a full-width card
            for i, instr in enumerate(instruments):
                c = InstrumentCard(instr["icon"], instr["label"], instr.get("subtitle", ""))
                c.clicked.connect(lambda iid=instr["id"]: self._on_select(iid))
                if self._allow_double_click:
                    c.double_clicked.connect(lambda iid=instr["id"]: self._on_double_select(iid))
                grid.addWidget(c, i, 0, 1, 2)
                self._card_positions[instr["id"]] = (i, 0, 1, 2)
                grid.setRowStretch(i, 1)
                self._cards[instr["id"]] = c
        else:
            num_rows = 0
            for i, instr in enumerate(instruments):
                c = InstrumentCard(instr["icon"], instr["label"], instr.get("subtitle", ""))
                c.clicked.connect(lambda iid=instr["id"]: self._on_select(iid))
                if self._allow_double_click:
                    c.double_clicked.connect(lambda iid=instr["id"]: self._on_double_select(iid))
                if i < 2:
                    # First two items: row 0, columns 0 and 1
                    grid.addWidget(c, 0, i)
                    self._card_positions[instr["id"]] = (0, i, 1, 1)
                    num_rows = max(num_rows, 1)
                else:
                    # Remaining items: row 1+, span 2 columns
                    row = 1 + (i - 2)
                    grid.addWidget(c, row, 0, 1, 2)
                    self._card_positions[instr["id"]] = (row, 0, 1, 2)
                    num_rows = max(num_rows, row + 1)
                self._cards[instr["id"]] = c
            for r in range(num_rows):
                grid.setRowStretch(r, 1)
        vl.addLayout(grid, 1)

        if instruments:
            self._on_select(instruments[0]["id"], emit=False)

    def _on_select(self, id_: str, emit: bool = True) -> None:
        _ui_log("instrument-card-selected", instrument=id_, emit=emit)
        self._selected_id = id_
        for cid, card in self._cards.items():
            card.set_selected(cid == id_)
        if emit:
            self.instrument_changed.emit(id_)

    def get_selected_id(self) -> str:
        return self._selected_id

    def _on_double_select(self, id_: str) -> None:
        _ui_log("instrument-card-double-clicked", instrument=id_)
        self._on_select(id_)
        self._animate_selected(id_)

    def _animate_selected(self, id_: str) -> None:
        card = self._cards.get(id_)
        if card is None or self._grid is None:
            self.instrument_double_clicked.emit(id_)
            return
        start = QRect(card.mapTo(self, QPoint(0, 0)), card.size())
        self._grid.removeWidget(card)
        for cid, other in self._cards.items():
            if cid != id_:
                other.setVisible(False)
        card.setParent(self)
        card.raise_()
        end = self.rect().adjusted(10, 28, -10, -10)
        self._expand_animation = QPropertyAnimation(card, b"geometry", self)
        self._expand_animation.setDuration(360)
        self._expand_animation.setStartValue(start)
        self._expand_animation.setEndValue(end)
        self._expand_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._expand_animation.finished.connect(lambda: self.instrument_double_clicked.emit(id_))
        self._expand_animation.start()

    def reset_layout(self) -> None:
        if self._expand_animation is not None:
            self._expand_animation.stop()
            self._expand_animation = None
        for cid, card in self._cards.items():
            card.setVisible(True)
            if self._grid.indexOf(card) == -1:
                row, column, rowspan, colspan = self._card_positions[cid]
                self._grid.addWidget(card, row, column, rowspan, colspan)
        self._grid.invalidate()
        self._grid.activate()

    def set_selected(self, id_: str) -> None:
        self._on_select(id_)


class VariantSelectorPanel(QWidget):
    variant_changed = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, enhanced: bool = False, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setFixedWidth(250)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        self._section_lbl = QLabel("SOM")
        self._section_lbl.setStyleSheet(f"background: transparent; border: none; font-size: {SECTION_FONT_SIZE}px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
        vl.addWidget(self._section_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: #C8C5C0; border-radius: 3px; }"
        )
        self._list_w = QWidget()
        self._list_w.setStyleSheet("background: transparent;")
        self._list_vl = QVBoxLayout(self._list_w)
        self._list_vl.setContentsMargins(0, 0, 4, 0)
        self._list_vl.setSpacing(4)
        self._list_vl.addStretch()
        scroll.setWidget(self._list_w)
        vl.addWidget(scroll, 1)

        self._items: dict[str, VariantItem] = {}
        self._selected: str = ""
        self._variants: list[str] = []
        self._enhanced = enhanced
        self._prefs = _load_menu_preferences()
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(140)
        self._filter_timer.timeout.connect(self._refresh_filtered)

        if enhanced:
            self._search = QLineEdit()
            self._search.setPlaceholderText("Pesquisar sons...")
            self._search.setClearButtonEnabled(True)
            self._search.textChanged.connect(self._schedule_filter_refresh)
            vl.insertWidget(1, self._search)

            self._category = QComboBox()
            self._category.addItem("Todas as categorias")
            self._category.addItems(list(SOUND_CATEGORIES) + ["Outros"])
            self._category.currentTextChanged.connect(self._refresh_filtered)
            vl.insertWidget(2, self._category)

    def load_variants(self, variants: list, section_label: str = "SOM") -> None:
        _ui_log("sound-list-load-start", section=section_label, count=len(variants), enhanced=self._enhanced)
        # Replacing a long sound list must be one visual transaction; otherwise
        # Qt repaints every removed item and the page appears to flicker.
        self._list_w.setUpdatesEnabled(False)
        self._section_lbl.setText(section_label)
        while self._list_vl.count() > 1:
            item = self._list_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._items.clear()

        self._variants = list(variants)
        if self._enhanced:
            self._refresh_filtered()
        else:
            for v in variants:
                item = VariantItem(v)
                item.clicked.connect(lambda _v=v: self._on_select(_v))
                self._list_vl.insertWidget(self._list_vl.count() - 1, item)
                self._items[v] = item

        if variants:
            self._on_select(variants[0], emit=False)
        self._list_w.setUpdatesEnabled(True)
        self._list_w.update()
        _ui_log("sound-list-load-end", section=section_label, visible_count=len(self._items), selected=self._selected)

    def _schedule_filter_refresh(self, text: str) -> None:
        _ui_log("sound-search-input", query=text)
        self._filter_timer.start()

    def _refresh_filtered(self, *_args) -> None:
        if not self._enhanced:
            return
        self._list_w.setUpdatesEnabled(False)
        while self._list_vl.count() > 1:
            item = self._list_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._items.clear()
        query = self._search.text().strip().casefold()
        category = self._category.currentText()
        recent = self._prefs.get("recent", [])
        ordered = [v for v in recent if v in self._variants] + [v for v in self._variants if v not in recent]
        for v in ordered:
            if query and query not in v.casefold():
                continue
            if category != "Todas as categorias" and _sound_category(v) != category:
                continue
            item = VariantItem(v, enhanced=True)
            item.clicked.connect(lambda _v=v: self._on_select(_v))
            item.preview_requested.connect(self.preview_requested.emit)
            self._list_vl.insertWidget(self._list_vl.count() - 1, item)
            self._items[v] = item
        self._refresh_selection_visuals()
        self._list_w.setUpdatesEnabled(True)
        self._list_w.update()
        _ui_log("sound-list-filtered", query=query, category=category, visible_count=len(self._items))

    def _refresh_selection_visuals(self) -> None:
        for vk, vi in self._items.items():
            vi.set_selected(vk == self._selected)

    def _remember_recent(self, value: str) -> None:
        recent = [value] + [v for v in self._prefs.get("recent", []) if v != value]
        self._prefs["recent"] = recent[:8]
        _save_menu_preferences(self._prefs)

    def _on_select(self, v: str, emit: bool = True) -> None:
        _ui_log("sound-selected", sound=v, emit=emit)
        self._selected = v
        self._refresh_selection_visuals()
        if self._enhanced and v:
            self._remember_recent(v)
        if emit:
            self.variant_changed.emit(v)

    def get_selected(self) -> str:
        return self._selected


class SoundPreview:
    """Small FluidSynth preview shared by the menu's sound browser."""
    def __init__(self):
        self._fs = None
        self._sfids = {}
        self._active_note = None

    def play(self, name: str) -> None:
        _ui_log("sound-preview-start", sound=name)
        try:
            from src.instruments.common import init_fluidsynth, load_single_soundfont
            if self._fs is None:
                self._fs, _ = init_fluidsynth()
                if not self._fs:
                    return
                for key, path in settings.SF2_PATHS.items():
                    sfid = load_single_soundfont(self._fs, key, path)
                    if sfid != -1:
                        self._sfids[key] = sfid
            if name not in settings.INSTRUMENTS:
                return
            sf_key, bank, preset = settings.INSTRUMENTS[name]
            sfid = self._sfids.get(sf_key)
            if sfid is None:
                return
            if self._active_note is not None:
                self._fs.noteoff(0, self._active_note)
            try:
                self._fs.setting("synth.gain", 1.0)
                self._fs.cc(0, 7, 127)
            except Exception:
                pass
            self._fs.program_select(0, sfid, bank, preset)
            note = 36 if sf_key == "drums" else 60
            self._fs.noteon(0, note, 105)
            self._active_note = note
            QTimer.singleShot(700, self._stop)
            _ui_log("sound-preview-playing", sound=name, soundfont=sf_key, bank=bank, preset=preset, note=note)
        except Exception as exc:
            _ui_log("sound-preview-error", sound=name, error=str(exc))
            self._stop()

    def _stop(self):
        if self._fs is not None and self._active_note is not None:
            try:
                self._fs.noteoff(0, self._active_note)
            except Exception:
                pass
        self._active_note = None


_SOUND_PREVIEW = SoundPreview()


# ---------------------------------------------------------------------------
# Prática page
# ---------------------------------------------------------------------------

class PraticaPage(QWidget):
    launch_requested = Signal(dict)
    nav_requested    = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {MENU_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        instr_frame = QFrame()
        instr_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        instr_vl = QVBoxLayout(instr_frame)
        instr_vl.setContentsMargins(20, 16, 20, 20)
        instr_vl.setSpacing(12)
        self._instr_sel = InstrumentSelectorPanel(PRACTICE_INSTRUMENTS, section_title="MODO PRÁTICA")
        self._instr_sel.instrument_changed.connect(self._on_instrument_changed)
        self._instr_sel.instrument_double_clicked.connect(self._on_double_click_start)
        instr_vl.addWidget(self._instr_sel)
        main_row.addWidget(instr_frame, 1)
        outer.addLayout(main_row, 1)

        # Practice launches from a double-click on an instrument card.
        self._action_stack = QStackedWidget()
        self._action_stack.setFixedHeight(56) # Prevents layout jumping

        prog_page = QWidget()
        prog_layout = QVBoxLayout(prog_page)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setAlignment(Qt.AlignBottom)
        self._loading_label = QLabel("Preparando...")
        self._loading_label.setStyleSheet(f"background: transparent; color: {MENU_TEXT_SUB}; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};")
        prog_layout.addWidget(self._loading_label)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(24)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background-color: {MENU_CARD_BORDER}; border-radius: 12px; border: none; }}"
            f"QProgressBar::chunk {{ background-color: {MENU_CARD_DARK}; border-radius: 12px; }}"
        )
        prog_layout.addWidget(self._progress)
        self._action_stack.addWidget(prog_page)
        self._action_stack.setVisible(False)

        outer.addWidget(self._action_stack)

        self._on_instrument_changed(PRACTICE_INSTRUMENTS[0]["id"])

    def set_loading_state(self, is_loading: bool):
        if not is_loading:
            self._instr_sel.reset_layout()
        self._action_stack.setVisible(is_loading)
        if is_loading:
            self._progress.setValue(0)
            self._loading_label.setText("Preparando...")

    def set_loading_stage(self, text: str) -> None:
        self._loading_label.setText(text)

    def update_progress(self, val: int):
        self._progress.setValue(val)

    def _get_info(self, id_: str) -> dict:
        return next((i for i in PRACTICE_INSTRUMENTS if i["id"] == id_), {})

    def _on_instrument_changed(self, id_: str) -> None:
        _ui_log("practice-instrument-selected", instrument=id_)

    def _on_double_click_start(self, id_: str) -> None:
        sel_id = id_ or self._instr_sel.get_selected_id()
        info   = self._get_info(sel_id)
        default_instruments = {"piano": "Piano", "bateria": "Classic", "maestro": "Maestro"}
        config = {
            "type": info.get("type", "keyboard"),
            "instrument": default_instruments.get(sel_id, sel_id),
        }
        _ui_log("practice-double-click-launch", config=config)
        self.launch_requested.emit(config)


# ---------------------------------------------------------------------------
# Jogo page
# ---------------------------------------------------------------------------

class JogoPage(QWidget):
    launch_requested = Signal(dict)
    nav_requested    = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {MENU_BG};")
        self._current_diff  = "easy"
        self._selected_song = PIANO_TILES_SONGS[0]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        instr_frame = QFrame()
        instr_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        instr_vl = QVBoxLayout(instr_frame)
        instr_vl.setContentsMargins(20, 16, 20, 20)
        instr_vl.setSpacing(12)
        self._instr_sel = InstrumentSelectorPanel(GAME_INSTRUMENTS, stacked=False, allow_double_click=False, section_title="MODO JOGO")
        self._instr_sel.instrument_changed.connect(self._on_game_changed)
        instr_vl.addWidget(self._instr_sel)
        outer.addWidget(instr_frame, 7)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(14)

        diff_frame = QFrame()
        self._diff_frame = diff_frame
        diff_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        diff_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        diff_vl = QVBoxLayout(diff_frame)
        diff_vl.setContentsMargins(14, 12, 14, 12)
        diff_vl.setSpacing(6)
        diff_vl.setAlignment(Qt.AlignTop)
        self._diff_btns: dict[str, QPushButton] = {}
        for key, label_ in DIFFICULTIES:
            btn = QPushButton(label_)
            btn.setObjectName(f"diffBtn_{key}")
            btn.setCheckable(True)
            btn.setChecked(False)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            btn.clicked.connect(lambda _c=False, k=key: self._on_diff(k))
            diff_vl.addWidget(btn, 1)
            self._diff_btns[key] = btn
        controls_row.addWidget(diff_frame, 1)

        # Song selector
        self._song_frame = QFrame()
        self._song_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._song_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        song_vl = QVBoxLayout(self._song_frame)
        song_vl.setContentsMargins(20, 14, 20, 14)
        song_vl.setSpacing(8)
        songs_grid = QGridLayout()
        songs_grid.setHorizontalSpacing(8)
        songs_grid.setVerticalSpacing(8)
        songs_grid.setColumnStretch(0, 1)
        songs_grid.setColumnStretch(1, 1)
        for row in range(3):
            songs_grid.setRowStretch(row, 1)
        self._song_items: dict[str, VariantItem] = {}
        for index, song in enumerate(PIANO_TILES_SONGS):
            si = VariantItem(song, borderless=True)
            si.setMinimumHeight(0)
            si.setMaximumHeight(16777215)
            si.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            si.clicked.connect(lambda _s=song: self._on_song(_s))
            songs_grid.addWidget(si, index // 2, index % 2)
            self._song_items[song] = si
        song_vl.addLayout(songs_grid, 1)
        _sp3 = self._song_frame.sizePolicy()
        _sp3.setHorizontalPolicy(QSizePolicy.Expanding)
        _sp3.setVerticalPolicy(QSizePolicy.Expanding)
        _sp3.setRetainSizeWhenHidden(False)
        self._song_frame.setSizePolicy(_sp3)
        controls_row.addWidget(self._song_frame, 1)

        self._start_btn = QPushButton(">  Iniciar Jogo")
        self._start_btn.setObjectName("menuGameStartBtn")
        self._start_btn.setMinimumSize(0, 0)
        self._start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._start_btn.clicked.connect(self._on_start)
        controls_row.addWidget(self._start_btn, 1)
        outer.addLayout(controls_row, 3)

        # Loading feedback remains at the bottom while the start action lives in the header.
        self._action_stack = QStackedWidget()
        self._action_stack.setFixedHeight(56)

        prog_page = QWidget()
        prog_layout = QVBoxLayout(prog_page)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setAlignment(Qt.AlignBottom)
        self._loading_label = QLabel("Preparando...")
        self._loading_label.setStyleSheet(f"background: transparent; color: {MENU_TEXT_SUB}; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};")
        prog_layout.addWidget(self._loading_label)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(24)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background-color: {MENU_CARD_BORDER}; border-radius: 12px; border: none; }}"
            f"QProgressBar::chunk {{ background-color: {MENU_CARD_DARK}; border-radius: 12px; }}"
        )
        prog_layout.addWidget(self._progress)
        self._action_stack.addWidget(prog_page)
        self._action_stack.setVisible(False)

        outer.addWidget(self._action_stack)

        self._reset_game_flow()
        self._apply_diff_styles()

    # Update this method:
    def set_loading_state(self, is_loading: bool):
        self._action_stack.setVisible(is_loading)
        self._start_btn.setVisible(not is_loading)
        if is_loading:
            self._progress.setValue(0)
            self._loading_label.setText("Preparando...")
    def update_progress(self, val: int):
        self._progress.setValue(val)

    def set_loading_stage(self, text: str) -> None:
        self._loading_label.setText(text)

    def _get_info(self, id_: str) -> dict:
        return next((i for i in GAME_INSTRUMENTS if i["id"] == id_), {})

    def _on_game_changed(self, id_: str) -> None:
        _ui_log("game-instrument-selected", instrument=id_)
        self._current_game_id = id_
        info = self._get_info(id_)
        self._song_frame.setVisible(bool(info.get("songs")))
        self._start_btn.setVisible(True)

    def _reset_game_flow(self) -> None:
        self._current_game_id = GAME_INSTRUMENTS[0]["id"]
        self._current_diff = "easy"
        for btn in self._diff_btns.values():
            btn.setChecked(btn.objectName() == "diffBtn_easy")
        self._song_frame.setVisible(True)
        self._start_btn.setVisible(True)

    def _on_diff(self, key: str) -> None:
        _ui_log("difficulty-selected", difficulty=key)
        self._current_diff = key
        for k, btn in self._diff_btns.items():
            btn.setChecked(k == key)
        self._apply_diff_styles()
        info = self._get_info(self._current_game_id)
        self._song_frame.setVisible(bool(info.get("songs")))
        self._start_btn.setVisible(True)

    def _apply_diff_styles(self) -> None:
        colors = {"easy": "#4E7C5E", "medium": "#7A6830", "hard": "#8A3A50"}
        for key, btn in self._diff_btns.items():
            if btn.isChecked():
                c = colors.get(key, "#555")
                btn.setStyleSheet(
                    f"QPushButton#diffBtn_{key} {{"
                    f" background-color: {c}; color: white;"
                    f" border: 1px solid {c}; border-radius: 8px;"
                    f" font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};"
                    f" text-align: left; padding: 0 14px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton#diffBtn_{key} {{"
                    f" background-color: {MENU_CARD_BG}; color: {MENU_TEXT_MAIN};"
                    f" border: 1px solid {MENU_CARD_BORDER}; border-radius: 8px;"
                    f" font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};"
                    f" text-align: left; padding: 0 14px; }}"
                    f" QPushButton#diffBtn_{key}:hover {{ border-color: #B0ADA8; }}"
                )

    def _on_song(self, song: str) -> None:
        _ui_log("song-selected", song=song)
        self._selected_song = song
        for s, si in self._song_items.items():
            si.set_selected(s == song)
        self._start_btn.setVisible(True)

    def _on_start(self) -> None:
        sel_id  = self._instr_sel.get_selected_id()
        info    = self._get_info(sel_id)
        config = {
            "type":       info.get("type", "drums_game"),
            "instrument": info.get("default_instrument", "Piano"),
            "difficulty": self._current_diff,
            "song":       self._selected_song,
        }
        _ui_log("game-start-clicked", config=config)
        self.launch_requested.emit(config)


# ---------------------------------------------------------------------------
# Estatísticas page
# ---------------------------------------------------------------------------

class StatisticsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {MENU_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        section = QLabel("ESTATÍSTICAS")
        section.setAlignment(Qt.AlignHCenter)
        section.setStyleSheet(
            f"background: transparent; border: none; font-size: {SECTION_FONT_SIZE}px; "
            f"font-weight: bold; letter-spacing: 1px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};"
        )
        outer.addWidget(section)

        subtitle = QLabel("Acompanhe sua evolução musical")
        subtitle.setAlignment(Qt.AlignHCenter)
        subtitle.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
        outer.addWidget(subtitle)
        outer.addSpacing(12)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(14)
        stats_row.addWidget(StatCard("⏱️", "TEMPO HOJE", "--"))
        stats_row.addWidget(StatCard("🎯", "PRECISÃO MÉDIA", "--"))
        stats_row.addWidget(StatCard("🔥", "SEQUÊNCIA", "--"))
        outer.addLayout(stats_row)
        outer.addStretch()


# ---------------------------------------------------------------------------
# Gravações page
# ---------------------------------------------------------------------------

class RecordingsPage(QWidget):
    nav_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {MENU_BG};")

        vl = QVBoxLayout(self)
        vl.setContentsMargins(28, 24, 28, 24)
        vl.setSpacing(16)

        section = QLabel("GRAVAÇÕES")
        section.setAlignment(Qt.AlignHCenter)
        section.setStyleSheet(
            f"background: transparent; border: none; font-size: {SECTION_FONT_SIZE}px; "
            f"font-weight: bold; letter-spacing: 1px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};"
        )
        vl.addWidget(section)

        sub = QLabel("Suas sessões salvas em MIDI e áudio")
        sub.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
        vl.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: #C8C5C0; border-radius: 3px; }"
        )
        self._list_w = QWidget()
        self._list_w.setStyleSheet("background: transparent;")
        self._list_vl = QVBoxLayout(self._list_w)
        self._list_vl.setContentsMargins(0, 0, 0, 0)
        self._list_vl.setSpacing(6)
        self._list_vl.addStretch()
        scroll.setWidget(self._list_w)
        vl.addWidget(scroll, 1)

        actions = QHBoxLayout()
        open_btn = QPushButton("Abrir pasta")
        open_btn.clicked.connect(self._open_recordings_folder)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self._refresh)
        actions.addWidget(open_btn)
        actions.addStretch()
        actions.addWidget(refresh_btn)
        vl.addLayout(actions)

        self._refresh()

    def _refresh(self) -> None:
        while self._list_vl.count() > 1:
            item = self._list_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        mids_dir = Path(settings.MIDS_DIR)
        wav_dir = Path(settings.WAV_DIR)
        files = sorted(mids_dir.glob("*.mid"), key=lambda f: f.stat().st_mtime, reverse=True) if mids_dir.exists() else []

        if not files:
            none_lbl = QLabel("Nenhuma gravação encontrada. Comece uma sessão para vê-la aqui.")
            none_lbl.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
            self._list_vl.insertWidget(0, none_lbl)
            return

        for f in files:
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 8px; }}")
            row.setFixedHeight(54)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(16, 0, 16, 0)
            hl.setSpacing(12)

            ic = QLabel("🎵")
            ic.setStyleSheet(f"background: transparent; {EMOJI_FONT_CSS} font-size: 16px;")
            hl.addWidget(ic)

            col = QVBoxLayout()
            col.setSpacing(2)
            name_lbl = QLabel(f.stem)
            name_lbl.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
            col.addWidget(name_lbl)
            ts = time.strftime("%d/%m/%Y  %H:%M", time.localtime(f.stat().st_mtime))
            date_lbl = QLabel(ts)
            date_lbl.setStyleSheet(f"background: transparent; font-size: 11px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
            col.addWidget(date_lbl)
            hl.addLayout(col)
            hl.addStretch()

            sz_lbl = QLabel(f"{max(1, f.stat().st_size // 1024)} KB")
            sz_lbl.setStyleSheet(f"background: transparent; font-size: 11px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
            hl.addWidget(sz_lbl)
            wav_path = wav_dir / f"{f.stem}.wav"
            play_btn = QPushButton("▶ Ouvir")
            play_btn.setFixedHeight(30)
            play_btn.setEnabled(wav_path.exists())
            play_btn.setToolTip("Reproduzir o áudio salvo" if wav_path.exists() else "O áudio ainda não foi gerado")
            play_btn.clicked.connect(lambda _checked=False, p=wav_path, b=play_btn: self._toggle_audio(p, b))
            hl.addWidget(play_btn)
            folder_btn = QPushButton("Pasta")
            folder_btn.setFixedHeight(30)
            folder_btn.clicked.connect(self._open_recordings_folder)
            hl.addWidget(folder_btn)
            delete_btn = QPushButton("Excluir")
            delete_btn.setFixedHeight(30)
            delete_btn.clicked.connect(lambda _checked=False, m=f, w=wav_path: self._delete_recording(m, w))
            hl.addWidget(delete_btn)
            self._list_vl.insertWidget(self._list_vl.count() - 1, row)

    def _toggle_audio(self, path: Path, button: QPushButton) -> None:
        _ui_log("recording-audio-toggle", path=str(path))
        try:
            import pygame
            if not path.exists():
                return
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                button.setText("▶ Ouvir")
                return
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            button.setText("⏹ Parar")
            QTimer.singleShot(max(1000, int(path.stat().st_size / 12)), lambda: button.setText("▶ Ouvir") if not pygame.mixer.music.get_busy() else None)
        except Exception as exc:
            QMessageBox.warning(self, "Não foi possível reproduzir", str(exc))

    def _open_recordings_folder(self) -> None:
        _ui_log("recordings-open-folder", path=str(settings.RECORDINGS_ROOT))
        folder = Path(settings.RECORDINGS_ROOT)
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception:
            if os.name == "nt":
                subprocess.Popen(["explorer", str(folder)])

    def _delete_recording(self, midi_path: Path, wav_path: Path) -> None:
        _ui_log("recording-delete-request", midi=str(midi_path), wav=str(wav_path))
        answer = QMessageBox.question(self, "Excluir gravação", f"Excluir '{midi_path.stem}'?", QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        for path in (midi_path, wav_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "Não foi possível excluir", str(exc))
        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()


# ---------------------------------------------------------------------------
# Shared button QSS
# ---------------------------------------------------------------------------

_SHARED_BTN_QSS = f"""
QPushButton#menuBackBtn {{
    background-color: transparent;
    color: {MENU_TEXT_SUB};
    border: 1px solid {MENU_SEPARATOR};
    border-radius: {BORDER_RAD}px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
    padding: 6px 14px;
}}
QPushButton#menuBackBtn:hover {{
    background-color: {MENU_CARD_BG};
    color: {MENU_TEXT_MAIN};
}}
QPushButton#menuStartBtn {{
    background-color: {MENU_ACCENT_GREEN};
    color: {MENU_TEXT_MAIN};
    border: 1px solid #67B58A;
    border-radius: {BORDER_RAD}px;
    font-size: {FONT_SIZE_LG}px;
    font-weight: bold;
    padding: 0 28px;
    font-family: {FONT_FAMILY};
}}
QPushButton#menuStartBtn:hover {{
    background-color: #96DDB4;
    border-color: #4E9D71;
}}
QPushButton#menuGameStartBtn {{
    background-color: {MENU_CARD_BG};
    color: {MENU_TEXT_MAIN};
    border: 1px solid {MENU_SEPARATOR};
    border-radius: {BORDER_RAD}px;
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    padding: 0 20px;
    font-family: {FONT_FAMILY};
}}
QPushButton#menuGameStartBtn:hover {{
    background-color: {MENU_CARD_HOVER};
    border-color: #B0ADA8;
}}
QPushButton#menuNavArrow {{
    background-color: transparent;
    color: {MENU_TEXT_MAIN};
    border: none;
    border-radius: 18px;
    font-size: 38px;
    font-family: sans-serif;
}}
QPushButton#menuNavArrow:hover {{
    background-color: {MENU_CARD_HOVER};
}}
QPushButton#menuWindowControl, QPushButton#menuCloseControl {{
    background-color: transparent;
    color: {MENU_TEXT_SUB};
    border: none;
    border-radius: 6px;
    font-size: 17px;
    font-family: sans-serif;
}}
QPushButton#menuWindowControl:hover {{
    background-color: {MENU_CARD_HOVER};
    color: {MENU_TEXT_MAIN};
}}
QPushButton#menuCloseControl:hover {{
    background-color: #C94C4C;
    color: white;
}}
QLabel#menuReadyLabel {{
    background: transparent;
    color: {MENU_TEXT_SUB};
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
"""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class WindowTitleBar(QFrame):
    """Small draggable area used by the frameless menu window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class MainMenuWindow(QMainWindow):
    launch_triggered = Signal(dict)
    closed_by_user = Signal()
    
    def __init__(
        self,
        resolution_profile=None,
        show_trackers: bool = False,
        hand_model_complexity: int = 1,
    ):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle("Talking Hands")
        self.setStyleSheet(_SHARED_BTN_QSS)

        central = QWidget()
        central.setStyleSheet(f"background-color: {MENU_BG};")
        self.setCentralWidget(central)

        window_layout = QVBoxLayout(central)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)

        self._window_bar = WindowTitleBar()
        self._window_bar.setFixedHeight(36)
        self._window_bar.setStyleSheet(f"background-color: {MENU_BG}; border: none;")
        bar_layout = QHBoxLayout(self._window_bar)
        bar_layout.setContentsMargins(12, 2, 8, 2)
        bar_layout.setSpacing(4)
        bar_layout.addStretch()

        minimize_btn = QPushButton("−")
        minimize_btn.setObjectName("menuWindowControl")
        minimize_btn.setFixedSize(32, 30)
        minimize_btn.setToolTip("Minimizar")
        minimize_btn.clicked.connect(self.showMinimized)
        bar_layout.addWidget(minimize_btn)

        close_btn = QPushButton("×")
        close_btn.setObjectName("menuCloseControl")
        close_btn.setFixedSize(32, 30)
        close_btn.setToolTip("Fechar")
        close_btn.clicked.connect(self.close)
        bar_layout.addWidget(close_btn)
        window_layout.addWidget(self._window_bar)

        root_widget = QWidget()
        root = QHBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        window_layout.addWidget(root_widget, 1)

        self._prev_btn = QPushButton("‹")
        self._prev_btn.setObjectName("menuNavArrow")
        self._prev_btn.setFixedWidth(56)
        self._prev_btn.setToolTip("Modo anterior")
        self._prev_btn.clicked.connect(lambda: self._cycle_page(-1))
        root.addWidget(self._prev_btn)

        content = QWidget()
        content.setStyleSheet(f"background-color: {MENU_BG};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 18, 0, 0)
        content_layout.setSpacing(0)

        app_title = QLabel("Talking Hands")
        app_title.setAlignment(Qt.AlignHCenter)
        app_title.setStyleSheet(
            f"background: transparent; border: none; font-size: 26px; font-weight: bold; "
            f"color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};"
        )
        content_layout.addWidget(app_title)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {MENU_BG};")
        content_layout.addWidget(self._stack, 1)
        root.addWidget(content, 1)

        self._next_btn = QPushButton("›")
        self._next_btn.setObjectName("menuNavArrow")
        self._next_btn.setFixedWidth(56)
        self._next_btn.setToolTip("Próximo modo")
        self._next_btn.clicked.connect(lambda: self._cycle_page(1))
        root.addWidget(self._next_btn)

        self._pratica   = PraticaPage()
        self._jogo      = JogoPage()
        self._estatisticas = StatisticsPage()
        self._gravacoes = RecordingsPage()

        self._stack.addWidget(self._pratica)       # 0
        self._stack.addWidget(self._jogo)          # 1
        self._stack.addWidget(self._estatisticas)  # 2
        self._stack.addWidget(self._gravacoes)     # 3

        self._page_index: dict[str, int] = {
            "pratica": 0, "jogo": 1, "estatisticas": 2, "gravacoes": 3,
        }
        self._carousel_anim = None

        self._pratica.launch_requested.connect(self.launch_triggered)
        self._jogo.launch_requested.connect(self.launch_triggered)
        self._stack.setCurrentIndex(self._page_index["pratica"])

    def closeEvent(self, event):
        """Intercepts the native window close to exit the local event loop safely."""
        self.closed_by_user.emit()
        super().closeEvent(event)

    def set_loading_state(self, is_loading: bool):
        _ui_log("loading-state", active=is_loading)
        # Guarantee EVERY page gets reset
        for i in range(self._stack.count()):
            page = self._stack.widget(i)
            if hasattr(page, "set_loading_state"):
                page.set_loading_state(is_loading)
                
        self._prev_btn.setDisabled(is_loading)
        self._next_btn.setDisabled(is_loading)
        # Keep the progress bar visible while making every page control inert.
        self._stack.setAttribute(Qt.WA_TransparentForMouseEvents, is_loading)

    def set_loading_stage(self, text: str) -> None:
        _ui_log("loading-stage", stage=text)
        for i in range(self._stack.count()):
            page = self._stack.widget(i)
            if hasattr(page, "set_loading_stage"):
                page.set_loading_stage(text)

    def update_progress(self, val: int):
        idx = self._stack.currentIndex()
        page = self._stack.widget(idx)
        if hasattr(page, "update_progress"):
            page.update_progress(val)

    @Slot(str)
    def _show_page(self, page_id: str) -> None:
        idx = self._page_index.get(page_id, 0)
        _ui_log("page-change", page=page_id, index=idx, previous_index=self._stack.currentIndex())
        self._stack.setCurrentIndex(idx)

    def _cycle_page(self, direction: int) -> None:
        count = self._stack.count()
        if count == 0 or self._carousel_anim is not None:
            return
        next_index = (self._stack.currentIndex() + direction) % count
        _ui_log("page-cycle", direction=direction, target_index=next_index)
        self._slide_to_page(next_index, direction)

    def _slide_to_page(self, target_index: int, direction: int) -> None:
        current_page = self._stack.currentWidget()
        target_page = self._stack.widget(target_index)
        width = self._stack.width()
        height = self._stack.height()
        if current_page is None or target_page is None or width <= 0 or height <= 0:
            self._stack.setCurrentIndex(target_index)
            return

        offset = width if direction > 0 else -width
        target_page.setGeometry(QRect(offset, 0, width, height))
        target_page.show()
        target_page.raise_()

        animation = QParallelAnimationGroup(self)
        outgoing = QPropertyAnimation(current_page, b"pos", animation)
        outgoing.setDuration(280)
        outgoing.setStartValue(QPoint(0, 0))
        outgoing.setEndValue(QPoint(-offset, 0))
        outgoing.setEasingCurve(QEasingCurve.OutCubic)

        incoming = QPropertyAnimation(target_page, b"pos", animation)
        incoming.setDuration(280)
        incoming.setStartValue(QPoint(offset, 0))
        incoming.setEndValue(QPoint(0, 0))
        incoming.setEasingCurve(QEasingCurve.OutCubic)
        animation.addAnimation(outgoing)
        animation.addAnimation(incoming)

        self._carousel_anim = animation
        self._prev_btn.setDisabled(True)
        self._next_btn.setDisabled(True)

        def _finish() -> None:
            self._stack.setCurrentIndex(target_index)
            current_page.hide()
            target_page.move(0, 0)
            self._carousel_anim = None
            self._prev_btn.setDisabled(False)
            self._next_btn.setDisabled(False)
            animation.deleteLater()

        animation.finished.connect(_finish)
        animation.start()


# ---------------------------------------------------------------------------
# Launch dispatcher
# ---------------------------------------------------------------------------

def _execute_launch(
    config: dict,
    resolution_profile,
    show_trackers: bool,
    hand_model_complexity: int,
) -> None:
    t          = config.get("type", "keyboard")
    instrument = config.get("instrument", "Piano")
    difficulty = config.get("difficulty", "easy")
    song       = config.get("song", "Twinkle Twinkle")

    try:
        if t == "keyboard":
            from src.instruments.keyboard_ui import start_piano_ui
            start_piano_ui(
                chosen_instrument=instrument,
                resolution_profile=resolution_profile,
                show_trackers=show_trackers,
                hand_model_complexity=hand_model_complexity,
            )
        elif t == "drums":
            from src.instruments.drums_ui import start_drums_ui
            start_drums_ui(
                chosen_instrument=instrument,
                resolution_profile=resolution_profile,
                show_trackers=show_trackers,
                hand_model_complexity=hand_model_complexity,
            )
        elif t == "maestro":
            from src.instruments.maestro_ui import start_maestro_ui
            start_maestro_ui(
                resolution_profile=resolution_profile,
                show_trackers=show_trackers,
                hand_model_complexity=hand_model_complexity,
            )
        elif t == "keyboard_game":
            from src.instruments.keyboard_game import start_piano_tiles_ui
            start_piano_tiles_ui(
                chosen_instrument=instrument,
                resolution_profile=resolution_profile,
                show_trackers=show_trackers,
                hand_model_complexity=hand_model_complexity,
                difficulty=difficulty,
                song=song,
            )
        elif t == "drums_game":
            from src.instruments.drums_game import start_drums_game
            start_drums_game(
                chosen_instrument=instrument,
                resolution_profile=resolution_profile,
                show_trackers=show_trackers,
                hand_model_complexity=hand_model_complexity,
                difficulty=difficulty,
            )
        else:
            print(f"[menu] Unknown type: {t!r}")
    except Exception as exc:
        import traceback
        print(f"[menu] Launch failed: {exc}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

class LoadingStream:
    """Intercepts stdout/stderr to forward lines to a callback for progress tracking."""
    def __init__(self, original_stream, callback):
        self.original_stream = original_stream
        self.callback = callback

    def write(self, text):
        self.original_stream.write(text)
        self.callback(text)

    def flush(self):
        self.original_stream.flush()


def start_menu(
    resolution_profile=None,
    show_trackers: bool = False,
    hand_model_complexity: int = 1,
) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()
    app.setQuitOnLastWindowClosed(False)

    # Create ONE window and reuse it across sessions — avoids the two-window flash.
    win = MainMenuWindow(resolution_profile, show_trackers, hand_model_complexity)

    while True:
        # 1. RESET WINDOW TO CLEAN STATE and show it
        win.set_loading_state(False)
        _state: dict = {"pending": None, "closed": False}
        menu_loop = QEventLoop()

        def on_launch(config: dict) -> None:
            _state["pending"] = config
            # Show loading bar immediately so the user gets feedback
            win.set_loading_state(True)
            app.processEvents()
            menu_loop.quit()

        def on_closed() -> None:
            _state["closed"] = True
            menu_loop.quit()

        win.launch_triggered.connect(on_launch)
        win.closed_by_user.connect(on_closed)

        # 2. SHOW AND WAIT
        win.showMaximized()
        menu_loop.exec()  # Blocks until user clicks start or closes window

        win.launch_triggered.disconnect(on_launch)
        win.closed_by_user.disconnect(on_closed)

        # 3. EXIT CONDITION
        if _state["closed"] or _state["pending"] is None:
            break

        # 4. INTERCEPT STDOUT/STDERR to drive the progress bar
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        current_progress = [0]

        def handle_log(text: str) -> None:
            text_lower = text.lower()
            prev = current_progress[0]

            # Translate internal startup logs into a small number of user-facing stages.
            stage = None
            if "modo pronto" in text_lower:
                current_progress[0] = 100
                stage = "Pronto!"
            elif "som:" in text_lower:
                current_progress[0] = max(prev, 90)
                stage = "Finalizando..."
            elif "tensorflow" in text_lower or "xnnpack" in text_lower:
                current_progress[0] = max(prev, 80)
                stage = "Preparando reconhecimento de mãos..."
            elif any(token in text_lower for token in ("fluidsynth", "bancos de som", "carregado:")):
                current_progress[0] = max(prev, 55)
                stage = "Carregando sons..."
            elif "pygame" in text_lower or "playback carregado" in text_lower:
                current_progress[0] = max(prev, 25)
                stage = "Preparando áudio..."

            if stage:
                win.set_loading_stage(stage)

            if current_progress[0] != prev:
                win.update_progress(current_progress[0])
                app.processEvents()

            # Once fully loaded, hide the menu so the instrument window takes focus
            if current_progress[0] == 100 and win.isVisible():
                win.hide()
                app.processEvents()

        sys.stdout = LoadingStream(original_stdout, handle_log)
        sys.stderr = LoadingStream(original_stderr, handle_log)

        # 5. LAUNCH — blocks here while the instrument event loop runs.
        # quitOnLastWindowClosed must be True so that app.exec() inside each
        # start_* function actually returns when the instrument window is closed.
        app.setQuitOnLastWindowClosed(True)
        try:
            _execute_launch(
                _state["pending"],
                resolution_profile,
                show_trackers,
                hand_model_complexity,
            )
        finally:
            # 6. RESTORE streams; keep quitOnLast=False for the menu loop
            app.setQuitOnLastWindowClosed(False)
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            win.hide()
            app.processEvents()

    win.hide()
    win.close()
    win.deleteLater()
    app.processEvents()
    print(">>> Menu encerrado.")
    app.quit()

if __name__ == "__main__":
    start_menu()
