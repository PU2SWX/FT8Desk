"""Maidenhead (grid square): conversao, distancia e azimute."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def grid_to_latlon(grid: str) -> tuple[float, float] | None:
    """Centro do grid. Aceita 4 ou 6 caracteres (ex.: GG66, GG66aa)."""
    if not grid:
        return None
    g = grid.strip().upper()
    if len(g) < 4:
        return None
    try:
        lon = float((ord(g[0]) - ord("A")) * 20 - 180)
        lat = float((ord(g[1]) - ord("A")) * 10 - 90)
        lon += int(g[2]) * 2
        lat += int(g[3]) * 1
        lon += 1
        lat += 0.5
        if len(g) >= 6:
            lon += (ord(g[4]) - ord("A")) * (2 / 24) - 1 + (1 / 24)
            lat += (ord(g[5]) - ord("A")) * (1 / 24) - 0.5 + (1 / 48)
        return (lat, lon)
    except (ValueError, IndexError):
        return None


def latlon_to_grid(lat: float, lon: float, precision: int = 6) -> str:
    lon = (lon + 180.0) % 360.0
    lat = max(-90.0, min(90.0, lat)) + 90.0
    A = ord("A")
    g = chr(A + int(lon // 20)) + chr(A + int(lat // 10))
    g += str(int((lon % 20) // 2)) + str(int(lat % 10))
    if precision >= 6:
        g += chr(A + int((lon % 2) * 12)) + chr(A + int((lat % 1) * 24))
    return g


def distance_bearing(grid1: str, grid2: str) -> tuple[float, float] | None:
    """(km, azimute em graus) do grid1 para o grid2."""
    p1 = grid_to_latlon(grid1)
    p2 = grid_to_latlon(grid2)
    if not p1 or not p2:
        return None
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    d = 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return (d, brg)


def compass_point(bearing: float) -> str:
    pts = ["N", "NNE", "NE", "ENE", "L", "ESE", "SE", "SSE",
           "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return pts[int((bearing + 11.25) % 360 // 22.5)]
