"""Widgets de visualizacao: waterfall, espectro, barra de slot e bussola."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..waterfall_model import WaterfallModel
from .theme import C, DARK, FONT_MONO, fade

SECONDS_PER_COLUMN = 0.05  # hop do WaterfallModel


def _mono(size: int, bold: bool = False) -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(size)
    f.setBold(bold)
    return f


PAD_LEFT = 46
PAD_RIGHT = 10


class WaterfallWidget(QWidget):
    """Waterfall vertical: frequencia no eixo X, tempo descendo.

    E' o mesmo eixo do espectro logo acima, entao o pico do espectro fica
    alinhado com a marca do sinal na cachoeira.
    """

    freqClicked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model: WaterfallModel | None = None
        self.tx_freq = 1500.0
        self.markers: list[tuple[float, str, float]] = []
        self.elapsed = 0.0
        self.slot_seconds = 15.0
        self.decoding = False
        self.setMinimumSize(420, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # -- dados ---------------------------------------------------------
    def set_model(self, model: WaterfallModel) -> None:
        self.model = model

    def set_tx_freq(self, hz: float) -> None:
        self.tx_freq = hz
        self.update()

    def set_markers(self, markers: list[tuple[float, str, float]]) -> None:
        self.markers = markers

    def set_elapsed(self, seconds: float, decoding: bool = False) -> None:
        self.elapsed = seconds
        self.decoding = decoding

    # -- geometria -----------------------------------------------------
    def _plot_rect(self) -> QRect:
        return QRect(PAD_LEFT, 10,
                     max(10, self.width() - PAD_LEFT - PAD_RIGHT),
                     max(10, self.height() - 36))

    def _freq_x(self, hz: float) -> float:
        r = self._plot_rect()
        if not self.model:
            return float(r.left())
        return r.left() + self.model.freq_to_frac(hz) * (r.width() - 1)

    def _px_to_freq(self, x: int) -> float:
        r = self._plot_rect()
        frac = min(max((x - r.left()) / max(1, r.width() - 1), 0.0), 1.0)
        if not self.model:
            return 0.0
        return self.model.f_min + frac * (self.model.f_max - self.model.f_min)

    def _age_y(self, age: float) -> float:
        """Segundos atras -> posicao vertical (0 s no topo)."""
        r = self._plot_rect()
        if not self.model:
            return r.top()
        rows = max(1, self.model.width)
        return r.top() + (age / SECONDS_PER_COLUMN) * (r.height()/rows)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            r = self._plot_rect()
            if r.contains(ev.position().toPoint()):
                self.freqClicked.emit(self._px_to_freq(int(ev.position().x())))
        super().mousePressEvent(ev)

    # -- desenho -------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(DARK["bg"]))
        r = self._plot_rect()

        if self.model is not None and self.model.data.any():
            rgb = self.model.rgb()          # (tempo, frequencia, 3)
            h, w, _ = rgb.shape
            # guardar a referencia: QImage nao copia o buffer do numpy
            self._rgb_ref = rgb
            img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            p.drawImage(r, img)
        else:
            p.setPen(QPen(QColor(DARK["text_faint"])))
            p.setFont(_mono(11))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       "aguardando audio do receptor")

        # fronteiras de slot (linhas horizontais) + rotulos de tempo
        p.setFont(_mono(9))
        k = 1
        while True:
            age = k * self.slot_seconds
            y = int(self._age_y(age))
            if y > r.bottom():
                break
            p.setPen(QPen(QColor(255, 255, 255, 45), 1, Qt.PenStyle.DashLine))
            p.drawLine(r.left(), y, r.right(), y)
            p.setPen(QPen(QColor(DARK["text_faint"])))
            p.drawText(4, y + 3, f"-{int(age)}s")
            k += 1

        # marcadores de decode: alinhados com o pico do espectro
        p.setFont(_mono(9, True))
        for hz, label, dt in self.markers:
            if not label:
                continue
            age = self.elapsed - dt
            if age < 0:
                continue
            my = self._age_y(age)
            if not (r.top() - 2 < my < r.bottom() + 2):
                continue
            x = int(self._freq_x(hz))
            p.setPen(QPen(QColor(25, 211, 155, 230)))
            p.drawLine(x, int(my) - 4, x, int(my) + 4)
            tx = x + 6
            if tx > r.right() - 58:
                tx = x - 6 - p.fontMetrics().horizontalAdvance(label[:9])
            p.drawText(tx, int(my) + 3, label[:9])

        # marcador de TX: linha vertical, como no espectro
        x = int(self._freq_x(self.tx_freq))
        p.setPen(QPen(QColor(255, 93, 93, 210), 1, Qt.PenStyle.DashLine))
        p.drawLine(x, r.top(), x, r.bottom())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 93, 93))
        p.drawPolygon(QPolygonF([
            QPointF(x - 5, r.top() + 1), QPointF(x + 5, r.top() + 1),
            QPointF(x, r.top() + 8),
        ]))

        # eixo de frequencia na base (compartilhado com o espectro)
        p.setBrush(Qt.BrushStyle.NoBrush)   # nao herdar o brush do marcador
        p.setPen(QPen(QColor(DARK["border2"])))
        p.drawRect(r)
        p.setFont(_mono(9))
        step = 500 if (self.model and (self.model.f_max - self.model.f_min) > 1400) else 250
        if self.model:
            f = int(math.ceil(self.model.f_min / step) * step)
            while f <= self.model.f_max:
                xx = int(self._freq_x(float(f)))
                p.setPen(QPen(QColor(255, 255, 255, 40), 1))
                p.drawLine(xx, r.bottom(), xx, r.bottom() - 5)
                p.setPen(QPen(QColor(DARK["text_dim"])))
                p.drawText(xx - 12, r.bottom() + 15, f"{f}")
                f += step

        if self.decoding:
            p.setPen(QPen(QColor(DARK["accent"])))
            p.setFont(_mono(9))
            p.drawText(r.left() + 4, r.bottom() - 6, "decodificando...")
        p.end()


class SpectrumWidget(QWidget):
    """Espectro horizontal: frequencia em X, alinhado com o waterfall."""

    freqClicked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model: WaterfallModel | None = None
        self.tx_freq = 1500.0
        self.setFixedHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_model(self, model: WaterfallModel) -> None:
        self.model = model

    def set_tx_freq(self, hz: float) -> None:
        self.tx_freq = hz
        self.update()

    def _plot_rect(self) -> QRect:
        return QRect(PAD_LEFT, 8,
                     max(10, self.width() - PAD_LEFT - PAD_RIGHT),
                     max(10, self.height() - 18))

    def _freq_x(self, hz: float) -> float:
        r = self._plot_rect()
        if not self.model:
            return float(r.left())
        return r.left() + self.model.freq_to_frac(hz) * (r.width() - 1)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if self.model is None:
            return
        r = self._plot_rect()
        frac = min(max((ev.position().x() - r.left()) / max(1, r.width() - 1), 0.0), 1.0)
        self.freqClicked.emit(
            self.model.f_min + frac * (self.model.f_max - self.model.f_min))

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(DARK["panel"]))
        if self.model is None or self.model.levels.size < 2:
            p.end()
            return
        r = self._plot_rect()
        lo, hi = self.model.lo_db, self.model.hi_db
        span = max(1.0, hi - lo)
        # suavizacao leve: realca o sinal contra o ruido bin a bin
        levels = np.convolve(self.model.levels, np.ones(3) / 3.0, mode="same")
        n = int(levels.size)

        def y_of(v: float) -> float:
            t = (v - lo) / span
            return r.bottom() - min(max(t, 0.0), 1.0) * r.height()

        pts = [QPointF(float(self._freq_x(self.model.f_min)) +
                       i / (n - 1) * (r.width() - 1),
                       y_of(float(levels[i]))) for i in range(n)]

        poly = QPolygonF([QPointF(r.left(), r.bottom())] + pts +
                         [QPointF(r.right(), r.bottom())])
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        grad.setColorAt(0.0, QColor(25, 211, 155, 120))
        grad.setColorAt(1.0, QColor(25, 211, 155, 8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawPolygon(poly)
        p.setPen(QPen(QColor(25, 211, 155), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(pts))

        # grade vertical (mesmas divisoes do waterfall)
        p.setFont(_mono(9))
        step = 500 if (self.model.f_max - self.model.f_min) > 1400 else 250
        f = int(math.ceil(self.model.f_min / step) * step)
        while f <= self.model.f_max:
            xx = self._freq_x(float(f))
            p.setPen(QPen(QColor(255, 255, 255, 22), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(xx, r.top()), QPointF(xx, r.bottom()))
            f += step

        # linha de TX
        xx = self._freq_x(self.tx_freq)
        p.setPen(QPen(QColor(255, 93, 93), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(xx, r.top()), QPointF(xx, r.bottom()))
        p.setPen(QPen(QColor(255, 140, 140)))
        p.setFont(_mono(9, True))
        p.drawText(int(min(xx + 4, r.right() - 54)), r.top() + 10,
                   f"{self.tx_freq:.0f} Hz")

        p.setPen(QPen(QColor(DARK["border2"])))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        p.end()


class SlotBar(QWidget):
    """Linha do tempo do slot: janela de TX, progresso e paridade."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fraction = 0.0
        self.slot_seconds = 15.0
        self.tx_start = 0.5
        self.tx_span = 12.64
        self.parity = 0
        self.setFixedHeight(26)

    def set_state(self, fraction: float, tx_start: float, slot_seconds: float,
                  parity: int = 0) -> None:
        self.fraction = min(max(fraction, 0.0), 1.0)
        self.tx_start = tx_start
        self.slot_seconds = max(slot_seconds, 1.0)
        self.parity = parity
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(0, 7, -1, -7)
        slot = max(self.slot_seconds, 1.0)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["panel2"]))
        p.drawRoundedRect(r, 4, 4)

        # janela de transmissao (sempre visivel, abaixo do progresso)
        x0 = r.left() + int(self.tx_start / slot * r.width())
        x1 = r.left() + int((self.tx_start + self.tx_span) / slot * r.width())
        p.setBrush(QColor(74, 158, 255, 70))
        p.drawRect(QRect(x0, r.top(), max(1, x1 - x0), r.height()))
        p.setPen(QPen(QColor(74, 158, 255, 120), 1))
        p.drawLine(x0, r.top(), x0, r.bottom())

        # progresso: faixa suave + cabeca luminosa
        w = int(self.fraction * r.width())
        if w > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(25, 211, 155, 78))
            p.drawRect(QRect(r.left(), r.top(), w, r.height()))
            p.setBrush(QColor(C["accent"]))
            p.drawRect(QRect(r.left(), r.top(), min(w, 2), r.height()))

        # marcas de 5 s
        p.setPen(QPen(fade("text", 28), 1))
        t = 5.0
        while t < slot:
            x = r.left() + int(t / slot * r.width())
            p.drawLine(x, r.bottom() - 4, x, r.bottom())
            t += 5.0

        # cabeca do progresso
        hx = r.left() + w
        p.setPen(QPen(QColor(C["accent"]), 2))
        p.drawLine(hx, r.top() + 2, hx, r.bottom() - 2)

        p.setPen(QPen(QColor(C["border2"])))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 4, 4)

        p.setFont(_mono(9, True))
        p.setPen(QPen(QColor(C["text"])))
        p.drawText(r.left() + 8, r.center().y() + 4,
                   "PAR" if self.parity % 2 == 0 else "IMPAR")
        p.setPen(QPen(QColor(C["text_dim"])))
        p.drawText(r.right() - 46, r.center().y() + 4,
                   f"{slot * (1.0 - self.fraction):4.1f}s")
        p.end()


