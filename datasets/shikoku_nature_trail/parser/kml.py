"""Parse archived KML into deterministic GeoJSON-compatible structures."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET


def _local(element, name):
    return next((child for child in element if child.tag.rsplit("}", 1)[-1] == name), None)


def _text(element, name):
    child = _local(element, name)
    return child.text.strip() if child is not None and child.text and child.text.strip() else None


def _plain_text(value):
    if not value:
        return None
    value = re.sub(r"(?i)<br\s*/?>", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split()) or None


def _coordinates(value):
    coordinates = []
    for tuple_ in (value or "").split():
        parts = tuple_.split(",")
        if len(parts) not in (2, 3):
            raise ValueError("KML coordinate must contain lon, lat and optional altitude")
        coordinates.append([float(number) for number in parts])
    return coordinates


def _geometry(element):
    kind = element.tag.rsplit("}", 1)[-1]
    if kind == "Point":
        values = _coordinates(_text(element, "coordinates"))
        if len(values) != 1:
            raise ValueError("KML Point must contain exactly one coordinate")
        return {"type": "Point", "coordinates": values[0]}
    if kind == "LineString":
        return {"type": "LineString", "coordinates": _coordinates(_text(element, "coordinates"))}
    if kind == "MultiGeometry":
        geometries = [geometry for child in element
                      if (geometry := _geometry(child)) is not None]
        return {"type": "GeometryCollection", "geometries": geometries}
    return None


def parse_kml(data):
    """Parse KML bytes or text; malformed XML and coordinates raise ValueError."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("malformed KML: %s" % error) from error

    document = next((item for item in root.iter()
                     if item.tag.rsplit("}", 1)[-1] == "Document"), root)
    placemarks = []
    for placemark in root.iter():
        if placemark.tag.rsplit("}", 1)[-1] != "Placemark":
            continue
        geometries = [geometry for child in placemark
                      if (geometry := _geometry(child)) is not None]
        if not geometries:
            geometry = None
        elif len(geometries) == 1:
            geometry = geometries[0]
        else:
            geometry = {"type": "GeometryCollection", "geometries": geometries}
        placemarks.append({
            "name": _text(placemark, "name"),
            "description": _plain_text(_text(placemark, "description")),
            "geometry": geometry,
        })
    return {
        "name": _text(document, "name"),
        "description": _plain_text(_text(document, "description")),
        "placemarks": placemarks,
    }
