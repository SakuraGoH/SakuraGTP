"""
SakuraGTP 科幻主题引擎 v2。

- 根据背景色生成整套 Qt 样式表（深色=深空霓虹 / 浅色=协调浅色系）
- 提供 HUD 面板、标签页容器等自绘控件所需的调色板（theme.pal()）
- 不再给 QWidget 全局铺底色：主窗口绘制星空背景，控件按类选择器着色，
  半透明面板浮在星图之上
"""

from PyQt5.QtGui import QColor

# ---------- 科幻配色常量 ----------
ACCENT_CYAN = "#00E5FF"      # 霓虹青：主高亮
ACCENT_PINK = "#FF6EC7"      # 樱花粉：次高亮
OK_GREEN = "#69F0AE"
DANGER_RED = "#FF5252"

TEXT_DARK = "#D7E3F4"
DIM_DARK = "#8FA3C0"
BORDER_DARK = "#2A4568"
FIELD_DARK = QColor(10, 18, 34, 215)
BTN_DARK = QColor(19, 30, 52, 225)

TEXT_LIGHT = "#222831"
DIM_LIGHT = "#7A8699"
BORDER_LIGHT = "#AEB9CB"
FIELD_LIGHT = QColor(255, 255, 255, 235)
BTN_LIGHT = QColor(255, 255, 255, 230)


def sci_fi_bg():
    """默认科幻背景色（深空蓝）。"""
    return "#0B1220"


def luminance(color_hex):
    """0~255 亮度，无效颜色返回 -1。"""
    try:
        h = color_hex.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return -1
    return 0.299 * r + 0.587 * g + 0.114 * b


def is_dark(color_hex):
    return luminance(color_hex) <= 128


def build_palette(bg_hex):
    """生成自绘控件（HUD 面板 / 标签页 / 星图装饰）使用的调色板。"""
    if is_dark(bg_hex):
        return {
            "accent": QColor(ACCENT_CYAN),
            "accent2": QColor(ACCENT_PINK),
            "ok": QColor(OK_GREEN),
            "danger": QColor(DANGER_RED),
            "text": QColor(TEXT_DARK),
            "dim": QColor(DIM_DARK),
            "hud_fill": QColor(13, 22, 40, 40),
            "hud_halo": QColor(0, 229, 255, 16),
            "hud_border": QColor(0, 229, 255, 70),
            "hud_bracket": QColor(0, 229, 255, 185),
            "pane_fill": QColor(9, 15, 29, 60),
            "pane_border": QColor(0, 229, 255, 60),
            "pane_halo": QColor(0, 229, 255, 12),
            "chip_fill": QColor(17, 28, 48, 235),
        }
    accent_l = QColor("#0891B2")
    return {
        "accent": accent_l,
        "accent2": QColor("#DB2777"),
        "ok": QColor("#16A34A"),
        "danger": QColor("#DC2626"),
        "text": QColor(TEXT_LIGHT),
        "dim": QColor(DIM_LIGHT),
        "hud_fill": QColor(255, 255, 255, 195),
        "hud_halo": QColor(8, 145, 178, 14),
        "hud_border": QColor(8, 145, 178, 70),
        "hud_bracket": QColor(8, 145, 178, 185),
        "pane_fill": QColor(255, 255, 255, 175),
        "pane_border": QColor(8, 145, 178, 55),
        "pane_halo": QColor(8, 145, 178, 10),
        "chip_fill": QColor(255, 255, 255, 240),
    }


_PALETTE = build_palette(sci_fi_bg())


def set_active_palette(bg_hex):
    global _PALETTE
    _PALETTE = build_palette(bg_hex)


def pal():
    """当前激活的调色板（QColor 字典）。"""
    return _PALETTE


def placeholder_color(bg_hex):
    return "#5E6E88" if is_dark(bg_hex) else "#999999"