class CompassWidget(QWidget):
    """Bussola compacta com o azimute do DX."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bearing: float | None = None
        self.setFixedSize(74, 74)

    def set_bearing(self, bearing: float | None) -> None:
        self.bearing = bearing
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy, rad = self.width() / 2, self.height() / 2, min(self.width(), self.height()) / 2 - 4

        p.setBrush(QColor(C["panel2"]))
        p.setPen(QPen(QColor(C["border2"])))
        p.drawEllipse(QPointF(cx, cy), rad, rad)

        p.setFont(_mono(8))
        for ang, lbl in ((0, "N"), (90, "L"), (180, "S"), (270, "O")):
            a = math.radians(ang - 90)
            p.setPen(QPen(QColor(C["text_faint"])))
            p.drawText(QPointF(cx + math.cos(a) * (rad - 9) - 3,
                               cy + math.sin(a) * (rad - 9) + 3), lbl)

        if self.bearing is not None:
            a = math.radians(self.bearing - 90)
            tip = QPointF(cx + math.cos(a) * (rad - 12), cy + math.sin(a) * (rad - 12))
            left = QPointF(cx + math.cos(a + 2.5) * 7, cy + math.sin(a + 2.5) * 7)
            right = QPointF(cx + math.cos(a - 2.5) * 7, cy + math.sin(a - 2.5) * 7)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["accent"]))
            p.drawPolygon(QPolygonF([tip, left, right]))
            p.setBrush(QColor(C["red"]))
            p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)
        p.end()
