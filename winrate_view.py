import time
from PyQt5.QtWidgets import QWidget, QSizePolicy, QFileDialog
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPixmap
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

        # 默认亮色
        self.bg_color = QColor(235, 235, 235)
        self.grid_color = QColor(180, 180, 180)
        self.text_color = QColor(40, 40, 40)
        self.black_line_color = QColor(30, 90, 220)
        self.white_line_color = QColor(220, 60, 60)
        self.score_line_color = QColor(30, 160, 60)

    def set_dark_mode(self, dark):
        """切换暗色背景"""
        if dark:
            self.bg_color = QColor(30, 30, 30)
            self.grid_color = QColor(70, 70, 70)
            self.text_color = QColor(220, 220, 220)
        else:
            self.bg_color = QColor(235, 235, 235)
            self.grid_color = QColor(180, 180, 180)
            self.text_color = QColor(40, 40, 40)
        self.update()

    def set_bg_color(self, color_hex):
        """根据背景色自动设置文字、网格颜色"""
        try:
            self.bg_color = QColor(color_hex)
        except Exception:
            self.bg_color = QColor(235, 235, 235)

        r = self.bg_color.red()
        g = self.bg_color.green()
        b = self.bg_color.blue()
        luminance = 0.299 * r + 0.587 * g + 0.114 * b

        if luminance > 128:
            self.text_color = QColor(40, 40, 40)
            self.grid_color = QColor(180, 180, 180)
        else:
            self.text_color = QColor(220, 220, 220)
            self.grid_color = QColor(70, 70, 70)

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

            pen = QPen(self.black_line_color)
            pen.setWidth(5)
            painter.setPen(pen)
            prev = None
            for move, black_wr in self.data:
                x = margin_left + plot_w * (move - min_move) / move_range
                y = margin_top + plot_h * (1.0 - black_wr)
                if prev:
                    painter.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
                prev = (x, y)
                last_black = black_wr
                last_black_x = x
                last_black_y = y

            pen = QPen(self.white_line_color)
            pen.setWidth(5)
            painter.setPen(pen)
            prev = None
            for move, black_wr in self.data:
                x = margin_left + plot_w * (move - min_move) / move_range
                white_wr = 1.0 - black_wr
                y = margin_top + plot_h * (1.0 - white_wr)
                if prev:
                    painter.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
                prev = (x, y)
                last_white = white_wr
                last_white_x = x
                last_white_y = y

        last_score = None
        last_score_x = 0
        last_score_y = 0

        if len(self.score_data) >= 2:
            max_score = max(s for _, s in self.score_data)
            min_score = min(s for _, s in self.score_data)
            score_range = max(abs(max_score), abs(min_score), 5)

            center_y = margin_top + plot_h / 2
            pen = QPen(QColor(150, 150, 150))
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(margin_left, int(center_y), w - margin_right, int(center_y))

            pen = QPen(self.score_line_color)
            pen.setWidth(5)
            painter.setPen(pen)

            min_move = min(m for m, _ in self.score_data)
            max_move = max(m for m, _ in self.score_data)
            move_range = max(1, max_move - min_move)

            prev = None
            for move, score in self.score_data:
                x = margin_left + plot_w * (move - min_move) / move_range
                y = margin_top + plot_h / 2 - (score / score_range) * (plot_h / 2)
                if prev:
                    painter.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
                prev = (x, y)
                last_score = score
                last_score_x = x
                last_score_y = y

        bold_font = QFont("Arial", 11)
        bold_font.setBold(True)
        painter.setFont(bold_font)

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
            painter.setPen(QPen(color))
            painter.drawText(int(x) - 55, int(ty), text)

        painter.setFont(QFont("Arial", 10))
        block_size = 12
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