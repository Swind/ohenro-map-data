"""Acquire APKPure archives as validated, content-addressed ARM64 snapshots.

APKPure's app API and headers follow EFF apkeep. The protobuf field paths below
are explicit: no strings are scraped from the binary response or an HTML page.
Only data is read from APKs; none of their code is installed or executed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import zlib

PACKAGE = "com.henrohelper100.app"
API_URL = "https://api.pureapk.com/m/v3/cms/app_version?hl=en-US&package_name=" + PACKAGE
API_HEADERS = {"x-cv": "3172501", "x-sv": "29", "x-abis": "arm64-v8a", "x-gp": "1"}
LIBRARIES = ("libapp.so", "libflutter.so")
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_API = 8 * 1024 * 1024
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


class MissingArm64(ValueError):
    """A valid package variant does not contain the required ARM64 libraries."""


def _varint(body: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(body):
            raise ValueError("truncated protobuf varint")
        byte = body[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("protobuf varint exceeds uint64")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("protobuf varint exceeds uint64")


def _protobuf(body: bytes) -> dict[int, list]:
    if not isinstance(body, bytes):
        raise ValueError("protobuf message has an invalid wire type")
    fields: dict[int, list] = {}
    offset = 0
    count = 0
    while offset < len(body):
        key, offset = _varint(body, offset)
        number, wire = key >> 3, key & 7
        if not 0 < number < (1 << 29):
            raise ValueError("invalid protobuf field number")
        if wire == 0:
            value, offset = _varint(body, offset)
        else:
            if wire == 2:
                size, offset = _varint(body, offset)
            elif wire in (1, 5):
                size = 8 if wire == 1 else 4
            else:
                raise ValueError("unsupported protobuf wire type")
            if size > len(body) - offset:
                raise ValueError("truncated protobuf field")
            value = body[offset:offset + size]
            offset += size
        fields.setdefault(number, []).append(value)
        count += 1
        if count > 100000:
            raise ValueError("too many protobuf fields")
    return fields


def _one(fields: dict, number: int, kind=bytes):
    values = fields.get(number, [])
    if len(values) != 1 or not isinstance(values[0], kind):
        raise ValueError(f"missing or ambiguous protobuf field {number}")
    return values[0]


def _text(fields: dict, number: int) -> str:
    try:
        return _one(fields, number).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("invalid protobuf text") from error


def parse_versions(body: bytes) -> list[dict]:
    """Read cms/app_version -> page(1.7) -> version_list(2.3.2).

    The API does not label each variant's ABI, even with x-abis set. XAPK's
    manifest is range-read before downloading to select the ARM64 variant.
    """
    if not body or len(body) > MAX_API:
        raise ValueError("invalid APKPure API response size")
    envelope = _protobuf(_one(_protobuf(body), 1))
    page = _protobuf(_one(envelope, 7))
    versions = []
    for raw in page.get(2, []):
        section = _protobuf(raw)
        if _text(section, 1) != "version_list":
            continue
        app = _protobuf(_one(_protobuf(_one(section, 3)), 2))
        if _text(app, 4) != PACKAGE:
            continue
        code = _text(app, 5)
        name = _text(app, 6)
        if not re.fullmatch(r"[0-9]{1,10}", code) or not name:
            raise ValueError("invalid API package version")
        asset = _protobuf(_one(app, 24))
        digest, archive_type, url = _text(asset, 3), _text(asset, 8), _text(asset, 9)
        size = _one(asset, 4, int)
        if not re.fullmatch(r"[0-9a-fA-F]{40}", digest):
            raise ValueError("invalid API archive SHA1")
        parsed = urllib.parse.urlsplit(url)
        if (archive_type not in ("APK", "XAPK") or parsed.scheme != "https"
                or parsed.netloc != "download.pureapk.com"
                or not parsed.path.startswith(f"/b/{archive_type}/")
                or any(ord(c) < 32 for c in url) or not 0 < size <= MAX_ARCHIVE):
            raise ValueError("invalid API download descriptor")
        versions.append({"package_name": PACKAGE, "version_code": int(code),
                         "version_name": name, "archive_type": archive_type,
                         "source_sha1": digest.lower(), "archive_size": size, "url": url})
    if not versions:
        raise ValueError("APKPure API has no matching package versions")
    return sorted(versions, key=lambda item: item["version_code"], reverse=True)


def _curl(url: str, output: Path, *, headers: dict | None = None,
          byte_range: tuple[int, int] | None = None, limit: int = MAX_ARCHIVE) -> None:
    command = ["curl", "--fail", "--silent", "--show-error", "--location",
               "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "30",
               "--max-time", "1800", "--max-filesize", str(limit), "--output", str(output)]
    for key, value in (headers or {}).items():
        command.extend(["--header", f"{key}: {value}"])
    if byte_range is not None:
        command.extend(["--range", f"{byte_range[0]}-{byte_range[1]}"])
    command.append(url)
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    except FileNotFoundError as error:
        raise RuntimeError("curl is required to download APKPure archives") from error
    except subprocess.CalledProcessError as error:
        # Do not include the expiring signed URL in exception messages.
        raise RuntimeError(f"APKPure curl request failed (exit {error.returncode})") from None
    if output.stat().st_size > limit:
        raise ValueError("APKPure response exceeds size limit")


def _range(version: dict, start: int, end: int, work: Path) -> bytes:
    if not 0 <= start <= end < version["archive_size"]:
        raise ValueError("invalid remote ZIP range")
    path = work / "range.bin"
    # curl applies max-filesize to the redirect's HTML body as well.
    _curl(version["url"], path, byte_range=(start, end), limit=max(65557, end - start + 1))
    data = path.read_bytes()
    if len(data) != end - start + 1:
        raise ValueError("server did not return the requested ZIP range")
    return data


def _safe_member(name: str) -> bool:
    return bool(name) and not name.startswith("/") and "\\" not in name and all(
        part not in ("", ".", "..") for part in name.split("/"))


def _xapk_manifest(version: dict, work: Path) -> dict:
    """Read only the central directory and manifest, not the 200+ MB payload."""
    size = version["archive_size"]
    start = max(0, size - 65557)
    tail = _range(version, start, size - 1, work)
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or len(tail) - end < 22:
        raise ValueError("missing XAPK ZIP directory")
    _, disk, central_disk, count_disk, count, length, offset, comment = struct.unpack_from("<4s4H2LH", tail, end)
    if (disk or central_disk or count_disk != count or count > 50000
            or end + 22 + comment != len(tail) or length > MAX_MANIFEST
            or offset + length != start + end):
        raise ValueError("unsupported or invalid XAPK ZIP directory")
    central = (tail[offset - start:offset - start + length] if offset >= start
               else _range(version, offset, offset + length - 1, work))
    position = 0
    manifest = None
    for _ in range(count):
        if position + 46 > len(central):
            raise ValueError("truncated XAPK ZIP directory")
        entry = struct.unpack_from("<4s6H3L5H2L", central, position)
        name_length, extra_length, comment_length = entry[10:13]
        stop = position + 46 + name_length + extra_length + comment_length
        if entry[0] != b"PK\x01\x02" or stop > len(central):
            raise ValueError("invalid XAPK ZIP directory entry")
        name = central[position + 46:position + 46 + name_length]
        if name == b"manifest.json":
            if manifest is not None:
                raise ValueError("duplicate XAPK manifest")
            manifest = entry
        position = stop
    if position != len(central) or manifest is None:
        raise ValueError("invalid or missing XAPK manifest")
    entry = manifest
    method, compressed, uncompressed, local = entry[4], entry[8], entry[9], entry[-1]
    if entry[3] & 1 or method not in (0, 8) or max(compressed, uncompressed) > MAX_MANIFEST:
        raise ValueError("unsupported XAPK manifest compression")
    header = _range(version, local, local + 29, work)
    local_fields = struct.unpack("<4s5H3L2H", header)
    if local_fields[0] != b"PK\x03\x04":
        raise ValueError("invalid XAPK manifest header")
    data_start = local + 30 + local_fields[-2] + local_fields[-1]
    if not compressed:
        raise ValueError("empty XAPK manifest")
    data = _range(version, data_start, data_start + compressed - 1, work)
    if method == 8:
        inflater = zlib.decompressobj(-15)
        data = inflater.decompress(data, MAX_MANIFEST + 1)
        if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data:
            raise ValueError("invalid compressed XAPK manifest")
    if len(data) != uncompressed or zlib.crc32(data) != entry[7]:
        raise ValueError("XAPK manifest CRC or size mismatch")
    manifest_data = json.loads(data)
    _check_identity(manifest_data, version, require_name=True)
    return manifest_data


def _check_identity(identity: dict, expected: dict, *, require_name: bool = False) -> None:
    if not isinstance(identity, dict) or identity.get("package_name") != PACKAGE:
        raise ValueError("archive package does not match Henro Helper")
    if str(identity.get("version_code")) != str(expected["version_code"]):
        raise ValueError("archive version code does not match API metadata")
    name = identity.get("version_name")
    if (require_name or name is not None) and name != expected["version_name"]:
        raise ValueError("archive version name does not match API metadata")


def _string_pool(data: bytes, offset: int, header_size: int, size: int) -> list[str]:
    if header_size < 28 or offset + header_size > len(data):
        raise ValueError("invalid Android string pool")
    count, styles, flags, strings_start, styles_start = struct.unpack_from("<5I", data, offset + 8)
    stop = offset + (styles_start or size)
    if (count > 100000 or not header_size + 4 * (count + styles) <= strings_start <= size
            or (styles_start and not strings_start <= styles_start <= size)):
        raise ValueError("invalid Android string offsets")
    utf8 = bool(flags & 0x100)
    strings = []
    for index in range(count):
        position = offset + strings_start + struct.unpack_from("<I", data, offset + header_size + 4 * index)[0]
        def length_at(position: int) -> tuple[int, int]:
            width = 1 if utf8 else 2
            if position + width > stop:
                raise ValueError("truncated Android string length")
            first = int.from_bytes(data[position:position + width], "little")
            position += width
            mask = 0x80 if utf8 else 0x8000
            if first & mask:
                if position + width > stop:
                    raise ValueError("truncated Android string length")
                second = int.from_bytes(data[position:position + width], "little")
                position += width
                first = ((first & (mask - 1)) << (8 * width)) | second
            return first, position
        length, position = length_at(position)
        if utf8:
            length, position = length_at(position)
        byte_length = length if utf8 else length * 2
        terminator = 1 if utf8 else 2
        if position + byte_length + terminator > stop or any(data[position + byte_length:position + byte_length + terminator]):
            raise ValueError("truncated Android string")
        strings.append(data[position:position + byte_length].decode("utf-8" if utf8 else "utf-16le"))
    return strings


def _android_manifest(data: bytes) -> dict:
    if len(data) > MAX_MANIFEST:
        raise ValueError("Android manifest exceeds size limit")
    if data.lstrip().startswith(b"<"):
        root = ET.fromstring(data)
        if root.tag != "manifest":
            raise ValueError("invalid Android manifest root")
        return {"package_name": root.get("package"), "version_code": root.get(ANDROID_NS + "versionCode"),
                "version_name": root.get(ANDROID_NS + "versionName")}
    if len(data) < 8 or struct.unpack_from("<HHI", data) != (3, 8, len(data)):
        raise ValueError("invalid binary Android manifest")
    strings: list[str] = []
    offset = 8
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated Android XML chunk")
        kind, header_size, size = struct.unpack_from("<HHI", data, offset)
        if header_size < 8 or size < header_size or offset + size > len(data):
            raise ValueError("invalid Android XML chunk bounds")
        if kind == 1:
            strings = _string_pool(data, offset, header_size, size)
        elif kind == 0x102:
            if header_size < 16 or size < header_size + 20:
                raise ValueError("invalid Android XML element")
            extension = offset + header_size
            _, name, attribute_start, attribute_size, count = struct.unpack_from("<IIHHH", data, extension)
            if name >= len(strings) or strings[name] != "manifest" or attribute_size < 20:
                raise ValueError("invalid Android manifest element")
            position = extension + attribute_start
            if attribute_start < 20 or position + count * attribute_size > offset + size:
                raise ValueError("invalid Android manifest attributes")
            attributes = {}
            for index in range(count):
                attr = position + index * attribute_size
                namespace, key, raw, value_size, zero, value_type, value = struct.unpack_from("<IIIHBBI", data, attr)
                if key >= len(strings) or value_size != 8 or zero:
                    raise ValueError("invalid Android manifest attribute")
                if raw != 0xffffffff:
                    if raw >= len(strings):
                        raise ValueError("invalid Android attribute string")
                    result = strings[raw]
                elif value_type == 3:
                    if value >= len(strings):
                        raise ValueError("invalid Android typed string")
                    result = strings[value]
                elif value_type in (0x10, 0x11):
                    result = value
                else:
                    continue
                if namespace == 0xffffffff:
                    attr_name = strings[key]
                elif namespace < len(strings) and strings[namespace] == ANDROID_NS[1:-1]:
                    attr_name = ANDROID_NS + strings[key]
                else:
                    continue
                if attr_name in attributes:
                    raise ValueError("duplicate Android manifest attribute")
                attributes[attr_name] = result
            return {"package_name": attributes.get("package"),
                    "version_code": attributes.get(ANDROID_NS + "versionCode"),
                    "version_name": attributes.get(ANDROID_NS + "versionName")}
        offset += size
    raise ValueError("Android manifest has no root element")


def _validate_elf(header: bytes) -> None:
    if (len(header) < 64 or header[:7] != b"\x7fELF\x02\x01\x01"
            or struct.unpack_from("<HHI", header, 16) != (3, 183, 1)
            or struct.unpack_from("<H", header, 52)[0] != 64):
        raise ValueError("native library is not a little-endian ARM64 shared ELF")


def _check_zip(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > 50000 or sum(item.file_size for item in entries) > 4 * MAX_ARCHIVE:
        raise ValueError("ZIP archive exceeds extraction limits")
    names = [item.filename for item in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate ZIP member")
    for item in entries:
        if item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("encrypted or symlink ZIP member")
    bad = archive.testzip()
    if bad is not None:
        raise ValueError("ZIP CRC validation failed")


def validate_archive(path: Path, expected: dict, output: Path | None = None) -> dict[str, str]:
    """Validate all ZIP CRCs and identities; write only the two exact ARM64 libs."""
    found: dict[str, str] = {}

    def inspect(apk: zipfile.ZipFile) -> None:
        _check_zip(apk)
        if apk.getinfo("AndroidManifest.xml").file_size > MAX_MANIFEST:
            raise ValueError("Android manifest exceeds size limit")
        _check_identity(_android_manifest(apk.read("AndroidManifest.xml")), expected)
        for name in LIBRARIES:
            member = "lib/arm64-v8a/" + name
            if member not in apk.namelist():
                continue
            if name in found or apk.getinfo(member).file_size > MAX_ARCHIVE // 2:
                raise ValueError("duplicate or oversized ARM64 native library")
            digest = hashlib.sha256()
            destination = None
            try:
                if output is not None:
                    output.mkdir(parents=True, exist_ok=True)
                    destination = (output / name).open("xb")
                with apk.open(member) as source:
                    header = source.read(64)
                    _validate_elf(header)
                    digest.update(header)
                    if destination is not None:
                        destination.write(header)
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        if destination is not None:
                            destination.write(chunk)
            finally:
                if destination is not None:
                    destination.close()
            found[name] = digest.hexdigest()

    try:
        with zipfile.ZipFile(path) as archive:
            if path.suffix == ".apk":
                inspect(archive)
            elif path.suffix == ".xapk":
                _check_zip(archive)
                if archive.getinfo("manifest.json").file_size > MAX_MANIFEST:
                    raise ValueError("XAPK manifest exceeds size limit")
                manifest = json.loads(archive.read("manifest.json"))
                _check_identity(manifest, expected, require_name=True)
                apks = [item.filename for item in archive.infolist() if item.filename.endswith(".apk")]
                if not apks:
                    raise ValueError("XAPK contains no APKs")
                declared = manifest.get("split_apks")
                if declared is not None:
                    if (not isinstance(declared, list) or any(
                            not isinstance(item, dict) or not isinstance(item.get("file"), str) for item in declared)
                            or sorted(item.get("file", "") for item in declared) != sorted(apks)):
                        raise ValueError("XAPK split APK list does not match its contents")
                for member in apks:
                    if not _safe_member(member) or archive.getinfo(member).file_size > MAX_ARCHIVE:
                        raise ValueError("invalid XAPK split APK")
                    # Nested APKs need seeking; spool to disk rather than copying them into RAM.
                    with tempfile.TemporaryFile(dir=path.parent) as temporary:
                        with archive.open(member) as source:
                            shutil.copyfileobj(source, temporary, 1024 * 1024)
                        temporary.seek(0)
                        with zipfile.ZipFile(temporary) as apk:
                            inspect(apk)
            else:
                raise ValueError("unsupported archive extension")
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeError, struct.error, zlib.error) as error:
        raise ValueError("invalid APK/XAPK archive or manifest") from error
    if set(found) != set(LIBRARIES):
        raise MissingArm64("package variant lacks libapp.so and/or libflutter.so for ARM64")
    return found


def _sha(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_write(path: Path, value: dict) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _validate_snapshot(snapshot: Path, digest: str) -> dict:
    metadata = json.loads((snapshot / "metadata.json").read_text(encoding="utf-8"))
    if (not isinstance(metadata, dict) or metadata.get("package_name") != PACKAGE
            or metadata.get("archive_sha256") != digest
            or metadata.get("archive") not in ("archive.apk", "archive.xapk")
            or not isinstance(metadata.get("version_code"), int)
            or not isinstance(metadata.get("version_name"), str)):
        raise ValueError("invalid Henro Helper snapshot metadata")
    archive = snapshot / metadata["archive"]
    if archive.stat().st_size != metadata.get("archive_size") or _sha(archive) != digest:
        raise ValueError("cached Henro Helper archive checksum mismatch")
    if _sha(archive, "sha1") != metadata.get("source_sha1"):
        raise ValueError("cached archive does not match APKPure digest")
    libraries = validate_archive(archive, metadata)
    if libraries != metadata.get("libraries"):
        raise ValueError("cached archive library metadata mismatch")
    for name, checksum in libraries.items():
        library = snapshot / "lib" / "arm64-v8a" / name
        if _sha(library) != checksum:
            raise ValueError("cached extracted library checksum mismatch")
        with library.open("rb") as source:
            _validate_elf(source.read(64))
    return metadata


def resolve(raw: Path) -> Path:
    """Resolve and fully validate raw/current.json without accessing the network."""
    raw = Path(raw)
    current = json.loads((raw / "current.json").read_text(encoding="utf-8"))
    digest = current.get("archive_sha256") if isinstance(current, dict) else None
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid Henro Helper current snapshot selector")
    snapshot = raw / "snapshots" / digest
    _validate_snapshot(snapshot, digest)
    return snapshot


def _select(raw: Path, digest: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".current-", suffix=".json", dir=raw)
    os.close(descriptor)
    path = Path(temporary)
    try:
        _json_write(path, {"archive_sha256": digest})
        os.replace(path, raw / "current.json")
    finally:
        path.unlink(missing_ok=True)


def fetch(raw: Path) -> Path:
    """Fetch newest ARM64 source, committing current only after full validation."""
    raw = Path(raw)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "snapshots").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw) as temporary:
        stage = Path(temporary)
        api = stage / "api-response.pb"
        _curl(API_URL, api, headers=API_HEADERS, limit=MAX_API)
        versions = parse_versions(api.read_bytes())
        cached = None
        if (raw / "current.json").exists():
            cached = resolve(raw)
            metadata = json.loads((cached / "metadata.json").read_text(encoding="utf-8"))
        for version in versions:
            if version["archive_type"] == "XAPK":
                manifest = _xapk_manifest(version, stage)
                splits = manifest.get("split_configs", [])
                if (splits and "config.arm64_v8a" not in splits
                        and any(str(value).startswith("config.armeabi") or str(value).startswith("config.x86") for value in splits)):
                    continue
            if cached is not None and all(metadata.get(key) == version[key] for key in (
                    "package_name", "version_name", "version_code", "source_sha1", "archive_size")):
                return cached
            archive = stage / ("archive." + version["archive_type"].lower())
            _curl(version["url"], archive, limit=version["archive_size"])
            if archive.stat().st_size != version["archive_size"] or _sha(archive, "sha1") != version["source_sha1"]:
                raise ValueError("downloaded archive size or APKPure SHA1 mismatch")
            library_dir = stage / "lib" / "arm64-v8a"
            try:
                libraries = validate_archive(archive, version, library_dir)
            except MissingArm64:
                shutil.rmtree(stage / "lib", ignore_errors=True)
                archive.unlink()
                continue
            digest = _sha(archive)
            metadata = {key: value for key, value in version.items() if key not in ("url", "archive_type")}
            metadata.update(archive=archive.name, archive_sha256=digest, libraries=libraries,
                            source_api=API_URL, schema_version=1)
            _json_write(stage / "metadata.json", metadata)
            (stage / "range.bin").unlink(missing_ok=True)
            target = raw / "snapshots" / digest
            if target.exists():
                _validate_snapshot(target, digest)
            else:
                os.rename(stage, target)
            _select(raw, digest)
            return target
    raise MissingArm64("APKPure has no matching Henro Helper ARM64 package")
