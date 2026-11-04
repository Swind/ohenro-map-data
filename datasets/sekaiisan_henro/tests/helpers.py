"""Shared helpers for building temporary 88sekaiisan snapshots in tests."""

from __future__ import annotations

import hashlib
import json
import os

NS = 'xmlns="http://www.opengis.net/kml/2.2"'

ROUTE_LOCAL_PATHS = ("routes/tokushima.kml", "routes/kochi.kml", "routes/ehime.kml", "routes/kagawa.kml")
TEMPLE_LOCAL_PATHS = ("temples/1-23.kml", "temples/24-39.kml", "temples/40-65.kml", "temples/66-88.kml")
TOILET_LOCAL_PATHS = ("toilets/tokushima.kml", "toilets/kochi.kml", "toilets/ehime.kml", "toilets/kagawa.kml")


def route_placemark(fid: str | None, parts: list[list[tuple[float, float]]], multi: bool = True) -> str:
    if fid is None:
        desc = ""
    else:
        desc = ('<description><![CDATA[<table><tr><td>FID</td><td>%s</td></tr>'
                '<tr><td>区分</td><td>みち案内ルート</td></tr></table>]]></description>' % fid)
    inner = []
    for part in parts:
        coords = " ".join("%.6f,%.6f,0" % (lon, lat) for lon, lat in part)
        inner.append("<LineString><coordinates>%s</coordinates></LineString>" % coords)
    if multi:
        geometry = "<MultiGeometry>%s</MultiGeometry>" % "".join(inner)
    else:
        geometry = "".join(inner)
    return "<Placemark>%s%s</Placemark>" % (desc, geometry)


def route_kml(placemarks: list[str]) -> bytes:
    body = "".join(placemarks)
    return ('<?xml version="1.0"?><kml %s><Document>%s</Document></kml>' % (NS, body)).encode()


