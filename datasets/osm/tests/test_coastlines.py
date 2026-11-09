import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from datasets.osm import coastlines


def archive(kind, date="2026-10-31", *, missing=None, projection="Mercator 6378137", corrupt=False):
    folder, layer = f"{kind}-polygons-split-3857", f"{kind}_polygons"
    shape = struct.pack("<I4dIII10d", 5, 0, 0, 1, 1, 1, 5, 0,
                        0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
    def header(size):
        result = bytearray(100)
        struct.pack_into(">I", result, 0, 9994)
        struct.pack_into(">I", result, 24, size // 2)
        struct.pack_into("<II4d", result, 28, 1000, 5, 0, 0, 1, 1)
        return bytes(result)
    shp = header(108 + len(shape)) + struct.pack(">II", 1, len(shape) // 2) + shape
    shx = header(108) + struct.pack(">II", 50, len(shape) // 2)
    dbf = bytearray(34)
    dbf[0], dbf[32], dbf[33] = 3, 13, 32
    struct.pack_into("<IHH", dbf, 4, 1, 33, 1)
    files = {"README.txt": f"EPSG: 3857\nDate of the data used is {date}T00:00:00Z\nOpen Database License (ODbL)\n",
             f"{layer}.prj": projection, f"{layer}.shp": shp,
             f"{layer}.shx": shx, f"{layer}.dbf": bytes(dbf)}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as result:
        for name, body in files.items():
            if name != missing:
                result.writestr(f"{folder}/{name}", body)
    payload = bytearray(stream.getvalue())
    if corrupt:
        with zipfile.ZipFile(io.BytesIO(payload)) as result:
            entry = result.getinfo(f"{folder}/{layer}.dbf")
            start = entry.header_offset + 30 + len(entry.filename.encode())
            payload[start + entry.file_size - 1] ^= 1
    return bytes(payload)


class CoastlineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources, self.reports = self.root / "sources", self.root / "reports"
        self.bodies, self.requests = {}, []
        for kind in ("water", "land"):
            name = f"{kind}-polygons-split-3857.zip"
            self.bodies[f"/official/{name}"] = (200, archive(kind, "2026-11-08"))
            self.bodies[f"/mirror/{name}"] = (200, archive(kind))
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                status, body = owner.bodies.get(self.path, (404, b"missing"))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/"
        for attribute, value in (("OFFICIAL", base + "official/"), ("MIRROR", base + "mirror/")):
            patched = patch.object(coastlines, attribute, value)
            patched.start()
            self.addCleanup(patched.stop)
        patched = patch("datasets.osm.__main__.time.sleep", return_value=None)
        patched.start()
        self.addCleanup(patched.stop)

    def prepare(self):
        return coastlines.prepare(self.sources, self.reports)

    def fail_official(self):
        for name in coastlines.ARCHIVES:
            self.bodies[f"/official/{name}"] = (503, b"offline")

    def test_official_data_takes_precedence_over_older_mirror(self):
        records = self.prepare()
        self.assertEqual({row["data_date"] for row in records.values()}, {"2026-11-08T00:00:00Z"})
        self.assertEqual({row["source"] for row in records.values()}, {"official"})
        self.assertFalse(any(path.startswith("/mirror/") for path in self.requests))

    def test_http_failure_uses_verified_pinned_mirror(self):
        self.fail_official()
        records = self.prepare()
        for name, record in records.items():
            self.assertEqual(record["source"], "rrze")
            self.assertEqual(record["data_date"], "2026-10-31T00:00:00Z")
            self.assertEqual(record["mirror_snapshot"], "2026-10-31")
            self.assertEqual(record["sha256"], coastlines.digest(self.sources / name))

    def test_invalid_primary_bodies_never_replace_valid_mirror_data(self):
        cases = (b"<html>error</html>", archive("water", missing="water_polygons.prj"),
                 archive("water", projection="WGS84 degrees"), archive("water", corrupt=True))
        for index, body in enumerate(cases):
            with self.subTest(case=index):
                self.sources = self.root / f"sources-{index}"
                self.reports = self.root / f"reports-{index}"
                self.bodies["/official/water-polygons-split-3857.zip"] = (200, body)
                records = self.prepare()
                self.assertEqual(records["water-polygons-split-3857.zip"]["source"], "rrze")
                self.assertEqual(records["water-polygons-split-3857.zip"]["data_date"], "2026-10-31T00:00:00Z")

    def test_failed_missing_companion_keeps_good_cache_and_previous_report(self):
        self.prepare()
        water = self.sources / "water-polygons-split-3857.zip"
        land = self.sources / "land-polygons-split-3857.zip"
        report = self.reports / "coastlines.json"
        before = water.read_bytes(), water.stat().st_mtime_ns, report.read_bytes()
        land.unlink()
        for key in self.bodies:
            self.bodies[key] = (503, b"offline")
        with self.assertRaisesRegex(ValueError, "No valid coastline archive"):
            self.prepare()
        self.assertEqual((water.read_bytes(), water.stat().st_mtime_ns, report.read_bytes()), before)
        self.assertFalse(land.exists())
        self.assertEqual(list(self.sources.glob(".coastlines-*")), [])

    def test_good_cache_and_origin_are_reused_without_timestamp_churn(self):
        records = self.prepare()
        paths = [self.sources / name for name in coastlines.ARCHIVES] + [self.reports / "coastlines.json"]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        self.requests.clear()
        self.fail_official()
        self.assertEqual(self.prepare(), records)
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)
        self.assertEqual(self.requests, [])

    def test_mirror_with_wrong_snapshot_date_is_rejected(self):
        self.fail_official()
        self.bodies["/mirror/water-polygons-split-3857.zip"] = (200, archive("water", "2025-01-01"))
        with self.assertRaisesRegex(ValueError, "pinned snapshot date"):
            self.prepare()
        self.assertFalse((self.sources / "water-polygons-split-3857.zip").exists())
        self.assertFalse((self.reports / "coastlines.json").exists())

    def test_existing_cache_without_provenance_never_claims_official_origin(self):
        self.sources.mkdir()
        self.reports.mkdir()
        (self.reports / "coastlines.json").write_text("broken JSON")
        for kind in ("water", "land"):
            (self.sources / f"{kind}-polygons-split-3857.zip").write_bytes(archive(kind))
        records = self.prepare()
        self.assertEqual({row["source"] for row in records.values()}, {"existing_cache"})
        self.assertTrue(all(row["url"] is None for row in records.values()))
        self.assertEqual(self.requests, [])
        self.assertEqual(json.loads((self.reports / "coastlines.json").read_text())["archives"], records)


if __name__ == "__main__":
    unittest.main()
