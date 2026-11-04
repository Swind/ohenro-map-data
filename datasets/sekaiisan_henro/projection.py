"""Local equirectangular metric projection for 88sekaiisan topology analysis.

Per plan §4.1: a fixed, deterministic local metric projection centred near
Shikoku is used only for relative topology / distance comparisons. WGS84
(lon/lat) remains authoritative; every result preserves WGS84 coordinates and
this projection's output is never claimed as navigation-grade.
"""

from __future__ import annotations

import math

# Mean Earth radius in metres and the fixed reference point (Shikoku central).
R = 6371008.8
LON0 = 133.75
LAT0 = 33.65

_LAT0_RAD = math.radians(LAT0)
_COS_LAT0 = math.cos(_LAT0_RAD)

# Deterministic metadata recorded verbatim in any inventory/report output.
PROJECTION_METADATA = {"kind": "equirectangular", "R": R, "lon0": LON0, "lat0": LAT0}

_LIMITATION_NOTE = (
    "equirectangular local projection: relative metric distances are approximate "
    "(percent-level distortion away from lat0=%.2f); not a navigation-grade "
    "measurement. WGS84 lon/lat remains authoritative."
)


def limitation_note() -> str:
    """Documented accuracy limitation to embed in reports."""
    return _LIMITATION_NOTE % LAT0


def project_point(lon: float, lat: float) -> tuple[float, float]:
    """Map one WGS84 (lon, lat) degree pair to local metric (x, y) metres."""
    x = R * math.radians(lon - LON0) * _COS_LAT0
    y = R * math.radians(lat - LAT0)
    return (x, y)


def unproject_point(x: float, y: float) -> tuple[float, float]:
    """Inverse of :func:`project_point`: local metric (x, y) -> (lon, lat)."""
    lon = LON0 + math.degrees(x / (R * _COS_LAT0))
    lat = LAT0 + math.degrees(y / R)
    return (lon, lat)


def project_coords(coords):
    """Project a list of (lon, lat) pairs to a list of metric (x, y) pairs."""
    return [project_point(lon, lat) for lon, lat in coords]


def unproject_coords(xys):
    """Inverse of :func:`project_coords`; returns list of (lon, lat) pairs."""
    return [unproject_point(x, y) for x, y in xys]