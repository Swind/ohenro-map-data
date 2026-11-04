"""RawInn: raw intermediate model (plan §19, Step 3).

Extraction-level values, close to the website representation. No semantic
normalization here; normalization happens in the Normalizer (Step 4).
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class RawFacility:
    """One facility icon entry (plan §12/13). available=False when cross.png is present."""
    icon: Optional[str]
    remark: Optional[str]
    available: bool


@dataclass
class RawInn:
    source_context: dict
    name: str
    description: Optional[str]
    route: Optional[str]
    notice: Optional[str]
    room: Optional[str]
    meal: Optional[str]
    check_in: Optional[str]
    check_out: Optional[str]
    facilities: List[RawFacility] = field(default_factory=list)
    pricing_items: List[str] = field(default_factory=list)
    payment: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    google_maps_search_url: Optional[str] = None
    google_maps_embed_url: Optional[str] = None
    images: List[str] = field(default_factory=list)
    extra_details: List[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
