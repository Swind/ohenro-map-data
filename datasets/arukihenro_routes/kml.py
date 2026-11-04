"""Parse Google My Maps KML exports into plain line/point records."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from datasets.arukihenro_routes.classify import classify_point, line_source

_KML = "{http://www.opengis.net/kml/2.2}"


def _find(elem, tag):
    return elem.find(_KML + tag)


def _text(elem, tag):
    child = _find(elem, tag)
    return child.text if child is not None else None


def _coords_line(element) -> list[list[float]]:
    coords = _text(element, "coordinates")
    if not coords:
        return []
    points = []
    for part in coords.strip().split():
        tokens = part.split(",")
        if len(tokens) >= 2:
            points.append([float(tokens[0]), float(tokens[1])])
    return points


def _coords_point(element) -> list[float] | None:
    coords = _coords_line(element)
    return coords[0] if coords else None


def _photos(placemark) -> list[str]:
    for data in placemark.findall(".//" + _KML + "Data"):
        if (data.get("name") or "") == "gx_media_links":
            value = _text(data, "value") or ""
            urls = []
            for url in value.split():
                if url not in urls:
                    urls.append(url)
            return urls
    return []


def parse_kml(data: bytes) -> dict:
    """Parse a KML export into ``{name, description, lines, points}``.

    Lines and points are emitted in document order with their enclosing
    Folder name preserved. Coordinates are reduced to ``[lon, lat]``.
    Points carry a unified ``category`` and ``photos`` from
    ``gx_media_links``; lines carry a ``source`` of ``google_directions``
    or ``manual``.
    """
    root = ET.fromstring(data)
    document = _find(root, "Document")
    if document is None:
        document = root
    name = _text(document, "name")
    description = _text(document, "description")

    lines = []
    points = []

    def visit(container, folder):
        for element in container:
            tag = element.tag.split("}", 1)[-1]
            if tag == "Folder":
                visit(element, _text(element, "name"))
                continue
            if tag != "Placemark":
                continue
            placemark = element
            pm_name = (_text(placemark, "name") or "").strip()
            line = _find(placemark, "LineString")
            if line is not None:
                lines.append({
                    "name": pm_name,
                    "folder": folder,
                    "source": line_source(pm_name),
                    "coordinates": _coords_line(line),
                })
                continue
            point = _find(placemark, "Point")
            if point is not None:
                coordinates = _coords_point(point)
                if coordinates is None:
                    continue
                points.append({
                    "name": pm_name,
                    "folder": folder,
                    "category": classify_point(pm_name),
                    "coordinates": coordinates,
                    "photos": _photos(placemark),
                })

    visit(document, None)
    return {"name": name, "description": description, "lines": lines, "points": points}