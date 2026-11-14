"""
深空星图背景绘制器 v3。

- 整个天穹绕窗口中心刚体旋转（斗转星移，不画拖尾弧线）
- 繁星：1100 颗，多色（蓝白/暖黄/青），约半数闪烁
- 银河：对角光带 + 300 颗密集星点
- 彩色星云 + 十字亮星
- day 参数 0..1：0=纯星空，1=白昼；昼夜更替时按 (1-day) 淡出星象
"""

import math
import random

from PyQt5.QtGui import QColor, QPainter, QRadialGradient, QLinearGradient, QBrush, QPen
from PyQt5.QtCore import QPointF, Qt, QRectF

# 昼夜更替循环周期（秒）
DAY_CYCLE_SEC = 180.0

# 天穹旋转中心（窗口中心，单位坐标）与自转速度（度/秒）
ROT_CENTER_UX, ROT_CENTER_UY = 0.5, 0.5
ROT_DEG_PER_SEC = 2.0
# 星盘半径（保证任意旋转角度下窗口四角都被星盘覆盖）
DISK_RADIUS = 0.80


def day_factor(now):
    """给定时间戳，返回 0..1 的白昼系数（3 分钟一个完整昼夜，余弦平滑）。"""
    phase = (now % DAY_CYCLE_SEC) / DAY_CYCLE_SEC
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)


def _star_color(rng):
    """繁星配色：70% 蓝白 / 20% 暖黄 / 10% 青色。"""
    k = rng.random()
    if k < 0.70:
        return (200 + rng.randint(0, 35), 224 + rng.randint(0, 20), 255)
    if k < 0.90:
        return (255, 222 + rng.randint(0, 25), 175 + rng.randint(0, 30))
    return (165, 232 + rng.randint(0, 20), 255)


def _in_disk(rng, r_max):
    """在单位圆盘内均匀取点（相对旋转中心）。"""
    rho = math.sqrt(rng.random()) * r_max
    phi = rng.random() * math.tau
    return rho * math.cos(phi), rho * math.sin(phi)


