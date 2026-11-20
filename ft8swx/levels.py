"""Medidores de nivel de audio (dBFS): RMS com release suave, pico retido e aviso de clip.

Sem Qt: a janela alimenta com blocos de audio e le level/peak/clip para desenhar.
"""

from __future__ import annotations

import numpy as np

FLOOR_DB = -60.0       # base da escala da barra
CLIP_DB = -1.0         # pico acima disso conta como saturacao


def _db(v: float) -> float:
    return max(FLOOR_DB, 20.0 * float(np.log10(max(v, 1e-9))))


def block_levels(x: np.ndarray) -> tuple[float, float]:
    """(rms_dbfs, pico_dbfs) de um bloco de audio com amostras em -1..1."""
    if x is None or x.size == 0:
        return FLOOR_DB, FLOOR_DB
    x = np.asarray(x, dtype=np.float32)
    return _db(float(np.sqrt(np.mean(x * x)))), _db(float(np.max(np.abs(x))))


def tx_envelope(wave: np.ndarray, gain: float, rate: int = 12000,
                chunk_s: float = 0.05) -> list[tuple[float, float]]:
    """Nivel por trecho do audio de TX, ja com o ganho e o limitador do play_12k."""
    y = np.asarray(wave, dtype=np.float32) * float(gain)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    n = max(1, int(rate * chunk_s))
    return [block_levels(y[i:i + n]) for i in range(0, y.size, n)]


class LevelMeter:
    FALL_DB_S = 24.0      # queda do nivel
    PEAK_FALL_DB_S = 12.0
    HOLD_S = 1.5          # tempo que o pico fica parado
    CLIP_S = 2.0          # tempo que o aviso de CLIP fica aceso

    def __init__(self) -> None:
        self.level = FLOOR_DB
        self.peak = FLOOR_DB
        self._t: float | None = None
        self._peak_t = 0.0
        self._clip_until = 0.0

    def push(self, rms_db: float, peak_db: float, now: float) -> None:
        dt = 0.0 if self._t is None else max(0.0, now - self._t)
        self._t = now
        self.level = max(rms_db, self.level - self.FALL_DB_S * dt, FLOOR_DB)
        if peak_db >= self.peak:
            self.peak = peak_db
            self._peak_t = now
        elif now - self._peak_t > self.HOLD_S:
            self.peak = max(peak_db, self.peak - self.PEAK_FALL_DB_S * dt, FLOOR_DB)
        if peak_db >= CLIP_DB:
            self._clip_until = now + self.CLIP_S

    def decay(self, now: float) -> None:
        self.push(FLOOR_DB, FLOOR_DB, now)

    def clip(self, now: float) -> bool:
        return now < self._clip_until

    def reset(self) -> None:
        self.__init__()
