"""Interpretacao de mensagens FT8 decodificadas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CALL_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z]{1,4}(/[A-Z0-9]{1,3})?$")
GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")
REPORT_RE = re.compile(r"^[+-]?[0-9]{2}$")

TOKENS = {"CQ", "DE", "QRZ", "73", "RR73", "RRR", "TU", "R", "RR", "QSL", "QRZ?"}


@dataclass
class Parsed:
    raw: str
    tokens: list[str]
    call_from: str = ""      # quem transmitiu
    call_to: str = ""        # destinatario ("" se CQ)
    grid: str = ""
    report: int | None = None
    token: str = ""          # RR73, 73, RRR...
    cq_modifier: str = ""    # "DX" de "CQ DX", "POTA", "TEST"...
    is_cq: bool = False
    is_hashed: bool = False

    @property
    def summary(self) -> str:
        return self.raw


def parse_message(raw: str, my_call: str = "") -> Parsed:
    """Interpreta um texto FT8 tipo 'CQ PY2ABC GG66' ou 'W1AW PY2ABC -12'."""
    text = " ".join(raw.strip().split())
    toks = text.split(" ")
    p = Parsed(raw=text, tokens=toks)
    p.is_hashed = "<" in text

    if not toks:
        return p

    if toks[0].upper() == "CQ":
        p.is_cq = True
        rest = toks[1:]
        # CQ DX / CQ POTA / CQ TEST ...
        mods: list[str] = []
        while rest and (rest[0].isalpha() and not CALL_RE.match(rest[0])
                        and not GRID_RE.match(rest[0])):
            mods.append(rest[0])
            rest = rest[1:]
        p.cq_modifier = " ".join(mods).upper()
        if rest:
            p.call_from = rest[0]
        if len(rest) > 1:
            for t in rest[1:]:
                if GRID_RE.match(t.upper()):
                    p.grid = t.upper()
                    break
                if REPORT_RE.match(t):
                    p.report = int(t)
        return p

    # destinatario primeiro? "W1AW PY2ABC ..." -> quem fala e' o 2o
    if len(toks) >= 2:
        a, b = toks[0], toks[1]
        if my_call and a.upper().startswith(my_call.upper()[:2]):
            pass
        p.call_to, p.call_from = a, b

        for t in toks[2:]:
            tu = t.upper()
            # "R-10" / "R+05": relatorio com acuse de recebimento
            if len(tu) > 1 and tu.startswith("R") and REPORT_RE.match(tu[1:]):
                p.report = int(tu[1:])
                p.token = "R"
                continue
            if tu in TOKENS or tu.startswith("RR") or tu.startswith("73"):
                p.token = tu
            elif GRID_RE.match(tu):
                p.grid = tu
            elif REPORT_RE.match(t):
                p.report = int(t)
    elif len(toks) == 1:
        p.call_from = toks[0]

    return p


def directed_to(parsed: Parsed, my_call: str) -> bool:
    if not my_call or not parsed.call_to:
        return False
    return parsed.call_to.upper() == my_call.upper()


def is_73(parsed: Parsed) -> bool:
    return parsed.token in ("73", "RR73") or "73" in parsed.tokens


def is_roger(parsed: Parsed) -> bool:
    return parsed.token in ("RRR", "RR73", "RR", "R") or "RR73" in parsed.tokens
