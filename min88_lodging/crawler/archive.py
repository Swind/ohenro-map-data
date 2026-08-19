"""Crawl the min88 list and archive its Japanese lodging detail pages."""

from __future__ import annotations

import datetime
import json
import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from min88_lodging.index_parser import (
    LIST_URL,
    canonical_detail_url,
    extract_source_id,
    parse_index_document,
)

from .http import HttpClient
from .storage import atomic_write_bytes, atomic_write_json, sha256_bytes


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _header(headers: dict, name: str):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def _http_result(url: str, local_path: str, status, headers: dict, body: bytes,
                 archive_status: str, error: str | None = None,
                 source_id: str | None = None) -> dict:
    result = {
        "url": url,
        "local_path": local_path,
        "status": archive_status,
        "http_status": status,
        "retrieved_at": utc_now() if archive_status != "skipped" else None,
        "sha256": sha256_bytes(body) if body and archive_status != "failed" else None,
        "etag": _header(headers, "ETag"),
        "last_modified": _header(headers, "Last-Modified"),
        "error": error,
    }
    if source_id is not None:
        result["source_id"] = source_id
    return result


def validate_index_html(body: bytes, list_url: str = LIST_URL) -> dict:
    if not body:
        raise ValueError("empty index response")
    html = body.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical is None or urljoin(list_url, canonical["href"]).rstrip("/") != list_url.rstrip("/"):
        raise ValueError("index canonical URL mismatch")
    return parse_index_document(html, list_url)


def validate_detail_html(body: bytes, source_id: str) -> None:
    if not body:
        raise ValueError("empty detail response")
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    canonical = soup.select_one('link[rel="canonical"][href]')
    canonical_url = urljoin(canonical_detail_url(source_id), canonical["href"]) if canonical else ""
    if extract_source_id(canonical_url) != source_id:
        raise ValueError("detail canonical post ID mismatch")
    title = soup.select_one("h1#post_title")
    if title is None or not title.get_text(" ", strip=True):
        raise ValueError("missing h1#post_title")


def _validate_index_record(record: dict) -> tuple[str, str]:
    source_id = record.get("source_id")
    url = record.get("source_url")
    if not isinstance(source_id, str) or re.fullmatch(r"[0-9]+", source_id) is None:
        raise ValueError("source_id must contain only decimal digits")
    if url != canonical_detail_url(source_id):
        raise ValueError("source_url is not the canonical Japanese detail URL")
    return source_id, url


def crawl_index(data_dir: str, force: bool = False, client=None,
                list_url: str = LIST_URL, timeout: float = 30, delay: float = 0.3) -> dict:
    """Archive the list page and write deterministic ``index.json``."""
    page_path = os.path.join(data_dir, "index", "page.html")
    relative_page = os.path.relpath(page_path, data_dir)
    body = None
    if os.path.exists(page_path) and not force:
        with open(page_path, "rb") as source:
            candidate = source.read()
        try:
            parsed = validate_index_html(candidate, list_url)
            body = candidate
            status, headers, archive_status = 200, {}, "skipped"
        except ValueError:
            pass
    if body is None:
        client = client or HttpClient(timeout=timeout, delay=delay)
        status, headers, candidate = client.get_bytes(list_url)
        if status != 200:
            return {"record_count": 0, "archive": _http_result(
                list_url, relative_page, status, headers, candidate, "failed", f"HTTP {status}"
            )}
        try:
            parsed = validate_index_html(candidate, list_url)
        except ValueError as error:
            return {"record_count": 0, "archive": _http_result(
                list_url, relative_page, status, headers, candidate, "failed", str(error)
            )}
        atomic_write_bytes(page_path, candidate)
        body, archive_status = candidate, "fetched"

    occurrence_counts = {}
    for occurrence in parsed["occurrences"]:
        source_id = occurrence["source_id"]
        occurrence_counts[source_id] = occurrence_counts.get(source_id, 0) + 1
    index = {
        "schema_version": 1,
        "list_url": list_url,
        "record_count": len(parsed["records"]),
        "temple_header_count": parsed["temple_header_count"],
        "prefectures": parsed["prefectures_found"],
        "occurrence_count": len(parsed["occurrences"]),
        "occurrences": parsed["occurrences"],
        "duplicate_occurrences": [
            {"source_id": source_id, "count": count}
            for source_id, count in occurrence_counts.items() if count > 1
        ],
        "records": parsed["records"],
    }
    atomic_write_json(os.path.join(data_dir, "index.json"), index)
    return {
        "record_count": len(parsed["records"]),
        "occurrence_count": len(parsed["occurrences"]),
        "archive": _http_result(list_url, relative_page, status, headers, body, archive_status),
        "index": index,
    }


def crawl_details(data_dir: str, force: bool = False, client=None,
                  timeout: float = 30, delay: float = 0.3) -> dict:
    """Archive each detail listed in ``index.json`` and continue on errors."""
    index_path = os.path.join(data_dir, "index.json")
    if not os.path.exists(index_path):
        raise FileNotFoundError("index.json missing; run crawl-index first")
    with open(index_path, encoding="utf-8") as source:
        records = json.load(source)["records"]
    client = client or HttpClient(timeout=timeout, delay=delay)
    results = []

    for record in records:
        try:
            source_id, url = _validate_index_record(record)
        except (AttributeError, ValueError) as error:
            results.append(_http_result(
                record.get("source_url", "") if isinstance(record, dict) else "",
                "", None, {}, b"", "failed", str(error),
                record.get("source_id") if isinstance(record, dict) else None,
            ))
            continue
        page_path = os.path.join(data_dir, "records", source_id, "page.html")
        local_path = os.path.relpath(page_path, data_dir)
        if os.path.exists(page_path) and not force:
            with open(page_path, "rb") as source:
                body = source.read()
            try:
                validate_detail_html(body, source_id)
                results.append(_http_result(url, local_path, 200, {}, body, "skipped", source_id=source_id))
                continue
            except ValueError:
                pass

        try:
            status, headers, body = client.get_bytes(url)
        except Exception as error:
            results.append(_http_result(url, local_path, None, {}, b"", "failed", str(error), source_id))
            continue
        if status != 200:
            results.append(_http_result(url, local_path, status, headers, body, "failed", f"HTTP {status}", source_id))
            continue
        try:
            validate_detail_html(body, source_id)
        except ValueError as error:
            results.append(_http_result(url, local_path, status, headers, body, "failed", str(error), source_id))
            continue
        atomic_write_bytes(page_path, body)
        results.append(_http_result(url, local_path, status, headers, body, "fetched", source_id=source_id))

    counts = {status: sum(item["status"] == status for item in results)
              for status in ("fetched", "skipped", "failed")}
    return {"total": len(records), **counts, "records": results}
