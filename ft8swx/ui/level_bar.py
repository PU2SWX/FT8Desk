"""Barra horizontal de nivel de audio (dBFS) com zonas, pico retido e LED de CLIP."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..levels import FLOOR_DB
from .theme import C, FONT_MONO


class LevelBar(QWidget):
    def __init__(self, label: str, low: float = -45.0, high: float = -15.0, tip: str = "", parent=None):
        super().__init__(parent)
        self.label, self.low, self.high = label, low, high
        self.level, self.peak, self.clip = FLOOR_DB, FLOOR_DB, False
        self.setFixedHeight(14)
        self.setMinimumWidth(190)
        self.setMaximumWidth(380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(tip)

    def set_state(self, level: float, peak: float, clip: bool) -> None:
        if (level, peak, clip) != (self.level, self.peak, self.clip):
            self.level, self.peak, self.clip = level, peak, clip
            self.update()

    @staticmethod
    def _frac(db: float) -> float:
        return max(0.0, min(1.0, (db - FLOOR_DB) / -FLOOR_DB))

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        f.setBold(True)
        p.setFont(f)
        w, h = self.width(), self.height()
        p.setPen(QColor(C["text_faint"]))
        p.drawText(QRectF(0, 0, 20, h), Qt.AlignmentFlag.AlignVCenter, self.label)

        x0, x1 = 22.0, w - 44.0                    # barra; a direita ficam LED e valor
        bar = QRectF(x0, 2, max(10.0, x1 - x0), h - 4)
        p.setPen(QPen(QColor(C["border2"]), 1))
        p.setBrush(QColor(C["panel3"]))
        p.drawRoundedRect(bar, 3, 3)

        if self.level > FLOOR_DB + 0.5:
            ok = self.low <= self.level <= self.high
            col = QColor(C["red"] if self.clip else C["accent"] if ok else C["amber"])
            fill = QRectF(bar.x() + 1, bar.y() + 1,
                          (bar.width() - 2) * self._frac(self.level), bar.height() - 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(fill, 2, 2)

        for db in (self.low, self.high):          # limites da faixa boa
            x = bar.x() + bar.width() * self._frac(db)
            p.setPen(QPen(QColor(C["text_faint"]), 1))
            p.drawLine(int(x), int(bar.y()) + 1, int(x), int(bar.bottom()) - 1)
        if self.peak > FLOOR_DB + 0.5:             # pico retido
            x = bar.x() + bar.width() * self._frac(self.peak)
            p.setPen(QPen(QColor(C["text"]), 2))
            p.drawLine(int(x), int(bar.y()), int(x), int(bar.bottom()))

        led = QRectF(x1 + 5, 3, 8, h - 6)          # LED de CLIP
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["red"]) if self.clip else QColor(C["border2"]))
        p.drawRoundedRect(led, 2, 2)
        mono = QFont(FONT_MONO.split(",")[0].strip('" '))
        mono.setPointSizeF(7.5)
        p.setFont(mono)
        p.setPen(QColor(C["text_dim"]))
        txt = "--" if self.level <= FLOOR_DB + 0.5 else f"{self.level:.0f}"
        p.drawText(QRectF(x1 + 14, 0, 30, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, txt)
