"""Log de QSOs em ADIF (3.1.4) — gravacao, leitura e campos extras."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

# ADIF 3.1.4. O QRZ Logbook exige CALL, QSO_DATE, BAND e MODE por registro.
ADIF_VERSION = "3.1.4"
PROGRAM_ID = "FT8SWX"
PROGRAM_VERSION = "0.9.0"

# Estilos de MODE/SUBMODE aceitos por cada destino.
#   "qrz"  -> MODE=FT8  (o que o QRZ Logbook e o WSJT-X usam)
#   "lotw" -> MODE=MFSK + SUBMODE=FT8 (forma historica do LoTW)
MODE_STYLES = {
    "qrz": {"FT8": ("FT8", ""), "FT4": ("FT4", "")},
    "lotw": {"FT8": ("MFSK", "FT8"), "FT4": ("MFSK", "FT4")},
}


def adif_header(mode_style: str = "qrz") -> str:
    return (
        f"FT8SWX ADIF export ({mode_style})\n"
        f"<ADIF_VER:{len(ADIF_VERSION)}>{ADIF_VERSION}"
        f"<PROGRAMID:{len(PROGRAM_ID)}>{PROGRAM_ID}"
        f"<PROGRAMVERSION:{len(PROGRAM_VERSION)}>{PROGRAM_VERSION}"
        "<EOH>\n"
    )


@dataclass
class QsoRecord:
    call: str = ""
    grid: str = ""
    freq_mhz: float = 0.0
    mode: str = "FT8"
    rst_sent: str = "-10"
    rst_rcvd: str = "-10"
    qso_date: str = ""
    time_on: str = ""
    time_off: str = ""
    band: str = ""
    my_call: str = ""
    my_grid: str = ""
    comment: str = ""

    def adif(self, mode_style: str = "qrz") -> str:
        d = self.qso_date or time.strftime("%Y%m%d", time.gmtime())
        t = self.time_on or time.strftime("%H%M%S", time.gmtime())
        band = self.band or band_from_mhz(self.freq_mhz)
        mode, submode = MODE_STYLES.get(
            mode_style, MODE_STYLES["qrz"]).get(self.mode.upper(), (self.mode, ""))
        fields = [
            ("CALL", self.call),                      # obrigatorio no QRZ
            ("QSO_DATE", d),                          # obrigatorio no QRZ
            ("TIME_ON", t),
            ("BAND", band),                           # obrigatorio no QRZ
            ("MODE", mode),                           # obrigatorio no QRZ
            ("SUBMODE", submode),
            ("GRIDSQUARE", self.grid),
            ("RST_SENT", self.rst_sent),
            ("RST_RCVD", self.rst_rcvd),
            ("QSO_DATE_OFF", d),
            ("TIME_OFF", self.time_off or t),
            ("FREQ", f"{self.freq_mhz:.6f}" if self.freq_mhz else ""),
            ("STATION_CALLSIGN", self.my_call),
            ("MY_GRIDSQUARE", self.my_grid),
            ("COMMENT", self.comment),
        ]
        out = []
        for k, v in fields:
            if v == "" or v is None:
                continue
            v = _ascii(str(v))          # ADIF conta caracteres, nao bytes
            out.append(f"<{k}:{len(v)}>{v}")
        return "".join(out) + "<EOR>\n"


def _ascii(text: str) -> str:
    """Remove acentos: o comprimento em ADIF e' de caracteres e a maioria dos
    servidores (QRZ, LoTW) le bytes -- manter ASCII evita registro corrompido."""
    import unicodedata

    return (unicodedata.normalize("NFKD", text)
            .encode("ascii", "ignore").decode("ascii"))


def band_from_mhz(mhz: float) -> str:
    table = [
        (1.8, 2.0, "160M"), (3.5, 4.0, "80M"), (5.3, 5.4, "60M"), (7.0, 7.3, "40M"),
        (10.1, 10.15, "30M"), (14.0, 14.35, "20M"), (18.068, 18.168, "17M"),
        (21.0, 21.45, "15M"), (24.89, 24.99, "12M"), (28.0, 29.7, "10M"),
        (50.0, 54.0, "6M"), (144.0, 148.0, "2M"), (430.0, 450.0, "70CM"),
    ]
    for lo, hi, name in table:
        if lo <= mhz <= hi:
            return name
    return ""


class AdifLog:
    """Log append-only; cada QSO e' gravado imediatamente em disco."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records: list[QsoRecord] = []
        self._ensure_file()
        self.reload()

    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.write_text(adif_header(), encoding="utf-8")

    def reload(self) -> None:
        self.records = read_adif(self.path)

    def append(self, rec: QsoRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(rec.adif())
        self.records.append(rec)

    def archive(self) -> Path:
        """Renomeia o log atual para um backup e comeca um novo.

        Nada e' apagado: o arquivo antigo continua na pasta com data/hora.
        """
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = self.path.with_name(f"{self.path.stem}-backup-{ts}{self.path.suffix}")
        if self.path.exists():
            os.replace(self.path, dest)
        self.records = []
        self._ensure_file()
        return dest

    def export(self, path: str | Path, records: list[QsoRecord] | None = None,
               mode_style: str = "qrz") -> int:
        """Grava um ADIF completo (cabecalho + registros). Retorna n de QSOs."""
        recs = self.records if records is None else records
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(adif_header(mode_style))
            for r in recs:
                fh.write(r.adif(mode_style))
        return len(recs)

    def worked_calls(self, band: str = "") -> set[str]:
        """Indicativos ja trabalhados. Com `band`, considera so' aquela banda:
        um QSO em 40 m nao impede chamar a mesma estacao em 20 m."""
        if not band:
            return {r.call.upper() for r in self.records if r.call}
        b = band.upper()
        return {r.call.upper() for r in self.records
                if r.call and (r.band or band_from_mhz(r.freq_mhz)).upper() == b}

    def find(self, call: str) -> list[QsoRecord]:
        c = call.upper()
        return [r for r in self.records if r.call.upper() == c]


def filter_records(records: list[QsoRecord], since: str = "", until: str = "",
                   band: str = "", mode: str = "",
                   dedupe: bool = False) -> list[QsoRecord]:
    """Filtra por data (AAAAMMDD), banda e modo. since/until inclusivos."""
    out = []
    seen: set[tuple[str, str, str]] = set()
    for r in records:
        if since and r.qso_date and r.qso_date < since:
            continue
        if until and r.qso_date and r.qso_date > until:
            continue
        if band and (r.band or band_from_mhz(r.freq_mhz)).upper() != band.upper():
            continue
        if mode and r.mode.upper() != mode.upper():
            continue
        if dedupe:
            key = (r.call.upper(), r.qso_date, (r.time_on or "")[:4])
            if key in seen:
                continue
            seen.add(key)
        out.append(r)
    return out


def _record_dt(rec: QsoRecord):
    from datetime import datetime

    try:
        return datetime.strptime((rec.qso_date or "") + (rec.time_on or "")[:6],
                                 "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None


def is_recent_duplicate(records: list[QsoRecord], rec: QsoRecord,
                        window_minutes: float = 10.0) -> bool:
    """True se ja existe QSO com o mesmo indicativo/banda/modo na janela.

    Evita a repeticao de registros quando o outro lado nao copia o nosso
    RR73/73 e a sequencia recomeca varias vezes seguidas.
    """
    t = _record_dt(rec)
    if t is None:
        return False
    band = (rec.band or band_from_mhz(rec.freq_mhz)).upper()
    for r in records:
        if r.call.upper() != rec.call.upper():
            continue
        if (r.band or band_from_mhz(r.freq_mhz)).upper() != band:
            continue
        if r.mode.upper() != rec.mode.upper():
            continue
        rt = _record_dt(r)
        if rt is None:
            continue
        if abs((t - rt).total_seconds()) <= window_minutes * 60.0:
            return True
    return False


def read_adif(path: str | Path) -> list[QsoRecord]:
    p = Path(path)
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8", errors="replace")
    body = txt.split("<EOH>", 1)[-1]
    out: list[QsoRecord] = []
    for chunk in body.split("<EOR>"):
        if not chunk.strip():
            continue
        fields: dict[str, str] = {}
        i = 0
        n = len(chunk)
        while i < n:
            j = chunk.find("<", i)
            if j < 0:
                break
            k = chunk.find(">", j)
            if k < 0:
                break
            spec = chunk[j + 1:k]
            if ":" in spec:
                name, rest = spec.split(":", 1)
                try:
                    length = int(rest.split(":")[0])
                except ValueError:
                    i = k + 1
                    continue
                val = chunk[k + 1:k + 1 + length]
                fields[name.upper()] = val
                i = k + 1 + length
            else:
                i = k + 1
        if not fields.get("CALL"):
            continue
        out.append(QsoRecord(
            call=fields.get("CALL", ""),
            grid=fields.get("GRIDSQUARE", ""),
            freq_mhz=float(fields.get("FREQ", 0) or 0),
            mode=fields.get("MODE", "FT8"),
            rst_sent=fields.get("RST_SENT", ""),
            rst_rcvd=fields.get("RST_RCVD", ""),
            qso_date=fields.get("QSO_DATE", ""),
            time_on=fields.get("TIME_ON", ""),
            time_off=fields.get("TIME_OFF", ""),
            band=fields.get("BAND", ""),
            my_call=fields.get("STATION_CALLSIGN", ""),
            my_grid=fields.get("MY_GRIDSQUARE", ""),
            comment=fields.get("COMMENT", ""),
        ))
    return out
