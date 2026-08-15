#!/usr/bin/env python3
import re
import sys
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.seichijunrei-shikokuhenro.jp/map/all"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "source", "seichijunrei", "spots.json")

req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")

m = re.search(r"var spots = (\[.*?\]);", html, re.S)
if not m:
    print("No spots array found.", file=sys.stderr)
    sys.exit(1)

spots = json.loads(m.group(1))
temple = [s for s in spots if s["Spot"]["spot_category_id"] == "3"]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(temple, f, ensure_ascii=False, indent=2)

print(f"spots total: {len(spots)}, temples kept: {len(temple)}")
print(f"saved -> {OUT}")
