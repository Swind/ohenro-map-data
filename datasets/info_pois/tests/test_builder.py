from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

from google.protobuf.message import DecodeError
import mapbox_vector_tile
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build-info-pois.py"
spec = importlib.util.spec_from_file_location("info_poi_builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def archive(path: Path, payload: bytes) -> None:
    with path.open("wb") as handle:
        writer = Writer(handle)
        writer.write_tile(zxy_to_tileid(15, 28541, 13068), payload)
        writer.finalize({"tile_compression": Compression.NONE, "tile_type": TileType.MVT},
                        {"vector_layers": [{"id": "pois"}]})


class BuilderTests(unittest.TestCase):
    def test_mvt_coordinates_keep_north_south_orientation_and_curated_kinds(self):
        tile = mapbox_vector_tile.encode({"name": "pois", "features": [
            {"geometry": {"type": "Point", "coordinates": [1000, 500]},
             "properties": {"kind": kind, "name": kind}}
            for kind in ("toilets", "hotel", "restaurant")
        ]}, default_options={"y_coord_down": True})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pois.pmtiles"
            archive(path, tile)
            points, counts = builder.load_osm_basemap(path)
        self.assertEqual({point["properties"]["category"] for point in points},
                         {"toilet", "lodging"})
        self.assertEqual(counts, {"toilet": 1, "lodging": 1, "total": 2})
        expected_lon = (28541 + 1000 / 4096) / 32768 * 360 - 180
        expected_lat = math.degrees(math.atan(math.sinh(
            math.pi * (1 - 2 * (13068 + 500 / 4096) / 32768))))
        for point in points:
            lon, lat = point["geometry"]["coordinates"]
            self.assertAlmostEqual(lon, expected_lon, places=6)
            self.assertAlmostEqual(lat, expected_lat, places=6)

    def test_corrupt_osm_tile_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pois.pmtiles"
            archive(path, b"not a valid vector tile")
            with self.assertRaises(DecodeError):
                builder.load_osm_basemap(path)

    def test_dedicated_lodging_excluded_while_useful_pois_remain(self):
        point = {"type": "Point", "coordinates": [133.5, 34]}
        features = [{"properties": {"feature_id": "lodging", "category": "lodging"},
                     "geometry": point},
                    {"properties": {"feature_id": "rest", "category": "water_toilet_rest",
                                    "name": "休憩所"}, "geometry": point}]
        selected, counts = builder.load_mizutani(features)
        self.assertEqual([item["id"] for item in selected], ["rest"])
        self.assertEqual(counts, {"total": 1, "water_toilet_rest_split": {"rest_area": 1}})
        selected, counts = builder.load_arukihenro({"routes": [{"maps": [{"points": [
            {"category": "lodging", "coordinates": [133.5, 34]},
            {"category": "shrine", "coordinates": [133.5, 34]},
        ]}]}]})
        self.assertEqual([item["properties"]["category"] for item in selected], ["shrine"])

    def test_water_toilet_rest_precedence_is_conservative(self):
        expected = {"道の駅 温泉 湧水": "rest_area", "共楽湯": "onsen",
                    "湧き水": "water", "公園": "rest_area"}
        self.assertEqual({name: builder.mizutani_water_toilet_rest_category(name)
                          for name in expected}, expected)

    def test_invalid_included_coordinates_are_rejected(self):
        for coordinates in (None, [], [133.5], [True, 34], [133.5, float("nan")], [0, 0]):
            with self.subTest(coordinates=coordinates), self.assertRaises(ValueError):
                builder.load_arukihenro({"routes": [{"maps": [{"points": [
                    {"category": "shrine", "coordinates": coordinates},
                ]}]}]})

    def test_explicit_source_coordinate_defects_never_become_pois(self):
        point = {"type": "Point", "coordinates": [133.5, 34]}
        selected, counts = builder.load_sekaiisan({
            "temples": [{"id": "temple", "geometry": point}],
            "toilets": [{"id": "toilet", "geometry": point}],
            "toilet_defects": [{"id": "typo", "raw_coordinate": "1330000212,32.7873752"}],
        })
        self.assertEqual({item["id"] for item in selected}, {"temple", "toilet"})
        self.assertEqual(counts, {"sekaiisan_temples": 1, "sekaiisan_toilets": 1})


if __name__ == "__main__":
    unittest.main()
