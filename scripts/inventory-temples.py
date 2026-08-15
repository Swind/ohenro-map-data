#!/usr/bin/env python3
"""v1.1 inventory: how the 88 Shikoku Henro temples are tagged in the OSM PBF.

Reads the local immutable PBF directly with pyosmium (no online queries).
Reports:
  1. all amenity=place_of_worship objects (geometry / religion / tag keys)
  2. the 88 numbered temples via the 第<N>番札所 name prefix
  3. coverage, duplicates, missing numbers, and format inconsistencies
  4. noise that must be excluded (mini replicas, 別格, route relations, etc.)
  5. temple-name candidates cross-validated against henro route relations

Usage:
  python3 scripts/inventory-temples.py <shikoku-latest.osm.pbf> [--report PATH]
"""
import argparse
import re
import sys
from collections import Counter, defaultdict

import osmium

PBF_NUM = re.compile(r"^第(\d{1,2})番札所")
FULL_WIDTH = re.compile(r"[０-９]")
SUBSTRUCTURE_SUFFIX = ("大師堂", "観音堂", "善女庵", "法南寺")
NOISE_MARKERS = ("爺神山ミニ", "別格")
ROUTE_REL_NAME = re.compile(r"四国遍路 (\d{1,2})番札所(.+?)~(\d{1,2})番札所(.+)$")


class InventoryHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.pow = []            # (otype, oid, tags) all place_of_worship
        self.candidates = []     # (otype, oid, number, name, tags) strict 第N番札所
        self.relations = []      # (rid, tags) all relations

    def _check(self, o, otype):
        t = dict(o.tags)
        if t.get("amenity") == "place_of_worship":
            self.pow.append((otype, o.id, t))
            name = t.get("name", "")
            m = PBF_NUM.match(name)
            if m:
                self.candidates.append((otype, o.id, int(m.group(1)), name, t))
        if otype == "relation":
            self.relations.append((o.id, t))

    def node(self, n):
        self._check(n, "node")

    def way(self, w):
        self._check(w, "way")

    def relation(self, r):
        self._check(r, "relation")


def section(title):
    print(f"\n=== {title} ===")


def report_pow(h):
    section(f"amenity=place_of_worship total: {len(h.pow)}")
    geo = Counter(o for o, _, _ in h.pow)
    for g in ("node", "way", "relation"):
        print(f"  {g}: {geo[g]}")

    religion = Counter(t.get("religion", "(none)") for _, _, t in h.pow)
    print("\nreligion values:")
    for r, c in religion.most_common(15):
        print(f"  {r!r}: {c}")

    all_keys = Counter(k for _, _, t in h.pow for k in t)
    print("\ntop tag keys on place_of_worship:")
    for k, c in all_keys.most_common(25):
        print(f"  {k}: {c}")


def report_candidates(h):
    by_num = defaultdict(list)
    for otype, oid, num, name, tags in h.candidates:
        by_num[num].append((otype, oid, name, tags))

    section(f"strict candidates (^第N番札所 prefix): {len(h.candidates)}")
    missing = [n for n in range(1, 89) if n not in by_num]
    print(f"missing in 1-88: {missing}")

    print("\nduplicates (number with >1 candidate):")
    for n in sorted(by_num):
        if len(by_num[n]) > 1:
            for otype, oid, name, _ in by_num[n]:
                print(f"  #{n:02d} {otype} {oid}: {name!r}")

    print("\ngeometry distribution:")
    geo = Counter(o for lst in by_num.values() for (o, _, _, _) in lst)
    for g, c in geo.items():
        print(f"  {g}: {c}")

    print("\nformat inconsistencies (full-width digits in 第N番札所):")
    for otype, oid, num, name, _ in h.candidates:
        m = re.match(r"^第([０-９]{1,2})番札所", name)
        if m:
            print(f"  #{num:02d} {otype} {oid}: {name!r}")

    print("\nnoise that matches the number pattern but is NOT a numbered temple:")
    for otype, oid, num, name, _ in h.candidates:
        if any(mk in name for mk in NOISE_MARKERS):
            print(f"  [{', '.join(mk for mk in NOISE_MARKERS if mk in name)}] "
                  f"#{num:02d} {otype} {oid}: {name!r}")
        if name.endswith(SUBSTRUCTURE_SUFFIX):
            print(f"  [sub-structure] #{num:02d} {otype} {oid}: {name!r}")

    return by_num


def report_noise(h):
    # route relations whose name embeds 番札所 (these are relations, not temples)
    section("route relations matching 四国遍路 N番札所X~M番札所Y")
    name_pairs = {}
    for rid, t in h.relations:
        if t.get("type") != "route" or t.get("route") != "hiking":
            continue
        m = ROUTE_REL_NAME.match(t.get("name", ""))
        if m:
            a, b = int(m.group(1)), int(m.group(3))
            name_pairs[(a, b)] = (m.group(2), m.group(4), rid, t.get("name"))
    print(f"  found {len(name_pairs)} segment relations")
    return name_pairs


def cross_check(by_num, name_pairs):
    section("cross-check: temple names in route relations vs numbered candidates")
    canonical = {}
    for n, lst in by_num.items():
        for otype, oid, name, tags in lst:
            if any(mk in name for mk in NOISE_MARKERS):
                continue
            canonical.setdefault(n, []).append((otype, oid, name))

    for (a, b), (name_a, name_b, rid, relname) in sorted(name_pairs.items()):
        status_a = "ok" if a in canonical else "MISSING"
        status_b = "ok" if b in canonical else "MISSING"
        print(f"  {a:02d} {name_a} [{status_a}] ~ {b:02d} {name_b} [{status_b}] "
              f"(relation {rid})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pbf", help="path to shikoku-latest.osm.pbf")
    parser.add_argument("--report", help="also append the full per-number listing to this file")
    args = parser.parse_args()

    h = InventoryHandler()
    h.apply_file(args.pbf, locations=True)

    report_pow(h)
    by_num = report_candidates(h)
    name_pairs = report_noise(h)
    cross_check(by_num, name_pairs)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write("# temples-inventory\n\n")
            f.write("## per-number strict candidates\n\n")
            for n in sorted(by_num):
                for otype, oid, name, tags in by_num[n]:
                    f.write(f"  #{n:02d} {otype} {oid}: {name!r} "
                            f"religion={tags.get('religion')!r} "
                            f"denomination={tags.get('denomination')!r}\n")
        print(f"\n(report written to {args.report})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
