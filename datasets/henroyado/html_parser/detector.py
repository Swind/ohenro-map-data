#!/usr/bin/env python3
"""Accommodation record detection (plan Step 2).

Every accommodation is a <tr class="bl_table_row_frontInfo"> immediately
followed by a <tr class="bl_table_row_detail"> (its hidden detail card).
Rows are grouped into tables; each table is headed either by a temple caption
(<caption class="bl_heading js_temple_N">) or a route-section heading
(<tr class="bl_heading">, e.g. "#10-11合流後ルート").

This stage only answers: which elements are accommodation records, and can they
be identified reliably? No field normalization here.
"""

import json
import re

from bs4 import BeautifulSoup

TEMPLE_NUM_RE = re.compile(r"js_temple_(\d+)")


def _clean(text):
    return " ".join(text.split())


def _table_heading(table):
    """Return (kind, text) for a table's heading: ('temple', {number, name}) or ('route', text) or None."""
    cap = table.find("caption")
    if cap is not None:
        m = TEMPLE_NUM_RE.search(" ".join(cap.get("class") or []))
        if m:
            text = _clean(cap.get_text(" ", strip=True))
            return "temple", {"number": int(m.group(1)), "text": text}
    h = table.select_one("tr.bl_heading")
    if h is not None:
        return "route", _clean(h.get_text(" ", strip=True))
    return None, None


def _front_name(row):
    td = row.select_one("td span") or row.find("td")
    return _clean(td.get_text(" ", strip=True)) if td is not None else ""


def _detail_name(detail):
    h3 = detail.select_one("h3")
    return _clean(h3.get_text(" ", strip=True)) if h3 is not None else None


def detect_records(html):
    """Detect every accommodation record in the page.

    Returns (records, stats):
      records: list of
        {"name", "raw_html", "prefecture", "table_heading",
         "temple": int|None, "has_detail": bool}
      stats: dict of counts / issues.
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []
    issues = []

    for group in soup.select("div.js_prefGroup"):
        pref = group.get("data-pref")
        for table in group.select("table.bl_table"):
            kind, heading = _table_heading(table)
            temple = heading["number"] if kind == "temple" else None
            for row in table.select("tr.bl_table_row_frontInfo"):
                detail = row.find_next_sibling("tr")
                has_detail = detail is not None and "bl_table_row_detail" in (detail.get("class") or [])
                detail_name = _detail_name(detail) if has_detail and detail is not None else None
                name = detail_name or _front_name(row)
                if not name:
                    issues.append({"issue": "MISSING_NAME", "prefecture": pref, "temple": temple})
                records.append({
                    "name": name,
                    "raw_html": str(row),
                    "prefecture": pref,
                    "table_heading": heading if kind == "route" else (heading["text"] if kind else None),
                    "table_kind": kind,
                    "temple": temple,
                    "has_detail": bool(has_detail and detail_name),
                })

    stats = _summarize(records, issues)
    return records, stats


def _summarize(records, issues):
    names = [r["name"] for r in records]
    dupes = {}
    for n in sorted(set(n for n in names if names.count(n) > 1)):
        dupes[n] = names.count(n)
    by_pref = {}
    by_kind = {"temple": 0, "route": 0}
    for r in records:
        by_pref[r["prefecture"]] = by_pref.get(r["prefecture"], 0) + 1
        by_kind[r["table_kind"]] = by_kind.get(r["table_kind"], 0) + 1
    return {
        "records": len(records),
        "records_with_detail": sum(1 for r in records if r["has_detail"]),
        "records_without_detail": sum(1 for r in records if not r["has_detail"]),
        "distinct_names": len(set(names)),
        "duplicate_listings": dupes,
        "by_prefecture": by_pref,
        "by_table_kind": by_kind,
        "issues": issues,
    }
