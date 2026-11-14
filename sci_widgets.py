"""
SakuraGTP 科幻自绘控件库。

- GlowButton / GlowLineEdit / GlowComboBox / GlowCheckBox：
  悬停辉光、点击脉冲、焦点光晕，全部 QPropertyAnimation 驱动
- HudGroupBox：深空 HUD 面板（角括号边框 + 发光标题点），替代方框分组
- SciFiTabBar / SciFiTabWidget：芯片式标签页，滑动指示条 + 悬停渐变 + 点击闪屏
"""

from PyQt5.QtWidgets import (
    QWidget, QPushButton, QLineEdit, QComboBox, QCheckBox, QGroupBox,
    QTabBar, QStackedLayout, QVBoxLayout, QSizePolicy, QGraphicsDropShadowEffect,
    QToolButton,
)
from PyQt5.QtCore import (
    Qt, pyqtProperty, pyqtSignal, QPropertyAnimation, QEasingCurve, QRectF, QPointF, QSize,
)
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QPainterPath,
    QFontMetrics, QLinearGradient,
)

import theme


def _accent():
    return theme.pal()["accent"]


def _make_glow_effect(parent, color=None, radius=0):
    eff = QGraphicsDropShadowEffect(parent)
    eff.setColor(color or _accent())
    eff.setBlurRadius(radius)
    eff.setOffset(0, 0)
    return eff


def _fade_effect(widget, effect, target, duration, remove_when_zero=True):
    """把 effect 的 blurRadius 动画到 target；到 0 时摘除效果。"""
    anim = QPropertyAnimation(effect, b"blurRadius", widget)
    anim.setDuration(duration)
    anim.setStartValue(effect.blurRadius())
    anim.setEndValue(target)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    if remove_when_zero and target == 0:
        def _done():
            if effect.blurRadius() < 0.5:
                widget.setGraphicsEffect(None)
        anim.finished.connect(_done)
    anim.start()
    # 动画对象需要存活到结束：挂到控件上
    widget._glow_anim = anim


