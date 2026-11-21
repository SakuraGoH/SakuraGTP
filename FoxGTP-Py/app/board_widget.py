"""Go board rendering (used for both the Fox board and the AI engine board)."""

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QSizePolicy, QWidget

from . import theme

STAR_POINTS = {
    9: [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)],
    13: [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)],
    19: [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)],
}

LETTERS = "ABCDEFGHJKLMNOPQRST"


class BoardWidget(QWidget):
    clicked = pyqtSignal(int, int)
    right_clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.board_size = 19
        self.moves = []              # [{"no","color","x","y"}]
        self.last_move = 0
        self.candidates = []
        self.ai_color = "B"
        self.show_coordinates = True
        self.show_move_numbers = False
        self.show_candidates = True
        self.interactive = False
        self.title = ""
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------------ state
    def set_state(self, board_size=19, moves=None, last_move=0, candidates=None,
                  ai_color=None, **kwargs):
        self.board_size = int(board_size or 19)
        self.moves = list(moves or [])
        self.last_move = int(last_move or 0)
        self.candidates = list(candidates or [])
        if ai_color:
            self.ai_color = ai_color
        for key in ("show_coordinates", "show_move_numbers", "show_candidates",
                    "interactive", "title"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        self.update()

    def clear(self):
        self.moves = []
        self.candidates = []
        self.last_move = 0
        self.update()

    # ------------------------------------------------------------------ geometry
    def _layout(self):
        size = self.board_size
        margin = 36 if self.show_coordinates else 14
        width = max(1, self.width() - 2 * margin)
        height = max(1, self.height() - 2 * margin)
        cell = min(width / max(1, size - 1), height / max(1, size - 1))
        ox = (self.width() - cell * (size - 1)) / 2.0
        oy = (self.height() - cell * (size - 1)) / 2.0
        return cell, ox, oy

    def _xy(self, x, y, cell, ox, oy):
        return QPointF(ox + x * cell, oy + y * cell)

    def _point_to_xy(self, position):
        cell, ox, oy = self._layout()
        if cell <= 0:
            return None
        x = int(round((position.x() - ox) / cell))
        y = int(round((position.y() - oy) / cell))
        if 0 <= x < self.board_size and 0 <= y < self.board_size:
            point = self._xy(x, y, cell, ox, oy)
            if (point - QPointF(position)).manhattanLength() <= cell * 0.7:
                return x, y
        return None

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.BOARD_BG))

        cell, ox, oy = self._layout()
        if cell <= 0:
            return
        size = self.board_size
        radius = cell * 0.46

        # board surface
        board_rect = QRectF(ox - cell * 0.6, oy - cell * 0.6,
                            cell * (size - 1) + cell * 1.2,
                            cell * (size - 1) + cell * 1.2)
        gradient = QLinearGradient(board_rect.topLeft(), board_rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#17233A"))
        gradient.setColorAt(1.0, QColor("#101A2B"))
        painter.fillRect(board_rect, QBrush(gradient))

        # grid
        pen = QPen(QColor(theme.BOARD_LINE), 1.0)
        painter.setPen(pen)
        for i in range(size):
            painter.drawLine(QPointF(ox, oy + i * cell), QPointF(ox + (size - 1) * cell, oy + i * cell))
            painter.drawLine(QPointF(ox + i * cell, oy), QPointF(ox + i * cell, oy + (size - 1) * cell))

        # star points
        painter.setBrush(QColor(theme.BOARD_STAR))
        painter.setPen(Qt.NoPen)
        for (sx, sy) in STAR_POINTS.get(size, []):
            painter.drawEllipse(self._xy(sx, sy, cell, ox, oy), cell * 0.07, cell * 0.07)

        # coordinates
        if self.show_coordinates:
            painter.setPen(QColor(theme.MUTED))
            font = QFont(self.font())
            font.setPointSizeF(max(6.0, min(8.5, cell * 0.26)))
            painter.setFont(font)
            label_h = max(12.0, min(16.0, cell * 0.62))
            span = cell * (size - 1)
            for i in range(size):
                letter = LETTERS[i] if i < len(LETTERS) else "?"
                painter.drawText(QRectF(ox + i * cell - cell / 2, oy - 30, cell, label_h),
                                 Qt.AlignCenter, letter)
                painter.drawText(QRectF(ox + i * cell - cell / 2,
                                        oy + span + 30 - label_h, cell, label_h),
                                 Qt.AlignCenter, letter)
                painter.drawText(QRectF(ox - 32, oy + i * cell - label_h / 2, 26, label_h),
                                 Qt.AlignCenter, str(size - i))
                painter.drawText(QRectF(ox + span + 6, oy + i * cell - label_h / 2, 26, label_h),
                                 Qt.AlignCenter, str(size - i))

        # candidates (under the stones, only on empty points)
        occupied = {(int(m["x"]), int(m["y"])) for m in self.moves}
        if self.show_candidates and self.candidates:
            ordered = sorted(self.candidates, key=lambda c: c.get("order", 999))[:6]
            for index, cand in enumerate(ordered):
                cx, cy = int(cand.get("x", -1)), int(cand.get("y", -1))
                if (cx, cy) in occupied or not (0 <= cx < size and 0 <= cy < size):
                    continue
                center = self._xy(cx, cy, cell, ox, oy)
                winrate = float(cand.get("winrate") or 0.0)
                alpha = 190 if index == 0 else 110
                color = QColor(theme.ACCENT if index == 0 else theme.ACCENT_DIM)
                color.setAlpha(alpha)
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)
                half = cell * (0.34 if index == 0 else 0.28)
                painter.drawRoundedRect(QRectF(center.x() - half, center.y() - half,
                                               half * 2, half * 2), 3, 3)
                if cell >= 30:
                    painter.setPen(QColor("#04121A"))
                    font = QFont(self.font())
                    font.setPointSizeF(max(6.5, cell * 0.24))
                    font.setBold(index == 0)
                    painter.setFont(font)
                    text = "%.0f%%" % (winrate * 100) if winrate else str(cand.get("order", ""))
                    painter.drawText(QRectF(center.x() - cell * 0.45, center.y() - half,
                                            cell * 0.9, half * 2),
                                     Qt.AlignCenter, text)

        # stones
        for move in self.moves:
            mx, my = int(move["x"]), int(move["y"])
            if not (0 <= mx < size and 0 <= my < size):
                continue
            center = self._xy(mx, my, cell, ox, oy)
            color = str(move.get("color", "B")).upper()
            if color == "B":
                gradient = QRadialGradient(center + QPointF(-radius * 0.35, -radius * 0.35), radius * 1.6)
                gradient.setColorAt(0.0, QColor("#3A4557"))
                gradient.setColorAt(0.55, QColor(theme.BLACK_STONE))
                gradient.setColorAt(1.0, QColor("#05070B"))
                painter.setBrush(QBrush(gradient))
                painter.setPen(QPen(QColor("#000000"), 0.5))
            else:
                gradient = QRadialGradient(center + QPointF(-radius * 0.35, -radius * 0.35), radius * 1.6)
                gradient.setColorAt(0.0, QColor("#FFFFFF"))
                gradient.setColorAt(0.7, QColor(theme.WHITE_STONE))
                gradient.setColorAt(1.0, QColor("#B9C6DC"))
                painter.setBrush(QBrush(gradient))
                painter.setPen(QPen(QColor("#8EA0BC"), 0.6))
            painter.drawEllipse(center, radius, radius)

            if self.show_move_numbers:
                number = move.get("no", 0)
                if number and number > 0:
                    painter.setPen(QColor("#F2F6FF") if color == "B" else QColor("#101828"))
                    font = QFont(self.font())
                    font.setPointSizeF(max(5.5, radius * 0.62))
                    painter.setFont(font)
                    painter.drawText(QRectF(center.x() - radius, center.y() - radius,
                                            radius * 2, radius * 2),
                                     Qt.AlignCenter, str(number))

        # last move marker
        if self.last_move:
            for move in self.moves:
                if int(move.get("no", 0)) == self.last_move:
                    center = self._xy(int(move["x"]), int(move["y"]), cell, ox, oy)
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(QPen(QColor(theme.ACCENT), max(1.5, cell * 0.06)))
                    painter.drawEllipse(center, radius * 0.55, radius * 0.55)
                    break

        # title overlay
        if self.title:
            painter.setPen(QColor(theme.MUTED))
            font = QFont(self.font())
            font.setPointSizeF(9.0)
            painter.setFont(font)
            painter.drawText(QRectF(10, 6, self.width() - 20, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, self.title)

        painter.end()

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, event):
        if not self.interactive:
            return
        point = self._point_to_xy(event.pos())
        if point is None:
            return
        if event.button() == Qt.LeftButton:
            self.clicked.emit(point[0], point[1])
        elif event.button() == Qt.RightButton:
            self.right_clicked.emit(point[0], point[1])
