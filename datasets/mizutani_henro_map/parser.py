"""Parse a Mizutani Google My Maps KML snapshot without inferring semantics."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ElementTree

ICON_STYLE_RE = re.compile(r"^#icon-(\d+)-([0-9A-Fa-f]{6})(?:-[A-Za-z0-9_-]+)?$")


def _name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, name: str):
    return next((item for item in element if _name(item) == name), None)


def _text(element: ElementTree.Element, name: str) -> str | None:
    child = _child(element, name)
    return child.text if child is not None else None


def _color(value: str | None) -> dict | None:
    if not value:
        return None
    value = value.strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{8}", value):
        return {"raw": value, "rgb": None}
    return {"raw": value, "rgb": ("#" + value[6:8] + value[4:6] + value[2:4]).upper()}


def _coordinates(value: str | None, geometry_type: str) -> list[list[float]]:
    coordinates = []
    for tuple_ in (value or "").split():
        values = tuple_.split(",")
        if len(values) not in (2, 3):
            raise ValueError("%s coordinate must contain lon,lat[,alt]" % geometry_type)
        try:
            coordinate = [float(number) for number in values]
        except ValueError as error:
            raise ValueError("%s coordinate is not numeric" % geometry_type) from error
        if not all(math.isfinite(number) for number in coordinate) or not (-180 <= coordinate[0] <= 180 and -90 <= coordinate[1] <= 90):
            raise ValueError("%s coordinate is outside valid longitude/latitude bounds" % geometry_type)
        coordinates.append(coordinate)
    if geometry_type == "Point" and len(coordinates) != 1:
        raise ValueError("KML Point must contain exactly one coordinate")
    if geometry_type == "LineString" and len(coordinates) < 2:
        raise ValueError("KML LineString must contain at least two coordinates")
    return coordinates


def _geometry(element: ElementTree.Element, unsupported: set[str]):
    kind = _name(element)
    if kind == "Point":
        return {"type": kind, "coordinates": _coordinates(_text(element, "coordinates"), kind)[0]}
    if kind == "LineString":
        return {"type": kind, "coordinates": _coordinates(_text(element, "coordinates"), kind)}
    if kind == "MultiGeometry":
        geometries = [_geometry(child, unsupported) for child in element]
        geometries = [geometry for geometry in geometries if geometry is not None]
        return {"type": "MultiGeometry", "geometries": geometries}
    unsupported.add(kind)
    return None


def _style(element: ElementTree.Element) -> dict:
    icon_style = _child(element, "IconStyle")
    line_style = _child(element, "LineStyle")
    poly_style = _child(element, "PolyStyle")
    icon = _child(icon_style, "Icon") if icon_style is not None else None
    return {
        "id": element.attrib.get("id"),
        "icon_href": _text(icon, "href") if icon is not None else None,
        "icon_color": _color(_text(icon_style, "color")) if icon_style is not None else None,
        "line_color": _color(_text(line_style, "color")) if line_style is not None else None,
        "line_width": _text(line_style, "width") if line_style is not None else None,
        "poly_color": _color(_text(poly_style, "color")) if poly_style is not None else None,
    }


def _style_map(element: ElementTree.Element) -> dict:
    pairs = {}
    for pair in element:
        if _name(pair) == "Pair" and (key := _text(pair, "key")):
            pairs[key] = _text(pair, "styleUrl")
    return {"id": element.attrib.get("id"), "normal": pairs.get("normal"), "highlight": pairs.get("highlight")}


def _walk(element: ElementTree.Element, folder_path: list[str], placemarks: list[dict], unsupported: set[str]) -> None:
    for child in element:
        kind = _name(child)
        if kind == "Folder":
            name = _text(child, "name")
            _walk(child, folder_path + ([name] if name else []), placemarks, unsupported)
        elif kind == "Placemark":
            geometry_elements = [item for item in child if _name(item) in {"Point", "LineString", "MultiGeometry", "Polygon", "Track", "NetworkLink"}]
            geometries = [_geometry(item, unsupported) for item in geometry_elements]
            placemarks.append({
                "source_order": len(placemarks) + 1,
                "name": _text(child, "name"),
                "description_html": _text(child, "description"),
                "folder_path": folder_path,
                "style_url": _text(child, "styleUrl"),
                "geometries": [geometry for geometry in geometries if geometry is not None],
                "unsupported_geometry_types": sorted({_name(item) for item, geometry in zip(geometry_elements, geometries) if geometry is None}),
            })
        elif kind == "NetworkLink":
            unsupported.add(kind)
        elif kind in {"Document", "kml"}:
            _walk(child, folder_path, placemarks, unsupported)


def parse_kml(data: bytes | str) -> dict:
    """Parse KML bytes or text. Invalid coordinates and XML raise ValueError."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("malformed KML: %s" % error) from error
    if _name(root) != "kml":
        raise ValueError("KML root element is missing")
    document = next((element for element in root.iter() if _name(element) == "Document"), None)
    if document is None:
        raise ValueError("KML Document element is missing")
    styles = {_style(element)["id"]: _style(element) for element in document.iter() if _name(element) == "Style" and element.attrib.get("id")}
    style_maps = {_style_map(element)["id"]: _style_map(element) for element in document.iter() if _name(element) == "StyleMap" and element.attrib.get("id")}
    placemarks: list[dict] = []
    unsupported: set[str] = set()
    _walk(document, [], placemarks, unsupported)
    return {
        "document_name": _text(document, "name"),
        "styles": styles,
        "style_maps": style_maps,
        "placemarks": placemarks,
        "unsupported_geometry_types": sorted(unsupported),
    }


