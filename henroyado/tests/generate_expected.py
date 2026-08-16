#!/usr/bin/env python3
"""Generate expected V1 JSONs for fixtures from the current pipeline.

Freeze current (reviewed) output so future code changes get regression tests.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "henroyado", "tests", "fixtures")
EXPECTED = os.path.join(FIXTURES, "expected")

sys.path.insert(0, ROOT)

from bs4 import BeautifulSoup

from henroyado.html_parser.inn import extract_inn
from henroyado.normalize import normalize_inn


def parse_fixture(html):
    soup = BeautifulSoup(html, "html.parser")
    row = soup.select_one("tr.bl_table_row_frontInfo")
    detail = row.find_next_sibling("tr")
    return extract_inn(row, detail)


def main():
    os.makedirs(EXPECTED, exist_ok=True)
    for path in sorted(os.listdir(FIXTURES)):
        if not path.endswith(".html"):
            continue
        slug = path[:-5]
        raw = parse_fixture(open(os.path.join(FIXTURES, path), encoding="utf-8").read())
        v1 = normalize_inn(raw.to_dict(), retrieved_at=None)
        with open(os.path.join(EXPECTED, slug + ".json"), "w", encoding="utf-8") as f:
            json.dump(v1, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("wrote expected/%s.json" % slug)


if __name__ == "__main__":
    main()
