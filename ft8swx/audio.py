"""Audio: captura/transmissao via PortAudio (sounddevice) e coleta de slots."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_PROBE_ENV = "FT8SWX_AUDIO_PROBE"


def _prefer_bundled_portaudio() -> str:
    """Windows: faz o sounddevice carregar native/portaudio.dll (compilada SEM WDM-KS).

    A DLL que vem com o sounddevice inclui WDM-KS; com o FlexRadio DAX ativo
    (SmartSDR aberto) o Pa_Initialize() dela corrompe o heap (0xC0000374) e
    derruba o processo. O sounddevice procura 'portaudio.dll' no PATH antes de
    usar a propria DLL, entao basta colocar a nossa pasta na frente.
    """
    if not sys.platform.startswith("win"):
        return ""
    from .native import resource_path

    for folder in (resource_path("native"), Path(__file__).resolve().parent.parent / "native"):
        if (folder / "portaudio.dll").exists():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return str(folder / "portaudio.dll")
    return ""


def _probe_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--audio-probe"]          # tratado no run.py
    return [sys.executable, "-c", "from ft8swx.audio import probe_main; raise SystemExit(probe_main())"]


def _probe_portaudio() -> str:
    """Inicializa a PortAudio num processo filho. Se algum driver derrubar o
    processo, o app abre mesmo assim (sem audio) em vez de fechar sem aviso.
    Devolve "" se deu certo, ou a mensagem de erro."""
    if os.environ.get(_PROBE_ENV) or not sys.platform.startswith("win"):
        return ""
    env = dict(os.environ, **{_PROBE_ENV: "1"})
    # o filho faz "from ft8swx.audio import ...": precisa achar o pacote mesmo
    # quando o app foi iniciado de outra pasta (python C:\...\run.py)
    root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        r = subprocess.run(_probe_command(), env=env, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return "a inicializacao do audio (PortAudio) travou ao listar os dispositivos"
    except OSError:
        return ""                     # nao deu para testar: segue o caminho normal
    if r.returncode == 0:
        return ""
    return (f"um driver de audio derrubou a PortAudio (codigo 0x{r.returncode & 0xFFFFFFFF:08X}). "
            "Feche programas de audio virtual e tente de novo.")


PORTAUDIO_DLL = _prefer_bundled_portaudio()
_SD_ERROR = _probe_portaudio()
sd = None
if not _SD_ERROR:
    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover
        sd = None
        _SD_ERROR = str(exc)


def probe_main() -> int:
    """Executado no processo filho (FT8SWX.exe --audio-probe)."""
    if sd is None:
        return 3
    sd.query_devices()
    return 0

FT8_RATE = 12000
SLOT_SECONDS = {"FT8": 15.0, "FT4": 7.5}
TX_SECONDS = {"FT8": 12.64, "FT4": 4.98}


def backend_available() -> tuple[bool, str]:
    return (sd is not None, _SD_ERROR)


def list_devices() -> list[dict]:
    if sd is None:
        return []
    out = []
    try:
        for idx, d in enumerate(sd.query_devices()):
            if "WDM-KS" in sd.query_hostapis(d["hostapi"])["name"]:
                continue          # kernel streaming: fonte comum de travamentos
            out.append({
                "index": idx,
                "name": d["name"],
                "in": int(d["max_input_channels"]),
                "out": int(d["max_output_channels"]),
                "rate": int(d["default_samplerate"]),
                "hostapi": sd.query_hostapis(d["hostapi"])["name"],
            })
    except Exception:
        pass
    return out


# ----------------------------------------------------------------------
# Reamostragem
# ----------------------------------------------------------------------

def _lowpass_fir(factor: int, taps: int = 63) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    fc = 0.45 / factor  # corte normalizado (fs=1)
    h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(taps)
    return h / h.sum()


def resample(x: np.ndarray, fs_in: int, fs_out: int) -> np.ndarray:
    """Reamostragem de qualidade suficiente para FT8 (sinc se possivel)."""
    x = np.asarray(x, dtype=np.float32)
    if fs_in == fs_out or x.size == 0:
        return x
    if fs_out < fs_in and fs_in % fs_out == 0:
        factor = fs_in // fs_out
        h = _lowpass_fir(factor)
        y = np.convolve(x, h, mode="same")
        return np.ascontiguousarray(y[::factor], dtype=np.float32)
    if fs_out > fs_in and fs_out % fs_in == 0:
        factor = fs_out // fs_in
        # zero-stuffing + filtro (evita imagens que poluem o espectro)
        up = np.zeros(x.size * factor, dtype=np.float32)
        up[::factor] = x
        h = _lowpass_fir(factor) * factor
        return np.convolve(up, h, mode="same").astype(np.float32)
    try:
        from scipy.signal import resample_poly  # type: ignore
        from math import gcd

        g = gcd(fs_in, fs_out)
        return resample_poly(x, fs_out // g, fs_in // g).astype(np.float32)
    except Exception:
        n_out = int(round(x.size * fs_out / fs_in))
        t_in = np.arange(x.size) / fs_in
        t_out = np.arange(n_out) / fs_out
        return np.interp(t_out, t_in, x).astype(np.float32)


# ----------------------------------------------------------------------
# Coletor de slots (logica pura, testavel sem hardware)
# ----------------------------------------------------------------------

class SlotCollector:
    """Junta audio continuo em janelas alinhadas aos slots UTC.

    Recebe blocos com o instante do *ultimo* sample de cada bloco e devolve
    janelas completas de ``slot_seconds`` a partir da fronteira do slot.
    """

    def __init__(self, fs: int = FT8_RATE, slot_seconds: float = 15.0,
                 keep_seconds: float = 40.0):
        self.fs = fs
        self.slot_seconds = slot_seconds
        self.keep = int(fs * keep_seconds)
        self._buf = np.zeros(0, dtype=np.float32)
        self._t_end = 0.0   # instante do ultimo sample no buffer
        self._emitted_slot: int | None = None

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.float32)
        self._t_end = 0.0
        self._emitted_slot = None

    def push(self, block: np.ndarray, t_last_sample: float) -> list[tuple[float, np.ndarray]]:
        block = np.asarray(block, dtype=np.float32)
        self._buf = np.concatenate([self._buf, block])
        if self._buf.size > self.keep:
            self._buf = self._buf[-self.keep:]
        self._t_end = t_last_sample

        out = []
        n_slot = int(round(self.slot_seconds * self.fs))
        # inicio do buffer em tempo absoluto
        t_start = self._t_end - (self._buf.size - 1) / self.fs

        # slot mais antigo completo disponivel
        first_slot = int(np.floor(t_start / self.slot_seconds)) + 1
        last_slot = int(np.floor((self._t_end - self.slot_seconds) / self.slot_seconds))

        if self._emitted_slot is None:
            self._emitted_slot = last_slot - 1
        s = max(first_slot, self._emitted_slot + 1)
        while s <= last_slot:
            t0 = s * self.slot_seconds
            i0 = int(round((t0 - t_start) * self.fs))
            if i0 < 0:
                s += 1
                continue
            i1 = i0 + n_slot
            if i1 > self._buf.size:
                break
            out.append((t0, self._buf[i0:i1].copy()))
            self._emitted_slot = s
            s += 1
        return out


# ----------------------------------------------------------------------
# Motor de audio
# ----------------------------------------------------------------------

@dataclass
class AudioConfig:
    input_device: int | None = None
    output_device: int | None = None
    input_rate: int = 48000
    output_rate: int = 48000
    tx_gain: float = 0.5


class AudioEngine:
    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self.q: queue.Queue = queue.Queue(maxsize=400)
        self._in_stream: object | None = None
        self._out_stream: object | None = None
        self._lock = threading.Lock()
        self.last_error = ""
        self.overflows = 0

    # -- RX -----------------------------------------------------------
    def start_rx(self) -> None:
        if sd is None:
            raise RuntimeError(f"Audio indisponivel: {_SD_ERROR}")
        self.stop_rx()

        def cb(indata, frames, time_info, status):  # noqa: ANN001
            if status:
                self.overflows += 1
            try:
                self.q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                self.overflows += 1

        stream = sd.InputStream(
            device=self.cfg.input_device,
            channels=1,
            samplerate=self.cfg.input_rate,
            blocksize=int(self.cfg.input_rate * 0.05),
            dtype="float32",
            callback=cb,
        )
        self._in_stream = stream
        stream.start()

    def stop_rx(self) -> None:
        stream = self._in_stream
        if stream is not None:
            try:
                stream.stop()      # type: ignore[attr-defined]
                stream.close()     # type: ignore[attr-defined]
            except Exception:
                pass
            self._in_stream = None

    def drain(self) -> list[np.ndarray]:
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out

    # -- TX -----------------------------------------------------------
    def play_12k(self, wave: np.ndarray, blocking: bool = True) -> float:
        """Toca uma forma de onda de 12 kHz no dispositivo de saida."""
        if sd is None:
            raise RuntimeError(f"Audio indisponivel: {_SD_ERROR}")
        wave = np.asarray(wave, dtype=np.float32) * float(self.cfg.tx_gain)
        y = resample(wave, FT8_RATE, self.cfg.output_rate)
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak > 0.99:
            y = y * (0.99 / peak)
        dur = y.size / self.cfg.output_rate
        with self._lock:
            sd.play(y, self.cfg.output_rate, device=self.cfg.output_device, blocking=blocking)
        return dur

    def stop_play(self) -> None:
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass

    def close(self) -> None:
        self.stop_rx()
        self.stop_play()
