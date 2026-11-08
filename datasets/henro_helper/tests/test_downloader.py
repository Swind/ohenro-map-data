import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from datasets.henro_helper import downloader as source


def elf(machine=183):
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", header, 16, 3, machine, 1)
    struct.pack_into("<H", header, 52, 64)
    return bytes(header) + b"native fixture data"


def manifest(package=source.PACKAGE, code=7, name="1.7"):
    return (f'<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
            f'package="{package}" android:versionCode="{code}" '
            f'android:versionName="{name}"/>').encode()


def binary_manifest(utf8=True):
    strings = ["manifest", "package", source.PACKAGE, "versionCode", "versionName", "1.7",
               "http://schemas.android.com/apk/res/android"]
    offsets = []
    encoded = bytearray()
    for value in strings:
        offsets.append(len(encoded))
        if utf8:
            data = value.encode()
            encoded.extend(bytes([len(value), len(data)]) + data + b"\0")
        else:
            encoded.extend(struct.pack("<H", len(value)) + value.encode("utf-16le") + b"\0\0")
    encoded.extend(b"\0" * (-len(encoded) % 4))
    pool_size = 28 + 4 * len(strings) + len(encoded)
    pool = (struct.pack("<HHI5I", 1, 28, pool_size, len(strings), 0, 0x100 if utf8 else 0,
                        28 + 4 * len(strings), 0)
            + struct.pack("<" + "I" * len(offsets), *offsets) + encoded)
    attributes = (struct.pack("<IIIHBBI", 0xffffffff, 1, 2, 8, 0, 3, 2)
                  + struct.pack("<IIIHBBI", 6, 3, 0xffffffff, 8, 0, 0x10, 7)
                  + struct.pack("<IIIHBBI", 6, 4, 5, 8, 0, 3, 5))
    element = (struct.pack("<HHIII", 0x102, 16, 36 + len(attributes), 1, 0xffffffff)
               + struct.pack("<II6H", 0xffffffff, 0, 20, 20, 3, 0, 0, 0) + attributes)
    return struct.pack("<HHI", 3, 8, 8 + len(pool) + len(element)) + pool + element