# ============================================================ 全局样式表
def build_app_stylesheet(bg_hex):
    """根据背景色生成全局样式表。背景本身由主窗口 paintEvent 绘制。"""
    dark = is_dark(bg_hex)
    if dark:
        text = TEXT_DARK
        dim = DIM_DARK
        border = BORDER_DARK
        field = FIELD_DARK.name(QColor.HexArgb)
        btn = BTN_DARK.name(QColor.HexArgb)
        btn_hover = "rgba(0, 229, 255, 22)"
        btn_pressed = "rgba(0, 229, 255, 48)"
        disabled_bg = "rgba(18, 28, 48, 200)"
        disabled_fg = "#4E5D75"
        sel_bg = ACCENT_CYAN
        sel_fg = "#06121F"
        tab_idle = "rgba(17, 28, 48, 230)"
        dlg_bg = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                  "stop:0 #0E1830, stop:1 #090E1A)")
        status_bg = "rgba(8, 13, 25, 230)"
    else:
        text = TEXT_LIGHT
        dim = DIM_LIGHT
        border = BORDER_LIGHT
        field = FIELD_LIGHT.name(QColor.HexArgb)
        btn = BTN_LIGHT.name(QColor.HexArgb)
        btn_hover = "rgba(8, 145, 178, 26)"
        btn_pressed = "rgba(8, 145, 178, 52)"
        disabled_bg = "rgba(228, 233, 240, 220)"
        disabled_fg = "#A5AEBD"
        sel_bg = "#0891B2"
        sel_fg = "#FFFFFF"
        tab_idle = "rgba(226, 233, 242, 235)"
        dlg_bg = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                  "stop:0 #FBFCFE, stop:1 #EEF2F8)")
        status_bg = "rgba(244, 247, 251, 235)"

    return f"""
/* 主窗口背景由 paintEvent 绘制（星图/渐变），这里保持透明 */
QMainWindow {{ background: transparent; }}
QStatusBar {{
    background: {status_bg};
    border-top: 1px solid {border};
    color: {dim};
}}
QStatusBar QLabel {{ background: transparent; }}

QDialog, QMessageBox, QInputDialog {{
    background: {dlg_bg};
    color: {text};
}}

/* 只统一样式与字号，不铺背景 —— 星图能透过半透明控件看到 */
QWidget {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    color: {text};
}}
QLabel {{ background: transparent; color: {text}; }}
QLabel#dimLabel {{ color: {dim}; }}

/* 滚动区视口透明 —— 星图能透过面板间隙；QTextEdit/QListWidget 各自在后面覆盖 */
#sfViewport {{ background: transparent; }}

/* ---------- 输入类 ---------- */
GlowLineEdit, QLineEdit, GlowComboBox, QComboBox, QSpinBox, QPlainTextEdit {{
    background: {field};
    color: {text};
    border: 1px solid {border};
    border-radius: 7px;
    padding: 6px 11px;
    min-height: 26px;
    selection-background-color: {sel_bg};
    selection-color: {sel_fg};
}}
GlowLineEdit:focus, QLineEdit:focus, GlowComboBox:focus, QComboBox:focus,
QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {sel_bg};
}}
GlowLineEdit:disabled, QLineEdit:disabled, GlowComboBox:disabled,
QComboBox:disabled, QSpinBox:disabled {{
    background: {disabled_bg};
    color: {disabled_fg};
}}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {dim};
    margin-right: 9px;
}}
QComboBox QAbstractItemView {{
    background-color: {chip_fill_name(dark)};
    color: {text};
    border: 1px solid {border};
    selection-background-color: {sel_bg};
    selection-color: {sel_fg};
    outline: none;
}}

/* ---------- 按钮 ---------- */
GlowButton, QPushButton {{
    background: {btn};
    color: {text};
    border: 1px solid {border};
    border-radius: 7px;
    padding: 7px 18px;
    min-height: 26px;
}}
GlowButton:hover, QPushButton:hover {{
    border: 1px solid {sel_bg};
    color: {sel_bg};
    background: {btn_hover};
}}
GlowButton:pressed, QPushButton:pressed {{ background: {btn_pressed}; }}
GlowButton:disabled, QPushButton:disabled {{
    background: {disabled_bg};
    color: {disabled_fg};
    border: 1px solid {border};
}}
GlowButton:default, QPushButton:default {{
    border: 1px solid {sel_bg};
    color: {sel_bg};
}}

/* ---------- HUD 分组框（自绘） ---------- */
HudGroupBox, QGroupBox {{
    background: transparent;
    border: none;
    color: {text};
}}

/* ---------- 复选框 ---------- */
GlowCheckBox, QCheckBox, QRadioButton {{
    color: {text};
    background: transparent;
    spacing: 8px;
}}
GlowCheckBox::indicator, QCheckBox::indicator {{
    width: 19px;
    height: 19px;
    border: 1px solid {border};
    border-radius: 5px;
    background: {field};
}}
GlowCheckBox::indicator:hover, QCheckBox::indicator:hover {{
    border: 1px solid {sel_bg};
}}
GlowCheckBox::indicator:checked, QCheckBox::indicator:checked {{
    background: {sel_bg};
    border: 1px solid {sel_bg};
    image: none;
}}

/* ---------- 标签页（自绘芯片，QSS 兜底） ---------- */
SciFiTabBar, QTabBar {{ background: transparent; }}
SciFiTabBar QToolButton, QTabBar QToolButton {{ background: transparent; border: none; }}
SciFiTabWidget::pane, QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: {tab_idle};
    color: {dim};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 9px 22px;
    margin-right: 4px;
    min-width: 84px;
}}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{ color: {sel_bg}; }}

/* ---------- 菜单 ---------- */
QMenuBar {{
    background-color: transparent;
    color: {text};
    border-bottom: 1px solid {border};
}}
QMenuBar::item {{ padding: 7px 14px; background: transparent; }}
QMenuBar::item:selected {{ color: {sel_bg}; background: rgba(0, 229, 255, 18); }}
QMenu {{
    background-color: {chip_fill_name(dark)};
    color: {text};
    border: 1px solid {border};
    padding: 5px;
}}
QMenu::item {{ padding: 8px 30px 8px 26px; border-radius: 5px; }}
QMenu::item:selected {{ background: {sel_bg}; color: {sel_fg}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 5px 10px; }}

/* ---------- 日志/文本区（完全透明，文字浮在星空上） ---------- */
QTextEdit {{
    background: transparent;
    border: none;
    color: {text};
    padding: 8px;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    selection-background-color: {sel_bg};
    selection-color: {sel_fg};
}}

/* ---------- 列表 ---------- */
QListWidget {{
    background: {field};
    color: {text};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 5px;
    outline: none;
}}
QListWidget::item {{ padding: 7px 10px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {sel_bg}; color: {sel_fg}; }}

/* ---------- 滑条 ---------- */
QSlider::groove:horizontal {{
    height: 6px;
    background: {border};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
    background: {sel_bg};
}}
QSlider::sub-page:horizontal {{ background: {sel_bg}; border-radius: 3px; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 3px;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 6px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: {sel_bg}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {border};
    border-radius: 6px;
    min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: {sel_bg}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ---------- 提示框 ---------- */
QToolTip {{
    background-color: {chip_fill_name(dark)};
    color: {text};
    border: 1px solid {sel_bg};
    padding: 5px 10px;
}}
"""


def chip_fill_name(dark):
    return "#111C30" if dark else "#FFFFFF"
