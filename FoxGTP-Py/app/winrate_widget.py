"""Winrate / score-lead sparkline (a small nod to SakuraGTP's winrate view)."""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QSizePolicy, QWidget

from . import theme


class WinrateWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []          # [(move_no, black_winrate 0..1, score_lead)]
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.show_score = True

    def add_point(self, move_no, black_winrate, score_lead=None):
        if black_winrate is None:
            return
        for index, (no, _wr, _sc) in enumerate(self.points):
            if no == move_no:
                self.points[index] = (move_no, black_winrate, score_lead)
                break
        else:
            self.points.append((move_no, black_winrate, score_lead))
        self.points.sort(key=lambda item: item[0])
        self.update()

    def clear(self):
        self.points = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.BG_ALT))
        font = QFont(self.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)
        label_w = max(44.0, painter.fontMetrics().horizontalAdvance("100%") + 6.0)
        rect = QRectF(self.rect()).adjusted(label_w + 6, 14, -12, -20)

        # frame + 50% line
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRect(rect)
        painter.setPen(QPen(QColor(theme.BORDER), 1, Qt.DashLine))
        mid = rect.center().y()
        painter.drawLine(QPointF(rect.left(), mid), QPointF(rect.right(), mid))

        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(0, rect.top() - 6, label_w, 14), Qt.AlignRight | Qt.AlignVCenter, "100%")
        painter.drawText(QRectF(0, mid - 7, label_w, 14), Qt.AlignRight | Qt.AlignVCenter, "50%")
        painter.drawText(QRectF(0, rect.bottom() - 8, label_w, 14), Qt.AlignRight | Qt.AlignVCenter, "0%")

        if len(self.points) < 2:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(rect, Qt.AlignCenter, "—")
            painter.end()
            return

        max_move = max(1, self.points[-1][0])
        polygon = QPolygonF()
        for move_no, winrate, _score in self.points:
            x = rect.left() + rect.width() * (move_no / max_move)
            y = rect.bottom() - rect.height() * max(0.0, min(1.0, winrate))
            polygon.append(QPointF(x, y))

        painter.setPen(QPen(QColor(theme.ACCENT), 1.8))
        painter.drawPolyline(polygon)
        painter.setBrush(QColor(theme.ACCENT))
        last = polygon.last()
        painter.drawEllipse(last, 3.0, 3.0)

        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(rect.left(), rect.bottom() + 3, rect.width(), 16),
                         Qt.AlignLeft | Qt.AlignVCenter, "1")
        painter.drawText(QRectF(rect.left(), rect.bottom() + 3, rect.width(), 16),
                         Qt.AlignRight | Qt.AlignVCenter, str(max_move))
        painter.end()
