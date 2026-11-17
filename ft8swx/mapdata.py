"""Dados do mapa de conexoes (sem Qt): estacoes do log, distancias e arcos."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache

from .adif import QsoRecord, band_from_mhz, filter_records
from .grid import distance_bearing, grid_to_latlon

_GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")

PERIODS: list[tuple[str, int]] = [("Tudo", 0), ("24 h", 1), ("7 dias", 7), ("30 dias", 30)]


def valid_grid(grid: str) -> bool:
    return bool(grid) and bool(_GRID_RE.match(grid.strip().upper()))


@dataclass
class Link:
    call: str
    grid: str
    lat: float
    lon: float
    km: float
    bearing: float
    qsos: int = 1
    bands: list[str] = field(default_factory=list)
    last: str = ""                 # AAAAMMDD HHMMSS do QSO mais recente


def since_for_days(days: int, now: float | None = None) -> str:
    """AAAAMMDD de `days` dias atras (UTC). 0 = sem limite."""
    if days <= 0:
        return ""
    t = (time.time() if now is None else now) - days * 86400
    return time.strftime("%Y%m%d", time.gmtime(t))


def build_links(records: list[QsoRecord], my_grid: str, band: str = "",
                since: str = "") -> tuple[list[Link], int]:
    """Uma entrada por indicativo (QSOs repetidos em outras bandas viram contagem).

    Retorna (links ordenados do mais longe para o mais perto, qtd de QSOs sem grid valido).
    """
    if not valid_grid(my_grid):
        return [], 0
    recs = filter_records(records, since=since, band=band)
    by_call: dict[str, Link] = {}
    skipped = 0
    for r in recs:
        call = r.call.upper()
        if not valid_grid(r.grid):
            skipped += 1
            continue
        stamp = f"{r.qso_date} {r.time_on}"
        b = (r.band or band_from_mhz(r.freq_mhz)).upper()
        lk = by_call.get(call)
        if lk is None:
            db = distance_bearing(my_grid, r.grid)
            pos = grid_to_latlon(r.grid)
            if db is None or pos is None:
                skipped += 1
                continue
            by_call[call] = Link(call, r.grid.upper(), pos[0], pos[1], db[0], db[1],
                                 1, [b] if b else [], stamp)
            continue
        lk.qsos += 1
        if b and b not in lk.bands:
            lk.bands.append(b)
        if stamp > lk.last:
            lk.last = stamp
            if r.grid.upper() != lk.grid:   # usa o grid mais recente
                db = distance_bearing(my_grid, r.grid)
                pos = grid_to_latlon(r.grid)
                if db and pos:
                    lk.grid, lk.lat, lk.lon = r.grid.upper(), pos[0], pos[1]
                    lk.km, lk.bearing = db
    return sorted(by_call.values(), key=lambda x: -x.km), skipped


def summarize(links: list[Link]) -> dict:
    if not links:
        return {"stations": 0, "qsos": 0, "farthest": None, "avg_km": 0.0, "total_km": 0.0}
    far = max(links, key=lambda x: x.km)
    return {
        "stations": len(links),
        "qsos": sum(x.qsos for x in links),
        "farthest": far,
        "avg_km": sum(x.km for x in links) / len(links),
        "total_km": sum(x.km for x in links),
    }


def great_circle(lat1: float, lon1: float, lat2: float, lon2: float,
                 n: int = 64) -> list[list[tuple[float, float]]]:
    """Arco de circulo maximo como lista de segmentos [(lon, lat), ...].

    O arco e' cortado onde cruza o antimeridiano (±180°) para nao desenhar
    uma linha atravessando o mapa inteiro.
    """
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2, l2 = math.radians(lat2), math.radians(lon2)

    def vec(p, l):
        return (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))

    a, b = vec(p1, l1), vec(p2, l2)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    omega = math.acos(dot)
    if omega < 1e-9:
        return [[(lon1, lat1), (lon2, lat2)]]
    so = math.sin(omega)
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        ka = math.sin((1 - t) * omega) / so if abs(so) > 1e-9 else 1 - t
        kb = math.sin(t * omega) / so if abs(so) > 1e-9 else t
        x = ka * a[0] + kb * b[0]
        y = ka * a[1] + kb * b[1]
        z = ka * a[2] + kb * b[2]
        pts.append((math.degrees(math.atan2(y, x)),
                    math.degrees(math.atan2(z, math.hypot(x, y)))))

    segs: list[list[tuple[float, float]]] = [[pts[0]]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if abs(x1 - x0) > 180:
            edge = 180.0 if x0 > 0 else -180.0
            f = (edge - x0) / ((x1 + (360 if x0 > 0 else -360)) - x0)
            ye = y0 + (y1 - y0) * f
            segs[-1].append((edge, ye))
            segs.append([(-edge, ye)])
        segs[-1].append((x1, y1))
    return segs


@lru_cache(maxsize=1)
def load_world() -> list[list[float]]:
    """Aneis do mapa-mundi como listas planas [lon, lat, lon, lat, ...].

    Fonte: Natural Earth 110m (dominio publico), em ft8swx/data/world.json.
    Se o arquivo faltar, devolve lista vazia (o mapa so perde o fundo).
    """
    try:
        from .native import resource_path

        p = resource_path("ft8swx", "data", "world.json")
        return json.loads(p.read_text(encoding="utf-8"))["rings"]
    except Exception:
        return []
