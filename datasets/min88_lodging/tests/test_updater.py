import copy
from pathlib import Path
import tempfile
import unittest

from datasets import _pipeline as common
from datasets.min88_lodging.export_map import export_map
from datasets.min88_lodging.geocode import enrich_record
from datasets.min88_lodging.pipeline import normalize_file, parse_archive, read_jsonl, write_jsonl
from datasets.min88_lodging.report import generate_report
from datasets.min88_lodging.updater import FILES, build, fetch, resolve, validate_data
from datasets.min88_lodging.tests.test_pipeline import FakeClient, detail
from datasets.min88_lodging.index_parser import parse_index_document

FIXTURE = Path(__file__).parent / "fixtures/index-list.html"


class UpdaterBoundaryTests(unittest.TestCase):
    def archive(self, root, uncertain_price=False):
        body = FIXTURE.read_bytes()
        ids = [row["source_id"] for row in parse_index_document(body.decode())["records"]]
        pages = [detail(source_id) for source_id in ids]
        if uncertain_price:
            pages = [page.replace("素泊り：4,200円".encode(), "素泊り：".encode()) for page in pages]
        client = FakeClient([(200, {}, body), *((200, {}, page) for page in pages)])
        return fetch(root, client=client, delay=0), ids

    def test_partial_refresh_preserves_current_snapshot_and_original_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, ids = self.archive(root)
            selector = (root / "current.json").read_bytes()
            original = (snapshot / f"records/{ids[0]}/page.html").read_bytes()
            body = FIXTURE.read_bytes()
            responses = [(200, {}, body), (503, {}, b"maintenance")]
            responses.extend((200, {}, detail(source_id)) for source_id in ids[1:])
            with self.assertRaisesRegex(ValueError, "Incomplete min88 refresh"):
                fetch(root, client=FakeClient(responses), delay=0)
            self.assertEqual((root / "current.json").read_bytes(), selector)
            self.assertEqual(resolve(root), snapshot)
            self.assertEqual((snapshot / f"records/{ids[0]}/page.html").read_bytes(), original)

    def test_content_identical_refresh_reuses_snapshot_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, ids = self.archive(root)
            again, _ = self.archive(root)
            self.assertEqual(snapshot, again)
            page = snapshot / f"records/{ids[0]}/page.html"
            page.write_bytes(page.read_bytes() + b"\nchanged")
            with self.assertRaisesRegex(ValueError, "provenance"):
                resolve(root)

    def test_local_missing_geocode_preserves_prior_outputs_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, _ = self.archive(root / "raw")
            output, reports = root / "output", root / "reports"
            output.mkdir()
            reports.mkdir()
            for name in FILES:
                (output / name).write_bytes(b"prior published artifact")
            (reports / "pipeline.json").write_bytes(b"prior published report")
            with self.assertRaisesRegex(ValueError, "Google fetch failed"):
                build(snapshot, output, reports, root / "empty-cache", local=True, delay=0)
            for name in FILES:
                self.assertEqual((output / name).read_bytes(), b"prior published artifact")
            self.assertEqual((reports / "pipeline.json").read_bytes(), b"prior published report")

    def test_warning_retention_and_exact_resolved_map_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, _ = self.archive(root / "raw", uncertain_price=True)
            output = root / "output"
            parse_archive(str(snapshot), str(output / "raw.jsonl"))
            normalize_file(str(output / "raw.jsonl"), str(output / "v1.jsonl"))
            rows = read_jsonl(output / "v1.jsonl")
            enriched = copy.deepcopy(rows)
            def place(*args, **kwargs):
                return ({"latitude": 34.0, "longitude": 134.0, "name": "宿",
                         "address": "徳島県", "place_id": "fixture-place", "cid": "1"},
                        False, "https://www.google.com/maps?q=fixture", True)
            for row in enriched:
                enrich_record(row, str(root / "cache"), fetcher=place)
            write_jsonl(output / "v1-geocoded.jsonl", enriched)
            export_map(str(output / "v1-geocoded.jsonl"), str(output / "map.geojson"))
            generate_report(str(snapshot), str(output))
            summary = validate_data(snapshot, output, tiles=False)
            self.assertEqual(summary["features"], len(rows))
            self.assertGreaterEqual(summary["warnings"]["by_code"]["UNRECOGNIZED_FORMAT"], 1)
            collection = common.read_json(output / "map.geojson")
            collection["features"][0]["geometry"]["coordinates"][0] += 0.01
            common.atomic_json(output / "map.geojson", collection)
            with self.assertRaisesRegex(ValueError, "geometry/accounting"):
                validate_data(snapshot, output, tiles=False)


if __name__ == "__main__":
    unittest.main()
