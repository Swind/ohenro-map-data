"""Consumer-visible cache/publication boundaries without Maven or Planetiler."""

import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mapbox_vector_tile
import mercantile
import osmium
from pmtiles.reader import MemorySource, Reader, all_tiles
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

from datasets import _pipeline as shared
from datasets.info_pois import osm_input


@unittest.skipUnless(shutil.which("pmtiles") or shutil.which("go-pmtiles"), "requires PMTiles CLI")
class OsmInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.datasets = self.root / "datasets"
        self.raw = self.datasets / "info_pois/raw"
        self.pbf = self.datasets / "osm/raw/shikoku-latest.osm.pbf"
        self.pbf.parent.mkdir(parents=True)
        self.write_pbf()
        self.tiles = self.root / "basemaps/tiles"
        sources = self.tiles / "data/sources"
        sources.mkdir(parents=True)
        (sources / "qrank.csv.gz").write_bytes(b"fixture qrank identity")
        (sources / "pgf-encoding.zip").write_bytes(b"fixture encoding identity")
        (self.tiles / "pom.xml").write_text("fixture Maven identity")
        self.java = self.tiles / "src/main/java/Pois.java"
        self.java.parent.mkdir(parents=True)
        self.java.write_text("fixture profile version one")
        self.jar = self.tiles / "target/protomaps-basemap-HEAD-with-deps.jar"
        self.maven_runs = 0
        self.builds = 0
        self.fail_build = False
        self.after_build = None
        self.layer = "pois"
        self.kind = "toilets"
        self.zoom = 15
        self.center_zoom = 15
        real_run = subprocess.run

        def native_process(command, **kwargs):
            if command[0] == "mvn":
                self.maven_runs += 1
                self.jar.parent.mkdir(exist_ok=True)
                self.jar.write_bytes(self.java.read_bytes())
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        def profile_source(_tiles):
            return {"commit": "fixture-official-commit", "files": {
                "pom.xml": shared.digest(self.tiles / "pom.xml"),
                "src/main/java/Pois.java": shared.digest(self.java),
            }}

        for target, value in (("ROOT", self.root), ("_profile_source", profile_source),
                              ("_build", self.build_archive)):
            mock = patch.object(osm_input, target, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(osm_input.subprocess, "run", side_effect=native_process)
        mock.start()
        self.addCleanup(mock.stop)

    def write_pbf(self, node_id=1):
        candidate = self.pbf.with_name("candidate.osm.pbf")
        with osmium.SimpleWriter(str(candidate)) as writer:
            writer.add_node(osmium.osm.mutable.Node(id=node_id, location=(134.5, 34.1)))
        candidate.replace(self.pbf)

    def build_archive(self, _pbf, _tiles, _jar, destination, _memory):
        self.builds += 1
        tile = mercantile.tile(134.5, 34.1, self.zoom)
        data = mapbox_vector_tile.encode({
            "name": self.layer,
            "features": [{"id": 1, "properties": {"kind": self.kind},
                          "geometry": {"type": "Point", "coordinates": [2048, 2048]}}],
        })
        with destination.open("wb") as handle:
            writer = Writer(handle)
            writer.write_tile(zxy_to_tileid(tile.z, tile.x, tile.y), data)
            writer.finalize({
                "tile_compression": Compression.NONE, "tile_type": TileType.MVT,
                "center_zoom": self.center_zoom,
                "min_lon_e7": 1340000000, "min_lat_e7": 330000000,
                "max_lon_e7": 1350000000, "max_lat_e7": 350000000,
            }, {"vector_layers": [{"id": self.layer, "fields": {"kind": "String"}}]})
        if self.fail_build:
            raise RuntimeError("native build failed after partial output")
        if self.after_build:
            self.after_build()

    def resolve(self):
        return osm_input.resolve(self.raw, self.datasets)

    def test_unchanged_resolve_reuses_verified_archive_and_binary(self):
        first = self.resolve()
        original = first.read_bytes()
        self.assertEqual(self.resolve(), first)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual((self.builds, self.maven_runs), (1, 1))
        report = shared.read_json(first.parent / "provenance.json")
        self.assertEqual(report["descriptor"]["source"]["sha256"], shared.digest(self.pbf))
        self.assertEqual(report["artifact"]["sha256"], shared.digest(first))
        self.assertEqual(report["validation"]["kinds"], ["toilets"])

    def test_each_source_dependency_selects_new_immutable_cache(self):
        paths = [self.resolve()]
        changes = [
            lambda: self.write_pbf(2),
            lambda: (self.tiles / "data/sources/qrank.csv.gz").write_bytes(b"new qrank"),
            lambda: (self.tiles / "data/sources/pgf-encoding.zip").write_bytes(b"new encoding"),
            lambda: self.java.write_text("fixture profile version two"),
        ]
        for change in changes:
            old = {path: path.read_bytes() for path in paths}
            change()
            paths.append(self.resolve())
            self.assertEqual(len(set(paths)), len(paths))
            for path, data in old.items():
                self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.maven_runs, 2)
        self.assertEqual(self.builds, 5)

    def test_changed_settings_select_new_cache(self):
        with patch.dict(osm_input.os.environ, {"JAVA_MEM": "-Xmx1g"}):
            first = self.resolve()
        with patch.dict(osm_input.os.environ, {"JAVA_MEM": "-Xmx2g"}):
            second = self.resolve()
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertEqual(self.maven_runs, 1)

    def test_tampered_archive_is_rebuilt_not_blessed(self):
        path = self.resolve()
        valid = path.read_bytes()
        path.write_bytes(b"not PMTiles")
        self.assertEqual(self.resolve(), path)
        self.assertEqual(path.read_bytes(), valid)
        self.assertEqual(self.builds, 2)

    def test_missing_archive_is_rebuilt(self):
        path = self.resolve()
        path.unlink()
        self.assertEqual(self.resolve(), path)
        self.assertTrue(path.is_file())
        self.assertEqual(self.builds, 2)

    def test_failed_repair_keeps_rejected_cache_until_success(self):
        path = self.resolve()
        path.write_bytes(b"rejected prior bytes")
        report = (path.parent / "provenance.json").read_bytes()
        self.fail_build = True
        with self.assertRaisesRegex(RuntimeError, "native build failed"):
            self.resolve()
        self.assertEqual(path.read_bytes(), b"rejected prior bytes")
        self.assertEqual((path.parent / "provenance.json").read_bytes(), report)
        self.assertEqual(list((self.raw / "osm-pois").glob(".build-*")), [])

    def test_matching_hash_does_not_bless_wrong_layer(self):
        path = self.resolve()
        self.layer = "roads"
        self.build_archive(None, None, None, path, None)
        report_path = path.parent / "provenance.json"
        report = shared.read_json(report_path)
        report["artifact"] = {"sha256": shared.digest(path), "size": path.stat().st_size}
        report_path.write_text(json.dumps(report))
        self.layer = "pois"
        self.assertEqual(self.resolve(), path)
        self.assertEqual(osm_input._validate(path)["kinds"], ["toilets"])
        self.assertEqual(self.builds, 3)

    def test_source_change_during_build_cannot_promote(self):
        previous = self.resolve()
        original = previous.read_bytes()
        self.write_pbf(2)
        self.after_build = lambda: self.write_pbf(3)
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.resolve()
        self.assertEqual(previous.read_bytes(), original)
        self.assertEqual(list((self.raw / "osm-pois").glob("*/provenance.json")),
                         [previous.parent / "provenance.json"])
        self.assertEqual(list((self.raw / "osm-pois").glob(".build-*")), [])

    def test_partial_build_preserves_previous_cache_and_removes_stage(self):
        previous = self.resolve()
        original = previous.read_bytes()
        self.write_pbf(2)
        self.fail_build = True
        with self.assertRaisesRegex(RuntimeError, "native build failed"):
            self.resolve()
        self.assertEqual(previous.read_bytes(), original)
        self.assertEqual(list((self.raw / "osm-pois").glob(".build-*")), [])

    def test_invalid_poi_archive_is_never_published(self):
        for layer, kind in (("roads", "toilets"), ("pois", "")):
            with self.subTest(layer=layer, kind=kind):
                self.layer, self.kind = layer, kind
                with self.assertRaises(ValueError):
                    self.resolve()
                self.assertEqual(list((self.raw / "osm-pois").glob("*/provenance.json")), [])
                self.assertEqual(list((self.raw / "osm-pois").glob(".build-*")), [])

    def test_archive_without_full_resolution_pois_is_rejected(self):
        self.zoom = 14
        self.center_zoom = 14
        with self.assertRaisesRegex(ValueError, "complete z15"):
            self.resolve()
        self.assertEqual(list((self.raw / "osm-pois").glob("*/provenance.json")), [])

    def test_overview_center_is_normalized_without_changing_poi_tiles(self):
        self.center_zoom = 7
        path = self.root / "native.pmtiles"
        self.build_archive(None, None, None, path, None)
        before = MemorySource(path.read_bytes())
        header = Reader(before).header()
        payloads = list(all_tiles(before))
        osm_input._normalize_center(path)
        after = MemorySource(path.read_bytes())
        corrected = Reader(after).header()
        self.assertEqual(corrected["center_zoom"], 15)
        self.assertEqual((corrected["center_lon_e7"], corrected["center_lat_e7"]),
                         (header["center_lon_e7"], header["center_lat_e7"]))
        self.assertEqual(list(all_tiles(after)), payloads)
        self.assertEqual(osm_input._validate(path)["kinds"], ["toilets"])

    def test_shared_osm_lock_prevents_profile_or_cache_build(self):
        lock_path = self.datasets / "osm/.pipeline.lock"
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "already running"):
                self.resolve()
        self.assertEqual((self.builds, self.maven_runs), (0, 0))

    def test_custom_refresh_is_rejected_without_touching_sources(self):
        original = self.pbf.read_bytes()
        with self.assertRaisesRegex(ValueError, "default datasets root"):
            osm_input.resolve(self.raw, self.root / "custom-datasets", refresh=True)
        self.assertEqual(self.pbf.read_bytes(), original)
        self.assertEqual((self.builds, self.maven_runs), (0, 0))


if __name__ == "__main__":
    unittest.main()
