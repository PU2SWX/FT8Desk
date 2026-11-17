"""Bindings ctypes para a biblioteca nativa FT8 (ft8_lib + shim)."""

from __future__ import annotations

import ctypes
import platform
import sys
from pathlib import Path

SAMPLE_RATE = 12000  # ft8_lib trabalha em 12 kHz


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def frozen_base() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def resource_path(*parts: str) -> Path:
    """Caminho de um recurso que funciona no codigo e no executavel."""
    if is_frozen():
        base = frozen_base()
    else:
        base = Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)


def _lib_filename() -> str:
    if sys.platform.startswith("win"):
        return "ft8shim.dll"
    if sys.platform == "darwin":
        return "libft8shim.dylib"
    return "libft8shim.so"


class Result(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("text", ctypes.c_char * 48),
        ("freq_hz", ctypes.c_float),
        ("time_s", ctypes.c_float),
        ("snr", ctypes.c_float),
        ("score", ctypes.c_int32),
        ("ldpc_errors", ctypes.c_int32),
        ("flags", ctypes.c_int32),
    ]

    @property
    def hashed(self) -> bool:
        return bool(self.flags & 1)

    def __repr__(self) -> str:
        return f"<{self.text!r} {self.freq_hz:.0f}Hz {self.snr:+.0f}dB>"


_lib = None


def load_library(force_path: str | Path | None = None):
    global _lib
    if _lib is not None:
        return _lib

    candidates: list[Path] = [Path(force_path)] if force_path else []
    if is_frozen():
        # PyInstaller extrai os dados em sys._MEIPASS
        base = frozen_base()
        candidates += [base / "native" / _lib_filename(), base / _lib_filename()]
    here = Path(__file__).resolve().parent
    candidates += [
        here / "native" / _lib_filename(),        # pacote instalado
        here.parent / "native" / _lib_filename(), # checkout do projeto
        here / _lib_filename(),
    ]

    last_err: Exception | None = None
    for c in candidates:
        if not c.exists():
            continue
        try:
            lib = ctypes.CDLL(str(c))
        except OSError as exc:  # pragma: no cover
            last_err = exc
            continue
        _declare(lib)
        _lib = lib
        return lib

    # Ultimo recurso: compila agora (precisa de zig/MSVC/gcc). Nunca quando
    # empacotado: nao ha compilador no computador de quem recebeu o app.
    if is_frozen():
        raise RuntimeError(
            f"Biblioteca nativa ausente no pacote: {_lib_filename()}.\n"
            "O executavel foi gerado sem a DLL -- gere de novo com build_exe.bat.")
    try:
        import importlib
        import sys as _sys
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parent.parent
        if str(root) not in _sys.path:
            _sys.path.insert(0, str(root))
        build = importlib.import_module("build_native")
        build.build()
        lib = ctypes.CDLL(str(root / "native" / _lib_filename()))
        _declare(lib)
        _lib = lib
        return lib
    except Exception as exc:
        last_err = last_err or exc

    raise RuntimeError(
        "Biblioteca nativa nao encontrada/nao carregavel. Rode "
        "`python build_native.py` uma vez.\nProcurado em:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + (f"\nErro: {last_err}" if last_err else "")
    )


