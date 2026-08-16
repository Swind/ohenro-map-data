#!/usr/bin/env python3
"""Extract real record fragments from the raw HTML snapshot as test fixtures.

Each fixture is a minimal wrapper preserving the parser's context needs:
  <div class="js_prefGroup" data-pref="...">
    <table class="bl_table bl_tableGray">
      <caption class="bl_heading js_temple_N">...</caption>
      <tbody class="bl_table_item js_list" data-type="...">
        <tr class="bl_table_row_frontInfo">...</tr>
        <tr class="bl_table_row_detail">...</tr>
      </tbody>
    </table>
  </div>
"""

import os
import sys

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_HTML = os.path.join(ROOT, "source", "henroyado.html")
FIXTURE_DIR = os.path.join(ROOT, "henroyado", "tests", "fixtures")

SELECT = {
    "ootoriien": ["旅館.大鳥居苑"],
    "no_meal": ["ゲストハウス鳴門おへんろ"],
    "no_detail": ["Guesthose ほとけの座"],
    "multi_room": ["Hostel 東風ノ家"],
    "fullwidth_times": ["徳島ワシントンホテルプラザ"],
    "price": ["お遍路ハウス一番門前通り"],
}


def main():
    soup = BeautifulSoup(open(RAW_HTML, encoding="utf-8").read(), "html.parser")
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    found = {}
    for row in soup.select("tr.bl_table_row_frontInfo"):
        name = row.select_one("td span")
        name = " ".join(name.get_text(" ", strip=True).split()) if name else ""
        for slug, names in SELECT.items():
            if slug in found:
                continue
            if any(n == name for n in names):
                found[slug] = row
    for slug, row in found.items():
        detail = row.find_next_sibling("tr")
        table = row.find_parent("table")
        caption = table.find("caption")
        tbody = row.find_parent("tbody")
        group = row.find_parent("div", class_="js_prefGroup")
        row_name = row.select_one("td span")
        row_name = " ".join(row_name.get_text(" ", strip=True).split()) if row_name else ""
        html = (
            '<div class="js_prefGroup" data-pref="%s">\n'
            "<table class=\"bl_table bl_tableGray\">\n"
            "%s\n"
            '<tbody class="bl_table_item js_list" data-type="%s">\n'
            "%s\n%s\n"
            "</tbody>\n</table>\n</div>\n"
        ) % (
            group.get("data-pref"),
            caption.prettify() if caption else "",
            tbody.get("data-type") or "",
            row.prettify(),
            detail.prettify() if detail is not None else "",
        )
        with open(os.path.join(FIXTURE_DIR, slug + ".html"), "w", encoding="utf-8") as f:
            f.write(html)
        print("%-16s %s" % (slug, row_name))
    missing = [s for s in SELECT if s not in found]
    if missing:
        print("MISSING:", missing)
        sys.exit(1)


if __name__ == "__main__":
    main()
