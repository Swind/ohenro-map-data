"""Regression tests: HTML fixture -> RawInn -> HenroyadoInnV1 == frozen expected.

Plan §27/§28. Each fixture is a real record fragment extracted from the live
page (see extract_fixtures.py); expected JSON is frozen output (see
generate_expected.py). Run:  python3 -m unittest discover henroyado/tests
"""

import glob
import json
import os
import unittest

from bs4 import BeautifulSoup

from henroyado.html_parser.inn import extract_inn
from henroyado.normalize import normalize_inn

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture_records():
    records = {}
    for path in sorted(glob.glob(os.path.join(FIXTURES, "*.html"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        records[slug] = path
    return records


def _parse_fixture(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    row = soup.select_one("tr.bl_table_row_frontInfo")
    detail = row.find_next_sibling("tr")
    return normalize_inn(extract_inn(row, detail).to_dict(), retrieved_at=None)


class TestPipelineRegression(unittest.TestCase):
    def test_fixtures_match_frozen_expected(self):
        fixtures = _fixture_records()
        self.assertTrue(fixtures, "no fixtures found")
        for slug, path in fixtures.items():
            with self.subTest(slug=slug):
                actual = _parse_fixture(path)
                expected_path = os.path.join(FIXTURES, "expected", slug + ".json")
                with open(expected_path, encoding="utf-8") as f:
                    expected = json.load(f)
                self.assertEqual(actual, expected, "fixture %s drifted" % slug)


if __name__ == "__main__":
    unittest.main()
