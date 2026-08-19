"""Crawl report generation (plan §29): JSON + Markdown.

Aggregates discovery counts, download completeness, and any failures, so both
an AI agent and a human can confirm the archive state at a glance.
"""

from __future__ import annotations

import json
import logging
import os

from shikoku_nature_trail import config
from shikoku_nature_trail.storage import atomic_write_json, local_now
from shikoku_nature_trail.verify import verify

logger = logging.getLogger(__name__)


def _load_courses(data_dir: str):
    schema_path = config.data_layout(data_dir)["schema"]
    if not os.path.exists(schema_path):
        return []
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f).get("courses", [])


def generate_report(data_dir: str):
    """Write reports/shikoku-nature-trail-crawl-report.{json,md}."""
    courses = _load_courses(data_dir)
    v = verify(data_dir)

    per_pref = {}
    for c in courses:
        pref = c.get("prefecture")
        per_pref[pref] = per_pref.get(pref, 0) + 1

    # collect failures from verify + crawl state
    failures = list(v["errors"])

    report = {
        "schema_version": config.SCHEMA_VERSION,
        "generated_at": local_now(),
        "source": "shikoku-nature-trail.com",
        "data_dir": data_dir,
        "course_count": len(courses),
        "prefectures": per_pref,
        "detail_html_ok": sum(
            1 for c in courses
            if os.path.exists(os.path.join(config.course_dir(data_dir, c["source_post_id"]), "page.html"))
        ),
        "courses_with_map": v["courses_with_map"],
        "kml_ok": v["kml_ok"],
        "images_downloaded": v["images_downloaded"],
        "images_pending": v["images_pending"],
        "verify_ok": v["ok"],
        "verify_errors": failures,
        "verify_warnings": v["warnings"],
    }

    json_path, md_path = config.report_paths()
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    atomic_write_json(json_path, report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_markdown(report))
    logger.info("wrote %s and %s", json_path, md_path)
    return report


def _render_markdown(r: dict) -> str:
    lines = [
        "# Crawl Report",
        "",
        "Source: %s" % r["source"],
        "Generated: %s" % r["generated_at"],
        "",
        "## Summary",
        "",
        "- Courses discovered: %d" % r["course_count"],
    ]
    for pref, count in sorted(r["prefectures"].items()):
        lines.append("  - %s: %d" % (pref.capitalize(), count))
    lines += [
        "",
        "## Download status",
        "",
        "- Detail HTML: %d / %d" % (r["detail_html_ok"], r["course_count"]),
        "- Courses with Google My Maps: %d" % r["courses_with_map"],
        "- KML downloaded: %d / %d" % (r["kml_ok"], r["courses_with_map"]),
        "- Images downloaded: %d" % r["images_downloaded"],
        "- Images pending: %d" % r["images_pending"],
        "",
        "## Verify",
        "",
        "- Result: %s" % ("OK" if r["verify_ok"] else "FAILED"),
    ]
    if r["verify_errors"]:
        lines += ["", "### Failures", ""]
        lines += ["- %s" % e for e in r["verify_errors"]]
    if r["verify_warnings"]:
        lines += ["", "### Warnings", ""]
        lines += ["- %s" % e for e in r["verify_warnings"]]
    lines.append("")
    return "\n".join(lines)