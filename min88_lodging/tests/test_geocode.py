import tempfile
import unittest
from unittest.mock import Mock

from min88_lodging.geocode import (enrich_file, enrich_record, fetch_place,
                                   is_shikoku_place, parse_place_result)


CONTENT = ('[["0x3553716e3f5f7783:0x2a32cfd2665058f9",'
           '"徳島県鳴門市",[34.159699,134.501842],"3040721200995129593"],"旅館"]')


class TestGeocode(unittest.TestCase):
    def test_rejects_viewport_and_accepts_marker(self):
        self.assertEqual(parse_place_result('[[3301.4,134.4,34.1]]'), (None, False))
        place, ambiguous = parse_place_result("", "https://google/maps/!8m2!3d34.1!4d134.2")
        self.assertFalse(ambiguous)
        self.assertEqual(place["longitude"], 134.2)

    def test_enrich_record_offline(self):
        def fake_fetch(url, cache_dir, timeout=30, force=False):
            place, ambiguous = parse_place_result(CONTENT)
            return place, ambiguous, "https://request", True

        record = {"identity": {"name": "旅館"}, "location": {
            "address": "徳島県鳴門市", "coordinates": None, "map_data_status": "pending_geocode",
            "google_maps_place_embed_url": "https://google/maps/embed?pb=viewport"}, "_warnings": []}
        with tempfile.TemporaryDirectory() as directory:
            status, _ = enrich_record(record, directory, fetcher=fake_fetch)
        self.assertEqual(status, "resolved")
        self.assertEqual(record["location"]["coordinates"]["latitude"], 34.159699)

    def test_outside_shikoku_rejected(self):
        def fake_fetch(url, cache_dir, timeout=30, force=False):
            return {"latitude": 35.68, "longitude": 139.76, "place_id": "x", "cid": None,
                    "name": "Tokyo", "address": "Tokyo"}, False, url, True

        record = {"identity": {"name": "x"}, "location": {"address": None, "coordinates": None,
                  "google_maps_place_embed_url": "https://google/maps/embed"}, "_warnings": []}
        with tempfile.TemporaryDirectory() as directory:
            status, _ = enrich_record(record, directory, fetcher=fake_fetch)
        self.assertEqual(status, "place_outside_shikoku")
        self.assertIsNone(record["location"]["coordinates"])

    def test_prefecture_and_polygon_shikoku_acceptance(self):
        examples = [
            ("徳島県徳島市", 34.07, 134.55), ("高知県高知市", 33.56, 133.53),
            ("愛媛県松山市", 33.84, 132.77), ("香川県高松市", 34.34, 134.05),
        ]
        for address, latitude, longitude in examples:
            self.assertTrue(is_shikoku_place({"address": address, "latitude": latitude,
                                              "longitude": longitude}))
        self.assertFalse(is_shikoku_place({"address": "広島県広島市", "latitude": 34.39,
                                           "longitude": 132.46}))
        self.assertFalse(is_shikoku_place({"address": "福岡県福岡市", "latitude": 33.59,
                                           "longitude": 130.40}))
        self.assertTrue(is_shikoku_place({"address": None, "latitude": 33.84,
                                          "longitude": 132.77}))
        self.assertFalse(is_shikoku_place({"address": None, "latitude": 34.39,
                                           "longitude": 132.46}))

    def test_retry_preserves_failure_precedence_and_clears_provenance(self):
        calls = iter([RuntimeError("network"), (None, False, "fallback", True)])

        def fake_fetch(*args, **kwargs):
            result = next(calls)
            if isinstance(result, Exception):
                raise result
            return result

        record = {"identity": {"name": "宿"}, "location": {
            "address": "徳島県徳島市", "coordinates": {"latitude": 1, "longitude": 2},
            "google_maps_place_id": "stale", "google_maps_place_embed_url": "embed",
        }, "_warnings": []}
        status, _ = enrich_record(record, "unused", fetcher=fake_fetch)
        self.assertEqual(status, "fetch_failed")
        self.assertIsNone(record["location"]["coordinates"])
        self.assertNotIn("google_maps_place_id", record["location"])

    def test_ambiguity_is_not_downgraded_to_not_found(self):
        calls = iter([(None, True, "embed", True), (None, False, "fallback", True)])

        def fake_fetch(*args, **kwargs):
            return next(calls)

        record = {"identity": {"name": "宿"}, "location": {
            "address": "徳島県徳島市", "google_maps_place_embed_url": "embed"}, "_warnings": []}
        status, _ = enrich_record(record, "unused", fetcher=fake_fetch)
        self.assertEqual(status, "place_ambiguous")
        self.assertIsNone(record["location"]["coordinates"])

    def test_file_counts_fetch_error_even_when_fallback_resolves(self):
        calls = 0

        def fake_fetch(url, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("network")
            return ({"address": "徳島県徳島市", "latitude": 34.07, "longitude": 134.55,
                     "place_id": "x", "cid": None, "name": "宿"}, False, url, True)

        record = {"identity": {"name": "宿"}, "location": {
            "address": "徳島県徳島市", "google_maps_place_embed_url": "embed"}, "_warnings": []}
        with tempfile.TemporaryDirectory() as directory:
            input_path = directory + "/in.jsonl"
            output_path = directory + "/out.jsonl"
            with open(input_path, "w", encoding="utf-8") as handle:
                import json
                handle.write(json.dumps(record) + "\n")
            stats = enrich_file(input_path, output_path, directory, delay=0, fetcher=fake_fetch)
        self.assertEqual((stats["geocoded"], stats["errors"]), (1, 1))

    def test_redirect_marker_survives_cache(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"no viewport or place record"
        response.geturl.return_value = "https://www.google.com/maps/!8m2!3d34.1!4d134.2"
        opener = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as directory:
            first = fetch_place("https://www.google.com/maps?q=x", directory, opener=opener)
            second = fetch_place("https://www.google.com/maps?q=x", directory, opener=opener)
        self.assertEqual(first[0]["latitude"], 34.1)
        self.assertEqual(second[0]["latitude"], 34.1)
        self.assertTrue(second[3])
        opener.assert_called_once()

    def test_rejects_non_google_initial_host_without_fetching(self):
        opener = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "host is not allowed: evil.example"):
                fetch_place("https://evil.example/maps?q=x", directory, opener=opener)
        opener.assert_not_called()

    def test_rejects_non_google_redirect_before_reading_content(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = "https://evil.example/crafted"
        opener = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "host is not allowed: evil.example"):
                fetch_place("https://www.google.com/maps?q=x", directory, opener=opener)
        opener.assert_called_once()
        response.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
