import json
import os
import tempfile
import unittest

from henroyado.export_map import export_map


def record(place_id="place-1", status="resolved"):
    return {
        "identity": {"name": "宿"}, "contact": {"phone": "090-0000-0000"},
        "location": {"map_data_status": status, "google_maps_place_id": place_id,
                     "coordinates": {"latitude": 34.0, "longitude": 134.0, "source": "google"}},
    }


class ExportMapTest(unittest.TestCase):
    def test_exports_one_feature_per_resolved_place(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "v1.jsonl")
            output = os.path.join(root, "map.geojson")
            with open(source, "w", encoding="utf-8") as handle:
                for value in (record(), record(), record("place-2", "place_not_found")):
                    handle.write(json.dumps(value) + "\n")
            result = export_map(source, output)
            with open(output, encoding="utf-8") as handle:
                geojson = json.load(handle)
        self.assertEqual(result, {"records": 3, "features": 1, "skipped": 1, "duplicates": 1})
        self.assertEqual(geojson["features"][0]["properties"]["source_id"], "place-1")
