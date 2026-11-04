"""Public crawl/archive primitives for CLI integration."""

from .archive import (
    crawl_details,
    crawl_index,
    validate_detail_html,
    validate_index_html,
)
from .http import HttpClient

__all__ = [
    "HttpClient",
    "crawl_details",
    "crawl_index",
    "validate_detail_html",
    "validate_index_html",
]
