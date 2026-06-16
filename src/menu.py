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
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QStackedWidget, QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QCursor, QFontDatabase, QFont

FILE_PATH    = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.instruments.ui_shared import (
    load_custom_font, FONT_FAMILY,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG,
    BTN_HEIGHT, BORDER_RAD,
)

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

SIDEBAR_W = 195

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
        "id": "piano",   "label": "Piano",   "icon": "Piano",
        "type": "keyboard",  "subtitle": "Toque notas com os dedos",
        "variants": PIANO_VARIANTS,
    },
    {
        "id": "bateria", "label": "Bateria", "icon": "Bateria",
        "type": "drums",     "subtitle": "Percussao com as maos",
        "variants": DRUMS_VARIANTS,
    },
    {
        "id": "maestro", "label": "Maestro", "icon": "Maestro",
        "type": "maestro",   "subtitle": "Instrumento gestual expressivo",
        "variants": [],
    },
]

GAME_INSTRUMENTS = [
    {
        "id": "piano_tiles",  "label": "Piano Tiles",  "icon": "Tiles",
        "type": "keyboard_game", "subtitle": "Toque as notas na hora certa",
        "variants": PIANO_VARIANTS, "songs": PIANO_TILES_SONGS,
    },
    {
        "id": "genius_drums", "label": "Genius Drums", "icon": "Genius",
        "type": "drums_game",    "subtitle": "Repita a sequencia da bateria",
        "variants": DRUMS_VARIANTS, "songs": [],
    },
]

DIFFICULTIES = [
    ("easy",   "Facil"),
    ("medium", "Medio"),
    ("hard",   "Dificil"),
]


# ---------------------------------------------------------------------------
# Reusable card widgets
# ---------------------------------------------------------------------------

