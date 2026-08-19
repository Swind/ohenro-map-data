import json
import tempfile
import unittest
from pathlib import Path

from min88_lodging.export_map import export_map


class ExportMapTests(unittest.TestCase):
    def test_exports_only_resolved_coordinates(self):
        resolved = {
            "source": {"source_id": "85", "source_url": "https://min88.jp/inn/85/"},
            "identity": {"name": "宿"},
            "lodging_types": ["guesthouse"],
            "location": {
                "map_data_status": "resolved",
                "address": "徳島県",
                "coordinates": {"latitude": 34.1, "longitude": 134.2, "source": "google_maps_embed_place"},
            },
        }
        pending = {"source": {"source_id": "86"}, "location": {"map_data_status": "pending_geocode"}}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory, "input.jsonl")
            output_path = Path(directory, "map.geojson")
            input_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in (resolved, pending)) + "\n")
            stats = export_map(input_path, output_path)
            result = json.loads(output_path.read_text())

        self.assertEqual(stats, {"records": 2, "features": 1, "skipped": 1})
        self.assertEqual(result["features"][0]["id"], "min88-85")
        self.assertEqual(result["features"][0]["geometry"]["coordinates"], [134.2, 34.1])
        self.assertEqual(result["features"][0]["properties"]["lodging_type"], "guesthouse")
