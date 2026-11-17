"""Controle de PTT. Foco: FTDI/CP210x/CH340 via porta serial, chaveando DTR (ou RTS)."""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass, field

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - pyserial ausente
    serial = None
    list_ports = None


class PttError(RuntimeError):
    pass


def list_serial_ports() -> list[tuple[str, str]]:
    """Retorna [(device, description)] das portas seriais disponiveis."""
    if list_ports is None:
        return []
    out = []
    for p in list_ports.comports():
        desc = " ".join(x for x in (p.description, p.manufacturer) if x)
        out.append((p.device, desc or "sem descricao"))
    return out


@dataclass
class PttConfig:
    port: str = ""                 # "COM3", "/dev/ttyUSB0"
    baud: int = 38400
    line: str = "DTR"              # DTR | RTS | BOTH
    invert: bool = False           # inverte a polaridade logica
    tx_delay_ms: int = 150         # PTT antes do audio (amplificador/relé)
    hang_ms: int = 120             # PTT depois do audio
    enabled: bool = True


class PttController:
    """Chaveia PTT por linha de controle serial.

    Notas de hardware (importante para FTDI):
      - No FT232R o pino DTR# e' ativo em nivel baixo. Com ``invert=False``
        ``key()`` faz ``ser.dtr = True``, que coloca DTR# em LOW.
      - Muitos cabos caseiros e interfaces (DigiRig, XGGComms, SignaLink)
        usam RTS, ou usam DTR invertido. Por isso existem ``line`` e ``invert``.
      - A porta fica aberta durante toda a sessao: abrir/fechar porta faz o
        driver pulsar as linhas e pode gerar transmissao fantasma.
    """

    def __init__(self, cfg: PttConfig):
        self.cfg = cfg
        self._ser = None
        self._lock = threading.RLock()
        self._keyed = False

    # -- ciclo de vida ------------------------------------------------
    def open(self) -> None:
        if not self.cfg.enabled or not self.cfg.port:
            return
        if serial is None:
            raise PttError("pyserial nao instalado (pip install pyserial)")
        with self._lock:
            if self._ser is not None:
                return
            try:
                kwargs = dict(port=self.cfg.port, baudrate=self.cfg.baud,
                              timeout=0, write_timeout=0)
                if not self.cfg.port.upper().startswith("COM"):
                    kwargs["exclusive"] = True
                self._ser = serial.Serial(**kwargs)
            except Exception as exc:
                raise PttError(f"Nao foi possivel abrir {self.cfg.port}: {exc}") from exc
            # Estado de recepcao explicito, sem depender do default do driver
            self._apply(False)
            self._keyed = False

    def close(self) -> None:
        with self._lock:
            if self._ser is None:
                return
            try:
                self._apply(False)
            finally:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
                self._keyed = False

    # -- acao ---------------------------------------------------------
    def _apply(self, keyed: bool) -> None:
        ser = self._ser
        if ser is None:
            return
        level = bool(keyed) ^ bool(self.cfg.invert)
        try:
            if self.cfg.line.upper() in ("DTR", "BOTH"):
                ser.dtr = level
            if self.cfg.line.upper() in ("RTS", "BOTH"):
                ser.rts = level
        except Exception as exc:  # porta removida, driver caiu...
            raise PttError(f"Falha ao chavear PTT: {exc}") from exc

    def key(self) -> None:
        with self._lock:
            if self._ser is None:
                return
            self._apply(True)
            self._keyed = True

    def unkey(self) -> None:
        with self._lock:
            if self._ser is None:
                return
            self._apply(False)
            self._keyed = False

    @property
    def keyed(self) -> bool:
        return self._keyed

    @property
    def connected(self) -> bool:
        return self._ser is not None

    @contextlib.contextmanager
    def tx(self):
        """Contexto seguro: chaveia, espera tx_delay, libera com hang."""
        self.key()
        try:
            time.sleep(max(0, self.cfg.tx_delay_ms) / 1000.0)
            yield
        finally:
            time.sleep(max(0, self.cfg.hang_ms) / 1000.0)
            self.unkey()

    def test_pulse(self, ms: int = 800) -> None:
        """Pulsa o PTT sem audio: serve para descobrir a polaridade certa."""
        self.key()
        try:
            time.sleep(ms / 1000.0)
        finally:
            self.unkey()


class NullPtt(PttController):
    """PTT desligado (VOX ou somente RX)."""

    def __init__(self):
        super().__init__(PttConfig(enabled=False))
