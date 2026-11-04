#!/usr/bin/env python3
"""Smoke test for shikoku-henro.pmtiles.

TEMPORARY smoke-test rule (not a real Henro classification): verifies that
OSM relation 13653654 appears in at least one output feature with its
name/network/route metadata preserved.

Reads the PMTiles archive directly (header + directories + tile data) and
decodes the MVT tiles, so it does not depend on pmtiles CLI or hard-coded
tile coordinates.
"""
import gzip
import struct
import sys

SMOKE_RELATION_ID = 13653654
EXPECTED_NAME = "四国遍路 1番札所霊山寺~2番札所極楽寺"
EXPECTED_ROUTE = "hiking"
EXPECTED_NETWORK = "nwn"
EXPECTED_ROUTE_KIND = "henro_candidate"


def read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def hilbert_decode(n, index):
    """Decode Hilbert curve index into (x, y) on an n x n grid (n = 2^z)."""
    x = y = 0
    s = 1
    while s < n:
        rx = 1 if (index & 2) else 0
        ry = 1 if ((index & 1) ^ rx) else 0
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        index >>= 2
        s <<= 1
    return x, y


def zxy_from_tileid(tileid):
    remaining = tileid
    z = 0
    while True:
        n_tiles = 1 << (2 * z)
        if remaining < n_tiles:
            n = 1 << z
            x, y = hilbert_decode(n, remaining) if z > 0 else (0, 0)
            return z, x, y
        remaining -= n_tiles
        z += 1


def parse_directory(data, internal_compression, pos=0):
    if internal_compression == 2:  # gzip
        data = gzip.decompress(data)
        pos = 0
    num_entries, pos = read_varint(data, pos)
    entries = []
    last_id = 0
    for _ in range(num_entries):
        delta, pos = read_varint(data, pos)
        last_id += delta
        entries.append({"tile_id": last_id})
    for e in entries:
        e["run_length"], pos = read_varint(data, pos)
    for e in entries:
        e["length"], pos = read_varint(data, pos)
    next_byte = 0
    for i, e in enumerate(entries):
        value, pos = read_varint(data, pos)
        if value == 0 and i > 0:
            e["offset"] = entries[i - 1]["offset"] + entries[i - 1]["length"]
        else:
            e["offset"] = value - 1
        if e["run_length"] == 0:
            e["next_byte"] = e["offset"] + e["length"]
        else:
            e["next_byte"] = next_byte if e["offset"] == 0 else e["offset"] + e["length"]
        next_byte = e["offset"] + e["length"]
    return entries


def parse_mvt(raw):
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    features = []
    pos = 0
    while pos < len(raw):
        tag, pos = read_varint(raw, pos)
        field = tag >> 3
        wire = tag & 7
        if wire == 0:
            _, pos = read_varint(raw, pos)
            continue
        if wire != 2:
            break
        ln, pos = read_varint(raw, pos)
        sub = pos
        pos += ln
        if field != 3:  # only layers
            continue
        keys, values, layer_features = parse_mvt_layer(raw, sub, pos)
        features.extend(parse_mvt_features(keys, values, layer_features))
    return features


def parse_mvt_value(buf, pos, end):
    val = None
    while pos < end:
        tag, pos = read_varint(buf, pos)
        field = tag >> 3
        wire = tag & 7
        if field == 1:
            ln, pos = read_varint(buf, pos)
            val = buf[pos:pos + ln].decode("utf-8", errors="replace")
            pos += ln
        elif field in (2, 3):
            pos += 4 if field == 2 else 8
        elif field in (4, 5):
            val, pos = read_varint(buf, pos)
        elif field == 6:
            raw, pos = read_varint(buf, pos)
            val = (raw >> 1) ^ -(raw & 1)
        elif field == 7:
            b, pos = read_varint(buf, pos)
            val = bool(b)
        else:
            if wire == 0:
                _, pos = read_varint(buf, pos)
            elif wire == 1:
                pos += 8
            elif wire == 2:
                ln, pos = read_varint(buf, pos)
                pos += ln
            elif wire == 5:
                pos += 4
    return val


