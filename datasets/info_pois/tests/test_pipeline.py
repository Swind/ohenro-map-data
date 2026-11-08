import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from datasets import _pipeline as common
from datasets.info_pois import pipeline


def feature(properties):
    return {"type": "Feature", "properties": properties,
            "geometry": {"type": "Point", "coordinates": [134.5, 34.1]}}


def collection(features):
    return {"type": "FeatureCollection", "features": features}


class TestInformationPoiConsumers(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.datasets = self.root / "datasets"
        self.raw = self.root / "raw"
        self.output = self.root / "output"
        self.reports = self.root / "reports"
        self.documents = {
            "temples": collection([feature({"id": f"temple-{number:03d}", "number": number,
                                             "name_ja": f"Temple {number}"})
                                   for number in range(1, 89)]),
            "sekaiisan": {"temples": [{"id": "TEMPLE_1", "number": 1,
                                         "geometry": feature({})["geometry"]}],
                          "toilets": [{"id": "TOILET_1", "facility_name": "Toilet",
                                       "geometry": feature({})["geometry"]}]},
            "mizutani": collection([
                feature({"feature_id": "m-rest", "category": "water_toilet_rest", "name": "道の駅"}),
                feature({"feature_id": "m-onsen", "category": "water_toilet_rest", "name": "温泉"}),
                feature({"feature_id": "m-lodging", "category": "lodging", "name": "Lodging"}),
            ]),
            "nature_trail": collection([
                feature({"poi_id": "nature-tourism", "kind": "tourism_spot", "name": "Tourism"}),
                feature({"poi_id": "nature-kml", "kind": "kml_poi", "name": "KML"}),
            ]),
            "arukihenro": {"routes": [{"id": "r1", "maps": [{"map_id": "m1", "points": [
                {"coordinates": [134.5, 34.1], "category": "shrine", "name": "Shrine"},
                {"coordinates": [134.5, 34.1], "category": "lodging", "name": "Lodging"},
            ]}]}]},
        }
        for name, document in self.documents.items():
            self.write_source(name, document)
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.builder().main(["--datasets-dir", str(self.datasets), "--output-dir", str(self.output),
                                     "--skip-osm"])

    def write_source(self, name, document):
        common.atomic_json(self.datasets / pipeline.SOURCES[name], document)

    def validate_data(self):
        return pipeline.validate_data(self.datasets, self.output, tiles=False)

    def published_bytes(self):
        paths = [self.output / name for name in (pipeline.GEOJSON, pipeline.REPORT)]
        paths.append(self.reports / "pipeline.json")
        return {path: path.read_bytes() for path in paths if path.exists()}

    def build(self):
        return pipeline.build(self.datasets, self.raw, self.output, self.reports,
                              skip_osm=True, force=True)

    def test_preserves_overlapping_sources_and_existing_taxonomy(self):
        summary = self.validate_data()
        self.assertEqual(summary["sources"], {"temples": 88, "sekaiisan": 2, "mizutani": 2,
                                             "nature_trail": 2, "arukihenro": 1})
        features = common.read_json(self.output / pipeline.GEOJSON)["features"]
        self.assertEqual(len(features), 95)
        self.assertEqual({tuple(row["geometry"]["coordinates"]) for row in features}, {(134.5, 34.1)})
        props = {row["properties"]["poi_id"]: row["properties"] for row in features}
        self.assertEqual(props["m-rest"]["category"], "rest_area")
        self.assertEqual(props["m-onsen"]["category"], "onsen")
        self.assertEqual(props["m-onsen"]["source_category"], "water_toilet_rest")
        self.assertNotIn("m-lodging", props)
        self.assertFalse(any(row["category"] == "lodging" for row in props.values()))

    def test_rejects_corrupted_consumer_coordinates(self):
        original = common.read_json(self.output / pipeline.GEOJSON)
        for coordinates in ([34.1, 134.5], [134.5], [134.5, "34.1"], [True, 34.1], [134.5, None]):
            with self.subTest(coordinates=coordinates):
                damaged = copy.deepcopy(original)
                damaged["features"][0]["geometry"]["coordinates"] = coordinates
                common.atomic_json(self.output / pipeline.GEOJSON, damaged)
                with self.assertRaisesRegex(ValueError, "coordinates"):
                    self.validate_data()

    def test_rejects_nonfinite_consumer_coordinates(self):
        damaged = common.read_json(self.output / pipeline.GEOJSON)
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value):
                damaged["features"][0]["geometry"]["coordinates"] = [134.5, value]
                (self.output / pipeline.GEOJSON).write_text(json.dumps(damaged), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "coordinates"):
                    self.validate_data()

    def test_rejects_nonpoint_consumer_geometry(self):
        damaged = common.read_json(self.output / pipeline.GEOJSON)
        damaged["features"][0]["geometry"] = {"type": "LineString", "coordinates": [[134.5, 34.1]]}
        common.atomic_json(self.output / pipeline.GEOJSON, damaged)
        with self.assertRaisesRegex(ValueError, "Point geometry"):
            self.validate_data()

    def test_rejects_unknown_category_and_source(self):
        original = common.read_json(self.output / pipeline.GEOJSON)
        for field in ("category", "source"):
            with self.subTest(field=field):
                damaged = copy.deepcopy(original)
                damaged["features"][0]["properties"][field] = "not-a-real-value"
                common.atomic_json(self.output / pipeline.GEOJSON, damaged)
                with self.assertRaisesRegex(ValueError, "Unknown"):
                    self.validate_data()

    def test_rejects_duplicate_ids_even_when_counts_are_unchanged(self):
        damaged = common.read_json(self.output / pipeline.GEOJSON)
        damaged["features"][1] = copy.deepcopy(damaged["features"][0])
        common.atomic_json(self.output / pipeline.GEOJSON, damaged)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.validate_data()

    def test_rejects_source_relabeling_without_changing_total(self):
        damaged = common.read_json(self.output / pipeline.GEOJSON)
        damaged["features"][0]["properties"]["source"] = "mizutani"
        common.atomic_json(self.output / pipeline.GEOJSON, damaged)
        with self.assertRaisesRegex(ValueError, "source/category accounting"):
            self.validate_data()

    def test_rejects_falsified_source_and_category_report(self):
        original = common.read_json(self.output / pipeline.REPORT)
        for group, key in (("mizutani", "total"), ("categories", "temple"),
                           ("sekaiisan", "sekaiisan_toilets")):
            with self.subTest(group=group):
                damaged = copy.deepcopy(original)
                damaged[group][key] += 1
                common.atomic_json(self.output / pipeline.REPORT, damaged)
                with self.assertRaisesRegex(ValueError, "report source/category accounting"):
                    self.validate_data()

    def test_rejects_valid_but_stale_geometry(self):
        damaged = copy.deepcopy(self.documents["nature_trail"])
        damaged["features"][0]["geometry"]["coordinates"][0] = 134.6
        self.write_source("nature_trail", damaged)
        with self.assertRaisesRegex(ValueError, "differ from published inputs"):
            self.validate_data()

    def test_rejects_noncanonical_temple_numbers(self):
        damaged = copy.deepcopy(self.documents["temples"])
        damaged["features"][0]["properties"]["number"] = 2
        self.write_source("temples", damaged)
        with self.assertRaisesRegex(ValueError, "Canonical temples"):
            self.validate_data()

    def test_rejects_empty_source_specific_buckets(self):
        damaged = copy.deepcopy(self.documents["sekaiisan"])
        damaged["toilets"] = []
        self.write_source("sekaiisan", damaged)
        with self.assertRaisesRegex(ValueError, "nonempty toilets"):
            self.validate_data()

    def test_invalid_source_preserves_previous_valid_geojson_and_reports(self):
        self.validate_data()
        common.atomic_json(self.reports / "pipeline.json", {"previous": "publication"})
        before = self.published_bytes()
        damaged = copy.deepcopy(self.documents["mizutani"])
        damaged["features"][0]["geometry"]["coordinates"] = [0, 0]
        self.write_source("mizutani", damaged)
        with self.assertRaisesRegex(ValueError, "coordinates"):
            self.build()
        self.assertEqual(self.published_bytes(), before)

    def test_tile_compiler_failure_preserves_previous_valid_geojson_and_reports(self):
        self.validate_data()
        common.atomic_json(self.reports / "pipeline.json", {"previous": "publication"})
        before = self.published_bytes()
        with patch.object(common, "build_pmtiles", side_effect=RuntimeError("tile compiler failed")):
            with self.assertRaisesRegex(RuntimeError, "tile compiler failed"):
                self.build()
        self.assertEqual(self.published_bytes(), before)

    def test_upstream_failure_preserves_previous_valid_geojson_and_reports(self):
        self.validate_data()
        common.atomic_json(self.reports / "pipeline.json", {"previous": "publication"})
        before = self.published_bytes()
        error = subprocess.CalledProcessError(1, ["upstream", "run"])
        with patch.object(common, "run", side_effect=error), contextlib.redirect_stderr(io.StringIO()):
            result = pipeline.main(["run", "--skip-osm", "--output-dir", str(self.output),
                                    "--reports-dir", str(self.reports)])
        self.assertEqual(result, 1)
        self.assertEqual(self.published_bytes(), before)

    def test_hash_check_rejects_modified_managed_output(self):
        # Hash verification is independent of tile tools and catches any managed artifact change.
        (self.output / pipeline.TILES).write_bytes(b"recorded archive payload")
        common.atomic_json(self.reports / "pipeline.json", {
            "inputs": pipeline.source_inputs(self.datasets),
            "build_config": pipeline.settings(common.IMAGE, True),
            "outputs": common.output_hashes(self.output, pipeline.OUTPUTS),
        })
        damaged = common.read_json(self.output / pipeline.REPORT)
        damaged["feature_count"] += 1
        common.atomic_json(self.output / pipeline.REPORT, damaged)
        with self.assertRaisesRegex(ValueError, "hash differs"):
            pipeline.validate(self.datasets, self.output, self.reports)

    def test_unchanged_build_preserves_published_bytes_hashes_and_timestamps(self):
        summary = self.validate_data()
        (self.output / pipeline.TILES).write_bytes(b"recorded archive payload")
        common.atomic_json(self.reports / "pipeline.json", {
            "inputs": pipeline.source_inputs(self.datasets),
            "build_config": pipeline.settings(common.IMAGE, True),
            "summary": summary,
            "outputs": common.output_hashes(self.output, pipeline.OUTPUTS),
        })
        paths = [self.output / name for name in pipeline.OUTPUTS] + [self.reports / "pipeline.json"]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        metadata = pipeline.tile_metadata(common.read_json(self.output / pipeline.REPORT))
        metadata["vector_layers"] = [{"id": "info_pois", "fields": dict.fromkeys(pipeline.FIELDS, "String")}]
        # Only the external archive verifier is substituted; real source and report checks still run.
        with patch.object(common, "validate_pmtiles", return_value=metadata):
            pipeline.build(self.datasets, self.raw, self.output, self.reports, skip_osm=True)
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)

    def test_remote_custom_root_fails_without_changing_published_files(self):
        before = self.published_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                pipeline.main(["run", "--datasets-dir", str(self.datasets), "--skip-osm",
                               "--output-dir", str(self.output)])
        self.assertEqual(self.published_bytes(), before)


if __name__ == "__main__":
    unittest.main()
