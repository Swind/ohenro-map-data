"""Strict, namespace-agnostic KML parsing for 88sekaiisan route/temple files.

Phase 1 normalization only. No topology, anchoring, or section inference lives
here; this module extracts raw, validated geometry plus conservative identity
(FID / temple number) that the orchestration layer (`normalize.py`) aggregates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ElementTree

_FID_RE = re.compile(r"<td>FID</td>\s*<td>\s*([^<]+?)\s*</td>", re.DOTALL)
_TEMPLE_NUMBER_RE = re.compile(r"第\s*(\d+)\s*番")

# KML geometry element names (namespace-stripped) that must be explicitly
# accounted for. Anything in this set that is not supported by a given
# Placemark context raises ValueError instead of being silently dropped.
_GEOMETRY_TAGS = frozenset({
    "Point", "LineString", "LinearRing", "Polygon",
    "MultiGeometry", "MultiPoint", "MultiLineString", "MultiPolygon", "Model",
    "Track", "MultiTrack",
})

# Namespace-agnostic helpers ------------------------------------------------


def _name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, name: str):
    return next((item for item in element if _name(item) == name), None)


def _text(element: ElementTree.Element, name: str) -> str | None:
    child = _child(element, name)
    return child.text if child is not None else None


def _coordinates(value: str | None, geometry_type: str) -> list[list[float]]:
    """Parse a KML <coordinates> block into [[lon, lat], ...] (altitude dropped).

    Validates finite values, lon/lat bounds, and cardinality for the geometry
    type. Raises ValueError on malformed input.
    """
    coordinates: list[list[float]] = []
    for tuple_ in (value or "").split():
        parts = tuple_.split(",")
        if len(parts) not in (2, 3):
            raise ValueError("%s coordinate must contain lon,lat[,alt]" % geometry_type)
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError as error:
            raise ValueError("%s coordinate is not numeric" % geometry_type) from error
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError("%s coordinate must be finite" % geometry_type)
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("%s coordinate is outside valid longitude/latitude bounds" % geometry_type)
        coordinates.append([lon, lat])
    if geometry_type == "Point" and len(coordinates) != 1:
        raise ValueError("KML Point must contain exactly one coordinate")
    if geometry_type == "LineString" and len(coordinates) < 2:
        raise ValueError("KML LineString must contain at least two coordinates")
    return coordinates


def _parse_kml_root(data: bytes | str) -> ElementTree.Element:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("malformed KML: %s" % error) from error
    if _name(root) != "kml":
        raise ValueError("KML root element is missing")
    return root


def _line_coordinates(line: ElementTree.Element) -> list[list[float]]:
    coordinates = _text(line, "coordinates")
    return _coordinates(coordinates, "LineString")


# Route parsing ---------------------------------------------------------------


def _route_fid(description: str | None) -> str | None:
    """Conservatively parse source FID from the description attribute table."""
    if not description:
        return None
    match = _FID_RE.search(description)
    return match.group(1).strip() if match else None


def parse_route_file(data: bytes | str, prefecture: str) -> dict:
    """Parse one routes/<prefecture>.kml into stable route records.

    Returns {"placemark_count": int, "missing_source_fid": int,
    "records": [route, ...]} where each record corresponds to a single
    LineString part. Raises ValueError for duplicate source FID within the
    file, a duplicate geometry identity among FID-less Placemarks, unsupported
    geometry, or invalid coordinates. Missing FID is accounted for (a source
    fact), not fatal.
    """
    root = _parse_kml_root(data)
    records: list[dict] = []
    fids: dict[str, int] = {}
    geometry_ids: dict[str, int] = {}
    placemark_count = 0
    missing_source_fid = 0
    for placemark in _iter_placemarks(root):
        placemark_count += 1
        raw_name = _text(placemark, "name") or ""
        raw_description = _text(placemark, "description") or ""
        parts = _collect_line_parts(placemark, prefecture)
        if not parts:
            raise ValueError(
                "route placemark #%d in %s has no LineString geometry" % (placemark_count, prefecture)
            )

        fid = _route_fid(raw_description)
        if fid is None:
            missing_source_fid += 1
            geometry_hash = _geometry_hash(parts)
            if geometry_hash in geometry_ids:
                raise ValueError(
                    "duplicate geometry identity in %s: %s" % (prefecture, geometry_hash)
                )
            geometry_ids[geometry_hash] = placemark_count
            identity = "geometry_%s" % geometry_hash[:16]
            identity_kind = "geometry_sha256"
        else:
            fids[fid] = fids.get(fid, 0) + 1
            identity = fid
            identity_kind = "fid"
            geometry_hash = None

        for part_index, coordinates in enumerate(parts, start=1):
            record = {
                "id": "SHR_%s_%s_%d" % (prefecture, identity, part_index),
                "prefecture": prefecture,
                "source_fid": fid,
                "source_identity": identity,
                "source_identity_kind": identity_kind,
                "part": part_index,
                "source_order": placemark_count - 1,
                "raw_name": raw_name,
                "raw_description": raw_description,
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
            if geometry_hash is not None:
                record["geometry_sha256"] = geometry_hash
            records.append(record)

    duplicates = sorted(fid for fid, count in fids.items() if count > 1)
    if duplicates:
        raise ValueError("duplicate route FID in %s: %s" % (prefecture, ", ".join(duplicates)))
    return {"placemark_count": placemark_count, "missing_source_fid": missing_source_fid, "records": records}


def _iter_placemarks(root: ElementTree.Element):
    for element in root.iter():
        if _name(element) == "Placemark":
            yield element


def _geometry_hash(parts: list[list[list[float]]]) -> str:
    """Deterministic SHA-256 of all normalized LineString parts of a Placemark."""
    canonical = json.dumps(parts, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _collect_line_parts(placemark: ElementTree.Element, prefecture: str) -> list[list[list[float]]]:
    """Return every LineString's coordinates (direct + recursive MultiGeometry).

    Fails explicitly on any other geometry (Point/Polygon/etc.) under the
    Placemark or a nested MultiGeometry.
    """
    parts: list[list[list[float]]] = []
    _walk_route_geometry(placemark, parts, prefecture, "Placemark")
    return parts


def _walk_route_geometry(element, parts, prefecture, context) -> None:
    for child in element:
        kind = _name(child)
        if kind not in _GEOMETRY_TAGS:
            continue  # non-geometry (name/description/styleUrl) is ignored
        if kind == "LineString":
            parts.append(_line_coordinates(child))
        elif kind == "MultiGeometry":
            _walk_route_geometry(child, parts, prefecture, "MultiGeometry")
        else:
            raise ValueError(
                "unsupported %s geometry in %s route: %s" % (context, prefecture, kind)
            )


# Temple parsing --------------------------------------------------------------


def _temple_display_name(raw_name: str) -> str:
    """Conservative Japanese display name from the raw temple name.

    NFKC-normalizes, drops the leading ``第N番札所`` marker and a trailing
    parenthetical romanization group, then collapses whitespace.
    """
    name = unicodedata.normalize("NFKC", raw_name or "")
    name = re.sub(r"^第\s*\d+\s*番札所", "", name).strip()
    name = re.sub(r"[（(][^)）]*[)）]$", "", name).strip()
    name = re.sub(r"[\s\u3000]+", "", name)
    return name


def parse_temple_file(data: bytes | str, source_file: str) -> list[dict]:
    """Parse one temples/<range>.kml into temple records with unique numbers.

    Each temple Placemark must contain exactly one direct Point and no other
    geometry. Raises ValueError for a missing Point, multiple Points, any
    unsupported geometry, a missing/non-1..88 number, or invalid coordinates.
    Duplicate numbers are validated by the caller across all four temple files.
    """
    root = _parse_kml_root(data)
    temples: list[dict] = []
    for placemark in _iter_placemarks(root):
        raw_name = _text(placemark, "name") or ""
        points = []
        for child in placemark:
            kind = _name(child)
            if kind == "Point":
                points.append(child)
            elif kind in _GEOMETRY_TAGS:
                raise ValueError("unsupported geometry in temple placemark: %s" % kind)
        if len(points) != 1:
            raise ValueError("temple placemark must contain exactly one Point: %r" % raw_name)
        coordinate = _coordinates(_text(points[0], "coordinates"), "Point")[0]

        match = _TEMPLE_NUMBER_RE.search(unicodedata.normalize("NFKC", raw_name))
        if not match:
            raise ValueError("temple name has no 第N番 number: %r" % raw_name)
        number = int(match.group(1))
        if not 1 <= number <= 88:
            raise ValueError("temple number out of range 1..88: %d" % number)
        temples.append({
            "id": "TEMPLE_%d" % number,
            "number": number,
            "raw_name": raw_name,
            "name_jp": _temple_display_name(raw_name),
            "geometry": {"type": "Point", "coordinates": coordinate},
            "source_file": source_file,
        })
    return temples