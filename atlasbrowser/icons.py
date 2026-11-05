"""Toolbar icons drawn with QPainter on a 20x20 grid, so every button shares one line weight and style."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

FG = "#c9cfdb"
DISABLED = "#575d6e"
ACCENT = "#5FE0CF"   # Pelagic surface teal
BADGE = "#1B8C9A"


def _path(points, close=False) -> QPainterPath:
    p = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        p.lineTo(QPointF(*pt))
    if close:
        p.closeSubpath()
    return p


def _star(cx=10, cy=10.4, r1=7.6, r2=3.4) -> QPainterPath:
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = r1 if i % 2 == 0 else r2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return _path(pts, close=True)


def _draw(name: str, p: QPainter, color: QColor):
    pen = QPen(color, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if name == "back":
        p.drawPath(_path([(16, 10), (4.5, 10)]))
        p.drawPath(_path([(9.5, 5), (4.5, 10), (9.5, 15)]))
    elif name == "forward":
        p.drawPath(_path([(4, 10), (15.5, 10)]))
        p.drawPath(_path([(10.5, 5), (15.5, 10), (10.5, 15)]))
    elif name == "reload":
        p.drawArc(QRectF(4, 4, 12, 12), 60 * 16, 290 * 16)
        p.drawPath(_path([(12.6, 2.9), (13.4, 5.2), (11, 6.1)]))
    elif name in ("stop", "close"):
        k = 5 if name == "stop" else 6
        p.drawLine(QPointF(k, k), QPointF(20 - k, 20 - k))
        p.drawLine(QPointF(20 - k, k), QPointF(k, 20 - k))
    elif name == "home":
        p.drawPath(_path([(3, 10), (10, 3.6), (17, 10)]))
        p.drawPath(_path([(5.3, 8.4), (5.3, 16.5), (14.7, 16.5), (14.7, 8.4)]))
    elif name == "star":
        p.drawPath(_star())
    elif name == "star-filled":
        p.setPen(QPen(QColor(ACCENT), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(ACCENT))
        p.drawPath(_star())
    elif name == "gear":
        p.setPen(QPen(color, 2.6, Qt.SolidLine, Qt.FlatCap))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(10 + 5.6 * math.cos(a), 10 + 5.6 * math.sin(a)),
                       QPointF(10 + 8.2 * math.cos(a), 10 + 8.2 * math.sin(a)))
        p.setPen(pen)
        p.drawEllipse(QPointF(10, 10), 5.4, 5.4)
        p.drawEllipse(QPointF(10, 10), 2.1, 2.1)
    elif name == "more":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for y in (4.5, 10, 15.5):
            p.drawEllipse(QPointF(10, y), 1.55, 1.55)
    elif name == "up":
        p.drawPath(_path([(5, 12.5), (10, 7.5), (15, 12.5)]))
    elif name == "down":
        p.drawPath(_path([(5, 7.5), (10, 12.5), (15, 7.5)]))
    elif name == "search":
        p.drawEllipse(QPointF(8.6, 8.6), 4.6, 4.6)
        p.drawLine(QPointF(12.1, 12.1), QPointF(16, 16))
    elif name == "history":
        p.drawEllipse(QPointF(10, 10), 6.8, 6.8)
        p.drawPath(_path([(10, 6), (10, 10), (12.8, 11.8)]))
    elif name == "globe":
        p.drawEllipse(QPointF(10, 10), 6.8, 6.8)
        p.drawEllipse(QPointF(10, 10), 2.9, 6.8)
        p.drawLine(QPointF(3.2, 10), QPointF(16.8, 10))
    elif name in ("audible", "muted"):
        p.drawPath(_path([(3.5, 8), (6.5, 8), (10.5, 4.5), (10.5, 15.5), (6.5, 12), (3.5, 12)], close=True))
        if name == "audible":
            p.drawArc(QRectF(9, 6.5, 6, 7), -60 * 16, 120 * 16)
            p.drawArc(QRectF(9, 4, 9, 12), -60 * 16, 120 * 16)
        else:
            p.drawLine(QPointF(13, 8), QPointF(17, 12))
            p.drawLine(QPointF(17, 8), QPointF(13, 12))
    elif name == "minimize":
        p.setPen(QPen(color, 1.2))
        p.drawLine(QPointF(5, 10.5), QPointF(15, 10.5))
    elif name == "restore":   # two overlapping windows, like Windows' restore button
        p.setPen(QPen(color, 1.2))
        p.drawRect(QRectF(5, 7, 8, 8))
        p.drawPath(_path([(7, 7), (7, 5), (15, 5), (15, 13), (13, 13)]))
    elif name == "window-close":
        p.setPen(QPen(color, 1.2))
        p.drawLine(QPointF(5, 5), QPointF(15, 15))
        p.drawLine(QPointF(15, 5), QPointF(5, 15))
    elif name == "folder":
        p.drawPath(_path([(2.8, 5.2), (7.6, 5.2), (9.2, 6.9), (17.2, 6.9), (17.2, 15.4), (2.8, 15.4)], close=True))
    elif name == "plus":
        p.drawLine(QPointF(10, 4.5), QPointF(10, 15.5))
        p.drawLine(QPointF(4.5, 10), QPointF(15.5, 10))
    elif name == "ai":   # the round Pelagic logo as a monochrome glyph: a surface wave over a glowing orb
        p.setPen(QPen(color, 1.5))
        p.drawEllipse(QPointF(10, 10), 8.2, 8.2)
        p.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(_wave(7.2))
        p.setPen(Qt.NoPen)
        glow = QColor(color)
        glow.setAlpha(60)
        p.setBrush(glow)
        p.drawEllipse(QPointF(11.4, 12.9), 3.7, 3.7)
        p.setBrush(color)
        p.drawEllipse(QPointF(11.4, 12.9), 2.0, 2.0)
        p.drawEllipse(QPointF(6.4, 13.8), 0.9, 0.9)


def _wave(y) -> QPainterPath:
    w = QPainterPath(QPointF(3, y + 1))
    w.cubicTo(QPointF(5.2, y - 1.2), QPointF(7.6, y - 1.2), QPointF(10, y + 0.6))
    w.cubicTo(QPointF(12.4, y + 2.2), QPointF(14.8, y + 2.2), QPointF(17, y))
    return w


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 20, size / 20)
    _draw(name, p, QColor(color))
    p.end()
    return pix


def icon(name: str, color: str = FG) -> QIcon:
    ic = QIcon()
    for size in (20, 40):
        ic.addPixmap(_pixmap(name, color, size), QIcon.Normal)
        ic.addPixmap(_pixmap(name, DISABLED, size), QIcon.Disabled)
    return ic


def with_badge(base: QIcon, count: int) -> QIcon:
    """The icon with a small count bubble in its lower-right corner (like Chrome's extension badges)."""
    if not count:
        return base
    text = "99+" if count > 99 else str(count)
    ic = QIcon()
    for size in (20, 40):
        k = size / 20
        pix = base.pixmap(size, size)
        pix = pix.copy() if not pix.isNull() else QPixmap(size, size)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont("Segoe UI")
        font.setPixelSize(round(7.5 * k))
        font.setBold(True)
        p.setFont(font)
        w = max(9 * k, p.fontMetrics().horizontalAdvance(text) + 4 * k)
        r = QRectF(size - w, size - 9 * k, w, 9 * k)
        p.setPen(QPen(QColor("#14161c"), 1.2 * k))
        p.setBrush(QColor(BADGE))
        p.drawRoundedRect(r, 4.5 * k, 4.5 * k)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignCenter, text)
        p.end()
        ic.addPixmap(pix)
    return ic
