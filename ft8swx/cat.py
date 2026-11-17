"""Controle de radio via CAT: le/ajusta a frequencia, coloca em USB-DATA e (opcional) chaveia o PTT.

Backends:
  rigctld  - Hamlib (TCP). Serve para qualquer radio que o Hamlib conheca.
  icom     - Icom CI-V direto na serial (IC-7300, IC-705, IC-7610...).
  kenwood  - ASCII Kenwood (FA com 11 digitos; TS-590, TS-2000...).
  yaesu    - ASCII Yaesu (FA com 9 digitos; FT-991A, FT-710, FT-891, FTDX10).

Este modulo nao depende de Qt: a janela so le ``freq_hz`` e chama set_freq/set_ptt.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .ptt import PttConfig, PttController, PttError

try:
    import serial
except Exception:  # pragma: no cover - pyserial ausente
    serial = None


class CatError(RuntimeError):
    pass


BACKENDS: dict[str, str] = {
    "rigctld": "Hamlib rigctld (qualquer radio)",
    "icom": "Icom CI-V (serial)",
    "kenwood": "Kenwood ASCII (serial)",
    "yaesu": "Yaesu ASCII (serial)",
}


@dataclass
class CatConfig:
    enabled: bool = False
    backend: str = "rigctld"
    port: str = ""                 # serial (icom / kenwood / yaesu)
    baud: int = 19200
    host: str = "127.0.0.1"        # rigctld
    tcp_port: int = 4532
    civ_addr: int = 0x94           # Icom: IC-7300 = 0x94, IC-705 = 0xA4, IC-7610 = 0x98
    set_mode: bool = True          # coloca em USB-DATA ao sintonizar
    ptt_via_cat: bool = False      # PTT pelo comando CAT em vez de DTR/RTS
    poll_s: float = 1.0

    @property
    def uses_serial(self) -> bool:
        return self.backend != "rigctld"


# ----------------------------------------------------------------------
# enlace serial
# ----------------------------------------------------------------------
class SerialLink:
    """Porta serial com DTR/RTS em nivel baixo ja na abertura.

    Em varios radios (FT-991A, IC-7300...) DTR/RTS podem estar mapeados para
    PTT/CW. Abrir a porta com as linhas ativas pode colocar o radio em TX.
    """

    def __init__(self, port: str, baud: int):
        self.port = port
        self.baud = baud
        self._ser = None

    def open(self) -> None:
        if serial is None:
            raise CatError("pyserial nao instalado (pip install pyserial)")
        if not self.port:
            raise CatError("Nenhuma porta serial selecionada para o CAT")
        try:
            ser = serial.Serial()
            ser.port = self.port
            ser.baudrate = self.baud
            ser.timeout = 0.05
            ser.write_timeout = 1.0
            ser.dtr = False
            ser.rts = False
            if not self.port.upper().startswith("COM"):
                ser.exclusive = True
            ser.open()
            self._ser = ser
        except Exception as exc:
            raise CatError(f"Nao foi possivel abrir {self.port}: {exc}") from exc

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def write(self, data: bytes) -> None:
        try:
            self._ser.write(data)
            self._ser.flush()
        except Exception as exc:
            raise CatError(f"Falha de escrita na serial: {exc}") from exc

    def flush_input(self) -> None:
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def read_until(self, terminator: bytes, timeout: float) -> bytes:
        end = time.monotonic() + timeout
        buf = bytearray()
        try:
            while time.monotonic() < end:
                chunk = self._ser.read(self._ser.in_waiting or 1)
                if chunk:
                    buf += chunk
                    if terminator in buf:
                        break
        except Exception as exc:
            raise CatError(f"Falha de leitura na serial: {exc}") from exc
        return bytes(buf)


# ----------------------------------------------------------------------
# backends
# ----------------------------------------------------------------------
class _Backend:
    def open(self) -> None: ...
    def close(self) -> None: ...
    def get_freq(self) -> float: raise NotImplementedError      # Hz
    def set_freq(self, hz: float) -> None: raise NotImplementedError
    def set_mode_data(self) -> None: raise NotImplementedError
    def set_ptt(self, on: bool) -> None: raise NotImplementedError


class RigctldBackend(_Backend):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._buf = b""

    def open(self) -> None:
        self._connect()

    def _connect(self) -> None:
        try:
            s = socket.create_connection((self.host, self.port), timeout=1.5)
        except OSError as exc:
            raise CatError(f"rigctld em {self.host}:{self.port}: {exc}") from exc
        s.settimeout(1.0)
        self._sock = s
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None

    def _line(self) -> str:
        while b"\n" not in self._buf:
            data = self._sock.recv(256)
            if not data:
                raise OSError("conexao encerrada")
            self._buf += data
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("ascii", "ignore").strip()

    def _cmd(self, text: str) -> str:
        try:
            if self._sock is None:
                self._connect()
            self._sock.sendall((text + "\n").encode("ascii"))
            return self._line()
        except CatError:
            raise
        except OSError as exc:
            self.close()                 # reconecta na proxima chamada
            raise CatError(f"rigctld: {exc}") from exc

    def _ok(self, text: str) -> None:
        r = self._cmd(text)
        if r != "RPRT 0":
            raise CatError(f"rigctld recusou '{text}': {r}")

    def get_freq(self) -> float:
        r = self._cmd("f")
        try:
            return float(r)
        except ValueError:
            raise CatError(f"rigctld: resposta inesperada '{r}'") from None

    def set_freq(self, hz: float) -> None:
        self._ok(f"F {int(round(hz))}")

    def set_mode_data(self) -> None:
        self._ok("M PKTUSB 0")

    def set_ptt(self, on: bool) -> None:
        self._ok(f"T {1 if on else 0}")


class IcomBackend(_Backend):
    CTRL = 0xE0

    def __init__(self, port: str, baud: int, addr: int, link=None, timeout: float = 0.5):
        self.addr = int(addr) & 0xFF
        self.link = link or SerialLink(port, baud)
        self.timeout = timeout

    def open(self) -> None:
        self.link.open()

    def close(self) -> None:
        self.link.close()

    # -- BCD little-endian de 5 bytes (10 digitos, em Hz) ---------------
    @staticmethod
    def encode_freq(hz: float) -> bytes:
        n = int(round(hz))
        out = bytearray()
        for _ in range(5):
            pair = n % 100
            out.append(((pair // 10) << 4) | (pair % 10))
            n //= 100
        return bytes(out)

    @staticmethod
    def decode_freq(data: bytes) -> float:
        n = 0
        for i, b in enumerate(data[:5]):
            n += ((b >> 4) * 10 + (b & 0x0F)) * (100 ** i)
        return float(n)

    @staticmethod
    def _pop_frame(buf: bytes):
        i = buf.find(b"\xfe\xfe")
        if i < 0:
            return None, b""
        j = buf.find(b"\xfd", i + 2)
        if j < 0:
            return None, buf[i:]
        body = buf[i + 2:j]
        rest = buf[j + 1:]
        if len(body) < 3:
            return (None, rest) if rest else (None, b"")
        return (body[0], body[1], body[2:]), rest

    def _txn(self, cmd: bytes, want: Callable[[bytes], bool]) -> bytes:
        self.link.flush_input()
        self.link.write(b"\xfe\xfe" + bytes([self.addr, self.CTRL]) + cmd + b"\xfd")
        deadline = time.monotonic() + self.timeout
        buf = b""
        while time.monotonic() < deadline:
            buf += self.link.read_until(b"\xfd", max(0.05, deadline - time.monotonic()))
            while True:
                frame, buf = self._pop_frame(buf)
                if frame is None:
                    break
                dst, src, payload = frame
                # ignora o eco do nosso comando e mensagens "transceive" (dst 0x00)
                if dst == self.CTRL and src == self.addr and want(payload):
                    return payload
        raise CatError("Sem resposta do radio (CI-V). Confira porta, baud e endereco.")

    def _ack(self, cmd: bytes) -> None:
        p = self._txn(cmd, lambda x: x[:1] in (b"\xfb", b"\xfa"))
        if p[:1] == b"\xfa":
            raise CatError("O radio recusou o comando (CI-V NG)")

    def get_freq(self) -> float:
        p = self._txn(b"\x03", lambda x: x[:1] == b"\x03" and len(x) >= 6)
        return self.decode_freq(p[1:6])

    def set_freq(self, hz: float) -> None:
        self._ack(b"\x05" + self.encode_freq(hz))

    def set_mode_data(self) -> None:
        self._ack(b"\x06\x01")                 # USB
        try:
            self._ack(b"\x1a\x06\x01\x01")     # DATA ligado, filtro 1 (IC-7300/705/7610)
        except CatError:
            pass                               # radio sem este comando: fica em USB

    def set_ptt(self, on: bool) -> None:
        self._ack(b"\x1c\x00" + (b"\x01" if on else b"\x00"))


class AsciiBackend(_Backend):
    """Kenwood (FA de 11 digitos) e Yaesu (FA de 9 digitos)."""

    def __init__(self, style: str, port: str, baud: int, link=None, timeout: float = 0.4):
        if style not in ("kenwood", "yaesu"):
            raise ValueError(style)
        self.style = style
        self.digits = 11 if style == "kenwood" else 9
        self.link = link or SerialLink(port, baud)
        self.timeout = timeout

    def open(self) -> None:
        self.link.open()

    def close(self) -> None:
        self.link.close()

    def _send(self, text: str) -> None:
        self.link.flush_input()
        self.link.write(text.encode("ascii"))

    def get_freq(self) -> float:
        self._send("FA;")
        deadline = time.monotonic() + self.timeout
        buf = b""
        while time.monotonic() < deadline:
            buf += self.link.read_until(b";", max(0.05, deadline - time.monotonic()))
            parts = buf.decode("ascii", "ignore").split(";")
            for r in parts[:-1]:
                r = r.strip()
                if r.startswith("FA") and r[2:].isdigit():
                    return float(r[2:])
                if r == "?":
                    raise CatError("O radio nao reconheceu o comando FA; (estilo CAT errado?)")
        raise CatError("Sem resposta do radio (CAT). Confira porta e baud.")

    def set_freq(self, hz: float) -> None:
        self._send(f"FA{int(round(hz)):0{self.digits}d};")

    def set_mode_data(self) -> None:
        if self.style == "yaesu":
            self._send("MD0C;")                # DATA-USB
        else:
            self._send("MD2;")                 # USB
            self._send("DA1;")                 # modo de dados (ignorado se nao existir)

    def set_ptt(self, on: bool) -> None:
        if self.style == "yaesu":
            self._send("TX1;" if on else "TX0;")
        else:
            self._send("TX1;" if on else "RX;")


def make_backend(cfg: CatConfig) -> _Backend:
    if cfg.backend == "rigctld":
        return RigctldBackend(cfg.host, int(cfg.tcp_port))
    if cfg.backend == "icom":
        return IcomBackend(cfg.port, int(cfg.baud), int(cfg.civ_addr))
    if cfg.backend in ("kenwood", "yaesu"):
        return AsciiBackend(cfg.backend, cfg.port, int(cfg.baud))
    raise CatError(f"Backend CAT desconhecido: {cfg.backend}")


# ----------------------------------------------------------------------
# controlador (thread de leitura de frequencia)
# ----------------------------------------------------------------------
class CatController:
    def __init__(self, cfg: CatConfig, backend: _Backend | None = None):
        self.cfg = cfg
        self._be = backend
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.freq_hz: float | None = None
        self.freq_stamp = 0              # incrementa a cada leitura valida
        self.last_error = ""
        self.keyed = False
        self._fails = 0

    @property
    def connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def healthy(self) -> bool:
        return self.connected and self._fails < 3 and self.freq_hz is not None

    def open(self) -> None:
        if not self.cfg.enabled or self._thread is not None:
            return
        with self._lock:
            be = self._be or make_backend(self.cfg)
            be.open()                    # CatError sobe para a interface
            self._be = be
        self._stop.clear()
        self._fails = 0
        self._thread = threading.Thread(target=self._poll, name="cat-poll", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        self._thread = None
        with self._lock:
            if self._be is not None:
                try:
                    if self.keyed:
                        self._be.set_ptt(False)
                except Exception:
                    pass
                self._be.close()
                self._be = None
        self.keyed = False
        self.freq_hz = None

    def _poll(self) -> None:
        interval = max(0.25, float(self.cfg.poll_s))
        while not self._stop.is_set():
            if not self.keyed:
                try:
                    with self._lock:
                        be = self._be
                        hz = be.get_freq() if be is not None else None
                    if hz is not None:
                        self.freq_hz = hz
                        self.freq_stamp += 1
                        self._fails = 0
                        self.last_error = ""
                except CatError as exc:
                    self._fails += 1
                    self.last_error = str(exc)
                except Exception as exc:  # pragma: no cover
                    self._fails += 1
                    self.last_error = str(exc)
            self._stop.wait(interval)

    # -- comandos --------------------------------------------------------
    def _call(self, fn):
        with self._lock:
            if self._be is None:
                raise CatError("CAT desconectado")
            return fn(self._be)

    def read_freq(self) -> float:
        return self._call(lambda b: b.get_freq())

    def set_freq(self, hz: float) -> None:
        self._call(lambda b: b.set_freq(hz))
        self.freq_hz = float(hz)

    def set_mode_data(self) -> None:
        self._call(lambda b: b.set_mode_data())

    def set_ptt(self, on: bool) -> None:
        if on:
            self.keyed = True            # a thread de leitura para antes de chavear
        try:
            self._call(lambda b: b.set_ptt(on))
        except CatError:
            if on:
                self.keyed = False
            raise
        self.keyed = bool(on)


class CatPtt(PttController):
    """PTT pelo comando CAT. Mesma interface do PttController (TxJob nao muda)."""

    def __init__(self, cat: CatController, cfg: PttConfig):
        super().__init__(cfg)
        self.cat = cat

    def open(self) -> None:          # a porta pertence ao CatController
        return

    def close(self) -> None:
        try:
            self.unkey()
        except PttError:
            pass

    def key(self) -> None:
        try:
            self.cat.set_ptt(True)
        except CatError as exc:
            try:
                self.cat.set_ptt(False)
            except CatError:
                pass
            raise PttError(f"CAT: {exc}") from exc
        self._keyed = True

    def unkey(self) -> None:
        try:
            self.cat.set_ptt(False)
        except CatError as exc:
            raise PttError(f"CAT: {exc}") from exc
        self._keyed = False

    @property
    def connected(self) -> bool:
        return self.cat.connected
