"""Relogio de slots FT8/FT4 com sincronizacao SNTP (sem dependencias externas)."""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass

NTP_EPOCH_DELTA = 2208988800  # 1900 -> 1970


@dataclass
class ClockStatus:
    offset: float = 0.0          # segundos a somar ao relogio local
    last_sync: float = 0.0       # time.time() da ultima sincronizacao
    source: str = "local"
    error: str = ""
    stratum: int = 0
    delay: float = 0.0

    @property
    def synced(self) -> bool:
        return self.source in ("ntp", "http") and not self.error

    @property
    def precision(self) -> str:
        if self.source == "ntp":
            return f"±{(self.delay / 2 + 0.002) * 1000:.0f} ms"
        if self.source == "http":
            return "±0.5 s"
        return "sem sincronismo"


def _to_ntp(t: float) -> bytes:
    sec = int(t) + NTP_EPOCH_DELTA
    frac = int((t - int(t)) * 2**32)
    return struct.pack("!II", sec & 0xFFFFFFFF, frac & 0xFFFFFFFF)


def ntp_query(host: str, timeout: float = 1.5) -> tuple[float, float, int]:
    """Consulta SNTP. Retorna (offset, delay, stratum) em segundos.

    Offset = servidor - local. Layout NTP: as 48 palavras de 32 bits estao em
    big-endian; o campo "stratum" fica no *segundo byte do primeiro word* --
    ler de ``unpacked[1]`` (root delay) e' um erro classico e faz todo servidor
    bom ser rejeitado como "estrato 0".
    """
    originate = _to_ntp(time.time())
    packet = b"\x23" + 39 * b"\0" + originate  # LI=0 VN=4 Mode=3

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t1 = time.time()
        s.sendto(packet, (host, 123))
        data, _ = s.recvfrom(1024)
        t4 = time.time()

    if len(data) < 48:
        raise ValueError("resposta NTP curta")

    words = struct.unpack("!12I", data[:48])
    li_mode = words[0]
    stratum = (words[0] >> 16) & 0xFF
    mode = li_mode & 0x7

    if mode not in (4, 5):        # 4 = server, 5 = broadcast
        raise ValueError(f"modo NTP inesperado: {mode}")
    if li_mode >> 30 == 3:
        raise ValueError("servidor nao sincronizado (LI=3)")
    if stratum == 0:
        kiss = data[12:16].decode("ascii", "replace")
        raise ValueError(f"servidor recusou (KoD {kiss})")
    if stratum > 15:
        raise ValueError(f"estrato NTP invalido: {stratum}")

    # anti-spoofing: o campo originate devolvido deve ser o nosso
    if data[24:32] != originate:
        raise ValueError("resposta NTP nao corresponde a consulta")

    t2 = words[8] + words[9] / 2**32 - NTP_EPOCH_DELTA
    t3 = words[10] + words[11] / 2**32 - NTP_EPOCH_DELTA
    offset = ((t2 - t1) + (t3 - t4)) / 2.0
    delay = (t4 - t1) - (t3 - t2)
    return offset, delay, stratum


def http_time_query(host: str = "www.cloudflare.com", timeout: float = 3.0) -> float:
    """Ultimo recurso: cabecalho Date via HTTPS (precisao ~0.5 s)."""
    import email.utils
    import ssl

    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as s:
            s.settimeout(timeout)
            t1 = time.time()
            s.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 8192:
                chunk = s.recv(2048)
                if not chunk:
                    break
                buf += chunk
            t4 = time.time()
    for line in buf.decode("latin-1").split("\r\n"):
        if line.lower().startswith("date:"):
            dt = email.utils.parsedate_to_datetime(line[5:].strip())
            server = dt.timestamp()
            return server + (t4 - t1) / 2.0 - t1 + (t1 - t1)
    raise ValueError("sem cabecalho Date")


class SlotClock:
    """Fornece o tempo UTC corrigido e as fronteiras de slot."""

    def __init__(self, slot_seconds: float = 15.0):
        self.slot_seconds = float(slot_seconds)
        self.status = ClockStatus()
        self._lock = threading.Lock()

    # -- sincronizacao -------------------------------------------------
    def sync_ntp(self, hosts: tuple[str, ...] = ("pool.ntp.org", "a.st1.ntp.br",
                                                "time.google.com", "time.cloudflare.com",
                                                "time.windows.com")) -> ClockStatus:
        best: tuple[float, float, int] | None = None
        errors: list[str] = []
        for h in hosts:
            for _ in range(2):
                try:
                    off, delay, stratum = ntp_query(h)
                except Exception as exc:
                    errors.append(f"{h}: {exc}")
                    continue
                if best is None or delay < best[1]:
                    best = (off, delay, stratum)
                break
        if best is not None:
            with self._lock:
                self.status = ClockStatus(offset=best[0], last_sync=time.time(),
                                          source="ntp", error="",
                                          stratum=best[2], delay=best[1])
            return self.status

        # UDP/123 bloqueado? tenta o cabecalho HTTP Date
        for host in ("www.cloudflare.com", "www.google.com"):
            try:
                off = http_time_query(host)
                with self._lock:
                    self.status = ClockStatus(offset=off, last_sync=time.time(),
                                              source="http", error="", delay=1.0)
                return self.status
            except Exception as exc:
                errors.append(f"{host} (http): {exc}")

        with self._lock:
            self.status.error = "; ".join(errors[-3:]) or "falhou"
        return self.status

    # -- tempo ---------------------------------------------------------
    def now(self) -> float:
        return time.time() + self.status.offset

    def set_manual_offset(self, seconds: float) -> None:
        self.status = ClockStatus(offset=float(seconds), last_sync=time.time(),
                                  source="manual", error="")

    def slot_index(self, t: float | None = None) -> int:
        t = self.now() if t is None else t
        return int(t // self.slot_seconds)

    def slot_start(self, t: float | None = None) -> float:
        t = self.now() if t is None else t
        return self.slot_index(t) * self.slot_seconds

    def time_to_next_slot(self) -> float:
        t = self.now()
        return self.slot_seconds - (t % self.slot_seconds)

    def elapsed_in_slot(self) -> float:
        return self.now() % self.slot_seconds

    def utc_string(self, t: float | None = None) -> str:
        t = self.now() if t is None else t
        return time.strftime("%H:%M:%S", time.gmtime(t))

    def slot_utc(self, t: float | None = None) -> str:
        return self.utc_string(self.slot_start(t))
