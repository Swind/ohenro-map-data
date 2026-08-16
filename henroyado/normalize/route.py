"""Henro route parsing (plan §14).

Example:
  "こちらは 1番霊山寺 から 2番極楽寺 へのお宿です。"
    -> from_temple {"number": 1, "name": "霊山寺"}
       to_temple   {"number": 2, "name": "極楽寺"}

Future records may contain 番外 / 別格 / non-standard text; those return None.
"""

import re

ROUTE_RE = re.compile(r"(\d+)\s*番\s*(.+?)\s*から\s*(\d+)\s*番\s*(.+?)\s*へのお宿")


def _name(text):
    return " ".join(text.split())


def parse_route(text):
    """Returns (from_temple, to_temple) or (None, None)."""
    if not text:
        return None, None
    m = ROUTE_RE.search(text)
    if not m:
        return None, None
    return (
        {"number": int(m.group(1)), "name": _name(m.group(2))},
        {"number": int(m.group(3)), "name": _name(m.group(4))},
    )
