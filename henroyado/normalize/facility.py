"""Facility icon mapping (plan §12/13). Icon filenames are more stable than visual order."""

FACILITY_MAP = {
    "wash_g.png": "washing_machine",
    "dry_g.png": "dryer",
    "wifi_g.png": "wifi",
    "wc_g.png": "toilet",
    "bathtub_g.png": "bath",
    "sougei_g.png": "shuttle",
    "parking_g.png": "parking",
    "card_g.png": "card_payment",
}


def facility_type(icon):
    """Map an icon filename to a facility type, or None if unknown."""
    return FACILITY_MAP.get(icon)
