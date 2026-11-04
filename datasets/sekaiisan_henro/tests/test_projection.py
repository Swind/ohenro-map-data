import math
import unittest

from datasets.sekaiisan_henro.projection import (
    PROJECTION_METADATA,
    limitation_note,
    project_coords,
    project_point,
    unproject_coords,
    unproject_point,
)

# Bounding box of Shikoku (well within the projection domain).
SHIKOKU = [
    (131.77, 32.23),
    (135.18, 32.23),
    (135.18, 34.65),
    (131.77, 34.65),
    (133.75, 33.65),
    (134.0, 33.5),
]


class TestProjection(unittest.TestCase):
    def test_round_trip_across_shikoku(self):
        for lon, lat in SHIKOKU:
            x, y = project_point(lon, lat)
            lon2, lat2 = unproject_point(x, y)
            self.assertAlmostEqual(lon, lon2, places=9)
            self.assertAlmostEqual(lat, lat2, places=9)

    def test_round_trip_coordinate_lists(self):
        projected = project_coords(SHIKOKU)
        restored = unproject_coords(projected)
        for (lon, lat), (lon2, lat2) in zip(SHIKOKU, restored):
            self.assertAlmostEqual(lon, lon2, places=9)
            self.assertAlmostEqual(lat, lat2, places=9)

    def test_reference_point_is_origin(self):
        x, y = project_point(133.75, 33.65)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_scale_is_metric(self):
        # 1 degree of latitude is ~111.19 km (R * radians(1)).
        _, y0 = project_point(133.75, 33.65)
        _, y1 = project_point(133.75, 34.65)
        self.assertAlmostEqual(y1 - y0, 6371008.8 * math.radians(1.0), delta=1e-6)

    def test_metadata_is_fixed(self):
        self.assertEqual(PROJECTION_METADATA,
                         {"kind": "equirectangular", "R": 6371008.8,
                          "lon0": 133.75, "lat0": 33.65})

    def test_limitation_note_documents_approximation(self):
        note = limitation_note()
        self.assertIn("equirectangular", note)
        self.assertIn("approximate", note)
        self.assertIn("WGS84", note)


if __name__ == "__main__":
    unittest.main()