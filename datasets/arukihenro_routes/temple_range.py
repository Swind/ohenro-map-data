"""Extract 札所 temple-number ranges from route/map names.

The source names are not machine-friendly: the separator between the two
temple numbers varies (～, －, ―, ー, ‐), some ranges combine two temples
(e.g. 68・69), the closing loop runs 88→01, and some names carry only one
temple number (e.g. 23番～旧へんろ道). We extract the ordered list of
distinct main 札所 numbers, ignoring 別格 numbers.
"""

from __future__ import annotations

import re

_NUM_RE = re.compile(r"(\d+)番")
_BETSU_RE = re.compile(r"別格\d+番")
_COMBINED_RE = re.compile(r"(\d+)・(\d+)番")


def _expand_combined(name: str) -> str:
    """Turn ``68・69番`` into ``68番 69番`` so both numbers are found."""
    return _COMBINED_RE.sub(lambda m: "%s番 %s番" % (m.group(1), m.group(2)), name)


def parse_temple_range(name: str):
    """Return ``(from_temple, to_temple, temple_range)``.

    ``temple_range`` is the ordered list of distinct main 札所 numbers
    present in the name (別格 numbers ignored); ``from_temple`` /
    ``to_temple`` are its first/last elements, or ``None`` when empty.
    The 88→01 closing loop yields ``[88, 1]``; a name such as
    ``67番－68・69番所`` yields ``[67, 68, 69]``.
    """
    cleaned = _BETSU_RE.sub("", name or "")
    cleaned = _expand_combined(cleaned)
    numbers = []
    for match in _NUM_RE.finditer(cleaned):
        number = int(match.group(1))
        if 1 <= number <= 88 and (not numbers or numbers[-1] != number):
            numbers.append(number)
    if not numbers:
        return None, None, []
    return numbers[0], numbers[-1], numbers