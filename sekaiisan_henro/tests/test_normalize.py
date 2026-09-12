import json
import os
import tempfile
import unittest

from sekaiisan_henro import normalize
from sekaiisan_henro.tests import helpers

SNAPSHOT_SHA = "ab" * 32


def _make_data_dir(temple_numbers=None, route_counts=None):
    if temple_numbers is None:
        temple_numbers = list(range(1, 89))
    if route_counts is None:
        route_counts = helpers.standard_route_counts()
    data_dir = tempfile.mkdtemp()
    helpers.write_snapshot(data_dir, SNAPSHOT_SHA, route_counts, temple_numbers)
    return data_dir


class TestNormalize(unittest.TestCase):
    def test_deterministic_output_and_accounting(self):
        data_dir = _make_data_dir()
        first = normalize.build_normalized(data_dir, "current")
        second = normalize.build_normalized(data_dir, SNAPSHOT_SHA)
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["dataset_id"], "88sekaiisan-henro")
        self.assertEqual(first["snapshot_sha256"], SNAPSHOT_SHA)
        self.assertNotIn("timestamp", json.dumps(first))
        acct = first["accounting"]
        self.assertEqual(acct["routes"], 5)
        self.assertEqual(acct["linestrings"], 8)
        self.assertEqual(acct["points"], 16)
        self.assertEqual(acct["temples"], 88)
        self.assertEqual(acct["toilets"], 4)
        self.assertEqual(acct["missing_source_fid"], 0)
        self.assertEqual(acct["by_prefecture"]["tokushima"], {"routes": 2, "linestrings": 3, "points": 6, "missing_source_fid": 0})
        self.assertEqual(acct["by_prefecture"]["kochi"], {"routes": 1, "linestrings": 3, "points": 6, "missing_source_fid": 0})
        self.assertEqual(acct["by_prefecture"]["ehime"], {"routes": 1, "linestrings": 1, "points": 2, "missing_source_fid": 0})
        self.assertEqual(acct["by_prefecture"]["kagawa"], {"routes": 1, "linestrings": 1, "points": 2, "missing_source_fid": 0})
        self.assertEqual(acct["by_prefecture"]["toilets"],
                         {"tokushima": 2, "kochi": 1, "ehime": 0, "kagawa": 1})
        # toilets keep per-file source order and stable ids
        toilets = first["toilets"]
        self.assertEqual([t["id"] for t in toilets],
                         ["SHT_tokushima_1", "SHT_tokushima_2",
                          "SHT_kochi_1", "SHT_kagawa_1"])
        # structured description-table fields survive parsing
        self.assertEqual(toilets[0]["facility_name"], "県庁舎")
        self.assertEqual(toilets[0]["toilet_type"], "和・洋式両方、多目的トイレ")
        self.assertEqual(toilets[0]["washlet"], "有り")
        # HTML inside a value is stripped
        self.assertEqual(toilets[1]["notes"], "夜間は閉鎖")
        # toilet without a description keeps raw_type only
        self.assertEqual(toilets[2]["raw_type"], "屋外トイレ(Toilet)")
        self.assertNotIn("facility_name", toilets[2])
        # MultiGeometry parts share source_order and get distinct part/IDs
        tokushima = [r for r in first["routes"] if r["prefecture"] == "tokushima"]
        self.assertEqual([r["id"] for r in tokushima], ["SHR_tokushima_1_1", "SHR_tokushima_2_1", "SHR_tokushima_2_2"])
        self.assertEqual(tokushima[1]["source_order"], tokushima[2]["source_order"])
        # Routes keep the declared ROUTE_FILES order (tokushima, kochi, ehime, kagawa)
        self.assertEqual([r["prefecture"] for r in first["routes"]],
                         ["tokushima"] * 3 + ["kochi"] * 3 + ["ehime"] + ["kagawa"])
        # temples sorted by number, exactly 1..88
        self.assertEqual([t["number"] for t in first["temples"]], list(range(1, 89)))
        # source file references present
        self.assertEqual(first["source_files"]["routes/tokushima.kml"]["source_file"], "source_0.kml")

    def test_missing_source_fid_accounting(self):
        counts = helpers.standard_route_counts()
        counts["routes/ehime.kml"] = [
            (None, [[[132.0, 33.0], [132.1, 33.1]]]),   # FID-less -> geometry identity
            ("1", [[[132.2, 33.2], [132.3, 33.3]]]),
        ]
        data_dir = _make_data_dir(route_counts=counts)
        result = normalize.build_normalized(data_dir, "current")
        acct = result["accounting"]
        self.assertEqual(acct["missing_source_fid"], 1)
        self.assertEqual(acct["by_prefecture"]["ehime"]["missing_source_fid"], 1)
        self.assertEqual(acct["by_prefecture"]["tokushima"]["missing_source_fid"], 0)
        ehime = [r for r in result["routes"] if r["prefecture"] == "ehime"]
        self.assertEqual(len(ehime), 2)
        first = ehime[0]
        self.assertIsNone(first["source_fid"])
        self.assertEqual(first["source_identity_kind"], "geometry_sha256")
        self.assertTrue(first["id"].startswith("SHR_ehime_geometry_"))
        self.assertRegex(first["geometry_sha256"], r"^[0-9a-f]{64}$")
        # FID-based record keeps its identity
        self.assertEqual(ehime[1]["source_fid"], "1")
        self.assertEqual(ehime[1]["source_identity_kind"], "fid")

    def test_missing_temple_number_fails(self):
        data_dir = _make_data_dir(temple_numbers=list(range(1, 88)))
        with self.assertRaisesRegex(ValueError, "temple numbers missing"):
            normalize.build_normalized(data_dir, "current")

    def test_duplicate_temple_number_fails(self):
        data_dir = _make_data_dir(temple_numbers=list(range(1, 89)) + [1])
        with self.assertRaisesRegex(ValueError, "duplicate temple number"):
            normalize.build_normalized(data_dir, "current")

    def test_malformed_toilet_coordinate_accounted_as_defect(self):
        # Build the standard fixture, then replace the kochi toilet file body
        # with one malformed coordinate (a source-data typo, never "fixed").
        data_dir = _make_data_dir()
        snapshot_dir = os.path.join(data_dir, "snapshots", SNAPSHOT_SHA)
        body = helpers.toilet_kml([
            "<Placemark><name>公衆トイレ(Toilet)</name>"
            "<Point><coordinates>1330000212,32.7873752</coordinates></Point></Placemark>"
        ])
        path = os.path.join(snapshot_dir, "toilets/kochi.kml")
        with open(path, "wb") as stream:
            stream.write(body)
        import hashlib
        metadata_path = os.path.join(snapshot_dir, "metadata.json")
        with open(metadata_path, encoding="utf-8") as stream:
            metadata = json.load(stream)
        for entry in metadata["files"]:
            if entry["local_path"] == "toilets/kochi.kml":
                entry["sha256"] = hashlib.sha256(body).hexdigest()
                entry["size"] = len(body)
                break
        with open(metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, ensure_ascii=False, sort_keys=True)

        result = normalize.build_normalized(data_dir, "current")
        acct = result["accounting"]
        self.assertEqual(acct["toilets"], 3)
        self.assertEqual(acct["toilet_defects"], 1)
        self.assertEqual(acct["by_prefecture"]["toilets"]["kochi"], 0)
        self.assertEqual(acct["by_prefecture"]["toilet_defects"]["kochi"], 1)
        defect = result["toilet_defects"][0]
        self.assertEqual(defect["raw_type"], "公衆トイレ(Toilet)")
        self.assertEqual(defect["raw_coordinate"], "1330000212,32.7873752")
        self.assertIn("longitude", defect["reason"])

    def test_failed_normalization_preserves_existing_output(self):
        data_dir = _make_data_dir(temple_numbers=list(range(1, 88)))  # missing 88
        output = os.path.join(data_dir, "out.json")
        with open(output, "w", encoding="utf-8") as stream:
            stream.write("SENTINEL")
        with self.assertRaises(ValueError):
            normalize.run_normalize(data_dir, "current", output)
        with open(output, encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "SENTINEL")

    def test_successful_write_is_atomic_and_well_formed(self):
        data_dir = _make_data_dir()
        output = os.path.join(data_dir, "out.json")
        result = normalize.run_normalize(data_dir, "current", output)
        self.assertEqual(result["accounting"]["temples"], 88)
        with open(output, encoding="utf-8") as stream:
            loaded = json.load(stream)
        self.assertEqual(loaded["snapshot_sha256"], SNAPSHOT_SHA)
        self.assertFalse(os.path.exists(output + ".tmp"))

    def test_invalid_snapshot_rejected(self):
        data_dir = _make_data_dir()
        with self.assertRaisesRegex(ValueError, "current.json|not found|64-hex"):
            normalize.resolve_snapshot(os.path.join(data_dir, "nope"), "current")


if __name__ == "__main__":
    unittest.main()