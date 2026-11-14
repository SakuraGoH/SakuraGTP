"""
SakuraGTP 启动动画。

frameless 半透明启动窗：HUD 面板 + 星空 + 标题逐字点亮 + 旋转光环 +
发光进度条 + 扫描线。主窗口构造期间即显示，最短展示 ~2.2 秒后淡出。
"""

import time

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import (
    Qt, QElapsedTimer, QEventLoop, QPropertyAnimation, QRectF, QPointF, QTimer,
)
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QPainterPath, QFontMetrics,
    QConicalGradient, QLinearGradient,
)

from starfield import Starfield
from theme import pal

PHASES = [
    "校准星图坐标 ...",
    "建立引擎链路 ...",
    "连接野狐协议 ...",
    "点亮霓虹界面 ...",
]

MIN_DISPLAY_MS = 2200


class SakuraSplash(QWidget):
    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(760, 470)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.center().x() - self.width() // 2,
                  screen.center().y() - self.height() // 2)

        self._starfield = Starfield(seed=9527)
        self._clock = QElapsedTimer()
        self._clock.start()

        # 标题字号：保证完整标题在最宽情况下也能放进面板
        self._title_size = 26
        probe = QFont("Consolas")
        probe.setBold(True)
        while self._title_size > 16:
            probe.setPointSize(self._title_size)
            fm = QFontMetrics(probe)
            w = sum(fm.horizontalAdvance(ch) for ch in "SAKURAGTP") + 9 * 8
            if w <= self.width() - 170:
                break
            self._title_size -= 1

        self._tick = QTimer(self)
        self._tick.setInterval(30)
        self._tick.timeout.connect(self.update)
        self._tick.start()

    # ------------------------------------------------------------------
    def finish(self, min_ms=MIN_DISPLAY_MS):
        """阻塞到最短展示时间结束（期间保持动画），然后淡出关闭。"""
        while self._clock.elapsed() < min_ms:
            QApplication.processEvents(QEventLoop.AllEvents, 25)
            self.update()
            time.sleep(0.012)

        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(430)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.start()
        while anim.state() == QPropertyAnimation.Running:
            QApplication.processEvents(QEventLoop.AllEvents, 25)
            time.sleep(0.012)
        self.close()

    # ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        palette = pal()

        elapsed = self._clock.elapsed()
        t = elapsed / 1000.0
        progress = min(100.0, elapsed / MIN_DISPLAY_MS * 100.0)

        panel = QRectF(10, 10, self.width() - 20, self.height() - 20)

        # ---- HUD 面板 ----
        path = QPainterPath()
        path.addRoundedRect(panel, 16, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(11, 18, 32, 242)))
        p.drawPath(path)

        halo = QPainterPath()
        halo.addRoundedRect(panel.adjusted(-2, -2, 2, 2), 18, 18)
        p.setBrush(QBrush(palette["hud_halo"]))
        p.drawPath(halo)

        # 裁剪到面板内部画星空
        p.save()
        p.setClipPath(path)
        p.translate(panel.x(), panel.y())
        self._starfield.paint(p, int(panel.width()), int(panel.height()), t)
        p.restore()

        p.setPen(QPen(palette["hud_border"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # 角括号
        pen = QPen(palette["hud_bracket"], 2)
        p.setPen(pen)
        L = 22
        x0, y0 = panel.x(), panel.y()
        x1, y1 = panel.right(), panel.bottom()
        for sx, sy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                               (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(QPointF(sx + dx, sy + dy * L), QPointF(sx + dx, sy + dy))
            p.drawLine(QPointF(sx + dx, sy + dy), QPointF(sx + dx * L, sy + dy))

        cx = panel.center().x()
        accent = palette["accent"]

        # ---- 扫描线（位于星空之上、文字与光环之下，避免遮挡内容） ----
        scan_period = 2600.0
        scan_y = y0 + ((elapsed % scan_period) / scan_period) * panel.height()
        scan = QLinearGradient(0, scan_y - 14, 0, scan_y + 14)
        scan.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        scan.setColorAt(0.5, QColor(accent.red(), accent.green(), accent.blue(), 30))
        scan.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(panel.x(), scan_y - 14, panel.width(), 28), scan)
        p.restore()

        # ---- 旋转光环（缩小上移，给标题留出独立横带） ----
        ring_r = 44
        ring_cy = y0 + 72
        conic = QConicalGradient(QPointF(cx, ring_cy), -t * 160)
        conic.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        conic.setColorAt(0.12, accent)
        conic.setColorAt(0.25, QColor(accent.red(), accent.green(), accent.blue(), 40))
        conic.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(QPen(QBrush(conic), 4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, ring_cy), ring_r, ring_r)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 60), 1))
        p.drawEllipse(QPointF(cx, ring_cy), ring_r - 7, ring_r - 7)

        # ---- 标题（SAKURAGTP，无空格；渐变填充 + 色差分离 + 描边 + 能量基线） ----
        title = "SAKURAGTP"
        reveal = int(len(title) * min(1.0, elapsed / 1100.0) + 0.5)
        shown = title[:reveal]
        font = QFont("Consolas")
        font.setPointSize(self._title_size)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        spacing = 8
        total_w = sum(fm.horizontalAdvance(ch) for ch in title) + spacing * (len(title) - 1)
        title_base = y0 + 246
        tx_start = cx - total_w / 2
        tx = tx_start
        asc, desc = fm.ascent(), fm.descent()
        for ch in shown:
            w = fm.horizontalAdvance(ch)
            path = QPainterPath()
            path.addText(tx, title_base, font, ch)
            # 色差分离（左品红 / 右青色）
            p.setPen(Qt.NoPen)
            p.fillPath(path.translated(-2.2, 0), QColor(255, 64, 150, 72))
            p.fillPath(path.translated(2.2, 0), QColor(0, 229, 255, 82))
            # 纵向渐变填充：顶白 -> 青
            grad = QLinearGradient(0, title_base - asc, 0, title_base + desc)
            grad.setColorAt(0.0, QColor("#FFFFFF"))
            grad.setColorAt(0.55, QColor("#BDF3FF"))
            grad.setColorAt(1.0, QColor("#00D5F0"))
            p.fillPath(path, QBrush(grad))
            # 青色细描边
            p.setPen(QPen(QColor(0, 229, 255, 130), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            tx += w + spacing

        # 标题能量基线（两端渐隐）
        line_y = title_base + desc + 8
        base_grad = QLinearGradient(tx_start, 0, tx_start + total_w, 0)
        base_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        base_grad.setColorAt(0.5, QColor(accent.red(), accent.green(), accent.blue(), 200))
        base_grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(QPen(QBrush(base_grad), 2))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(tx_start, line_y), QPointF(tx_start + total_w, line_y))

        # ---- 进度条 ----
        bar_w = panel.width() - 180
        bar_h = 8
        bx = cx - bar_w / 2
        by = y1 - 96
        track = QPainterPath()
        track.addRoundedRect(QRectF(bx, by, bar_w, bar_h), 4, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(30, 48, 78, 200)))
        p.drawPath(track)

        fill_w = bar_w * progress / 100.0
        if fill_w > 1:
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(bx, by, fill_w, bar_h), 4, 4)
            grad = QLinearGradient(bx, 0, bx + bar_w, 0)
            grad.setColorAt(0.0, QColor(0, 190, 220))
            grad.setColorAt(1.0, accent)
            p.setBrush(QBrush(grad))
            p.drawPath(fill)
            # 端点光球
            p.setBrush(QBrush(QColor(220, 250, 255, 230)))
            p.drawEllipse(QPointF(bx + fill_w, by + bar_h / 2), 5, 5)

        pct_font = QFont("Consolas")
        pct_font.setBold(True)
        pct_font.setPointSize(10)
        p.setFont(pct_font)
        p.setPen(QPen(accent))
        pct_text = f"{int(progress):3d}%"
        pfm = QFontMetrics(pct_font)
        p.drawText(QPointF(x1 - 20 - pfm.horizontalAdvance(pct_text),
                           by - 6 + pfm.ascent()), pct_text)

        # ---- 阶段文字 ----
        phase = PHASES[min(len(PHASES) - 1, int(progress / 100.0 * len(PHASES)))]
        phase_font = QFont("Microsoft YaHei UI")
        phase_font.setPointSize(10)
        p.setFont(phase_font)
        p.setPen(QPen(QColor(143, 163, 192)))
        phfm = QFontMetrics(phase_font)
        p.drawText(QPointF(cx - phfm.horizontalAdvance(phase) / 2,
                           by + 26 + phfm.ascent()), phase)

        p.end()