class ClickableFrame(QFrame):
    """QFrame that emits clicked on mouse press."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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

        # Icon label - no custom font so system handles it
        self._ico = QLabel(icon)
        self._ico.setAlignment(Qt.AlignCenter)
        self._ico.setStyleSheet("background: transparent; font-size: 14px; font-weight: bold;")
        vl.addWidget(self._ico)

        self._lbl = QLabel(label)
        self._lbl.setAlignment(Qt.AlignCenter)
        vl.addWidget(self._lbl)

        if subtitle:
            self._sub = QLabel(subtitle)
            self._sub.setAlignment(Qt.AlignCenter)
            self._sub.setWordWrap(True)
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
            self._ico.setStyleSheet(f"background: transparent; font-size: 14px; font-weight: bold; color: {MENU_CARD_DARK_TEXT};")
            self._lbl.setStyleSheet(
                f"color: {MENU_CARD_DARK_TEXT}; background: transparent;"
                f" font-size: {FONT_SIZE_MD}px; font-weight: bold; font-family: {FONT_FAMILY};"
            )
            if self._sub:
                self._sub.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent; font-size: 11px;")
        else:
            self.setStyleSheet(
                f"QFrame#instrCard {{ background-color: {MENU_CARD_BG};"
                f" border: 1px solid {MENU_CARD_BORDER}; border-radius: 10px; }}"
            )
            self._ico.setStyleSheet(f"background: transparent; font-size: 14px; font-weight: bold; color: {MENU_TEXT_MAIN};")
            self._lbl.setStyleSheet(
                f"color: {MENU_TEXT_MAIN}; background: transparent;"
                f" font-size: {FONT_SIZE_MD}px; font-weight: bold; font-family: {FONT_FAMILY};"
            )
            if self._sub:
                self._sub.setStyleSheet(f"color: {MENU_TEXT_SUB}; background: transparent; font-size: 11px;")

    def set_selected(self, v: bool) -> None:
        self._selected = v
        self._apply(v)

    def is_selected(self) -> bool:
        return self._selected


class VariantItem(ClickableFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("variantItem")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(40)
        self._selected = False

        hl = QHBoxLayout(self)
        hl.setContentsMargins(14, 0, 12, 0)
        hl.setSpacing(0)

        self._lbl = QLabel(text)
        hl.addWidget(self._lbl, 1)
        self._chk = QLabel("v")
        self._chk.setVisible(False)
        hl.addWidget(self._chk)
        self._apply(False)

    def _apply(self, sel: bool) -> None:
        if sel:
            self.setStyleSheet(
                f"QFrame#variantItem {{ background-color: {MENU_CARD_DARK};"
                f" border: 1px solid {MENU_CARD_DARK}; border-radius: 8px; }}"
            )
            self._lbl.setStyleSheet(f"color: {MENU_CARD_DARK_TEXT}; background: transparent; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};")
            self._chk.setStyleSheet(f"color: {MENU_ACCENT_GREEN}; background: transparent; font-weight: bold;")
        else:
            self.setStyleSheet(
                f"QFrame#variantItem {{ background-color: {MENU_CARD_BG};"
                f" border: 1px solid {MENU_CARD_BORDER}; border-radius: 8px; }}"
            )
            self._lbl.setStyleSheet(f"color: {MENU_TEXT_MAIN}; background: transparent; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY};")
            self._chk.setStyleSheet(f"color: {MENU_ACCENT_GREEN}; background: transparent; font-weight: bold;")

    def set_selected(self, v: bool) -> None:
        self._selected = v
        self._chk.setVisible(v)
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
        em.setStyleSheet("background: transparent; font-size: 18px; font-weight: bold;")
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
        ic.setStyleSheet("background: transparent; font-size: 16px;")
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
        self.setFixedHeight(38)
        self._active = False

        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(8)

        # Icon: use default system font so symbols render
        self._ico = QLabel(icon)
        self._ico.setFixedWidth(20)
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
            self._ico.setStyleSheet(f"background: transparent; font-size: 14px; color: {MENU_TEXT_MAIN};")
            self._txt.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        else:
            self.setStyleSheet(f"QFrame {{ background-color: transparent; border-radius: 6px; border: none; }} QFrame:hover {{ background-color: {MENU_CARD_HOVER}; }}")
            self._ico.setStyleSheet(f"background: transparent; font-size: 14px; color: {MENU_TEXT_MAIN};")
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
        _btn("home",      "[~]", "Home")
        _btn("pratica",   "[P]", "Pratica")
        _btn("jogo",      "[J]", "Jogo")
        _section("SISTEMA")
        _btn("gravacoes", "[R]", "Gravacoes")

        nav_vl.addStretch()
        vl.addWidget(nav_w, 1)

        self._set_active_visual("home")

    def _on_nav(self, page_id: str) -> None:
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

        title = QLabel("O que voce quer\nexplorar hoje?")
        title.setStyleSheet(f"background: transparent; font-size: 32px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        outer.addWidget(title)
        outer.addSpacing(6)

        sub = QLabel("Transforme gestos no ar em musica real.")
        sub.setStyleSheet(f"background: transparent; font-size: {FONT_SIZE_SM}px; color: {MENU_TEXT_SUB}; font-family: {FONT_FAMILY};")
        outer.addWidget(sub)
        outer.addSpacing(28)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        def _card(icon, title_, subtitle, page_id, dark=False):
            c = ModeCard(icon, title_, subtitle, dark)
            c.setFixedHeight(160)
            c.clicked.connect(lambda pid=page_id: self.mode_selected.emit(pid))
            cards_row.addWidget(c)

        _card("[P]", "Pratica",    "Toque livremente",     "pratica",   dark=True)
        _card("[J]", "Jogo",       "Desafios ritmicos",    "jogo")
        _card("[R]", "Gravacoes",  "Ouca suas sessoes",    "gravacoes")
        outer.addLayout(cards_row)
        outer.addSpacing(24)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        stats_row.addWidget(StatCard("[t]", "TEMPO HOJE",      "--"))
        stats_row.addWidget(StatCard("[%]", "PRECISAO MEDIA",  "--"))
        stats_row.addWidget(StatCard("[s]", "SEQUENCIA",       "--"))
        outer.addLayout(stats_row)
        outer.addStretch()


# ---------------------------------------------------------------------------
# Shared: instrument selector + variant list
# ---------------------------------------------------------------------------

class InstrumentSelectorPanel(QWidget):
    instrument_changed = Signal(str)

    def __init__(self, instruments: list, stacked: bool = False, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._cards: dict[str, InstrumentCard] = {}
        self._instruments = instruments
        self._selected_id = ""

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(10)

        lbl = QLabel("INSTRUMENTO")
        lbl.setStyleSheet(f"background: transparent; font-size: 10px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
        vl.addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        if stacked:
            # Each instrument stacks vertically as a full-width card
            for i, instr in enumerate(instruments):
                c = InstrumentCard(instr["icon"], instr["label"], instr.get("subtitle", ""))
                c.clicked.connect(lambda iid=instr["id"]: self._on_select(iid))
                grid.addWidget(c, i, 0, 1, 2)
                grid.setRowStretch(i, 1)
                self._cards[instr["id"]] = c
        else:
            num_rows = 0
            for i, instr in enumerate(instruments):
                c = InstrumentCard(instr["icon"], instr["label"], instr.get("subtitle", ""))
                c.clicked.connect(lambda iid=instr["id"]: self._on_select(iid))
                if i < 2:
                    # First two items: row 0, columns 0 and 1
                    grid.addWidget(c, 0, i)
                    num_rows = max(num_rows, 1)
                else:
                    # Remaining items: row 1+, span 2 columns
                    row = 1 + (i - 2)
                    grid.addWidget(c, row, 0, 1, 2)
                    num_rows = max(num_rows, row + 1)
                self._cards[instr["id"]] = c
            for r in range(num_rows):
                grid.setRowStretch(r, 1)
        vl.addLayout(grid, 1)

        if instruments:
            self._on_select(instruments[0]["id"], emit=False)

    def _on_select(self, id_: str, emit: bool = True) -> None:
        self._selected_id = id_
        for cid, card in self._cards.items():
            card.set_selected(cid == id_)
        if emit:
            self.instrument_changed.emit(id_)

    def get_selected_id(self) -> str:
        return self._selected_id

    def set_selected(self, id_: str) -> None:
        self._on_select(id_)


class VariantSelectorPanel(QWidget):
    variant_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setFixedWidth(210)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        self._section_lbl = QLabel("SOM")
        self._section_lbl.setStyleSheet(f"background: transparent; font-size: 10px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
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

    def load_variants(self, variants: list, section_label: str = "SOM") -> None:
        self._section_lbl.setText(section_label)
        while self._list_vl.count() > 1:
            item = self._list_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._items.clear()

        for v in variants:
            item = VariantItem(v)
            item.clicked.connect(lambda _v=v: self._on_select(_v))
            self._list_vl.insertWidget(self._list_vl.count() - 1, item)
            self._items[v] = item

        if variants:
            self._on_select(variants[0], emit=False)

    def _on_select(self, v: str, emit: bool = True) -> None:
        self._selected = v
        for vk, vi in self._items.items():
            vi.set_selected(vk == v)
        if emit:
            self.variant_changed.emit(v)

    def get_selected(self) -> str:
        return self._selected


# ---------------------------------------------------------------------------
# Pratica page
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

        header = QHBoxLayout()
        title = QLabel("Modo Pratica")
        title.setStyleSheet(f"background: transparent; font-size: 22px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        header.addWidget(title)
        header.addStretch()
        back_btn = QPushButton("<- Voltar")
        back_btn.setObjectName("menuBackBtn")
        back_btn.clicked.connect(lambda: self.nav_requested.emit("home"))
        header.addWidget(back_btn)
        outer.addLayout(header)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        instr_frame = QFrame()
        instr_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        instr_vl = QVBoxLayout(instr_frame)
        instr_vl.setContentsMargins(20, 16, 20, 20)
        instr_vl.setSpacing(12)
        self._instr_sel = InstrumentSelectorPanel(PRACTICE_INSTRUMENTS)
        self._instr_sel.instrument_changed.connect(self._on_instrument_changed)
        instr_vl.addWidget(self._instr_sel)
        main_row.addWidget(instr_frame, 1)

        self._variant_panel = VariantSelectorPanel()
        _sp = self._variant_panel.sizePolicy()
        _sp.setRetainSizeWhenHidden(True)
        self._variant_panel.setSizePolicy(_sp)
        main_row.addWidget(self._variant_panel)
        outer.addLayout(main_row, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._start_btn = QPushButton(">  Iniciar Pratica")
        self._start_btn.setObjectName("menuStartBtn")
        self._start_btn.setFixedHeight(BTN_HEIGHT + 6)
        self._start_btn.setMinimumWidth(200)
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        outer.addLayout(btn_row)

        self._on_instrument_changed(PRACTICE_INSTRUMENTS[0]["id"])

    def _get_info(self, id_: str) -> dict:
        return next((i for i in PRACTICE_INSTRUMENTS if i["id"] == id_), {})

    def _on_instrument_changed(self, id_: str) -> None:
        info = self._get_info(id_)
        variants = info.get("variants", [])
        if variants:
            self._variant_panel.load_variants(variants, "SOM")
            self._variant_panel.setVisible(True)
        else:
            self._variant_panel.setVisible(False)

    def _on_start(self) -> None:
        sel_id = self._instr_sel.get_selected_id()
        info   = self._get_info(sel_id)
        variant = self._variant_panel.get_selected() if info.get("variants") else None
        self.launch_requested.emit({
            "type": info.get("type", "keyboard"),
            "instrument": variant or sel_id,
        })


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

        header = QHBoxLayout()
        title = QLabel("Modo Jogo")
        title.setStyleSheet(f"background: transparent; font-size: 22px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        header.addWidget(title)
        header.addStretch()
        back_btn = QPushButton("<- Voltar")
        back_btn.setObjectName("menuBackBtn")
        back_btn.clicked.connect(lambda: self.nav_requested.emit("home"))
        header.addWidget(back_btn)
        outer.addLayout(header)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        instr_frame = QFrame()
        instr_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        instr_vl = QVBoxLayout(instr_frame)
        instr_vl.setContentsMargins(20, 16, 20, 20)
        instr_vl.setSpacing(12)
        self._instr_sel = InstrumentSelectorPanel(GAME_INSTRUMENTS, stacked=True)
        self._instr_sel.instrument_changed.connect(self._on_game_changed)
        instr_vl.addWidget(self._instr_sel)
        main_row.addWidget(instr_frame, 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        diff_frame = QFrame()
        diff_frame.setFixedWidth(210)
        diff_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        diff_vl = QVBoxLayout(diff_frame)
        diff_vl.setContentsMargins(14, 12, 14, 12)
        diff_vl.setSpacing(6)
        diff_lbl = QLabel("DIFICULDADE")
        diff_lbl.setStyleSheet(f"background: transparent; font-size: 10px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
        diff_vl.addWidget(diff_lbl)
        self._diff_btns: dict[str, QPushButton] = {}
        for key, label_ in DIFFICULTIES:
            btn = QPushButton(label_)
            btn.setObjectName(f"diffBtn_{key}")
            btn.setCheckable(True)
            btn.setChecked(key == "easy")
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _c=False, k=key: self._on_diff(k))
            diff_vl.addWidget(btn)
            self._diff_btns[key] = btn
        right_col.addWidget(diff_frame)

        self._variant_panel = VariantSelectorPanel()
        self._variant_panel.setFixedWidth(210)
        _sp2 = self._variant_panel.sizePolicy()
        _sp2.setRetainSizeWhenHidden(True)
        self._variant_panel.setSizePolicy(_sp2)
        right_col.addWidget(self._variant_panel, 1)
        main_row.addLayout(right_col)
        outer.addLayout(main_row, 1)

        # Song selector
        self._song_frame = QFrame()
        self._song_frame.setStyleSheet(f"QFrame {{ background-color: {MENU_CARD_BG}; border: 1px solid {MENU_CARD_BORDER}; border-radius: 12px; }}")
        song_vl = QVBoxLayout(self._song_frame)
        song_vl.setContentsMargins(20, 14, 20, 14)
        song_vl.setSpacing(8)
        sl = QLabel("MUSICAS DISPONIVEIS")
        sl.setStyleSheet(f"background: transparent; font-size: 10px; font-weight: bold; color: {MENU_TEXT_SUB}; letter-spacing: 2px; font-family: {FONT_FAMILY};")
        song_vl.addWidget(sl)
        songs_row = QHBoxLayout()
        songs_row.setSpacing(8)
        self._song_items: dict[str, VariantItem] = {}
        for song in PIANO_TILES_SONGS:
            si = VariantItem(song)
            si.setFixedHeight(36)
            si.clicked.connect(lambda _s=song: self._on_song(_s))
            songs_row.addWidget(si)
            self._song_items[song] = si
        songs_row.addStretch()
        song_vl.addLayout(songs_row)
        self._song_items[self._selected_song].set_selected(True)
        _sp3 = self._song_frame.sizePolicy()
        _sp3.setRetainSizeWhenHidden(True)
        self._song_frame.setSizePolicy(_sp3)
        outer.addWidget(self._song_frame)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._start_btn = QPushButton(">  Iniciar Jogo")
        self._start_btn.setObjectName("menuStartBtn")
        self._start_btn.setFixedHeight(BTN_HEIGHT + 6)
        self._start_btn.setMinimumWidth(200)
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        outer.addLayout(btn_row)

        self._on_game_changed(GAME_INSTRUMENTS[0]["id"])
        self._apply_diff_styles()

    def _get_info(self, id_: str) -> dict:
        return next((i for i in GAME_INSTRUMENTS if i["id"] == id_), {})

    def _on_game_changed(self, id_: str) -> None:
        info = self._get_info(id_)
        variants = info.get("variants", [])
        if variants:
            self._variant_panel.load_variants(variants, "SOM")
            self._variant_panel.setVisible(True)
        else:
            self._variant_panel.setVisible(False)
        self._song_frame.setVisible(bool(info.get("songs")))

    def _on_diff(self, key: str) -> None:
        self._current_diff = key
        for k, btn in self._diff_btns.items():
            btn.setChecked(k == key)
        self._apply_diff_styles()

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
        self._selected_song = song
        for s, si in self._song_items.items():
            si.set_selected(s == song)

    def _on_start(self) -> None:
        sel_id  = self._instr_sel.get_selected_id()
        info    = self._get_info(sel_id)
        variant = self._variant_panel.get_selected() if info.get("variants") else None
        self.launch_requested.emit({
            "type":       info.get("type", "drums_game"),
            "instrument": variant or sel_id,
            "difficulty": self._current_diff,
            "song":       self._selected_song,
        })


# ---------------------------------------------------------------------------
# Gravacoes page
# ---------------------------------------------------------------------------

class RecordingsPage(QWidget):
    nav_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {MENU_BG};")

        vl = QVBoxLayout(self)
        vl.setContentsMargins(28, 24, 28, 24)
        vl.setSpacing(16)

        title = QLabel("Gravacoes")
        title.setStyleSheet(f"background: transparent; font-size: 22px; font-weight: bold; color: {MENU_TEXT_MAIN}; font-family: {FONT_FAMILY};")
        vl.addWidget(title)

        sub = QLabel("Suas sessoes salvas (.mid)")
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

        self._refresh()

    def _refresh(self) -> None:
        while self._list_vl.count() > 1:
            item = self._list_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        mids_dir = Path(settings.MIDS_DIR)
        files = (
            sorted(mids_dir.glob("*.mid"), key=lambda f: f.stat().st_mtime, reverse=True)
            if mids_dir.exists() else []
        )

        if not files:
            none_lbl = QLabel("Nenhuma gravacao encontrada.")
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

            ic = QLabel("[*]")
            ic.setStyleSheet("background: transparent; font-size: 14px;")
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
            self._list_vl.insertWidget(self._list_vl.count() - 1, row)

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
    background-color: {MENU_BTN_START_BG};
    color: {MENU_BTN_START_FG};
    border: none;
    border-radius: {BORDER_RAD}px;
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    padding: 0 28px;
    font-family: {FONT_FAMILY};
}}
QPushButton#menuStartBtn:hover {{
    background-color: #3A3A37;
}}
"""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainMenuWindow(QMainWindow):
    launch_triggered = Signal(dict)

    def __init__(
        self,
        resolution_profile=None,
        show_trackers: bool = False,
        hand_model_complexity: int = 1,
    ):
        super().__init__()
        self.setWindowTitle("Talking Hands")
        self.setStyleSheet(_SHARED_BTN_QSS)

        central = QWidget()
        central.setStyleSheet(f"background-color: {MENU_BG};")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.nav_changed.connect(self._show_page)
        root.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {MENU_BG};")
        root.addWidget(self._stack, 1)

        self._home      = HomePage()
        self._pratica   = PraticaPage()
        self._jogo      = JogoPage()
        self._gravacoes = RecordingsPage()

        self._stack.addWidget(self._home)       # 0
        self._stack.addWidget(self._pratica)    # 1
        self._stack.addWidget(self._jogo)       # 2
        self._stack.addWidget(self._gravacoes)  # 3

        self._page_index: dict[str, int] = {
            "home": 0, "pratica": 1, "jogo": 2, "gravacoes": 3,
        }

        self._home.mode_selected.connect(self._show_page)
        self._pratica.nav_requested.connect(self._show_page)
        self._jogo.nav_requested.connect(self._show_page)
        self._pratica.launch_requested.connect(self.launch_triggered)
        self._jogo.launch_requested.connect(self.launch_triggered)

    @Slot(str)
    def _show_page(self, page_id: str) -> None:
        idx = self._page_index.get(page_id, 0)
        self._stack.setCurrentIndex(idx)
        self._sidebar.set_active(page_id)


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

