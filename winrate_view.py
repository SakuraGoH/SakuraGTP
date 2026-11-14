import time
from PyQt5.QtWidgets import QWidget, QSizePolicy, QFileDialog
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFont, QPixmap, QLinearGradient,
    QPainterPath, QBrush,
)
from PyQt5.QtCore import Qt, QPointF


class WinrateView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(300, 200)

        self.data = []
        self.score_data = []
        self.max_points = 400

        self.stdev = None

        # 默认暗色星空：背景全透明，只留半透明网格，完全透出星图
        self.bg_color = QColor(13, 20, 34, 0)
        self.grid_color = QColor(96, 138, 178, 110)
        self.text_color = QColor(215, 227, 244)
        self.chip_bg = QColor(17, 28, 48, 225)
        self.black_line_color = QColor(30, 90, 220)
        self.white_line_color = QColor(220, 60, 60)
        self.score_line_color = QColor(30, 160, 60)
        self.glow_alpha = 60

    def set_dark_mode(self, dark):
        """切换暗色背景"""
        if dark:
            self.bg_color = QColor(13, 20, 34, 0)
            self.grid_color = QColor(96, 138, 178, 110)
            self.text_color = QColor(215, 227, 244)
            self.chip_bg = QColor(17, 28, 48, 225)
            self.glow_alpha = 60
        else:
            self.bg_color = QColor(235, 235, 235)
            self.grid_color = QColor(180, 180, 180)
            self.text_color = QColor(40, 40, 40)
            self.chip_bg = QColor(255, 255, 255, 200)
            self.glow_alpha = 40
        self.update()

    def set_bg_color(self, color_hex):
        """根据背景色自动设置文字、网格颜色"""
        try:
            base = QColor(color_hex)
        except Exception:
            base = QColor(235, 235, 235)
        base.setAlpha(0)
        self.bg_color = base

        r = base.red()
        g = base.green()
        b = base.blue()
        lum = 0.299 * r + 0.587 * g + 0.114 * b

        if lum > 128:
            self.text_color = QColor(40, 40, 40)
            self.grid_color = QColor(180, 180, 180)
            self.chip_bg = QColor(255, 255, 255, 200)
        else:
            self.text_color = QColor(220, 220, 220)
            self.grid_color = QColor(70, 70, 70)
            self.chip_bg = QColor(30, 30, 30, 220)
        self.update()

    def add_point(self, move_number, black_winrate):
        self.data.append((move_number, black_winrate))
        if len(self.data) > self.max_points:
            self.data = self.data[-self.max_points:]
        self.update()

    def add_score(self, move_number, own_score_lead):
        self.score_data.append((move_number, own_score_lead))
        if len(self.score_data) > self.max_points:
            self.score_data = self.score_data[-self.max_points:]
        self.update()

    def set_stdev(self, value):
        self.stdev = value
        self.update()

    def clear(self):
        self.data = []
        self.score_data = []
        self.stdev = None
        self.update()

    def export_image(self, parent=None):
        default_name = f"sakura_winrate_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            parent or self, "导出胜率曲线", default_name,
            "PNG 图片 (*.png);;所有文件 (*.*)"
        )
        if not path:
            return False, "取消导出"

        try:
            pixmap = QPixmap(self.size())
            self.render(pixmap)
            pixmap.save(path, "PNG")
            return True, f"已导出: {path}"
        except Exception as e:
            return False, f"导出失败: {e}"

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        margin_left = 60
        margin_right = 20
        margin_top = 60
        margin_bottom = 40

        painter.fillRect(0, 0, w, h, self.bg_color)

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        pen = QPen(self.grid_color)
        pen.setWidth(1)
        painter.setPen(pen)
        for i in range(5):
            y = margin_top + plot_h * i / 4
            painter.drawLine(margin_left, int(y), w - margin_right, int(y))

        painter.drawLine(margin_left, margin_top, margin_left, h - margin_bottom)
        painter.drawLine(margin_left, h - margin_bottom, w - margin_right, h - margin_bottom)

        font = QFont("Arial", 10)
        painter.setFont(font)
        painter.setPen(QPen(self.text_color))
        for i in range(5):
            y = margin_top + plot_h * i / 4
            label = f"{100 - i * 25}%"
            painter.drawText(5, int(y) + 5, label)

        if self.data:
            max_move = max(m for m, _ in self.data)
            min_move = min(m for m, _ in self.data)
            for i in range(5):
                move = min_move + (max_move - min_move) * i / 4
                x = margin_left + plot_w * i / 4
                painter.drawText(int(x) - 10, h - 15, str(int(move)))

        last_black = None
        last_black_x = 0
        last_black_y = 0
        last_white = None
        last_white_x = 0
        last_white_y = 0

        if len(self.data) >= 2:
            min_move = min(m for m, _ in self.data)
            max_move = max(m for m, _ in self.data)
            move_range = max(1, max_move - min_move)

            black_pts = []
            white_pts = []
            for move, black_wr in self.data:
                x = margin_left + plot_w * (move - min_move) / move_range
                y = margin_top + plot_h * (1.0 - black_wr)
                black_pts.append((x, y))
                white_pts.append((x, margin_top + plot_h * black_wr))

            # 黑棋胜率：渐变填充 + 辉光 + 主线
            self._draw_area_fill(painter, black_pts, margin_top, plot_h)
            self._draw_polyline(painter, black_pts, self.black_line_color)
            last_black = self.data[-1][1]
            last_black_x, last_black_y = black_pts[-1]

            # 白棋胜率
            self._draw_polyline(painter, white_pts, self.white_line_color)
            last_white = 1.0 - last_black
            last_white_x, last_white_y = white_pts[-1]

        last_score = None
        last_score_x = 0
        last_score_y = 0

        if len(self.score_data) >= 2:
            max_score = max(s for _, s in self.score_data)
            min_score = min(s for _, s in self.score_data)
            score_range = max(abs(max_score), abs(min_score), 5)

            center_y = margin_top + plot_h / 2
            pen = QPen(self.grid_color)
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(margin_left, int(center_y), w - margin_right, int(center_y))

            min_move = min(m for m, _ in self.score_data)
            max_move = max(m for m, _ in self.score_data)
            move_range = max(1, max_move - min_move)

            pts = []
            for move, score in self.score_data:
                x = margin_left + plot_w * (move - min_move) / move_range
                y = margin_top + plot_h / 2 - (score / score_range) * (plot_h / 2)
                pts.append((x, y))
            self._draw_polyline(painter, pts, self.score_line_color)
            last_score = self.score_data[-1][1]
            last_score_x, last_score_y = pts[-1]

        # 末端圆点
        for x, y, color in (
            (last_black_x, last_black_y, self.black_line_color),
            (last_white_x, last_white_y, self.white_line_color),
            (last_score_x, last_score_y, self.score_line_color),
        ):
            if last_black is None and last_white is None and last_score is None:
                break
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(self.bg_color, 1))
            painter.drawEllipse(QPointF(x, y), 4, 4)

        labels = []
        if last_black is not None:
            labels.append([last_black_x, last_black_y,
                           f"{last_black * 100:.1f}%", self.black_line_color])
        if last_white is not None:
            labels.append([last_white_x, last_white_y,
                           f"{last_white * 100:.1f}%", self.white_line_color])
        if last_score is not None:
            labels.append([last_score_x, last_score_y,
                           f"{last_score:+.1f}", self.score_line_color])

        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                if abs(labels[i][1] - labels[j][1]) < 18 and abs(labels[i][0] - labels[j][0]) < 80:
                    if labels[j][1] < labels[i][1]:
                        labels[j][1] -= 18
                    else:
                        labels[j][1] += 18

        for x, y, text, color in labels:
            if y < margin_top + 15:
                ty = y + 20
            elif y > h - margin_bottom - 15:
                ty = y - 20
            else:
                ty = y - 8
            self._draw_label_chip(painter, x, ty, text, color)

        painter.setFont(QFont("Arial", 10))
        block_size = 13
        legend_y = 18
        gap = 160

        x1 = margin_left
        painter.setBrush(self.black_line_color)
        painter.setPen(QPen(self.black_line_color))
        painter.drawRect(x1, legend_y, block_size, block_size)
        painter.setPen(QPen(self.text_color))
        painter.drawText(x1 + 18, legend_y + 10, "黑棋胜率")

        x2 = margin_left + gap
        painter.setBrush(self.white_line_color)
        painter.setPen(QPen(self.white_line_color))
        painter.drawRect(x2, legend_y, block_size, block_size)
        painter.setPen(QPen(self.text_color))
        painter.drawText(x2 + 18, legend_y + 10, "白棋胜率")

        x3 = margin_left + gap * 2
        painter.setBrush(self.score_line_color)
        painter.setPen(QPen(self.score_line_color))
        painter.drawRect(x3, legend_y, block_size, block_size)
        painter.setPen(QPen(self.text_color))
        painter.drawText(x3 + 18, legend_y + 10, "己方目差")

        painter.setPen(QPen(self.text_color))
        stdev_text = "不确定度: --"
        if self.stdev is not None:
            stdev_text = f"不确定度: {self.stdev:.1f}"
        painter.drawText(margin_left + gap * 3, legend_y + 10, stdev_text)

        painter.end()

    def _draw_polyline(self, painter, pts, color):
        """辉光 + 主线的折线绘制。"""
        glow = QColor(color)
        glow.setAlpha(self.glow_alpha)
        pen = QPen(glow)
        pen.setWidth(9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for i in range(1, len(pts)):
            painter.drawLine(QPointF(*pts[i - 1]), QPointF(*pts[i]))

        pen = QPen(color)
        pen.setWidth(3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for i in range(1, len(pts)):
            painter.drawLine(QPointF(*pts[i - 1]), QPointF(*pts[i]))

    def _draw_area_fill(self, painter, pts, top, height):
        """黑棋胜率曲线下方的渐变填充。"""
        if len(pts) < 2:
            return
        # 用 QLinearGradient 做一个从曲线到底部的柔和渐变填充
        grad = QLinearGradient(0, top, 0, top + height)
        c = self.black_line_color
        grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 46))
        grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 4))

        painter.save()
        ppath = QPainterPath()
        ppath.moveTo(QPointF(*pts[0]))
        for p in pts[1:]:
            ppath.lineTo(QPointF(*p))
        ppath.lineTo(QPointF(pts[-1][0], top + height))
        ppath.lineTo(QPointF(pts[0][0], top + height))
        ppath.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawPath(ppath)
        painter.restore()

    def _draw_label_chip(self, painter, x, y, text, color):
        """圆角标签：底色块 + 彩色文字。"""
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        cx = x - 55
        cy = y - th + 6

        painter.save()
        path = QPainterPath()
        rect_x, rect_y = cx - 5, cy - 2
        rect_w, rect_h = tw + 10, th + 4
        radius = 5
        path.addRoundedRect(rect_x, rect_y, rect_w, rect_h, radius, radius)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.chip_bg))
        painter.drawPath(path)

        bold_font = QFont("Arial", 11)
        bold_font.setBold(True)
        painter.setFont(bold_font)
        painter.setPen(QPen(color))
        painter.drawText(int(cx), int(cy + th - 4), text)
        painter.restore()
