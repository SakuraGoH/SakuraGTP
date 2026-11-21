"""Dark sci-fi theme (borrowed from SakuraGTP's look, without its engine code)."""

import os
import sys

from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication

BG = "#0B1220"
BG_ALT = "#0F1828"
PANEL = "#111C2E"
PANEL_LIGHT = "#16233A"
BORDER = "#22314D"
TEXT = "#D7E3F4"
MUTED = "#7C8BA3"
ACCENT = "#35E0D0"
ACCENT_DIM = "#1F7F78"
WARN = "#F2C14E"
ERROR = "#F26D6D"
GOOD = "#57D99A"

BOARD_BG = "#141E30"
BOARD_LINE = "#3B4E6D"
BOARD_STAR = "#5A7095"
BLACK_STONE = "#0B0E14"
WHITE_STONE = "#F2F6FF"


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(BG_ALT))
    palette.setColor(QPalette.AlternateBase, QColor(PANEL))
    palette.setColor(QPalette.ToolTipBase, QColor(PANEL))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(PANEL))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.BrightText, QColor(ACCENT))
    palette.setColor(QPalette.Highlight, QColor(ACCENT_DIM))
    palette.setColor(QPalette.HighlightedText, QColor("#04121A"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(MUTED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    app.setPalette(palette)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(STYLESHEET)


def _asset_uri(name):
    """Absolute, forward-slash path to an asset (works in dev and under PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name).replace("\\", "/")


STYLESHEET = """
QMainWindow, QDialog { background: %(bg)s; }
QWidget { color: %(text)s; font-family: "Microsoft YaHei UI"; font-size: 12px; }
QGroupBox {
    border: 1px solid %(border)s; border-radius: 8px; margin-top: 9px;
    padding: 16px 10px 9px 10px; background: %(panel)s;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left; left: 12px;
    padding: 0 5px; color: %(accent)s; font-weight: 600;
}
QPushButton {
    background: %(panel_light)s; border: 1px solid %(border)s; border-radius: 6px;
    padding: 5px 14px; color: %(text)s;
}
QPushButton:hover { border-color: %(accent)s; color: %(accent)s; }
QPushButton:pressed { background: %(accent_dim)s; color: #04121A; }
QPushButton:disabled { color: %(muted)s; border-color: %(border)s; }
QPushButton#primary {
    background: %(accent_dim)s; border-color: %(accent)s; color: #021014; font-weight: 600;
}
QPushButton#primary:hover { background: %(accent)s; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {
    background: %(bg_alt)s; border: 1px solid %(border)s; border-radius: 5px;
    padding: 3px 6px; selection-background-color: %(accent_dim)s;
}
QSpinBox, QDoubleSpinBox { padding-right: 18px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 15px; margin: 2px 2px 0 0; border: none;
    border-left: 1px solid %(border)s; border-top-right-radius: 5px;
    background: %(panel_light)s;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 15px; margin: 0 2px 2px 0; border: none;
    border-left: 1px solid %(border)s; border-bottom-right-radius: 5px;
    background: %(panel_light)s;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: %(accent_dim)s;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: %(accent)s; }
QComboBox QAbstractItemView { background: %(bg_alt)s; selection-background-color: %(accent_dim)s; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px; height: 14px; border: 1px solid %(border)s; border-radius: 3px;
    background: %(bg_alt)s;
}
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
QMenuBar { background: %(bg)s; }
QMenuBar::item { padding: 4px 12px; background: transparent; }
QMenuBar::item:selected { background: %(panel_light)s; color: %(accent)s; }
QMenu { background: %(panel)s; border: 1px solid %(border)s; }
QMenu::item { padding: 5px 22px; }
QMenu::item:selected { background: %(accent_dim)s; color: #04121A; }
QStatusBar { background: %(bg)s; color: %(muted)s; }
QSplitter::handle { background: %(bg)s; }
QScrollBar:vertical { background: %(bg)s; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: %(accent_dim)s; }
QHeaderView::section {
    background: %(panel_light)s; color: %(muted)s; border: none; padding: 4px;
}
QTabWidget::pane { border: 1px solid %(border)s; border-radius: 6px; }
QTabBar::tab {
    background: %(bg_alt)s; padding: 6px 16px; border: 1px solid %(border)s;
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: %(panel_light)s; color: %(accent)s; }
QToolTip { background: %(panel_light)s; color: %(text)s; border: 1px solid %(accent)s; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("%(arrow_up)s"); width: 8px; height: 6px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("%(arrow_down)s"); width: 8px; height: 6px;
}
""" % {
    "bg": BG, "bg_alt": BG_ALT, "panel": PANEL, "panel_light": PANEL_LIGHT,
    "border": BORDER, "text": TEXT, "muted": MUTED, "accent": ACCENT,
    "accent_dim": ACCENT_DIM,
    "arrow_up": _asset_uri("arrow_up.png"),
    "arrow_down": _asset_uri("arrow_down.png"),
}
