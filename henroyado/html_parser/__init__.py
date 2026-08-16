"""Henroyado HTML parser (Phase 1: Step 2 record detection, Step 3 RawInn)."""

from henroyado.html_parser.detector import detect_records
from henroyado.html_parser.inn import extract_all, extract_inn

__all__ = ["detect_records", "extract_inn", "extract_all"]
