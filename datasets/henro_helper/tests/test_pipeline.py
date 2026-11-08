import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.henro_helper import __main__ as pipeline
from datasets.henro_helper.reference import extract_routes as extractor


class ExtractionTests(unittest.TestCase):
    def test_record_before_another_class_is_not_lost(self):
        assembly = '''    // 0x100: r0 = AllocateTheTemplesStub(); AllocateTheTemplesStub -> TheTemples (size=0x40)
    // 0x104: r1 = "Temple 1"
    // 0x108: StoreField: r0->field_b = r1
    // 0x10c: r0 = AllocateOtherListStub(); AllocateOtherListStub -> OtherList (size=0x40)
'''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Temples.dart").write_text(assembly)
            with patch.object(extractor, "ASM_DIR", directory):
                records = extractor.parse_poi_class("Temples.dart", "TheTemples")
        self.assertEqual(records, [{"fields": {"field_b": ("str", "Temple 1")}, "obj_reg": "0"}])


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.layers = {}
        self.accounting = {"routes": {}, "pois": {}}
        for group, names in pipeline.GROUPS.items():
            for name in names:
                features = []
                if name == "black":
                    features = [{"type": "Feature", "properties": {"id": "black-0000", "layer": "black", "num_points": 2},
                                 "geometry": {"type": "LineString", "coordinates": [[134.0, 34.0], [134.1, 34.1]]}}]
                elif name == "temples":
                    features = [{"type": "Feature", "properties": {"id": f"temples-{n:04d}", "layer": "temples",
                                 "kind": "temple", "temple_number": n, "index": n - 1, "num_points": 1},
                                 "geometry": {"type": "Point", "coordinates": [134.0, 34.0]}} for n in range(1, 89)]
                self.layers[name] = features
                counts = {"features": len(features)}
                if group == "routes":
                    counts.update(points=sum(f["properties"]["num_points"] for f in features),
                                  reference_constructors=0, singleton_path_count=0)
                else:
                    counts.update(records=len(features), unresolved_coordinates=0, nonspatial_records=[])
                self.accounting[group][name] = counts
        self.save()

    def save(self):
        for group, names in pipeline.GROUPS.items():
            combined = []
            for name in names:
                features = self.layers[name]
                (self.output / f"{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "name": name, "features": features}))
                combined.extend(features)
            (self.output / f"henro-helper-{group}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": combined}))
        (self.output / "extraction-report.json").write_text(json.dumps(self.accounting))

    def test_complete_layers_preserve_route_and_temple_accounting(self):
        summary = pipeline.validate_data(self.output)
        self.assertEqual(summary["routes"], {
            "feature_count": 1, "point_count": 2, "by_layer": {"black": 1}, "singleton_path_count": 0})
        self.assertEqual(summary["pois"], {
            "feature_count": 88, "point_count": 88, "by_layer": {"temples": 88}, "nonspatial_record_count": 0})

    def test_combined_route_must_match_layer_geometry(self):
        path = self.output / "henro-helper-routes.geojson"
        data = json.loads(path.read_text())
        data["features"][0]["geometry"]["coordinates"].reverse()
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Combined routes"):
            pipeline.validate_data(self.output)

    def test_unresolved_poi_is_not_silently_published(self):
        self.accounting["pois"]["toilets"].update(records=1, unresolved_coordinates=1)
        self.save()
        with self.assertRaisesRegex(ValueError, "Unresolved/dropped POI"):
            pipeline.validate_data(self.output)

    def test_duplicate_temple_number_cannot_replace_missing_temple(self):
        self.layers["temples"][-1]["properties"]["temple_number"] = 87
        self.save()
        with self.assertRaisesRegex(ValueError, "temples 1–88"):
            pipeline.validate_data(self.output)

    def test_route_outside_shikoku_is_rejected(self):
        self.layers["black"][0]["geometry"]["coordinates"][1] = [0.0, 0.0]
        self.save()
        with self.assertRaisesRegex(ValueError, "Shikoku coordinate"):
            pipeline.validate_data(self.output)

    def test_nonspatial_source_text_is_preserved_without_inventing_poi(self):
        self.accounting["pois"]["roadside_yes_list"].update(records=1, nonspatial_records=[
            {"index": 0, "class": "RoadsideYesList", "fields": {"field_7": ["str", "https://maps.google.com/"]},
             "reason": "source_record_contains_text_not_coordinates"}])
        self.save()
        summary = pipeline.validate_data(self.output)
        self.assertEqual(summary["pois"]["feature_count"], 88)
        self.assertEqual(summary["pois"]["nonspatial_record_count"], 1)

    def test_source_singleton_path_is_valid_point_not_fabricated_segment(self):
        feature = self.layers["black"][0]
        feature["properties"]["num_points"] = 1
        feature["geometry"] = {"type": "Point", "coordinates": [134.0, 34.0]}
        self.accounting["routes"]["black"].update(points=1, singleton_path_count=1)
        self.save()
        self.assertEqual(pipeline.validate_data(self.output)["routes"]["singleton_path_count"], 1)


if __name__ == "__main__":
    unittest.main()