def _declare(lib) -> None:
    lib.ft8d_create.restype = ctypes.c_void_p
    lib.ft8d_create.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_int, ctypes.c_int]

    lib.ft8d_destroy.argtypes = [ctypes.c_void_p]
    lib.ft8d_reset.argtypes = [ctypes.c_void_p]

    lib.ft8d_frame_len.restype = ctypes.c_int
    lib.ft8d_frame_len.argtypes = [ctypes.c_void_p]
    lib.ft8d_blocks_ready.restype = ctypes.c_int
    lib.ft8d_blocks_ready.argtypes = [ctypes.c_void_p]
    lib.ft8d_blocks_max.restype = ctypes.c_int
    lib.ft8d_blocks_max.argtypes = [ctypes.c_void_p]

    lib.ft8d_feed.restype = ctypes.c_int
    lib.ft8d_feed.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int]
    lib.ft8d_feed_frame.restype = ctypes.c_int
    lib.ft8d_feed_frame.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)]

    lib.ft8d_decode.restype = ctypes.c_int
    lib.ft8d_decode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(Result)]

    lib.ft8d_encode_text.restype = ctypes.c_int
    lib.ft8d_encode_text.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_float, ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ]

    lib.ft8d_tx_samples.restype = ctypes.c_int
    lib.ft8d_tx_samples.argtypes = [ctypes.c_int, ctypes.c_int]

    lib.ft8d_check_text.restype = ctypes.c_int
    lib.ft8d_check_text.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
    ]


class Decoder:
    """Decodificador de um slot (15 s para FT8)."""

    def __init__(self, f_min: float = 200.0, f_max: float = 3000.0,
                 sample_rate: int = SAMPLE_RATE, protocol: str = "FT8"):
        self.lib = load_library()
        proto = 0 if protocol.upper() == "FT4" else 1
        self.sample_rate = sample_rate
        self.protocol = protocol.upper()
        self._ptr = self.lib.ft8d_create(f_min, f_max, sample_rate, proto)
        if not self._ptr:
            raise RuntimeError("ft8d_create falhou")
        self.frame_len = self.lib.ft8d_frame_len(self._ptr)
        self.max_blocks = self.lib.ft8d_blocks_max(self._ptr)
        self._buf = (ctypes.c_float * 65536)()
        self._results = (Result * 80)()

    # -- ciclo de vida -------------------------------------------------
    def reset(self) -> None:
        self.lib.ft8d_reset(self._ptr)

    def close(self) -> None:
        if getattr(self, "_ptr", None):
            self.lib.ft8d_destroy(self._ptr)
            self._ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # -- alimentacao ---------------------------------------------------
    @property
    def blocks_ready(self) -> int:
        return self.lib.ft8d_blocks_ready(self._ptr)

    def feed(self, samples) -> int:
        """Alimenta amostras float32; retorna nº de blocos produzidos."""
        import numpy as np

        arr = np.ascontiguousarray(samples, dtype=np.float32)
        n = int(arr.size)
        ptr = arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        return self.lib.ft8d_feed(self._ptr, ptr, n)

    def decode(self) -> list[Result]:
        n = self.lib.ft8d_decode(self._ptr, 80, self._results)
        return [self._results[i] for i in range(n)]

    # -- codificacao ---------------------------------------------------
    def encode(self, text: str, freq_hz: float = 1200.0,
               sample_rate: int | None = None):
        """Retorna numpy float32 com a forma de onda (12.64 s em 12 kHz)."""
        import numpy as np

        sr = sample_rate or self.sample_rate
        max_out = self.lib.ft8d_tx_samples(sr, 0 if self.protocol == "FT4" else 1)
        out = (ctypes.c_float * max_out)()
        n = self.lib.ft8d_encode_text(
            self._ptr, text.encode("ascii", "replace"), float(freq_hz), sr, out, max_out
        )
        if n < 0:
            raise ValueError(f"Mensagem nao codificavel (rc={n}): {text!r}")
        return np.frombuffer(bytes(out)[: n * 4], dtype=np.float32).copy()

    def check_text(self, text: str) -> tuple[bool, str]:
        """Valida se o texto cabe em 77 bits. Retorna (ok, texto_normalizado)."""
        buf = ctypes.create_string_buffer(64)
        rc = self.lib.ft8d_check_text(
            self._ptr, text.encode("ascii", "replace"), buf, len(buf)
        )
        return rc == 0, buf.value.decode("ascii", "replace")


def tx_samples(sample_rate: int = SAMPLE_RATE, protocol: str = "FT8") -> int:
    lib = load_library()
    return lib.ft8d_tx_samples(sample_rate, 0 if protocol.upper() == "FT4" else 1)
