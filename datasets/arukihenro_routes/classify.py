"""POI point classification for the とある歩き遍路の道しるべ Google My Maps points."""

from __future__ import annotations

import re

# Categories are evaluated in order; the first matching pattern wins.
# Ordering notes:
#   - waymarker before lodging/onsen (e.g. 旅人の宿道しるべ).
#   - viewpoint before temple_related (e.g. 種間寺遠望).
#   - elevation_mileage / route_feature before sightseeing (e.g. 国道距離表示).
_CATEGORIES: list[tuple[str, list[str]]] = [
    ("route_endpoint", [r"^(日本,|Unnamed Road)"]),
    ("waymarker", [r"道しるべ", r"石碑", r"しるべ石", r"真念"]),
    ("lodging", [
        r"民宿", r"旅館", r"ホテル", r"ゲストハウス", r"ユースホステル", r"ペンション",
        r"へんろ宿", r"休暇村", r"結願の宿", r"ビジネス", r"ロッジ", r"荘", r"御宿",
        r"お宿", r"旅籠屋", r"亭", r"家", r"館", r"ハイツ", r"宿",
    ]),
    ("onsen", [r"温泉", r"の湯", r"湯ノ浦", r"いやしの湯"]),
    ("food_shop", [
        r"うどん", r"旨いもの", r"おにぎり", r"製麺", r"パン", r"cafe", r"カフェ",
        r"たこ焼き", r"ところてん", r"お好み焼き", r"菓子", r"大福", r"食堂", r"喫茶",
        r"雑貨屋", r"茶店", r"売店", r"本舗", r"ｃａｆｅ",
    ]),
    ("rest_area", [r"道の駅", r"休憩所", r"東屋", r"ふれあいの里", r"サロン"]),
    ("shrine", [r"神社", r"八幡", r"神宮", r"大神", r"権現"]),
    ("viewpoint", [r"遠望", r"望む", r"望み", r"山並み", r"景色", r"眺望", r"夕日"]),
    ("temple_related", [
        r"札所", r"霊山寺", r"寺", r"院", r"坊", r"堂", r"禅定", r"嶽", r"大師",
        r"本坊", r"五百羅漢", r"仁王門", r"地蔵", r"納経所", r"山門", r"本堂",
    ]),
    ("elevation_mileage", [r"標高", r"丁", r"距離表示"]),
    ("route_feature", [
        r"分岐", r"峠", r"起点", r"トンネル", r"スタート", r"コース", r"ルート", r"遍路",
        r"へんろ道", r"参道", r"渡し", r"橋", r"潜水橋", r"道", r"登り", r"ル－ト",
    ]),
    ("sightseeing", [
        r"城", r"公園", r"灯台", r"海岸", r"岬", r"街並み", r"遺跡", r"史跡", r"名水",
        r"石塔", r"像", r"ビーチ", r"洞", r"ジオ", r"碑", r"絶景", r"岩", r"浜", r"山",
    ]),
]

_CATEGORY_RE = [(name, re.compile("|".join(patterns))) for name, patterns in _CATEGORIES]

POI_CATEGORIES = [name for name, _ in _CATEGORIES]
OTHER_CATEGORY = "other"


def classify_point(name: str) -> str:
    """Return the unified POI category for a point Placemark name.

    Empty names classify as ``no_name``; anything not matching a known
    category falls back to ``other``. Classification is conservative: no
    geocoding, no inference beyond the name itself.
    """
    if not name:
        return "no_name"
    for category, pattern in _CATEGORY_RE:
        if pattern.search(name):
            return category
    return OTHER_CATEGORY


def line_source(name: str) -> str:
    """Whether a LineString is a Google My Maps directions route or manually drawn."""
    return "google_directions" if re.search(r"^(日本,|Unnamed Road)", name) else "manual"