def zipped(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


def apk(*, package=source.PACKAGE, abi="arm64-v8a", libraries=source.LIBRARIES, binary=False):
    files = {"AndroidManifest.xml": binary_manifest() if binary else manifest(package)}
    files.update({f"lib/{abi}/{name}": elf() for name in libraries})
    files["assets/not-extracted.txt"] = b"not extracted"
    return zipped(files)


def xapk(*, package=source.PACKAGE, inner_package=source.PACKAGE, abi="arm64-v8a"):
    splits = {"base.apk": apk(package=inner_package, libraries=()),
              f"config.{abi.replace('-', '_')}.apk": apk(package=inner_package, abi=abi)}
    identity = {"package_name": package, "version_code": "7", "version_name": "1.7",
                "split_configs": [f"config.{abi.replace('-', '_')}"],
                "split_apks": [{"file": name, "id": name[:-4]} for name in splits]}
    return zipped({"manifest.json": json.dumps(identity).encode(), **splits})


def varint(value):
    data = bytearray()
    while value > 127:
        data.append((value & 127) | 128)
        value >>= 7
    data.append(value)
    return bytes(data)


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint((number << 3) | 2) + varint(len(value)) + value


def api_version(body, *, code=7, package=source.PACKAGE, kind="XAPK", digest=None, url=None):
    digest = digest or hashlib.sha1(body).hexdigest()
    url = url or f"https://download.pureapk.com/b/{kind}/fixture-{code}-{digest}"
    asset = field(3, digest) + field(4, len(body)) + field(8, kind) + field(9, url)
    app = (field(4, package) + field(5, str(code)) + field(6, "1.7") + field(24, asset))
    return field(2, field(1, "version_list") + field(3, field(2, app)))


def api(*records):
    return field(1, field(7, b"".join(records)))


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.expected = {"version_code": 7, "version_name": "1.7"}

    def validate(self, body, suffix=".xapk", output=None):
        path = self.root / ("archive" + suffix)
        path.write_bytes(body)
        return source.validate_archive(path, self.expected, output)

    def transport(self, response, archives, calls):
        def download(url, output, *, headers=None, byte_range=None, limit=source.MAX_ARCHIVE):
            calls.append((url, byte_range))
            data = response if url == source.API_URL else archives[url]
            if byte_range is not None:
                start, end = byte_range
                data = data[start:end + 1]
            if len(data) > limit:
                raise ValueError("fixture exceeds size limit")
            output.write_bytes(data)
        return patch.object(source, "_curl", side_effect=download)

    def test_binary_android_manifest_utf8_and_utf16(self):
        for utf8 in (False, True):
            identity = source._android_manifest(binary_manifest(utf8))
            self.assertEqual(identity, {"package_name": source.PACKAGE, "version_code": 7,
                                        "version_name": "1.7"})
        self.assertEqual(set(self.validate(apk(binary=True), ".apk")), set(source.LIBRARIES))

    def test_split_xapk_extracts_only_exact_arm64_libraries(self):
        output = self.root / "native"
        libraries = self.validate(xapk(), output=output)
        self.assertEqual(set(libraries), set(source.LIBRARIES))
        self.assertEqual(sorted(path.name for path in output.iterdir()), sorted(source.LIBRARIES))
        for name in source.LIBRARIES:
            self.assertEqual((output / name).read_bytes(), elf())
            self.assertEqual(libraries[name], hashlib.sha256(elf()).hexdigest())

    def test_incorrect_xapk_and_nested_apk_packages_rejected(self):
        for body, suffix in ((xapk(package="wrong.package"), ".xapk"),
                             (xapk(inner_package="wrong.package"), ".xapk"),
                             (apk(package="wrong.package"), ".apk")):
            with self.assertRaisesRegex(ValueError, "package"):
                self.validate(body, suffix)

    def test_wrong_archive_version_rejected(self):
        with self.assertRaisesRegex(ValueError, "version code"):
            source._check_identity({"package_name": source.PACKAGE, "version_code": "8",
                                    "version_name": "1.7"}, self.expected)

    def test_corrupt_archive_crc_rejected(self):
        body = bytearray(apk())
        position = body.index(b"native fixture data")
        body[position] ^= 1
        with self.assertRaises(ValueError):
            self.validate(bytes(body), ".apk")
        with self.assertRaises(ValueError):
            self.validate(xapk()[:-10])

    def test_missing_arm64_and_invalid_elf_rejected(self):
        for body in (apk(abi="armeabi-v7a"), apk(libraries=("libapp.so",))):
            with self.assertRaises(source.MissingArm64):
                self.validate(body, ".apk")
        body = zipped({"AndroidManifest.xml": manifest(),
                       "lib/arm64-v8a/libapp.so": elf(machine=62),
                       "lib/arm64-v8a/libflutter.so": elf()})
        with self.assertRaisesRegex(ValueError, "ARM64"):
            self.validate(body, ".apk")

    def test_xapk_split_inventory_mismatch_rejected(self):
        body = zipped({"manifest.json": json.dumps({"package_name": source.PACKAGE,
                       "version_code": "7", "version_name": "1.7", "split_apks": []}).encode(),
                       "base.apk": apk()})
        with self.assertRaisesRegex(ValueError, "split APK list"):
            self.validate(body)

    def test_protobuf_schema_and_latest_order(self):
        body = xapk()
        versions = source.parse_versions(api(api_version(body, code=6), api_version(body, code=7)))
        self.assertEqual([version["version_code"] for version in versions], [7, 6])
        self.assertEqual(versions[0]["source_sha1"], hashlib.sha1(body).hexdigest())
        self.assertEqual(versions[0]["archive_size"], len(body))
        self.assertEqual(versions[0]["archive_type"], "XAPK")

    def test_protobuf_bounds_package_and_url_rejected(self):
        body = xapk()
        invalid = [b"", b"<html>not protobuf</html>", b"\x0a\xff\xff\xff\xff\x7f",
                   b"\x08" + b"\xff" * 10, b"\x00\x00", api(api_version(body, package="wrong.package")),
                   api(api_version(body, digest="not-a-digest")),
                   api(api_version(body, url="https://attacker.example/archive.xapk")),
                   api(api_version(body, url="http://download.pureapk.com/b/XAPK/fixture"))]
        invalid.append(field(1, field(7, field(2, 123))))
        valid = api(api_version(body))
        invalid.extend(valid[:end] for end in (1, 2, len(valid) - 1))
        for response in invalid:
            with self.subTest(response=response[:30]), self.assertRaises(ValueError):
                source.parse_versions(response)
        with patch.object(source, "MAX_API", 3), self.assertRaises(ValueError):
            source.parse_versions(valid)

    def test_fetch_skips_v7a_commits_snapshot_and_reuses_without_download(self):
        arm32, arm64 = xapk(abi="armeabi-v7a"), xapk()
        response = api(api_version(arm32), api_version(arm64))
        versions = source.parse_versions(response)
        archives = {version["url"]: data for version, data in zip(versions, (arm32, arm64))}
        calls = []
        raw = self.root / "raw"
        with self.transport(response, archives, calls):
            snapshot = source.fetch(raw)
        self.assertEqual(snapshot.name, hashlib.sha256(arm64).hexdigest())
        self.assertEqual((snapshot / "archive.xapk").read_bytes(), arm64)
        self.assertEqual((snapshot / "api-response.pb").read_bytes(), response)
        self.assertEqual(source.resolve(raw), snapshot)
        self.assertNotIn((versions[0]["url"], None), calls)
        calls.clear()
        with self.transport(response, archives, calls):
            self.assertEqual(source.fetch(raw), snapshot)
        self.assertFalse(any(url != source.API_URL and byte_range is None for url, byte_range in calls))
        metadata = json.loads((snapshot / "metadata.json").read_text())
        self.assertNotIn("url", metadata)
        self.assertEqual(metadata["libraries"]["libapp.so"], hashlib.sha256(elf()).hexdigest())

    def test_failed_download_preserves_current_and_snapshot(self):
        body = xapk()
        response = api(api_version(body))
        version = source.parse_versions(response)[0]
        raw = self.root / "raw"
        with self.transport(response, {version["url"]: body}, []):
            snapshot = source.fetch(raw)
        current = (raw / "current.json").read_bytes()
        archive = (snapshot / "archive.xapk").read_bytes()
        changed = xapk(inner_package="wrong.package")
        response = api(api_version(changed))
        version = source.parse_versions(response)[0]
        with self.transport(response, {version["url"]: changed}, []):
            with self.assertRaisesRegex(ValueError, "package"):
                source.fetch(raw)
        self.assertEqual((raw / "current.json").read_bytes(), current)
        self.assertEqual((snapshot / "archive.xapk").read_bytes(), archive)

    def test_tampered_cached_library_prevents_reuse(self):
        body = xapk()
        response = api(api_version(body))
        version = source.parse_versions(response)[0]
        raw = self.root / "raw"
        with self.transport(response, {version["url"]: body}, []):
            snapshot = source.fetch(raw)
        (snapshot / "lib" / "arm64-v8a" / "libapp.so").write_bytes(elf() + b"tampered")
        current = (raw / "current.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "extracted library checksum"):
            source.resolve(raw)
        with self.transport(response, {version["url"]: body}, []):
            with self.assertRaisesRegex(ValueError, "extracted library checksum"):
                source.fetch(raw)
        self.assertEqual((raw / "current.json").read_bytes(), current)

    def test_tampered_cached_archive_rejected(self):
        body = xapk()
        response = api(api_version(body))
        version = source.parse_versions(response)[0]
        raw = self.root / "raw"
        with self.transport(response, {version["url"]: body}, []):
            snapshot = source.fetch(raw)
        (snapshot / "archive.xapk").write_bytes(body + b"tampered")
        with self.assertRaisesRegex(ValueError, "archive checksum"):
            source.resolve(raw)

    def test_remote_directory_bounds_and_manifest_crc(self):
        body = bytearray(xapk())
        position = body.index(b'"package_name"')
        body[position] ^= 1
        version = source.parse_versions(api(api_version(bytes(body))))[0]
        with self.transport(b"", {version["url"]: bytes(body)}, []):
            with self.assertRaisesRegex(ValueError, "CRC"):
                source._xapk_manifest(version, self.root)
        version["archive_size"] -= 1
        with self.transport(b"", {version["url"]: bytes(body)}, []):
            with self.assertRaises(ValueError):
                source._xapk_manifest(version, self.root)


if __name__ == "__main__":
    unittest.main()
