import hashlib
import json
import os
import tempfile
import unittest

from min88_lodging.pipeline import (crawl_detail_archive, crawl_index_archive,
                                    normalize_file, parse_archive)
from min88_lodging.report import generate_report
from min88_lodging.verify import verify


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "index-list.html")


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def get_bytes(self, url):
        return self.responses.pop(0)


def detail(source_id):
    return ("""<html><head><link rel="canonical" href="https://min88.jp/inn/%s/">
<meta property="og:image" content="https://example.test/image.jpg"></head>
<body><div id="article"><h1 id="post_title">宿 %s</h1>
<div class="min88-basicdata-pack"><textarea class="min88-basicdata-kv">
address = 徳島県鳴門市
rooms = ２室
checkin = 16:00～20:00
price = 素泊り：4,200円
</textarea></div></div></body></html>""" % (source_id, source_id)).encode("utf-8")


class PipelineTests(unittest.TestCase):
    def _build(self, root):
        with open(FIXTURE, "rb") as handle:
            index_body = handle.read()
        data_dir = os.path.join(root, "source")
        output_dir = os.path.join(root, "output")
        index_result = crawl_index_archive(data_dir, client=FakeClient([(200, {}, index_body)]))
        ids = [item["source_id"] for item in index_result["index"]["records"]]
        crawl_detail_archive(data_dir, client=FakeClient([(200, {}, detail(source_id)) for source_id in ids]))
        raw_path = os.path.join(output_dir, "raw.jsonl")
        v1_path = os.path.join(output_dir, "v1.jsonl")
        parse_archive(data_dir, raw_path)
        normalize_file(raw_path, v1_path, data_dir)
        return data_dir, output_dir, ids

    def test_archive_parse_normalize_verify_and_report(self):
        with open(FIXTURE, "rb") as handle:
            index_body = handle.read()
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "source")
            output_dir = os.path.join(root, "output")
            index_result = crawl_index_archive(data_dir, client=FakeClient([(200, {}, index_body)]))
            ids = [item["source_id"] for item in index_result["index"]["records"]]
            details = [(200, {}, detail(source_id)) for source_id in ids]
            crawl_detail_archive(data_dir, client=FakeClient(details))

            raw_path = os.path.join(output_dir, "raw.jsonl")
            v1_path = os.path.join(output_dir, "v1.jsonl")
            self.assertEqual(parse_archive(data_dir, raw_path)["records"], len(ids))
            self.assertEqual(normalize_file(raw_path, v1_path, data_dir)["records"], len(ids))
            with open(raw_path, "rb") as handle:
                first_raw = handle.read()
            parse_archive(data_dir, raw_path)
            with open(raw_path, "rb") as handle:
                self.assertEqual(handle.read(), first_raw)

            result = verify(data_dir, output_dir)
            self.assertTrue(result["ok"], result["errors"])
            report = generate_report(data_dir, output_dir)
            self.assertEqual(report["records"]["v1"], len(ids))
            self.assertEqual(report["normalization_coverage"]["room_count"], len(ids))
            self.assertEqual(report["normalization_coverage"]["payment"], 0)
            with open(os.path.join(output_dir, "report.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), report)

    def test_parse_skips_missing_archive_and_verify_reports_count(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "source")
            output_dir = os.path.join(root, "output")
            os.makedirs(data_dir)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({"records": [{"source_id": "1", "source_url": "https://min88.jp/inn/1/"}]}, handle)
            result = parse_archive(data_dir, os.path.join(output_dir, "raw.jsonl"))
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"][0]["source_id"], "1")

    def test_verify_rejects_same_count_id_substitution_and_duplicate_raw_ids(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir, output_dir, _ = self._build(root)
            raw_path = os.path.join(output_dir, "raw.jsonl")
            with open(raw_path, encoding="utf-8") as handle:
                raw = [json.loads(line) for line in handle]
            raw[1]["source_context"]["source_id"] = raw[0]["source_context"]["source_id"]
            with open(raw_path, "w", encoding="utf-8") as handle:
                for item in raw:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            v1_path = os.path.join(output_dir, "v1.jsonl")
            with open(v1_path, encoding="utf-8") as handle:
                v1 = [json.loads(line) for line in handle]
            v1[-1]["source"]["source_id"] = "999999"
            with open(v1_path, "w", encoding="utf-8") as handle:
                for item in v1:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            errors = verify(data_dir, output_dir)["errors"]
            self.assertIn("Raw contains duplicate source IDs", errors)
            self.assertIn("Raw source IDs/order do not match index", errors)
            self.assertIn("V1 source IDs/order do not match index", errors)

    def test_verify_rejects_wrong_geocoded_ids_and_stale_nonresolved_location(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir, output_dir, _ = self._build(root)
            with open(os.path.join(output_dir, "v1.jsonl"), encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle]
            records[-1]["source"]["source_id"] = "999999"
            records[0]["location"].update({
                "map_data_status": "place_not_found",
                "coordinates": {"latitude": 34.0, "longitude": 134.0,
                                "source": "google_maps_embed_place"},
                "google_maps_place_id": "stale",
            })
            records[0]["_warnings"].append({"code": "GOOGLE_MAPS_PLACE_NOT_FOUND"})
            path = os.path.join(output_dir, "v1-geocoded.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                for item in records:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            errors = verify(data_dir, output_dir)["errors"]
            self.assertIn("V1 geocoded source IDs/order do not match index", errors)
            self.assertTrue(any("non-resolved location retains" in error for error in errors))
            report = generate_report(data_dir, output_dir)
            self.assertEqual(report["warnings"]["by_code"]["GOOGLE_MAPS_PLACE_NOT_FOUND"], 1)

    def test_failed_forced_refresh_retains_archive_metadata_and_checksum(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir, _, ids = self._build(root)
            page = os.path.join(data_dir, "records", ids[0], "page.html")
            with open(page, "rb") as handle:
                expected_hash = hashlib.sha256(handle.read()).hexdigest()
            failures = [(200, {}, detail("999999")) for _ in ids]
            crawl_detail_archive(data_dir, force=True, client=FakeClient(failures))
            with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            retained = manifest["details"][0]
            self.assertEqual(retained["status"], "fetched")
            self.assertEqual(retained["sha256"], expected_hash)
            self.assertEqual(retained["latest_fetch"]["status"], "failed")
            self.assertIn("canonical", retained["latest_fetch"]["error"])


if __name__ == "__main__":
    unittest.main()
