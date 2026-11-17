"""Modelo de waterfall (numpy puro) e widgets de espectro."""

from __future__ import annotations

import numpy as np


def build_palette() -> np.ndarray:
    """LUT 256x3: preto -> azul -> ciano -> amarelo -> vermelho."""
    # pe' mais escuro: o ruido de fundo fica quase preto e so' os sinais
    # acendem -- e' o que deixa um sinal de -20 dB visivel num mar de ruido
    stops = [
        (0.00, (0, 0, 6)),
        (0.28, (0, 2, 26)),
        (0.44, (0, 14, 70)),
        (0.58, (0, 70, 150)),
        (0.70, (0, 175, 190)),
        (0.80, (120, 232, 120)),
        (0.89, (255, 214, 46)),
        (0.95, (255, 110, 20)),
        (1.00, (255, 255, 255)),
    ]
    lut = np.zeros((256, 3), dtype=np.uint8)
    xs = np.array([s[0] for s in stops]) * 255.0
    for ch in range(3):
        ys = np.array([s[1][ch] for s in stops], dtype=float)
        lut[:, ch] = np.interp(np.arange(256), xs, ys).astype(np.uint8)
    return lut


PALETTE = build_palette()


class WaterfallModel:
    """Matriz [freq, tempo] de magnitudes em escala 0..255."""

    def __init__(self, fs: int = 12000, width: int = 900,
                 f_min: float = 200.0, f_max: float = 3000.0,
                 nfft: int = 2048, db_range: float = 42.0):
        self.fs = fs
        self.width = width
        self.f_min = f_min
        self.f_max = f_max
        self.nfft = nfft
        self.db_range = db_range          # faixa dinamica exibida, em dB
        self.floor_db: float | None = None  # piso de ruido medido (adaptativo)
        self.lo_db = -120.0
        self.hi_db = -80.0
        self.window = np.hanning(nfft).astype(np.float32)
        self._tail = np.zeros(0, dtype=np.float32)   # amostras ainda nao usadas

        freqs = np.fft.rfftfreq(nfft, 1.0 / fs)
        self.bin_lo = int(np.searchsorted(freqs, f_min))
        self.bin_hi = int(np.searchsorted(freqs, f_max))
        self.n_bins = max(1, self.bin_hi - self.bin_lo)
        self.freqs = freqs[self.bin_lo:self.bin_hi]

        # imagem: mais alta frequencia no topo
        self._rgb_cache: np.ndarray | None = None
        self.data = np.zeros((self.n_bins, width), dtype=np.uint8)
        self.levels = np.full(self.n_bins, -120.0, dtype=np.float32)

    # -- entrada -------------------------------------------------------
    def add_audio(self, samples: np.ndarray, hop: int | None = None) -> int:
        """Adiciona colunas a partir de amostras 12 kHz. Retorna n colunas."""
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0
        hop = hop or int(self.fs * 0.05)
        buf = np.concatenate([self._tail, x]) if self._tail.size else x
        if buf.size < self.nfft:
            self._tail = buf
            return 0

        n_cols = (buf.size - self.nfft) // hop + 1
        idx = np.arange(n_cols)[:, None] * hop + np.arange(self.nfft)[None, :]
        frames = buf[idx] * self.window
        spec = np.abs(np.fft.rfft(frames, axis=1))[:, self.bin_lo:self.bin_hi]
        mag_db = 20.0 * np.log10(spec + 1e-9)

        # Piso de ruido adaptativo: o nivel absoluto depende do ganho da placa
        # de som, entao normalizamos pelo proprio ruido do receptor.
        col_floor = np.percentile(mag_db, 30, axis=1)
        new_floor = float(col_floor.mean())
        if self.floor_db is None:
            self.floor_db = new_floor
        else:
            # EMA para nao piscar entre colunas
            self.floor_db = 0.85 * self.floor_db + 0.15 * new_floor
        self.lo_db = self.floor_db - 3.0
        self.hi_db = self.lo_db + self.db_range

        mag = np.clip((mag_db - self.lo_db) / (self.hi_db - self.lo_db), 0, 1)
        cols = (mag * 255).astype(np.uint8).T  # [freq, n_cols]

        n = min(n_cols, self.width)
        self.data[:, :self.width - n] = self.data[:, n:]
        self.data[:, self.width - n:] = cols[:, n_cols - n:]
        self._rgb_cache = None
        self.levels = (mag[-1].astype(np.float32) * (self.hi_db - self.lo_db)
                       + self.lo_db)
        # descarta o que ja foi consumido, mantendo o necessario para o
        # proximo frame (evita contar a mesma janela duas vezes)
        self._tail = buf[n_cols * hop:]
        return n_cols

    def reset(self) -> None:
        self.data[:] = 0
        self._rgb_cache = None
        self._tail = np.zeros(0, dtype=np.float32)
        self.levels[:] = self.lo_db
        self.floor_db = None

    # -- saida ---------------------------------------------------------
    def rgb(self) -> np.ndarray:
        """Imagem para waterfall VERTICAL: X = frequencia, Y = tempo.

        `data` e' guardado como [freq, tempo]; transpondo, cada linha vira um
        instante. A linha 0 e' o instante mais recente (topo), como no WSJT-X.
        O resultado fica em cache ate' chegar audio novo.
        """
        cache = getattr(self, "_rgb_cache", None)
        if cache is not None:
            return cache
        self._rgb_cache = PALETTE[self.data.T[::-1]]
        return self._rgb_cache

    def freq_to_frac(self, hz: float) -> float:
        """Posicao horizontal normalizada (0 = esquerda = f_min)."""
        span = max(1e-6, self.f_max - self.f_min)
        return min(max((hz - self.f_min) / span, 0.0), 1.0)

    def freq_to_row(self, hz: float) -> float:
        """Compatibilidade: posicao vertical normalizada (0 = topo)."""
        return 1.0 - self.freq_to_frac(hz)


    def bin_to_row(self, idx: int) -> int:
        return int(self.n_bins - 1 - idx)
