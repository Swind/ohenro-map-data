#!/usr/bin/env python3
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, "source", "seichijunrei", "spots.json")
OUT = os.path.join(ROOT, "output", "temples.json")

with open(RAW, encoding="utf-8") as f:
    spots = json.load(f)


def clean(value):
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def has_lodging(syukubou):
    if not syukubou:
        return False
    return syukubou.startswith("あり")


temples = []
for spot in spots:
    s = spot["Spot"]
    sc = spot["SpotContent"]
    number = int(s["number"])
    temples.append({
        "id": f"temple-{number:03d}",
        "number": number,
        "name": {
            "ja": clean(sc["short_name_ja"]),
            "en": clean(sc["short_name_en"]),
            "kana": clean(sc["short_name_kana_ja"]),
        },
        "full_name": {
            "ja": clean(sc["long_name_ja"]),
            "en": clean(sc["long_name_en"]),
            "kana": clean(sc["long_name_kana_ja"]),
        },
        "location": {
            "latitude": float(s["latitude"]),
            "longitude": float(s["longitude"]),
            "source": "seichijunrei",
        },
        "address": {
            "postal_code": clean(s["post_code"]),
            "prefecture": clean(s["pref"]),
            "ja": clean(s["address_ja"]),
            "en": clean(s["address_en"]),
        },
        "phone": clean(sc["tel_ja"]),
        "temple": {
            "principal_deity": {
                "ja": clean(sc["honzon_ja"]),
                "en": clean(sc["honzon_en"]),
            },
            "sect": {
                "ja": clean(sc["syuha_ja"]),
                "en": clean(sc["syuha_en"]),
            },
            "founder": {
                "ja": clean(sc["kaiki_ja"]),
                "en": clean(sc["kaiki_en"]),
            },
            "founded": {
                "ja": clean(sc["souken_ja"]),
                "en": clean(sc["souken_en"]),
            },
            "has_lodging": has_lodging(clean(sc["syukubou_ja"])),
        },
        "history": {
            "ja": clean(sc["rekishiyurai_ja"]),
            "en": clean(sc["rekishiyurai_en"]),
        },
        "image": {
            "eyecatch": clean(s["eyecatch"]),
        },
        "sources": {
            "seichijunrei": {
                "spot_id": s["id"],
                "content_id": sc["id"],
                "modified_at": clean(s["modified"]),
            }
        },
    })

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(temples, f, ensure_ascii=False, indent=2)

print(f"normalized {len(temples)} temples -> {OUT}")
