"""Configuracao persistente e tabela de bandas."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .ptt import PttConfig

# Frequencias de discagem FT8 (USB) mais usadas, em MHz
BANDS: list[tuple[str, float]] = [
    ("160m", 1.840), ("80m", 3.573), ("60m", 5.357), ("40m", 7.074),
    ("30m", 10.136), ("20m", 14.074), ("17m", 18.100), ("15m", 21.074),
    ("12m", 24.915), ("10m", 28.074), ("6m", 50.313), ("2m", 144.174),
]

BAND_DEFAULT_OFFSET = 1500.0  # Hz de audio, dentro da faixa


def app_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "FT8Desk"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    my_call: str = ""
    my_grid: str = ""
    mode: str = "FT8"
    band: str = "20m"
    dial_mhz: float = 14.074
    tx_offset_hz: float = 1500.0
    tx_offset_s: float = 0.5          # inicio da transmissao dentro do slot
    tx_report: int = -10
    tx_parity: str = "auto"           # auto | even | odd
    auto_seq: bool = True             # responder automaticamente
    auto_cq: bool = False             # repetir CQ sozinho ao terminar um QSO
    auto_call_cq: bool = False        # modo AUTO: chamar quem esta em CQ
    auto_min_snr: float = -18.0
    auto_skip_worked: bool = True
    auto_skip_cq_dx: bool = True
    max_repeats: int = 4
    ntp_sync: bool = True
    ptt: PttConfig = field(default_factory=PttConfig)
    input_device: int | None = None
    output_device: int | None = None
    input_rate: int = 48000
    output_rate: int = 48000
    tx_gain: float = 0.5
    log_path: str = ""

    # -- io ------------------------------------------------------------
    @staticmethod
    def default_log() -> Path:
        return app_dir() / "ft8desk.adi"

    def ensure_log(self) -> Path:
        return Path(self.log_path) if self.log_path else self.default_log()

    def save(self, path: Path | None = None) -> Path:
        p = path or (app_dir() / "settings.json")
        data = asdict(self)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return p

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        p = path or (app_dir() / "settings.json")
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        ptt = data.pop("ptt", {}) or {}
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known and k != "ptt"}
        s = cls(**clean)
        ptt_known = set(PttConfig.__dataclass_fields__)  # type: ignore[attr-defined]
        s.ptt = PttConfig(**{k: v for k, v in ptt.items() if k in ptt_known})
        return s
