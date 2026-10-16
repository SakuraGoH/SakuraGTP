from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPixmap
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

        # 默认颜色（亮色）
        self.bg_color = QColor(232, 196, 138)
        self.line_color = QColor(90, 58, 26)
        self.star_color = QColor(90, 58, 26)

        self.base_pixmap = None
        self._last_side = 0

    def set_dark_mode(self, dark):
        """切换暗色棋盘"""
        if dark:
            self.bg_color = QColor(40, 40, 40)
            self.line_color = QColor(180, 180, 180)
            self.star_color = QColor(180, 180, 180)
        else:
            self.bg_color = QColor(232, 196, 138)
            self.line_color = QColor(90, 58, 26)
            self.star_color = QColor(90, 58, 26)
        self._last_side = 0
        self.update()

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

    def _render_base_pixmap(self):
        pm = QPixmap(self.board_px, self.board_px)
        pm.fill(self.bg_color)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)

        pen = QPen(self.line_color)
        pen.setWidth(1)
        painter.setPen(pen)
        m = self.margin

        for i in range(self.size):
            x = m + i * self.cell
            painter.drawLine(x, m, x, m + (self.size - 1) * self.cell)
            y = m + i * self.cell
            painter.drawLine(m, y, m + (self.size - 1) * self.cell, y)

        painter.setBrush(QBrush(self.star_color))
        stars = [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)]
        for sx, sy in stars:
            px, py = self._px(sx, sy)
            sr = max(2, self.cell // 16)
            painter.drawEllipse(QPointF(px, py), sr, sr)

        font_size = max(5, self.cell // 5)
        font = QFont("Arial", font_size)
        painter.setFont(font)
        painter.setPen(QPen(self.line_color))
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
            px, py = self._px(x, y)
            r = self.cell // 2 - 2
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(px, py), r, r)

        if self.show_candidates:
            for rank, cand in enumerate(self.candidates[:self.max_candidates]):
                self._draw_candidate(painter, rank, cand)

        painter.end()

    def _draw_stone(self, painter, color, x, y):
        px, py = self._px(x, y)
        r = self.cell // 2 - 3
        if color == "B":
            painter.setBrush(QBrush(QColor(0, 0, 0)))
            painter.setPen(QPen(QColor(0, 0, 0)))
        else:
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(0, 0, 0)))
        painter.drawEllipse(QPointF(px, py), r, r)

    def _draw_candidate(self, painter, rank, cand):
        x, y = cand["move"]
        px, py = self._px(x, y)
        r = self.cell // 2 - 2
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

        font_size = max(4, self.cell // 8)
        line1 = f"{wr:.0f}%"
        line2 = self._short_visits(visits)
        line3 = f"{score:+.1f}"

        # 暗色背景下文字用白色
        r_bg = self.bg_color.red()
        g_bg = self.bg_color.green()
        b_bg = self.bg_color.blue()
        if 0.299 * r_bg + 0.587 * g_bg + 0.114 * b_bg < 128:
            text_color = QColor(240, 240, 240)
        else:
            text_color = QColor(20, 20, 20)

        gap = font_size * 1.1
        self._draw_text_center(painter, line1, px, py - gap, font_size, text_color)
        self._draw_text_center(painter, line2, px, py, font_size, text_color)
        self._draw_text_center(painter, line3, px, py + gap, font_size, text_color)

        nr = max(3, self.cell // 12)
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