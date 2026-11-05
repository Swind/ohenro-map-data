"""Filesystem helpers: atomic JSON writes and reads."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import re


def atomic_write_bytes(path: str, data: bytes) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, obj) -> None:
    atomic_write_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def read_json(path: str):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def resolve_archive(data_dir):
    """Accept both legacy flat archives and the full pipeline's current snapshot."""
    root = Path(data_dir)
    if not (root / "current.json").exists():
        return root
    sha = read_json(root / "current.json").get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("Invalid archive snapshot hash")
    archive = root / "snapshots" / sha
    if not archive.is_dir():
        raise ValueError(f"Snapshot missing: {archive}")
    return archive
