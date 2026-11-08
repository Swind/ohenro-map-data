"""Read OHenro 88 APKPure packages statically; never install or execute app code.

The Henro Helper downloader's bounded protobuf, curl, ZIP and Android XML
readers are package-independent. Its descriptor/identity functions are not,
so those two small policies live here with an explicit package identity.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse
import zipfile

from datasets._pipeline import atomic_json, digest, read_json
from datasets.henro_helper import downloader as apk

PACKAGE = "com.sallyzzz.ohenroapp"
API_URL = "https://api.pureapk.com/m/v3/cms/app_version?hl=en-US&package_name=" + PACKAGE
ASSETS = ("trails_all.geojson", "merged.json")
ASSET_PREFIX = "assets/flutter_assets/assets/data/"
MAX_ASSET = 128 * 1024 * 1024


def parse_versions(body):
    if not body or len(body) > apk.MAX_API:
        raise ValueError("Invalid APKPure API response size")
    page = apk._protobuf(apk._one(apk._protobuf(apk._one(apk._protobuf(body), 1)), 7))
    versions = []
    for raw in page.get(2, []):
        section = apk._protobuf(raw)
        if apk._text(section, 1) != "version_list":
            continue
        app = apk._protobuf(apk._one(apk._protobuf(apk._one(section, 3)), 2))
        if apk._text(app, 4) != PACKAGE:
            continue
        code, name = apk._text(app, 5), apk._text(app, 6)
        asset = apk._protobuf(apk._one(app, 24))
        sha1, kind, url = (apk._text(asset, number) for number in (3, 8, 9))
        size = apk._one(asset, 4, int)
        parsed = urllib.parse.urlsplit(url)
        if (not re.fullmatch(r"[0-9]{1,10}", code) or not name
                or not re.fullmatch(r"[0-9a-fA-F]{40}", sha1)
                or kind not in ("APK", "XAPK") or parsed.scheme != "https"
                or parsed.netloc != "download.pureapk.com"
                or not parsed.path.startswith(f"/b/{kind}/")
                or any(ord(c) < 32 for c in url) or not 0 < size <= apk.MAX_ARCHIVE):
            raise ValueError("Invalid APKPure download descriptor")
        versions.append({"package_name": PACKAGE, "version_code": int(code), "version_name": name,
                         "source_sha1": sha1.lower(), "archive_type": kind,
                         "archive_size": size, "url": url})
    if not versions:
        raise ValueError("APKPure API has no matching OHenro 88 package")
    return sorted(versions, key=lambda row: row["version_code"], reverse=True)


def check_identity(identity, expected=None, require_name=False):
    if (not isinstance(identity, dict) or identity.get("package_name") != PACKAGE
            or not re.fullmatch(r"[0-9]{1,10}", str(identity.get("version_code")))):
        raise ValueError("Invalid OHenro 88 package identity")
    if require_name and (not isinstance(identity.get("version_name"), str) or not identity["version_name"]):
        raise ValueError("Missing OHenro 88 version name")
    if expected is not None:
        if str(identity["version_code"]) != str(expected["version_code"]):
            raise ValueError("Archive version code differs from source metadata")
        name = identity.get("version_name")
        if (require_name or name is not None) and name != expected["version_name"]:
            raise ValueError("Archive version name differs from source metadata")


def validate_geometry(geometry):
    kind, coordinates = geometry["type"], geometry["coordinates"]
    if kind == "Point":
        parts = [[coordinates]]
    elif kind == "LineString":
        parts = [coordinates]
    elif kind == "MultiLineString":
        parts = coordinates
    else:
        raise ValueError("Unsupported OHenro 88 geometry")
    if not parts or any(not part or (kind != "Point" and len(part) < 2) for part in parts):
        raise ValueError("Empty or degenerate OHenro 88 geometry")
    for part in parts:
        for point in part:
            if (len(point) not in (2, 3) or any(isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(v) for v in point)
                    or not (131 < point[0] < 136 and 32 < point[1] < 35)):
                raise ValueError("Invalid OHenro 88 Shikoku coordinate")


def validate_assets(data):
    for name in ASSETS:
        collection = data[name]
        if (collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list)
                or not collection["features"]):
            raise ValueError(f"Invalid source collection: {name}")
        for feature in collection["features"]:
            if (feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict)
                    or not isinstance(feature["properties"].get("name"), str) or not feature["properties"]["name"]):
                raise ValueError(f"Unnamed/invalid source feature: {name}")
            validate_geometry(feature["geometry"])
            if name == "merged.json" and feature["geometry"]["type"] == "Point":
                raise ValueError("Merged walking route must be a line")
    temples = [f["properties"].get("templeNumber") for f in data[ASSETS[0]]["features"]
               if f["geometry"]["type"] == "Point" and f["properties"].get("templeNumber") is not None]
    if any(type(n) is not int for n in temples) or sorted(temples) != list(range(1, 89)):
        raise ValueError("Source must include exactly temples 1–88")
    trail_names = [f["properties"]["name"] for f in data["trails_all.geojson"]["features"]
                   if f["geometry"]["type"] != "Point"]
    for i in range(1, 88):
        name = f"Walking ({i}-{i + 1})"
        if trail_names.count(name) + trail_names.count(name + " skip") < 1:
            raise ValueError(f"Missing trails_all main/skip section {i}")
    names = [f["properties"]["name"] for f in data["merged.json"]["features"]]
    for i in range(1, 89):
        if names.count(f"Walking ({i}-{i + 1 if i < 88 else 1})") != 1:
            raise ValueError(f"Missing/duplicate merged main section {i}")
    return {name: len(data[name]["features"]) for name in ASSETS}


def validate_archive(path, expected=None, output=None):
    found, identity = {}, None

    def inspect(archive):
        nonlocal identity
        apk._check_zip(archive)
        manifest = archive.getinfo("AndroidManifest.xml")
        if manifest.file_size > apk.MAX_MANIFEST:
            raise ValueError("Oversized Android manifest")
        current = apk._android_manifest(archive.read(manifest))
        check_identity(current, identity or expected)
        if identity is None:
            check_identity(current, require_name=True)
            identity = current
        for name in ASSETS:
            member = ASSET_PREFIX + name
            if member not in archive.namelist():
                continue
            if name in found or archive.getinfo(member).file_size > MAX_ASSET:
                raise ValueError("Duplicate or oversized app route asset")
            found[name] = archive.read(member)

    with zipfile.ZipFile(path) as archive:
        if path.suffix.lower() == ".apk":
            inspect(archive)
        elif path.suffix.lower() == ".xapk":
            apk._check_zip(archive)
            if archive.getinfo("manifest.json").file_size > apk.MAX_MANIFEST:
                raise ValueError("Oversized XAPK manifest")
            identity = json.loads(archive.read("manifest.json"))
            check_identity(identity, expected, require_name=True)
            members = [i for i in archive.infolist() if i.filename.endswith(".apk")]
            declared = identity.get("split_apks")
            if declared is not None and (not isinstance(declared, list) or any(not isinstance(i, dict) for i in declared)
                    or sorted(i.get("file", "") for i in declared) != sorted(i.filename for i in members)):
                raise ValueError("XAPK declared APK list differs from contents")
            if not members:
                raise ValueError("XAPK contains no APKs")
            for member in members:
                if not apk._safe_member(member.filename) or member.file_size > apk.MAX_ARCHIVE:
                    raise ValueError("Invalid nested APK")
                with tempfile.TemporaryFile() as temporary:
                    with archive.open(member) as source:
                        shutil.copyfileobj(source, temporary, 1024 * 1024)
                    temporary.seek(0)
                    with zipfile.ZipFile(temporary) as nested:
                        inspect(nested)
        else:
            raise ValueError("Expected a local .apk or .xapk archive")
    if set(found) != set(ASSETS):
        raise ValueError("APK lacks trails_all.geojson and/or merged.json assets")
    validate_assets({name: json.loads(body) for name, body in found.items()})
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        for name, body in found.items():
            (output / name).write_bytes(body)
    return ({"package_name": PACKAGE, "version_code": int(identity["version_code"]),
             "version_name": identity["version_name"]},
            {name: hashlib.sha256(body).hexdigest() for name, body in found.items()})


def validate_snapshot(snapshot, checksum):
    metadata = read_json(snapshot / "metadata.json")
    check_identity(metadata, require_name=True)
    if metadata.get("archive_sha256") != checksum or metadata.get("archive") not in ("archive.apk", "archive.xapk"):
        raise ValueError("Invalid OHenro 88 snapshot metadata")
    archive = snapshot / metadata["archive"]
    if archive.stat().st_size != metadata["archive_size"] or digest(archive) != checksum:
        raise ValueError("Cached app archive hash/size mismatch")
    if apk._sha(archive, "sha1") != metadata["source_sha1"]:
        raise ValueError("Cached app archive SHA1 mismatch")
    _, assets = validate_archive(archive, metadata)
    if assets != metadata["assets"] or any(digest(snapshot / "data" / name) != sha for name, sha in assets.items()):
        raise ValueError("Cached extracted app asset checksum mismatch")
    return metadata


def resolve(raw):
    checksum = read_json(raw / "current.json").get("archive_sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid OHenro 88 snapshot selector")
    snapshot = raw / "snapshots" / checksum
    validate_snapshot(snapshot, checksum)
    return snapshot


def fetch(raw, local_archive=None):
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "snapshots").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw) as directory:
        stage = Path(directory)
        version = None
        if local_archive is None:
            api = stage / "api-response.pb"
            apk._curl(API_URL, api, headers=apk.API_HEADERS, limit=apk.MAX_API)
            # Asset extraction is ABI-independent; use the newest descriptor, never an older fallback.
            version = parse_versions(api.read_bytes())[0]
            if (raw / "current.json").exists():
                cached = resolve(raw)
                metadata = read_json(cached / "metadata.json")
                if all(metadata.get(k) == version[k] for k in ("package_name", "version_code", "version_name", "source_sha1", "archive_size")):
                    return cached
            archive = stage / ("archive." + version["archive_type"].lower())
            apk._curl(version["url"], archive, limit=version["archive_size"])
            if archive.stat().st_size != version["archive_size"] or apk._sha(archive, "sha1") != version["source_sha1"]:
                raise ValueError("Downloaded archive size or APKPure SHA1 mismatch")
        else:
            if local_archive.stat().st_size > apk.MAX_ARCHIVE:
                raise ValueError("Local archive exceeds size limit")
            archive = stage / ("archive" + local_archive.suffix.lower())
            shutil.copyfile(local_archive, archive)
        identity, assets = validate_archive(archive, version, stage / "data")
        checksum = digest(archive)
        metadata = {**identity, "schema_version": 1, "archive": archive.name,
                    "archive_sha256": checksum, "archive_size": archive.stat().st_size,
                    "source_sha1": apk._sha(archive, "sha1"), "assets": assets,
                    "source_api": API_URL if version else None,
                    "source": "APKPure" if version else "local archive"}
        atomic_json(stage / "metadata.json", metadata)
        target = raw / "snapshots" / checksum
        if target.exists():
            validate_snapshot(target, checksum)
        else:
            os.rename(stage, target)
        atomic_json(raw / "current.json", {"archive_sha256": checksum})
        return target
