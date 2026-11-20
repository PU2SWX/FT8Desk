"""Controle de PTT. Foco: FTDI/CP210x/CH340 via porta serial, chaveando DTR (ou RTS)."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - pyserial ausente
    serial = None
    list_ports = None


log = logging.getLogger("ft8swx.ptt")


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
    max_tx_s: float = 20.0         # watchdog: solta o PTT a forca depois disso (0 = desliga)


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
        self._wd: threading.Timer | None = None

    # -- watchdog -----------------------------------------------------
    def _arm_wd(self) -> None:
        self._disarm_wd()
        if self.cfg.max_tx_s and self.cfg.max_tx_s > 0:
            t = threading.Timer(float(self.cfg.max_tx_s), self._wd_fired)
            t.daemon = True
            self._wd = t
            t.start()

    def _disarm_wd(self) -> None:
        t, self._wd = self._wd, None
        if t is not None:
            t.cancel()

    def _wd_fired(self) -> None:
        log.error("WATCHDOG: PTT ligado ha mais de %.1f s, liberando a forca", self.cfg.max_tx_s)
        try:
            self.unkey()
        except Exception as exc:  # noqa: BLE001
            log.error("WATCHDOG: falha ao liberar PTT: %s", exc)

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
                ser = serial.Serial()
                ser.port = self.cfg.port
                ser.baudrate = self.cfg.baud
                ser.timeout = 0
                ser.write_timeout = 0
                # DTR/RTS ja em nivel de repouso ANTES de abrir: sem isso o driver
                # (CH340/FTDI) assere as duas linhas na abertura e o radio pode chavear
                idle = bool(self.cfg.invert)
                ser.dtr = False
                ser.rts = False
                if self.cfg.line.upper() in ("DTR", "BOTH"):
                    ser.dtr = idle
                if self.cfg.line.upper() in ("RTS", "BOTH"):
                    ser.rts = idle
                if not self.cfg.port.upper().startswith("COM"):
                    ser.exclusive = True
                ser.open()
                self._ser = ser
                log.info("porta %s aberta (linha=%s, invert=%s)", self.cfg.port,
                         self.cfg.line, self.cfg.invert)
            except Exception as exc:
                log.error("falha ao abrir %s: %s", self.cfg.port, exc)
                raise PttError(f"Nao foi possivel abrir {self.cfg.port}: {exc}") from exc
            # Estado de recepcao explicito, sem depender do default do driver
            self._apply(False)
            self._keyed = False

    def close(self) -> None:
        self._disarm_wd()
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
            log.error("falha ao chavear PTT (%s): %s", "TX" if keyed else "RX", exc)
            raise PttError(f"Falha ao chavear PTT: {exc}") from exc

    def key(self) -> None:
        with self._lock:
            if self._ser is None:
                return
            self._apply(True)
            self._keyed = True
            self._arm_wd()
            log.info("PTT ON")

    def unkey(self) -> None:
        self._disarm_wd()
        with self._lock:
            if self._ser is None:
                return
            self._apply(False)
            if self._keyed:
                log.info("PTT OFF")
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
