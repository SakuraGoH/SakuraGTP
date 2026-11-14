"""
星光鼠标效果。

- make_star_cursor()：四芒星光标，↖ 长角为顶点（与普通箭头光标同轴向），
  渐变填充 + 多层辉光，质感细腻
- StarTrailWidget：鼠标滑过主界面时的流星尾迹——渐隐弧线 + 蓝色星辰粒子
"""

import math
import random
import time

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QPointF, QTimer
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QPainterPath, QCursor, QPixmap,
    QLinearGradient,
)

# 尾迹粒子配色（蓝色星辰）
PALETTE = [
    (0, 229, 255), (155, 239, 255), (79, 168, 255),
    (120, 200, 255), (220, 248, 255),
]


def _sparkle_path(cx, cy, spikes):
    """
    四芒星路径：每条角是从中心伸出的细长菱形（两侧微凹）。
    spikes: [(角度°, 长度)], 屏幕坐标系（y 向下）。
    """
    c = QPointF(cx, cy)
    path = QPainterPath()
    for ang, length in spikes:
        d = QPointF(math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        n = QPointF(-d.y(), d.x())
        w = 0.20 * length
        b1 = c + n * w
        b2 = c - n * w
        tip = c + d * length
        ctrl1 = c + d * (length * 0.5) + n * (w * 0.30)
        ctrl2 = c + d * (length * 0.5) - n * (w * 0.30)
        path.moveTo(b1)
        path.quadTo(ctrl1, tip)
        path.quadTo(ctrl2, b2)
        path.lineTo(c)
        path.closeSubpath()
    return path


# ↖ 长角（顶点），其余三角等长
_STAR_SPIKES = [(225.0, 26.0), (315.0, 15.0), (45.0, 14.5), (135.0, 14.5)]


def _draw_star(painter, cx, cy, scale, fill, outline=None, outline_w=1.0):
    path = _sparkle_path(cx, cy, [(a, L * scale) for a, L in _STAR_SPIKES])
    painter.setPen(Qt.NoPen)
    painter.fillPath(path, fill)
    if outline:
        painter.setPen(QPen(outline, outline_w))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


def make_star_cursor():
    """生成四芒星光标（64px 画布，热点在星心）。"""
    dpr = 2.0
    try:
        screen = QApplication.primaryScreen()
        dpr = max(1.0, min(2.0, screen.devicePixelRatio()))
    except Exception:
        dpr = 2.0
    base = 64
    pm = QPixmap(base, base)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    cx = cy = base / 2

    # 外层辉光（两层放大低透明）
    _draw_star(p, cx, cy, 1.42, QColor(0, 229, 255, 20))
    _draw_star(p, cx, cy, 1.20, QColor(0, 229, 255, 36))

    # 主体：纵向渐变（顶白 -> 青）
    grad = QLinearGradient(0, cy - 30, 0, cy + 30)
    grad.setColorAt(0.0, QColor("#FFFFFF"))
    grad.setColorAt(0.5, QColor("#BDF3FF"))
    grad.setColorAt(1.0, QColor("#009FD8"))
    _draw_star(p, cx, cy, 1.0, QBrush(grad),
               outline=QColor(0, 229, 255, 220), outline_w=1.7)

    # 顶点高光（长角方向 ↖）
    d = QPointF(math.cos(math.radians(225.0)), math.sin(math.radians(225.0)))
    tip = QPointF(cx, cy) + d * 24
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(240, 252, 255, 235)))
    p.drawEllipse(tip, 2.6, 2.6)
    # 星心亮点
    p.setBrush(QBrush(QColor(255, 255, 255, 245)))
    p.drawEllipse(QPointF(cx, cy), 2.2, 2.2)
    p.end()
    # 热点设在 ↖ 长角顶点（约 14,14），指向哪里点哪里
    tip_hot = QPointF(cx + 26.0 * math.cos(math.radians(225.0)),
                      cy + 26.0 * math.sin(math.radians(225.0)))
    return QCursor(pm, int(tip_hot.x()), int(tip_hot.y()))


class StarTrailWidget(QWidget):
    """全窗口透明覆盖层：绘制鼠标流星尾迹（蓝弧 + 星辰粒子）。"""

    MAX_POINTS = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._pts = []       # 尾迹主链 [(QPointF, t)]
        self._parts = []     # 星辰粒子
        self._last = None
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._prune)
        self._timer.start()

    def add_point(self, pos):
        if self._last is not None and (pos - self._last).manhattanLength() < 4:
            return
        now = time.time()
        self._pts.append((QPointF(pos), now))
        if len(self._pts) > self.MAX_POINTS:
            self._pts.pop(0)
        for _ in range(3):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(10.0, 48.0)
            self._parts.append({
                "pos": QPointF(pos),
                "vel": QPointF(math.cos(ang) * sp, math.sin(ang) * sp + 14.0),
                "birth": now,
                "life": random.uniform(0.45, 0.85),
                "size": random.uniform(2.2, 4.5),
                "c": random.choice(PALETTE),
                "spark": random.random() < 0.35,
            })
        if len(self._parts) > 140:
            self._parts = self._parts[-140:]
        self._last = pos
        self.update()

    def _prune(self):
        now = time.time()
        self._pts = [(p, t) for p, t in self._pts if now - t < 0.6]
        self._parts = [d for d in self._parts if now - d["birth"] < d["life"]]
        if self._pts or self._parts:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        now = time.time()

        # 流星主链（渐隐弧线）
        for i in range(1, len(self._pts)):
            p0, t0 = self._pts[i - 1]
            p1, t1 = self._pts[i]
            k = 1.0 - (now - t1) / 0.6
            if k <= 0.0:
                continue
            pen = QPen(QColor(0, 229, 255, int(200 * k)), 1.2 + 4.2 * k)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(p0, p1)

        # 星辰粒子
        p.setPen(Qt.NoPen)
        for d in self._parts:
            age = now - d["birth"]
            k = 1.0 - age / d["life"]
            if k <= 0.0:
                continue
            pos = d["pos"] + d["vel"] * age
            r = d["size"] * (0.45 + 0.55 * k)
            cr, cg, cb = d["c"]
            # 外晕
            p.setBrush(QBrush(QColor(cr, cg, cb, int(55 * k))))
            p.drawEllipse(pos, r * 2.6, r * 2.6)
            # 核心
            core = QColor(min(255, cr + 60), min(255, cg + 40), 255, int(225 * k))
            if d["spark"]:
                path = _sparkle_path(
                    pos.x(), pos.y(),
                    [(0.0, r * 3.4), (90.0, r * 1.6), (180.0, r * 3.4), (270.0, r * 1.6)],
                )
                p.fillPath(path, QBrush(core))
            else:
                p.setBrush(QBrush(core))
                p.drawEllipse(pos, r, r)
        p.end()
