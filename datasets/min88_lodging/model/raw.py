"""Extraction-level model for a min88 lodging detail page."""

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class RawMin88Lodging:
    source_context: dict
    canonical_source_id: Optional[str]
    canonical_url: Optional[str]
    name: Optional[str]
    modified_text: Optional[str]
    categories: List[str] = field(default_factory=list)
    lodging_types: List[str] = field(default_factory=list)
    route_lines: List[dict] = field(default_factory=list)
    basic_data: dict = field(default_factory=dict)
    basic_data_ignored_lines: List[str] = field(default_factory=list)
    extra_fields: List[dict] = field(default_factory=list)
    supplemental_facilities: List[str] = field(default_factory=list)
    editorial_title: Optional[str] = None
    editorial_description: Optional[str] = None
    featured_image_url: Optional[str] = None
    featured_image_display_url: Optional[str] = None
    gallery_image_urls: List[str] = field(default_factory=list)
    google_maps_place_embed_url: Optional[str] = None
    google_street_view_embed_url: Optional[str] = None
    google_maps_directions_url: Optional[str] = None
    alternate_languages: List[dict] = field(default_factory=list)
    content_sections: List[dict] = field(default_factory=list)
    unknown_sections: List[dict] = field(default_factory=list)
    parser_warnings: List[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