class Starfield:
    def __init__(self, seed=20261114):
        rng = random.Random(seed)

        # 繁星（含闪烁）：分布在旋转中心周围的圆盘内
        self.stars = []
        for _ in range(1100):
            ox, oy = _in_disk(rng, DISK_RADIUS)
            r, g, b = _star_color(rng)
            self.stars.append({
                "ux": ROT_CENTER_UX + ox,
                "uy": ROT_CENTER_UY + oy,
                "r": rng.choice([1, 1, 1, 1, 1, 2, 2, 2, 3]),
                "c": (r, g, b),
                "base": rng.randint(80, 240),
                "twinkle": rng.random() < 0.45,
                "phase": rng.random() * math.tau,
                "speed": rng.uniform(0.5, 2.2),
                "amp": rng.randint(35, 80),
            })

        # 十字亮星
        self.flares = [
            {"ux": ROT_CENTER_UX + ox, "uy": ROT_CENTER_UY + oy,
             "phase": rng.random() * math.tau}
            for ox, oy in (_in_disk(rng, 0.72) for _ in range(12))
        ]

        # 星云（须留在星盘内才能全程可见）
        self.nebulae = [
            {"ux": 0.22, "uy": 0.20, "ur": 0.42, "c": QColor(36, 72, 150, 46)},
            {"ux": 0.82, "uy": 0.68, "ur": 0.38, "c": QColor(120, 44, 140, 36)},
            {"ux": 0.60, "uy": 0.10, "ur": 0.30, "c": QColor(0, 150, 170, 30)},
            {"ux": 0.10, "uy": 0.80, "ur": 0.34, "c": QColor(200, 80, 140, 24)},
            {"ux": 0.45, "uy": 0.55, "ur": 0.50, "c": QColor(60, 90, 180, 26)},
        ]

        # 银河：对角亮带 + 高斯分布密集星（限制在星盘内）
        self.mw_angle = -28.0
        self.mw_cx, self.mw_cy = 0.50, 0.52
        a = math.radians(self.mw_angle)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        self.mw_stars = []
        for _ in range(300):
            along = rng.uniform(-0.72, 0.72)
            off = rng.gauss(0.0, 0.09)
            px = self.mw_cx + along * dx + off * nx - ROT_CENTER_UX
            py = self.mw_cy + along * dy + off * ny - ROT_CENTER_UY
            if px * px + py * py > DISK_RADIUS * DISK_RADIUS:
                continue
            r, g, b = _star_color(rng)
            self.mw_stars.append({
                "ux": ROT_CENTER_UX + px,
                "uy": ROT_CENTER_UY + py,
                "c": (r, g, b),
                "alpha": rng.randint(40, 150),
            })

    # ------------------------------------------------------------------
    def paint(self, painter, w, h, t, day=0.0):
        if w <= 0 or h <= 0:
            return
        p = painter
        p.setRenderHint(QPainter.Antialiasing, True)
        side = min(w, h)

        # 深空底色
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor("#0C1424"))
        bg.setColorAt(0.55, QColor("#0A101E"))
        bg.setColorAt(1.0, QColor("#070C16"))
        p.fillRect(0, 0, w, h, bg)

        vis = max(0.0, min(1.0, 1.0 - day))

        # 白昼覆盖层 + 太阳辉光
        if day > 0.003:
            sky = QLinearGradient(0, 0, 0, h)
            for pos, col in ((0.0, "#4F8FD0"), (0.5, "#9DC3E8"),
                             (0.78, "#D6E6F5"), (1.0, "#E9F1F9")):
                c = QColor(col)
                c.setAlpha(int(day * 255))
                sky.setColorAt(pos, c)
            p.fillRect(0, 0, w, h, sky)

            sun = QRadialGradient(QPointF(w * 0.76, h * 0.16), side * 0.55)
            sun.setColorAt(0.0, QColor(255, 250, 230, int(150 * day)))
            sun.setColorAt(0.25, QColor(255, 244, 200, int(64 * day)))
            sun.setColorAt(1.0, QColor(255, 244, 200, 0))
            p.fillRect(0, 0, w, h, sun)

        if vis <= 0.01:
            return

        # ---- 整个天穹绕窗口中心刚体旋转（斗转星移） ----
        p.save()
        p.translate(ROT_CENTER_UX * w, ROT_CENTER_UY * h)
        p.rotate(t * ROT_DEG_PER_SEC)
        p.translate(-ROT_CENTER_UX * w, -ROT_CENTER_UY * h)

        # 星云
        for neb in self.nebulae:
            cx, cy = neb["ux"] * w, neb["uy"] * h
            r = neb["ur"] * side
            grad = QRadialGradient(QPointF(cx, cy), r)
            c = neb["c"]
            grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(c.alpha() * vis)))
            grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, w, h, grad)

        # 银河光带（压扁的径向渐变椭圆）
        p.save()
        p.translate(self.mw_cx * w, self.mw_cy * h)
        p.rotate(self.mw_angle)
        p.scale(1.0, 0.30)
        R = side * 0.95
        mw = QRadialGradient(QPointF(0, 0), R)
        mw.setColorAt(0.0, QColor(176, 208, 255, int(46 * vis)))
        mw.setColorAt(0.5, QColor(150, 180, 240, int(24 * vis)))
        mw.setColorAt(1.0, QColor(150, 180, 240, 0))
        p.fillRect(QRectF(-R, -R, 2 * R, 2 * R), mw)
        p.restore()

        # 银河密集星
        p.setPen(Qt.NoPen)
        for s in self.mw_stars:
            if not (-0.2 <= s["ux"] <= 1.2 and -0.2 <= s["uy"] <= 1.2):
                continue
            alpha = int(s["alpha"] * vis)
            if alpha <= 4:
                continue
            r, g, b = s["c"]
            p.setBrush(QBrush(QColor(r, g, b, alpha)))
            p.drawEllipse(QPointF(s["ux"] * w, s["uy"] * h), 1, 1)

        # 繁星
        for s in self.stars:
            alpha = s["base"]
            if s["twinkle"]:
                alpha += int(s["amp"] * math.sin(t * s["speed"] + s["phase"]))
                alpha = max(25, min(255, alpha))
            alpha = int(alpha * vis)
            if alpha <= 4:
                continue
            r, g, b = s["c"]
            p.setBrush(QBrush(QColor(r, g, b, alpha)))
            p.drawEllipse(QPointF(s["ux"] * w, s["uy"] * h), s["r"], s["r"])

        # 十字亮星
        for f in self.flares:
            x, y = f["ux"] * w, f["uy"] * h
            glow = int((90 + 60 * math.sin(t * 0.9 + f["phase"])) * vis)
            if glow <= 4:
                continue
            color = QColor(190, 235, 255, glow)
            pen = QPen(color)
            pen.setWidth(1)
            p.setPen(pen)
            L = 7
            p.drawLine(QPointF(x - L, y), QPointF(x + L, y))
            p.drawLine(QPointF(x, y - L), QPointF(x, y + L))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(230, 248, 255, min(255, glow + 90))))
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)

        p.restore()
