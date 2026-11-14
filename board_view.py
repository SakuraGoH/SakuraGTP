from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPixmap, QRadialGradient,
)
from PyQt5.QtCore import Qt, QPointF


class BoardView(QWidget):
    RANK_COLORS = [
        QColor(30, 144, 255),
        QColor(50, 205, 50),
        QColor(160, 82, 45),
        QColor(138, 43, 226),
        QColor(255, 140, 0),
        QColor(220, 20, 60),
        QColor(0, 206, 209),
        QColor(255, 215, 0),
        QColor(255, 105, 180),
        QColor(128, 128, 0),
    ]

    def __init__(self, parent=None, size=19):
        super().__init__(parent)
        self.size = size
        self.cell = 40
        self.margin = 40
        self.board_px = 0

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(100, 100)

        self.stones = {}
        self.last_move = None
        self.candidates = []
        self.max_candidates = 10
        self.show_candidates = True

        # 默认暗色星空（与主背景统一）
        self._apply_theme(True)

        self.base_pixmap = None
        self._last_side = 0

    # ---------- 主题 ----------
    def _apply_theme(self, dark):
        if dark:
            # 科幻暗色：无底，只留半透明网格线与坐标，完全透出星空
            self.bg_color = QColor(13, 20, 34, 0)
            self.line_color = QColor(96, 154, 200)
            self.star_color = QColor(0, 229, 255)
            self.label_color = QColor(150, 190, 224)
            self.last_move_color = QColor(0, 229, 255)
            self.dark = True
        else:
            self.bg_color = QColor(232, 196, 138)
            self.line_color = QColor(90, 58, 26)
            self.star_color = QColor(90, 58, 26)
            self.label_color = QColor(90, 58, 26)
            self.last_move_color = QColor(220, 40, 40)
            self.dark = False

    def set_dark_mode(self, dark):
        """切换暗色棋盘"""
        self._apply_theme(dark)
        self._last_side = 0
        self.update()

    # ---------- 几何 ----------
    def _calc_geometry(self):
        w = self.width()
        h = self.height()
        side = min(w, h)
        if side <= 0:
            return
        margin = max(18, side // 18)
        cell = max(6, (side - margin * 2) // (self.size - 1))
        self.cell = cell
        self.margin = margin
        self.board_px = cell * (self.size - 1) + margin * 2

    def _ensure_base(self):
        side = min(self.width(), self.height())
        if side == self._last_side and self.base_pixmap is not None:
            return
        self._calc_geometry()
        self.base_pixmap = self._render_base_pixmap()
        self._last_side = side

    def resizeEvent(self, event):
        self._ensure_base()
        self.update()

    def _px(self, x, y):
        return self.margin + x * self.cell, self.margin + y * self.cell

    def _offset_x(self):
        return max(0, (self.width() - self.board_px) // 2)

    def _offset_y(self):
        return max(0, (self.height() - self.board_px) // 2)

    # ---------- 底图（无底：只画半透明网格线与坐标，完全透出星空） ----------
    def _render_base_pixmap(self):
        pm = QPixmap(self.board_px, self.board_px)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)

        line_a = 150 if self.dark else 170
        label_a = 225 if self.dark else 220
        pen = QPen(QColor(self.line_color.red(), self.line_color.green(),
                          self.line_color.blue(), line_a))
        pen.setWidth(1)
        painter.setPen(pen)
        m = self.margin

        for i in range(self.size):
            x = m + i * self.cell
            painter.drawLine(x, m, x, m + (self.size - 1) * self.cell)
            y = m + i * self.cell
            painter.drawLine(m, y, m + (self.size - 1) * self.cell, y)

        font_size = max(5, self.cell // 5)
        font = QFont("Arial", font_size)
        font.setBold(self.dark)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.label_color.red(), self.label_color.green(),
                                   self.label_color.blue(), label_a)))
        letters = "ABCDEFGHJKLMNOPQRST"

        top_y = self.margin // 2 + font_size // 2
        for i in range(self.size):
            x = m + i * self.cell
            painter.drawText(x - font_size // 2, top_y, letters[i])

        for i in range(self.size):
            y = m + i * self.cell
            num = str(self.size - i)
            painter.drawText(self.margin // 2 - font_size // 2, y + font_size // 3, num)

        painter.end()
        return pm

    # ---------- 数据接口 ----------
    def set_stones(self, stones):
        self.stones = stones
        self.update()

    def set_last_move(self, move):
        self.last_move = move
        self.update()

    def set_candidates(self, candidates):
        self.candidates = candidates or []
        self.update()

    def set_max_candidates(self, n):
        self.max_candidates = max(1, int(n))
        self.update()

    def set_show_candidates(self, show):
        self.show_candidates = bool(show)
        self.update()

    def clear(self):
        self.stones = {}
        self.last_move = None
        self.candidates = []
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        self._ensure_base()
        if self.base_pixmap is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        offset_x = self._offset_x()
        offset_y = self._offset_y()
        painter.translate(offset_x, offset_y)

        painter.drawPixmap(0, 0, self.base_pixmap)

        for n, (color, x, y) in self.stones.items():
            self._draw_stone(painter, color, x, y)

        if self.last_move:
            color, x, y = self.last_move
            self._draw_last_move(painter, x, y)

        if self.show_candidates:
            for rank, cand in enumerate(self.candidates[:self.max_candidates]):
                self._draw_candidate(painter, rank, cand)

        painter.end()

    def _draw_stone(self, painter, color, x, y):
        px, py = self._px(x, y)
        r = self.cell // 2 - 3

        # 阴影
        shadow = QColor(0, 0, 0, 60)
        painter.setBrush(QBrush(shadow))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(px + max(1, r // 8), py + max(1, r // 6)), r, r)

        # 径向渐变棋子
        grad = QRadialGradient(QPointF(px - r / 3, py - r / 3), r * 1.35)
        if color == "B":
            grad.setColorAt(0.0, QColor(88, 96, 110))
            grad.setColorAt(0.55, QColor(32, 36, 46))
            grad.setColorAt(1.0, QColor(8, 10, 16))
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(QColor(0, 0, 0), 1))
        else:
            grad.setColorAt(0.0, QColor(255, 255, 255))
            grad.setColorAt(0.7, QColor(240, 242, 246))
            grad.setColorAt(1.0, QColor(196, 202, 214))
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(QColor(110, 116, 128), 1))
        painter.drawEllipse(QPointF(px, py), r, r)

    def _draw_last_move(self, painter, x, y):
        px, py = self._px(x, y)
        r = self.cell // 2 - 2

        # 外圈霓虹光环
        halo = QColor(self.last_move_color)
        halo.setAlpha(70)
        painter.setBrush(QBrush(halo))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(px, py), r + 2, r + 2)

        pen = QPen(self.last_move_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(px, py), r, r)

    def _draw_candidate(self, painter, rank, cand):
        x, y = cand["move"]
        px, py = self._px(x, y)
        r = self.cell // 2 - 1
        base_color = self.RANK_COLORS[rank % len(self.RANK_COLORS)]

        fill_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 90)
        outline_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 220)

        pen = QPen(outline_color)
        pen.setWidth(max(1, self.cell // 40))
        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))
        painter.drawEllipse(QPointF(px, py), r, r)

        wr = cand.get("winrate", 0.0) * 100
        score = cand.get("score", 0.0)
        visits = cand.get("visits", 0)

        font_size = max(5, self.cell // 7)
        line1 = f"{wr:.0f}%"
        line2 = self._short_visits(visits)
        line3 = f"{score:+.1f}"

        # 暗色背景下文字用白色
        if self.dark:
            text_color = QColor(235, 244, 255)
        else:
            r_bg = self.bg_color.red()
            g_bg = self.bg_color.green()
            b_bg = self.bg_color.blue()
            if 0.299 * r_bg + 0.587 * g_bg + 0.114 * b_bg < 128:
                text_color = QColor(240, 240, 240)
            else:
                text_color = QColor(20, 20, 20)

        gap = font_size * 2.4
        self._draw_text_center(painter, line1, px, py - gap, font_size, text_color)
        self._draw_text_center(painter, line2, px, py, font_size, text_color)
        self._draw_text_center(painter, line3, px, py + gap, font_size, text_color)

        nr = max(4, self.cell // 10)
        nx = px + r - nr // 2
        ny = py - r + nr // 2
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        painter.setPen(QPen(outline_color, 1))
        painter.drawEllipse(QPointF(nx, ny), nr, nr)

        num_font = QFont("Arial", max(4, nr))
        num_font.setBold(True)
        painter.setFont(num_font)
        painter.setPen(QPen(QColor(0, 0, 0)))
        fm = painter.fontMetrics()
        text = str(rank + 1)
        w = fm.horizontalAdvance(text)
        h = fm.height()
        painter.drawText(QPointF(nx - w / 2, ny + h / 4), text)

    def _draw_text_center(self, painter, text, cx, cy, size, color):
        font = QFont("Consolas", size)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(color))
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text)
        h = fm.height()
        painter.drawText(QPointF(cx - w / 2, cy + h / 4), text)

    def _short_visits(self, v):
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v / 1_000:.0f}k"
        return str(v)