def temple_placemark(number: int) -> str:
    name = "第%d番札所　寺%d　（No.%d　Temple）" % (number, number, number)
    return ('<Placemark><name>%s</name>'
            '<description><![CDATA[<table><tr><td>読み</td><td>てら</td></tr></table>]]></description>'
            '<Point><coordinates>%d.%d,%d.%d</coordinates></Point></Placemark>'
            % (name, 130 + number // 100, number, 30 + number // 100, number))


def temple_kml(numbers: list[int]) -> bytes:
    body = "".join(temple_placemark(number) for number in numbers)
    return ('<?xml version="1.0"?><kml %s><Document>%s</Document></kml>' % (NS, body)).encode()


def toilet_placemark(raw_type: str, coord: tuple[float, float],
                     fields: dict[str, str] | None = None) -> str:
    """Build a toilet Placemark with a description table like the live archive."""
    rows = []
    for label, value in (fields or {}).items():
        rows.append(
            '<tr><td style="color:#0000FF;padding-right:1em;">%s</td><td>%s</td></tr>'
            % (label, value)
        )
    desc = ""
    if rows:
        desc = ("<description><![CDATA[<table>%s</table>]]></description>"
                % "".join(rows))
    return ("<Placemark><name>%s</name>%s"
            "<Point><coordinates>%.6f,%.6f</coordinates></Point></Placemark>"
            % (raw_type, desc, coord[0], coord[1]))


def toilet_kml(placemarks: list[str]) -> bytes:
    body = "".join(placemarks)
    return ('<?xml version="1.0"?><kml %s><Document>%s</Document></kml>' % (NS, body)).encode()


def write_snapshot(data_dir: str, snapshot_sha: str, route_counts: dict, temple_numbers: list[int],
                   toilet_counts: dict | None = None) -> None:
    """Build a snapshot directory populated with deterministic KML.

    route_counts maps local_path -> list[list[part]] where each inner list is a
    part (list of (lon, lat)); each part is wrapped in a single placemark.
    toilet_counts maps local_path -> list of (raw_type, coord, fields) specs;
    defaults to standard_toilet_counts().
    """
    if toilet_counts is None:
        toilet_counts = standard_toilet_counts()
    snapshot_dir = os.path.join(data_dir, "snapshots", snapshot_sha)
    files = []
    for idx, local_path in enumerate(ROUTE_LOCAL_PATHS):
        placemark_specs = route_counts[local_path]
        placemarks = []
        for fid, parts in placemark_specs:
            placemarks.append(route_placemark(fid, parts, multi=len(parts) > 1))
        body = route_kml(placemarks)
        path = os.path.join(snapshot_dir, local_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(body)
        files.append({
            "local_path": local_path,
            "source_file": "source_%d.kml" % idx,
            "url": "https://example.invalid/%d" % idx,
            "content_type": "application/vnd.google-earth.kml+xml",
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    for idx, local_path in enumerate(TEMPLE_LOCAL_PATHS):
        low = idx * 23 + 1
        high = min(low + 22, 88)
        numbers = [n for n in temple_numbers if low <= n <= high]
        body = temple_kml(numbers)
        path = os.path.join(snapshot_dir, local_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(body)
        files.append({
            "local_path": local_path,
            "source_file": "temple_%d.kml" % idx,
            "url": "https://example.invalid/t%d" % idx,
            "content_type": "application/vnd.google-earth.kml+xml",
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    for idx, local_path in enumerate(TOILET_LOCAL_PATHS):
        placemarks = [
            toilet_placemark(raw_type, coord, fields)
            for raw_type, coord, fields in toilet_counts.get(local_path, [])
        ]
        body = toilet_kml(placemarks)
        path = os.path.join(snapshot_dir, local_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(body)
        files.append({
            "local_path": local_path,
            "source_file": "toilet_%d.kml" % idx,
            "url": "https://example.invalid/w%d" % idx,
            "content_type": "application/vnd.google-earth.kml+xml",
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    metadata = {
        "schema_version": 1,
        "dataset_id": "88sekaiisan-henro",
        "organization": "test",
        "sha256": snapshot_sha,
        "files": files,
    }
    with open(os.path.join(snapshot_dir, "metadata.json"), "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, sort_keys=True)
    with open(os.path.join(data_dir, "current.json"), "w", encoding="utf-8") as stream:
        json.dump({"schema_version": 1, "sha256": snapshot_sha, "last_checked_at": "2026-01-01T00:00:00+00:00"}, stream)


def standard_route_counts() -> dict:
    """Deterministic small route set used by determinism/accounting tests.

    Each value is a list of ``(fid, parts)`` placemark specs where ``fid`` is a
    source FID string or ``None`` (FID-less) and ``parts`` is a list of parts;
    a part is a list of (lon, lat) coordinate tuples.
    """
    return {
        # FID1: direct LineString; FID2: 2 parts (MultiGeometry)
        "routes/tokushima.kml": [
            ("1", [[[134.1, 33.1], [134.2, 33.2]]]),
            ("2", [[[134.3, 33.3], [134.4, 33.4]], [[134.5, 33.5], [134.6, 33.6]]]),
        ],
        # FID1: 3 parts (MultiGeometry)
        "routes/kochi.kml": [
            ("1", [[[133.1, 33.1], [133.2, 33.2]], [[133.3, 33.3], [133.4, 33.4]], [[133.5, 33.5], [133.6, 33.6]]]),
        ],
        "routes/ehime.kml": [
            ("1", [[[132.1, 33.1], [132.2, 33.2]]]),
        ],
        "routes/kagawa.kml": [
            ("1", [[[134.0, 34.0], [134.1, 34.1]]]),
        ],
    }


def standard_toilet_counts() -> dict:
    """Deterministic small toilet set used by determinism/accounting tests.

    Each value is a list of ``(raw_type, coord, fields)`` specs; fields is a
    dict of description-table label -> value (or None for no description).
    """
    base = {
        "施設名(Name)": "県庁舎",
        "住所(Address)": "市町1-1",
        "利用時間": "8:30～18:15",
        "種類": "和・洋式両方、多目的トイレ",
        "ｳｫｼｭﾚｯﾄ有無等": "有り",
        "備考(Notes)": "",
    }
    return {
        # tokushima: one public toilet with full fields, one facility toilet
        # with an unescaped <br> in the notes value.
        "toilets/tokushima.kml": [
            ("公衆トイレ(Toilet)", (134.5, 34.0), base),
            ("施設内トイレ(Toilet in Facility)", (134.51, 34.01),
             {"施設名(Name)": "県合同庁舎", "住所(Address)": "市町2-2",
              "利用可能日": "月～金", "Open": "9:00", "Close": "17:00",
              "種類": "多目的トイレ", "備考(Notes)": "夜間は<b>閉鎖</b>"}),
        ],
        "toilets/kochi.kml": [
            ("屋外トイレ(Toilet)", (133.5, 33.5), None),
        ],
        "toilets/ehime.kml": [],
        "toilets/kagawa.kml": [
            ("道の駅(Toilet)", (134.05, 34.05), {"施設名(Name)": "道の駅"}),
        ],
    }