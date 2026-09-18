"""Colours and stylesheet: neutral greys plus one amber accent."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

BG = "#141414"
PANEL = "#1a1a1a"
LINE = "#2a2a2a"
LINE_STRONG = "#3a3a3a"
TEXT = "#e4e4e0"
MUTED = "#9a9a94"
DIM = "#8a8a84"
INPUT = "#121212"
ACCENT = "#e5a91a"
ACCENT_BG = "#2c2410"
WARN_BG = "#221c0c"
WARN_BORDER = "#4a3a12"
WARN_TEXT = "#e8cf8a"


def color(hex_value: str, alpha: int = 255) -> QColor:
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


def mono_font(point_size: float = 11.0) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPointSizeF(point_size)
    return font


STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QMenuBar {{ background: {PANEL}; color: {TEXT}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {LINE_STRONG}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE_STRONG}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE_STRONG}; padding: 4px; }}
#header, #rail, #inspector, #statusbar {{ background: {PANEL}; }}
#header {{ border-bottom: 1px solid {LINE}; }}
#rail {{ border-right: 1px solid {LINE}; }}
#inspector {{ border-left: 1px solid {LINE}; }}
#statusbar {{ border-top: 1px solid {LINE}; background: {BG}; }}
#section {{ border-bottom: 1px solid {LINE}; }}
#brand {{ font-weight: 700; letter-spacing: 3px; font-size: 12px; }}
#sectionTitle {{ color: {MUTED}; font-size: 11px; letter-spacing: 1px; }}
#muted {{ color: {MUTED}; }}
#dim {{ color: {DIM}; font-size: 11px; }}
#value {{ font-size: 19px; }}
#badge {{ color: {ACCENT}; }}
#warning {{ background: {WARN_BG}; border: 1px solid {WARN_BORDER}; color: {WARN_TEXT}; padding: 7px 9px; }}
QPushButton {{ background: transparent; border: 1px solid {LINE_STRONG}; border-radius: 2px; padding: 5px 10px; }}
QPushButton:hover {{ border-color: #5a5a55; }}
QPushButton:disabled {{ color: #5a5a55; border-color: {LINE}; }}
QPushButton#primary {{ background: {ACCENT}; color: {BG}; border-color: {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #f0bb3c; }}
QPushButton#primary:disabled {{ background: {LINE}; color: #5a5a55; border-color: {LINE}; }}
QToolButton#tool {{ background: transparent; border: 1px solid transparent; border-radius: 2px; color: {MUTED}; font-size: 10px; }}
QToolButton#tool:hover {{ border-color: {LINE_STRONG}; }}
QToolButton#tool:checked {{ background: {ACCENT_BG}; border-color: {ACCENT}; color: {ACCENT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {INPUT}; border: 1px solid {LINE_STRONG}; border-radius: 2px; padding: 4px 6px; selection-background-color: {ACCENT}; selection-color: {BG}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QCheckBox {{ spacing: 6px; color: {MUTED}; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid #5a5a55; border-radius: 2px; background: {INPUT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTableWidget {{ background: {PANEL}; border: 0; gridline-color: {LINE}; selection-background-color: {ACCENT_BG}; selection-color: {ACCENT}; }}
QTableWidget::item {{ padding: 2px 4px; border-bottom: 1px solid #242424; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: 0; border-bottom: 1px solid {LINE}; padding: 3px 4px; font-size: 11px; }}
QScrollBar:vertical {{ background: {PANEL}; width: 8px; }}
QScrollBar::handle:vertical {{ background: {LINE_STRONG}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QProgressDialog {{ background: {PANEL}; }}
QProgressBar {{ background: {INPUT}; border: 1px solid {LINE_STRONG}; border-radius: 2px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
"""
