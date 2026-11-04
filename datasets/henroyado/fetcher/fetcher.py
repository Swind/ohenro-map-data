#!/usr/bin/env python3
"""Henroyado fetcher: download the full Shikoku inn list and save raw HTML.

Plan §35 Step 1: implement only URL -> HTML file. No parsing.

The henroyado.com server ignores the `pref` query parameter and returns the
complete Shikoku dataset (all 88 temples) on every prefecture page. We fetch
the base URL once and keep a single immutable HTML snapshot.
"""

import os
import urllib.request

BASE_URL = "https://henroyado.com/inns"
DEFAULT_RAW_FILENAME = "henroyado.html"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) ohenro-map-data/henroyado-fetcher"

DEFAULT_TIMEOUT = 60


def fetch_bytes(url=BASE_URL, timeout=DEFAULT_TIMEOUT):
    """Download a URL and return the raw bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        if status != 200:
            raise RuntimeError("GET %s -> HTTP %s" % (url, status))
        return resp.read()


def save(output_path, url=BASE_URL, timeout=DEFAULT_TIMEOUT):
    """Download the page and write it to output_path. Returns output_path."""
    html = fetch_bytes(url, timeout=timeout)
    out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(html)
    return out


def fetch(output_path=DEFAULT_RAW_FILENAME, timeout=DEFAULT_TIMEOUT):
    """Download the full dataset and save it to output_path. Returns the path."""
    return save(output_path, timeout=timeout)