def parse_mvt_layer(buf, pos, end):
    keys = []
    values = []
    features = []
    while pos < end:
        tag, pos = read_varint(buf, pos)
        field = tag >> 3
        wire = tag & 7
        if wire == 0:
            _, pos = read_varint(buf, pos)
            continue
        if wire != 2:
            break
        ln, pos = read_varint(buf, pos)
        sub = pos
        pos += ln
        if field == 2:
            features.append(parse_mvt_feature(buf, sub, pos))
        elif field == 3:
            keys.append(buf[sub:pos].decode("utf-8", errors="replace"))
        elif field == 4:
            values.append(parse_mvt_value(buf, sub, pos))
    return keys, values, features


def parse_mvt_feature(buf, pos, end):
    tags = []
    while pos < end:
        tag, pos = read_varint(buf, pos)
        field = tag >> 3
        wire = tag & 7
        if field == 2 and wire == 2:
            ln, pos = read_varint(buf, pos)
            sub = pos
            pos += ln
            while sub < pos:
                k, sub = read_varint(buf, sub)
                v, sub = read_varint(buf, sub)
                tags.append((k, v))
        elif wire == 2:
            ln, pos = read_varint(buf, pos)
            pos += ln
        elif wire == 0:
            _, pos = read_varint(buf, pos)
        elif wire == 5:
            pos += 4
    return tags


def parse_mvt_features(keys, values, layer_features):
    result = []
    for tags in layer_features:
        attrs = {}
        for k, v in tags:
            if k < len(keys) and v < len(values):
                attrs[keys[k]] = values[v]
        result.append(attrs)
    return result


def main(path):
    with open(path, "rb") as f:
        data = f.read()

    if data[:7] != b"PMTiles":
        print(f"FAIL: not a PMTiles archive: {path}", file=sys.stderr)
        return 1

    root_dir_offset = struct.unpack_from("<Q", data, 8)[0]
    root_dir_length = struct.unpack_from("<Q", data, 16)[0]
    leaf_dirs_offset = struct.unpack_from("<Q", data, 40)[0]
    leaf_dirs_length = struct.unpack_from("<Q", data, 48)[0]
    tile_data_offset = struct.unpack_from("<Q", data, 56)[0]
    internal_compression = data[97]

    root = parse_directory(data[root_dir_offset:root_dir_offset + root_dir_length], internal_compression)

    tiles = []
    for e in root:
        if e["run_length"] == 0:  # leaf directory
            leaf = parse_directory(
                data[leaf_dirs_offset + e["offset"]: leaf_dirs_offset + e["offset"] + e["length"]],
                internal_compression,
            )
            for le in leaf:
                if le["run_length"] > 0:
                    tiles.append(le)
        else:
            tiles.append(e)

    matches = []
    for e in tiles:
        z, x, y = zxy_from_tileid(e["tile_id"])
        start = tile_data_offset + e["offset"]
        raw = data[start:start + e["length"]]
        for attrs in parse_mvt(raw):
            if attrs.get("relation_id") == SMOKE_RELATION_ID:
                matches.append((z, x, y, attrs))

    print(f"scanned {len(tiles)} tile entries, {len(matches)} features match relation {SMOKE_RELATION_ID}")
    if not matches:
        print(f"FAIL: relation {SMOKE_RELATION_ID} not found in any henro_routes feature", file=sys.stderr)
        return 1

    z, x, y, attrs = matches[0]
    checks = [
        ("name", attrs.get("name"), EXPECTED_NAME),
        ("route", attrs.get("route"), EXPECTED_ROUTE),
        ("network", attrs.get("network"), EXPECTED_NETWORK),
        ("route_kind", attrs.get("route_kind"), EXPECTED_ROUTE_KIND),
    ]
    ok = True
    for key, got, want in checks:
        status = "ok" if got == want else f"MISMATCH (expected {want!r})"
        if got != want:
            ok = False
        print(f"  relation_id={SMOKE_RELATION_ID} {key}={got!r} [{status}]")
    if not ok:
        print(f"FAIL: relation {SMOKE_RELATION_ID} metadata check failed", file=sys.stderr)
        return 1

    print(f"PASS: relation {SMOKE_RELATION_ID} found (sample tile {z}/{x}/{y})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
