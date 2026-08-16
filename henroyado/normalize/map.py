"""Google Maps coordinates from embed URL (plan §16).

Pattern: !2d<longitude>!3d<latitude>
"""

import re

COORD_RE = re.compile(r"!2d(-?\d+(?:\.\d+)?)!3d(-?\d+(?:\.\d+)?)")


def parse_coordinates(embed_url):
    """Returns {"latitude", "longitude"} or None."""
    if not embed_url:
        return None
    m = COORD_RE.search(embed_url)
    if not m:
        return None
    return {
        "longitude": float(m.group(1)),
        "latitude": float(m.group(2)),
    }
