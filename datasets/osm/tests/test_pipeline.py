import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

import osmium

from datasets.osm import __main__ as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        seed = self.root / "seed.osm.pbf"
        with osmium.SimpleWriter(str(seed)) as writer:
            writer.add_node(osmium.osm.mutable.Node(id=1, location=(134.5, 34.1)))
        self.body = seed.read_bytes()
        self.checksum = hashlib.md5(self.body).hexdigest()
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                body = (owner.checksum + "  shikoku-latest.osm.pbf\n").encode() if self.path.endswith(".md5") else owner.body
                self.send_response(200)
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
        url = f"http://127.0.0.1:{server.server_port}/shikoku-latest.osm.pbf"
        self.url_patch = patch.object(pipeline, "URL", url)
        self.url_patch.start()
        self.addCleanup(self.url_patch.stop)
        self.pbf = self.root / "raw/shikoku-latest.osm.pbf"

    def test_update_preserves_snapshot_and_unchanged_only_downloads_checksum(self):
        self.pbf.parent.mkdir()
        previous = b"previous manually supplied PBF"
        self.pbf.write_bytes(previous)
        pipeline.fetch(self.pbf)
        self.assertEqual(self.pbf.read_bytes(), self.body)
        snapshot = self.pbf.parent / "snapshots" / (hashlib.sha256(previous).hexdigest() + ".osm.pbf")
        self.assertEqual(snapshot.read_bytes(), previous)
        self.requests.clear()
        pipeline.fetch(self.pbf)
        self.assertEqual(self.requests, ["/shikoku-latest.osm.pbf.md5"])

    def test_checksum_failure_keeps_existing_input(self):
        self.pbf.parent.mkdir()
        self.pbf.write_bytes(b"keep me")
        self.checksum = "0" * 32
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            pipeline.fetch(self.pbf)
        self.assertEqual(self.pbf.read_bytes(), b"keep me")
        self.assertEqual(list(self.pbf.parent.iterdir()), [self.pbf])

    def test_checksum_matching_non_pbf_is_rejected(self):
        self.body = b"<html>upstream error</html>"
        self.checksum = hashlib.md5(self.body).hexdigest()
        with self.assertRaises(RuntimeError):
            pipeline.fetch(self.pbf)
        self.assertFalse(self.pbf.exists())

    def test_manual_run_never_fetches_or_replaces_input(self):
        with patch.object(pipeline, "DATASET", self.root), \
             patch.object(pipeline, "preflight"), \
             patch.object(pipeline, "fetch") as fetch, \
             patch.object(pipeline, "build") as build:
            self.assertEqual(pipeline.main(["--local", "--pbf", str(self.pbf)]), 0)
        fetch.assert_not_called()
        self.assertEqual(build.call_args.args[0], self.pbf)
        self.assertIsNone(build.call_args.kwargs["source_url"])

    def test_failed_build_keeps_published_outputs(self):
        pom = self.root / "basemaps/tiles/pom.xml"
        pom.parent.mkdir(parents=True)
        pom.write_text("fixture")
        self.pbf.parent.mkdir()
        self.pbf.write_bytes(self.body)
        output = self.root / "output"
        output.mkdir()
        for name in pipeline.OUTPUTS:
            (output / name).write_bytes(b"last good build")
        def fail(command, **_kwargs):
            # Simulate one builder producing partial output before failing.
            (Path(command[-1]) / pipeline.OUTPUTS[0]).write_bytes(b"partial build")
            raise subprocess.CalledProcessError(1, command)
        with patch.object(pipeline, "ROOT", self.root), patch.object(pipeline, "run", side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                pipeline.build(self.pbf, output, self.root / "reports")
        for name in pipeline.OUTPUTS:
            self.assertEqual((output / name).read_bytes(), b"last good build")
        self.assertEqual(list(self.root.glob(".osm-build-*")), [])

    @unittest.skipUnless(shutil.which("pmtiles") or shutil.which("go-pmtiles"), "requires PMTiles CLI")
    def test_overlay_header_repair_preserves_tile_payload(self):
        from pmtiles.reader import MmapSource, all_tiles, Reader
        from pmtiles.tile import Compression, TileType, zxy_to_tileid
        from pmtiles.writer import Writer

        path = self.root / "overlay.pmtiles"
        with path.open("wb") as handle:
            writer = Writer(handle)
            writer.write_tile(zxy_to_tileid(5, 27, 12), b"unchanged tile data")
            writer.finalize({"tile_compression": Compression.NONE, "tile_type": TileType.MVT}, {})
        with path.open("r+b") as handle:
            handle.seek(100)  # PMTiles v3 MinZoom byte (Planetiler's configured z0).
            handle.write(b"\x00")
        pipeline.normalize_zoom_header(path, self.root)
        with path.open("rb") as handle:
            source = MmapSource(handle)
            self.assertEqual(Reader(source).header()["min_zoom"], 5)
            self.assertEqual(list(all_tiles(source)), [((5, 27, 12), b"unchanged tile data")])
        subprocess.run([pipeline.pmtiles_cli(), "verify", str(path)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