def start_menu(
    resolution_profile=None,
    show_trackers: bool = False,
    hand_model_complexity: int = 1,
) -> None:
    """
    Main menu loop.

    Architecture: single QApplication, no nested event loops.
    - Menu shows with quitOnLastWindowClosed=False
    - User clicks Start -> store config, hide menu, call app.quit()
    - Outer app.exec() returns
    - _execute_launch() runs (instruments call app.exec() themselves;
      quitOnLastWindowClosed=True so closing the instrument window exits
      their app.exec())
    - Loop continues, menu shows again
    """
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()

    win = MainMenuWindow(resolution_profile, show_trackers, hand_model_complexity)
    _state: dict = {"pending": None}

    def on_launch(config: dict) -> None:
        _state["pending"] = config
        win.hide()
        app.quit()

    win.launch_triggered.connect(on_launch)

    while True:
        _state["pending"] = None
        app.setQuitOnLastWindowClosed(False)   # closing menu should not quit
        win.showMaximized()
        app.exec()                             # runs until on_launch calls app.quit()

        if _state["pending"] is None:
            # User closed the window without launching
            break

        # Instrument window closing should exit its own event loop
        app.setQuitOnLastWindowClosed(True)
        _execute_launch(
            _state["pending"],
            resolution_profile,
            show_trackers,
            hand_model_complexity,
        )
        # _execute_launch returned -> instrument was closed -> loop back to show menu

    print(">>> Menu encerrado.")


if __name__ == "__main__":
    start_menu()
