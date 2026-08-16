"""Room parsing (plan §9).

Types are extracted by known type words. room_count is the number of
``(\\d+)部屋/室`` occurrences; when a text lists per-type counts (e.g.
"ﾄﾞﾐﾄﾘｰ2人 1部屋. ﾄﾞﾐﾄﾘｰ4人 2部屋. 個室 2部屋"), the counts are summed
to a total (1+2+2=5). People counts (相部屋 16人) do not count as rooms.
"""

import re

from henroyado.normalize.text import normalize_digits

ROOM_TYPE_RE = re.compile(r"(個室|相部屋|ドミトリー|ﾄﾞﾐﾄﾘｰ|和洋室|洋室|和室|キャビン|コテージ|貸し切り|別棟)")
ROOM_COUNT_RE = re.compile(r"(\d+)\s*(?:部屋|室)")
ROOM_TYPE_KANA = {"ﾄﾞﾐﾄﾘｰ": "ドミトリー"}


def parse_room(text):
    """Returns (types, room_count)."""
    if not text:
        return [], None
    t = normalize_digits(text)
    types = []
    for m in ROOM_TYPE_RE.finditer(t):
        word = ROOM_TYPE_KANA.get(m.group(1), m.group(1))
        if word not in types:
            types.append(word)
    counts = [int(m.group(1)) for m in ROOM_COUNT_RE.finditer(t)]
    count = sum(counts) if counts else None
    return types, count
