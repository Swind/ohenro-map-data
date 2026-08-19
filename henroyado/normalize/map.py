"""Google Maps place-marker coordinates from a resolved URL."""

import re

COORD_RE = re.compile(
    r"!8m2!3d(?P<latitude>-?\d+(?:\.\d+)?)!4d(?P<longitude>-?\d+(?:\.\d+)?)"
)


def parse_coordinates(embed_url):
    """Returns {"latitude", "longitude"} or None."""
    if not embed_url:
        return None
    m = COORD_RE.search(embed_url)
    if not m:
        return None
    return {
        "longitude": float(m.group("longitude")),
        "latitude": float(m.group("latitude")),
    }
