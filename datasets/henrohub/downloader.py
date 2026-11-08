"""Acquire only the public planner release, never authenticated POIs."""

import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urljoin, urlparse

import requests

from datasets._pipeline import atomic_json, digest, read_json
from .validation import validate_routes

CHANNEL = "https://assets.henro.app/routes/channels/beta.json"


def public_url(base, path):
    if not isinstance(path, str) or not path or ".." in path.split("/"):
        raise ValueError("Invalid release asset path")
    url = urljoin(base, path)
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "assets.henro.app" or
            not parsed.path.startswith("/routes/") or parsed.query or parsed.fragment):
        raise ValueError("Release asset must use the public Henro Hub routes origin")
    return url


def download(url, destination):
    with requests.get(url, headers={"Cache-Control": "no-cache", "User-Agent": "ohenro-map-data/henrohub (personal-use)"},
                      stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        with destination.open("wb") as stream:
            for block in response.iter_content(1024 * 1024):
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())


def release_contract(channel, manifest, manifest_url):
    release = channel["active_release_id"]
    if (channel.get("schema") != "henro-route-release-channel" or channel.get("channel") != "beta" or
            not isinstance(release, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", release) or
            manifest.get("schema") != "henro-route-production-release" or
            manifest.get("immutable_release_id") != release or not manifest.get("planner", {}).get("available")):
        raise ValueError("Invalid channel/release identity or unavailable planner")
    if urlparse(manifest_url).path != f"/routes/releases/{release}/manifest.json":
        raise ValueError("Manifest does not belong to selected immutable release")
    planner = manifest["planner"]
    path = manifest["files"]["planner_geometry"]
    if planner.get("geometry") != path:
        raise ValueError("Conflicting planner paths in release manifest")
    asset = manifest.get("deployed_files", {}).get(path, {"path": path})
    if asset.get("path") != path:
        raise ValueError("Conflicting deployed planner path")
    url = public_url(manifest_url, path)
    if not url.startswith(manifest_url.rsplit("/", 1)[0] + "/"):
        raise ValueError("Planner path escaped immutable release")
    for key, value in asset.items():
        if key == "sha256" and (not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)):
            raise ValueError("Invalid declared planner SHA-256")
        if key == "bytes" and (type(value) is not int or value <= 0):
            raise ValueError("Invalid declared planner size")
    count = planner.get("feature_count")
    if type(count) is not int or count <= 0 or planner.get("coordinate_dimensions") != 3:
        raise ValueError("Invalid planner count/dimensions")
    return url, asset, count


def verify_snapshot(snapshot):
    snapshot = Path(snapshot)
    metadata = read_json(snapshot / "metadata.json")
    files = metadata["files"]
    expected = {"planner.geojson", "channel.json", "manifest.json"} if metadata["kind"] == "public-release" else {"planner.geojson"}
    if metadata["kind"] not in ("public-release", "local-import") or set(files) != expected:
        raise ValueError("Unexpected source snapshot files")
    for name, identity in files.items():
        path = snapshot / name
        if path.stat().st_size != identity["size"] or digest(path) != identity["sha256"]:
            raise ValueError(f"Corrupt immutable source snapshot: {name}")
    count = None
    if metadata["kind"] == "public-release":
        channel, manifest = read_json(snapshot / "channel.json"), read_json(snapshot / "manifest.json")
        manifest_url = public_url(CHANNEL, channel["manifest"])
        url, asset, count = release_contract(channel, manifest, manifest_url)
        if metadata["source_url"] != url or metadata["release_id"] != channel["active_release_id"]:
            raise ValueError("Snapshot provenance differs from release")
        if (("bytes" in asset and files["planner.geojson"]["size"] != asset["bytes"]) or
                ("sha256" in asset and files["planner.geojson"]["sha256"] != asset["sha256"])):
            raise ValueError("Planner hash/size differs from release manifest")
    summary = validate_routes(read_json(snapshot / "planner.geojson"), planner=True, expected_count=count)
    if metadata["summary"] != summary:
        raise ValueError("Source snapshot accounting mismatch")
    return metadata


def resolve(raw):
    selector = read_json(Path(raw) / "current.json")
    identity = selector["snapshot"]
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("Invalid current snapshot selector")
    snapshot = Path(raw) / "snapshots" / identity
    metadata = verify_snapshot(snapshot)
    if digest(snapshot / "metadata.json") != selector["metadata_sha256"]:
        raise ValueError("Current snapshot metadata changed")
    return snapshot


def fetch(raw, source=None):
    raw = Path(raw)
    snapshots = raw / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw) as directory:
        staged = Path(directory)
        if source is None:
            download(CHANNEL, staged / "channel.json")
            channel = read_json(staged / "channel.json")
            manifest_url = public_url(CHANNEL, channel["manifest"])
            download(manifest_url, staged / "manifest.json")
            manifest = read_json(staged / "manifest.json")
            url, asset, count = release_contract(channel, manifest, manifest_url)
            download(url, staged / "planner.geojson")
            names = ("channel.json", "manifest.json", "planner.geojson")
            metadata = {"kind": "public-release", "release_id": channel["active_release_id"],
                        "channel_url": CHANNEL, "manifest_url": manifest_url, "source_url": url}
        else:
            source = Path(source).resolve()
            shutil.copyfile(source, staged / "planner.geojson")
            names = ("planner.geojson",)
            metadata = {"kind": "local-import", "source_url": source.as_uri()}
            count = None
        metadata.update({"usage": "personal-use", "attribution": "Henro Hub / https://henro.app",
                         "files": {name: {"sha256": digest(staged / name), "size": (staged / name).stat().st_size} for name in names},
                         "summary": validate_routes(read_json(staged / "planner.geojson"), planner=True, expected_count=count)})
        atomic_json(staged / "metadata.json", metadata)
        verify_snapshot(staged)
        identity = digest(staged / "metadata.json")
        snapshot = snapshots / identity
        if snapshot.exists():
            verify_snapshot(snapshot)
            if digest(snapshot / "metadata.json") != identity:
                raise ValueError("Immutable snapshot metadata mismatch")
        else:
            os.replace(staged, snapshot)
        atomic_json(raw / "current.json", {"snapshot": identity, "metadata_sha256": identity})
    print(f"Verified source: {snapshot}", flush=True)
    return snapshot
