#!/usr/bin/env python3
"""Fetch the full four-prefecture listing without replacing valid HTML on failure."""

import os
import urllib.request
import tempfile

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
    """Download and validate the full page before atomically replacing a legacy file."""
    from datasets.henroyado.pipeline import validate_html

    html = fetch_bytes(url, timeout=timeout)
    validate_html(html)
    out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(out), delete=False) as stream:
            temporary = stream.name
            stream.write(html)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, out)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return out


def fetch(output_path=DEFAULT_RAW_FILENAME, timeout=DEFAULT_TIMEOUT):
    """Download the full dataset and save it to output_path. Returns the path."""
    return save(output_path, timeout=timeout)