def resolve_style(style_url: str | None, styles: dict, style_maps: dict) -> dict | None:
    """Resolve a placemark StyleMap to its normal Style, retaining source styleUrl."""
    if not style_url:
        return None
    style_id = style_url.removeprefix("#")
    mapping = style_maps.get(style_id)
    if mapping and mapping["normal"]:
        style_id = mapping["normal"].removeprefix("#")
    return styles.get(style_id)


def validate_source(data: bytes | str) -> dict:
    """Reject incomplete source documents before selecting an immutable snapshot."""
    parsed = parse_kml(data)
    if not parsed["placemarks"] or parsed["unsupported_geometry_types"]:
        raise ValueError("KML has no placemarks or contains unsupported geometry")
    kinds = set()
    for placemark in parsed["placemarks"]:
        if not placemark["geometries"] or placemark["unsupported_geometry_types"]:
            raise ValueError("KML Placemark has missing or unsupported geometry")
        if placemark["style_url"] and not resolve_style(
                placemark["style_url"], parsed["styles"], parsed["style_maps"]):
            raise ValueError("KML contains an unresolved style URL: %s" % placemark["style_url"])
        for geometry in placemark["geometries"]:
            parts = geometry["geometries"] if geometry["type"] == "MultiGeometry" else [geometry]
            if not parts:
                raise ValueError("KML contains empty MultiGeometry")
            for part in parts:
                if part["type"] not in {"Point", "LineString"}:
                    raise ValueError("KML contains unsupported nested geometry")
                kinds.add(part["type"])
                points = [part["coordinates"]] if part["type"] == "Point" else part["coordinates"]
                if any(not (131 < point[0] < 136 and 31.5 < point[1] < 35.5) for point in points):
                    raise ValueError("KML coordinate outside Shikoku")
    if kinds != {"Point", "LineString"}:
        raise ValueError("KML must contain both the source routes and POIs")
    return parsed


def icon_details(style_url: str | None) -> dict:
    match = ICON_STYLE_RE.fullmatch(style_url or "")
    return {"icon_id": match.group(1) if match else None, "color": "#" + match.group(2).upper() if match else None}