# ============================================================ 辉光按钮
class GlowButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._glow_effect = None

    # ---- 悬停辉光 ----
    def enterEvent(self, event):
        super().enterEvent(event)
        if not self.isEnabled():
            return
        self.setProperty("glow", True)
        self._restyle()
        if self._glow_effect is None or self.graphicsEffect() is None:
            self._glow_effect = _make_glow_effect(self, radius=0)
            self.setGraphicsEffect(self._glow_effect)
        _fade_effect(self, self._glow_effect, 16, 130)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.setProperty("glow", False)
        self._restyle()
        if self.graphicsEffect() is not None:
            _fade_effect(self, self.graphicsEffect(), 0, 200)

    # ---- 点击脉冲 ----
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if not self.isEnabled():
            return
        self.setProperty("pressedGlow", True)
        self._restyle()
        eff = self.graphicsEffect()
        if eff is None:
            eff = _make_glow_effect(self, radius=8)
            self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"blurRadius", self)
        anim.setDuration(260)
        anim.setKeyValueAt(0.0, eff.blurRadius())
        anim.setKeyValueAt(0.3, 30.0)
        anim.setKeyValueAt(1.0, 16.0 if self.property("glow") else 0.0)
        if not self.property("glow"):
            def _done():
                if eff.blurRadius() < 0.5:
                    self.setGraphicsEffect(None)
            anim.finished.connect(_done)
        anim.start()
        self._pulse_anim = anim

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setProperty("pressedGlow", False)
        self._restyle()

    def _restyle(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


# ============================================================ 焦点光晕输入框
class GlowLineEdit(QLineEdit):
    def __init__(self, *args):
        super().__init__(*args)
        self._focus_effect = None

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self._focus_effect is None or self.graphicsEffect() is None:
            self._focus_effect = _make_glow_effect(self, radius=0)
            self.setGraphicsEffect(self._focus_effect)
        _fade_effect(self, self._focus_effect, 13, 140)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.graphicsEffect() is not None:
            _fade_effect(self, self.graphicsEffect(), 0, 220)


class GlowComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._glow_effect = None

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self.isEnabled():
            return
        if self._glow_effect is None or self.graphicsEffect() is None:
            self._glow_effect = _make_glow_effect(self, radius=0)
            self.setGraphicsEffect(self._glow_effect)
        _fade_effect(self, self._glow_effect, 13, 130)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self.hasFocus() and self.graphicsEffect() is not None:
            _fade_effect(self, self.graphicsEffect(), 0, 200)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self._glow_effect is None or self.graphicsEffect() is None:
            self._glow_effect = _make_glow_effect(self, radius=0)
            self.setGraphicsEffect(self._glow_effect)
        _fade_effect(self, self._glow_effect, 13, 140)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.graphicsEffect() is not None:
            _fade_effect(self, self.graphicsEffect(), 0, 220)


# ============================================================ 切换闪光复选框
class GlowCheckBox(QCheckBox):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # 预闪：按下即辉光，切换后由 toggled 收尾
        self._flash(10)

    def _flash(self, start_blur):
        eff = _make_glow_effect(self, radius=start_blur)
        self.setGraphicsEffect(eff)
        _fade_effect(self, eff, 0, 320)


# ============================================================ HUD 分组面板
class HudGroupBox(QGroupBox):
    """深空 HUD 面板：半透明底 + 角括号 + 发光标题点。完全自绘。"""

    BRACKET = 16  # 角括号长度

    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def setLayout(self, layout):
        super().setLayout(layout)
        # 为标题区留出顶部空间（原 QFormLayout 的 8px 顶距不够）
        m = layout.contentsMargins()
        layout.setContentsMargins(max(m.left(), 16), 42, max(m.right(), 16),
                                  max(m.bottom(), 14))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = theme.pal()
        rect = self.rect().adjusted(1, 6, -1, -1)

        # 面板底 + 光晕 + 边框
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 10, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(pal["hud_fill"]))
        p.drawPath(path)

        halo = QPainterPath()
        halo.addRoundedRect(QRectF(rect.adjusted(-1, -1, 1, 1)), 12, 12)
        p.setBrush(QBrush(pal["hud_halo"]))
        p.drawPath(halo)

        p.setPen(QPen(pal["hud_border"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # 四角括号
        pen = QPen(pal["hud_bracket"], 2)
        p.setPen(pen)
        L = self.BRACKET
        x0, y0 = rect.x(), rect.y() + 4
        x1, y1 = rect.right(), rect.bottom()
        p.drawLine(QPointF(x0 + 1, y0 + L), QPointF(x0 + 1, y0 + 1))
        p.drawLine(QPointF(x0 + 1, y0 + 1), QPointF(x0 + L, y0 + 1))
        p.drawLine(QPointF(x1 - L, y0 + 1), QPointF(x1 - 1, y0 + 1))
        p.drawLine(QPointF(x1 - 1, y0 + 1), QPointF(x1 - 1, y0 + L))
        p.drawLine(QPointF(x0 + 1, y1 - L), QPointF(x0 + 1, y1 - 1))
        p.drawLine(QPointF(x0 + 1, y1 - 1), QPointF(x0 + L, y1 - 1))
        p.drawLine(QPointF(x1 - L, y1 - 1), QPointF(x1 - 1, y1 - 1))
        p.drawLine(QPointF(x1 - 1, y1 - L), QPointF(x1 - 1, y1 - 1))

        # 标题：发光点 + 文字
        title = self.title()
        if title:
            cy = y0 + 15
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(pal["accent"]))
            p.drawEllipse(QPointF(x0 + 20, cy), 3.2, 3.2)
            p.setBrush(QBrush(QColor(pal["accent"].red(), pal["accent"].green(),
                                     pal["accent"].blue(), 60)))
            p.drawEllipse(QPointF(x0 + 20, cy), 6.5, 6.5)

            font = QFont()
            font.setPointSize(11)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QPen(pal["accent"]))
            p.drawText(int(x0 + 32), int(cy + 6), title)
        p.end()


# ============================================================ 科幻标签页
class SciFiTabBar(QTabBar):
    """芯片式标签：悬停渐变、点击闪屏、滑动指示条。完全自绘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setMouseTracking(True)
        self._hover_index = -1
        self._hover_alpha = 0.0
        self._flash_index = -1
        self._flash_alpha = 0.0
        self._ind_x = -1.0

        self._hover_anim = QPropertyAnimation(self, b"hoverAlpha", self)
        self._hover_anim.setDuration(130)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._flash_anim = QPropertyAnimation(self, b"flashAlpha", self)
        self._flash_anim.setDuration(240)
        self._flash_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._ind_anim = QPropertyAnimation(self, b"indicatorX", self)
        self._ind_anim.setDuration(190)
        self._ind_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.currentChanged.connect(self._on_current_changed)

    def showEvent(self, event):
        super().showEvent(event)
        self._hide_scroll_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._hide_scroll_buttons()

    def _hide_scroll_buttons(self):
        # Qt5 的 QTabBar 溢出滚动按钮在 setUsesScrollButtons(False) 后仍可能残留显示，
        # 强制隐藏（我们的标签页永远不会溢出）
        for b in self.findChildren(QToolButton):
            b.hide()

    # ---- 动画属性 ----
    def getHoverAlpha(self):
        return self._hover_alpha

    def setHoverAlpha(self, v):
        self._hover_alpha = v
        self.update()

    hoverAlpha = pyqtProperty(float, getHoverAlpha, setHoverAlpha)

    def getFlashAlpha(self):
        return self._flash_alpha

    def setFlashAlpha(self, v):
        self._flash_alpha = v
        self.update()

    flashAlpha = pyqtProperty(float, getFlashAlpha, setFlashAlpha)

    def getIndicatorX(self):
        return self._ind_x

    def setIndicatorX(self, v):
        self._ind_x = v
        self.update()

    indicatorX = pyqtProperty(float, getIndicatorX, setIndicatorX)

    # ---- 行为 ----
    def tabSizeHint(self, index):
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self.tabText(index)) + 52
        return QSize(max(110, w), 44)

    def _on_current_changed(self, index):
        r = self.tabRect(index)
        if r.width() == 0:
            self._ind_x = -1
            return
        target = r.center().x()
        if self._ind_x < 0:
            self._ind_x = target
            self.update()
            return
        self._ind_anim.stop()
        self._ind_anim.setStartValue(self._ind_x)
        self._ind_anim.setEndValue(target)
        self._ind_anim.start()

    def _tab_at(self, pos):
        for i in range(self.count()):
            if self.tabRect(i).contains(pos):
                return i
        return -1

    def enterEvent(self, event):
        super().enterEvent(event)
        idx = self._tab_at(self.mapFromGlobal(self.cursor().pos()))
        self._set_hover(idx)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._set_hover(-1)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._set_hover(self._tab_at(event.pos()))

    def _set_hover(self, idx):
        if idx == self._hover_index:
            return
        self._hover_index = idx
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(1.0 if idx >= 0 else 0.0)
        self._hover_anim.start()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        idx = self._tab_at(event.pos())
        if idx >= 0:
            self._flash_index = idx
            self._flash_anim.stop()
            self._flash_anim.setStartValue(1.0)
            self._flash_anim.setEndValue(0.0)
            self._flash_anim.start()

    # ---- 绘制 ----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = theme.pal()

        for i in range(self.count()):
            r = QRectF(self.tabRect(i)).adjusted(2, 4, -2, 0)
            selected = (i == self.currentIndex())
            hovered = (i == self._hover_index)

            # 底色芯片（未选中也要在星图上足够醒目）
            if selected:
                fill = QColor(pal["accent"].red(), pal["accent"].green(),
                              pal["accent"].blue(), 52)
                text_color = pal["accent"]
                stroke = pal["hud_border"]
            else:
                base = QColor(pal["chip_fill"].red(), pal["chip_fill"].green(),
                              pal["chip_fill"].blue(), 255)
                if hovered:
                    a = self._hover_alpha
                    fill = QColor(
                        int(base.red() * (1 - a) + pal["accent"].red() * a * 0.22),
                        int(base.green() * (1 - a) + pal["accent"].green() * a * 0.22),
                        int(base.blue() * (1 - a) + pal["accent"].blue() * a * 0.22),
                    )
                    text_color = QColor(
                        int(pal["dim"].red() * (1 - a) + pal["text"].red() * a),
                        int(pal["dim"].green() * (1 - a) + pal["text"].green() * a),
                        int(pal["dim"].blue() * (1 - a) + pal["text"].blue() * a),
                    )
                else:
                    fill = base
                    text_color = QColor(
                        min(255, pal["dim"].red() + 30),
                        min(255, pal["dim"].green() + 30),
                        min(255, pal["dim"].blue() + 30))
                stroke = QColor(pal["accent"].red(), pal["accent"].green(),
                                pal["accent"].blue(), 46)

            path = QPainterPath()
            path.addRoundedRect(r, 9, 9)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(fill))
            p.drawPath(path)

            # 点击闪屏
            if i == self._flash_index and self._flash_alpha > 0.01:
                flash = QColor(pal["accent"].red(), pal["accent"].green(),
                               pal["accent"].blue(), int(110 * self._flash_alpha))
                p.setBrush(QBrush(flash))
                p.drawPath(path)

            # 描边
            p.setPen(QPen(stroke, 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

            # 文字（居中）
            title = self.tabText(i)
            font = QFont()
            font.setPointSize(10)
            font.setBold(selected)
            p.setFont(font)
            fm = QFontMetrics(font)
            tx = r.center().x() - fm.horizontalAdvance(title) / 2
            p.setPen(QPen(text_color))
            p.drawText(QPointF(tx, r.center().y() + 5), title)

        # 滑动指示条
        if self._ind_x >= 0:
            r = QRectF(self.tabRect(self.currentIndex()))
            if r.width() > 0:
                w = min(72.0, r.width() * 0.55)
                y = self.height() - 5.0
                halo = QPainterPath()
                halo.addRoundedRect(QRectF(self._ind_x - w / 2 - 3, y - 2, w + 6, 7), 4, 4)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(pal["accent"].red(), pal["accent"].green(),
                                         pal["accent"].blue(), 50)))
                p.drawPath(halo)
                bar = QPainterPath()
                bar.addRoundedRect(QRectF(self._ind_x - w / 2, y, w, 3), 2, 2)
                p.setBrush(QBrush(pal["accent"]))
                p.drawPath(bar)
        p.end()


class SciFiTabWidget(QWidget):
    """QTabWidget 的即插即用替代：SciFiTabBar + 自绘视窗面板 + QStackedLayout。"""

    currentChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bar = SciFiTabBar(self)
        self._stack = QStackedLayout()
        self._stack.setContentsMargins(10, 8, 10, 10)
        self._stack.setSpacing(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(2)
        layout.addWidget(self._bar)
        layout.addLayout(self._stack, stretch=1)

        self._bar.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index):
        self._stack.setCurrentIndex(index)
        self.currentChanged.emit(index)

    # ---- QTabWidget 兼容 API ----
    def addTab(self, widget, title):
        self._stack.addWidget(widget)
        return self._bar.addTab(title)

    def count(self):
        return self._bar.count()

    def setCurrentIndex(self, index):
        self._bar.setCurrentIndex(index)

    def currentIndex(self):
        return self._bar.currentIndex()

    def currentWidget(self):
        return self._stack.currentWidget()

    def widget(self, index):
        return self._stack.widget(index)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = theme.pal()
        # 面板区域 = 标签栏以下的容器区域（不依赖 layout.geometry()，其值不可靠）
        geo = self.rect().adjusted(8, 50, -8, -8)
        if geo.width() <= 0 or geo.height() <= 0:
            p.end()
            return
        rect = QRectF(geo)

        halo = QPainterPath()
        halo.addRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(pal["pane_halo"]))
        p.drawPath(halo)

        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.setBrush(QBrush(pal["pane_fill"]))
        p.drawPath(path)
        p.setPen(QPen(pal["pane_border"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # 顶部中央小高光
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        grad.setColorAt(0.0, QColor(pal["accent"].red(), pal["accent"].green(), pal["accent"].blue(), 0))
        grad.setColorAt(0.5, QColor(pal["accent"].red(), pal["accent"].green(), pal["accent"].blue(), 90))
        grad.setColorAt(1.0, QColor(pal["accent"].red(), pal["accent"].green(), pal["accent"].blue(), 0))
        pen = QPen(QBrush(grad), 1.5)
        p.setPen(pen)
        p.drawLine(QPointF(rect.left() + 14, rect.top()), QPointF(rect.right() - 14, rect.top()))
        p.end()
