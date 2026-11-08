"""Discover the authoritative app's ES module graph and retain verified snapshots."""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from datasets._pipeline import atomic_json, digest, read_json
from .reference import build_web_reference as extractor

APP_URL = extractor.APP_URL


def identity(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def authoritative_url(base, reference):
    url = urljoin(base, reference)
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != urlsplit(APP_URL).netloc or
            parts.fragment or parts.username or parts.password):
        raise ValueError(f"Non-authoritative module URL: {url}")
    return url


class ModuleHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.modules = set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "script" and attrs.get("type") == "module" and attrs.get("src"):
            self.modules.add(authoritative_url(APP_URL, attrs["src"]))
        elif tag == "link" and attrs.get("rel") == "modulepreload" and attrs.get("href"):
            self.modules.add(authoritative_url(APP_URL, attrs["href"]))


def entrypoints(html):
    parser = ModuleHTML()
    parser.feed(html)
    if not parser.modules:
        raise ValueError("App HTML contains no module entrypoint")
    return sorted(parser.modules)


def dependencies(text, url):
    result = []
    for reference in extractor.module_imports(text):
        if not reference.startswith((".", "/", "https://", "http://")):
            raise ValueError(f"Unresolved bare module import: {reference}")
        dependency = authoritative_url(url, reference)
        if not urlsplit(dependency).path.endswith((".js", ".mjs")):
            raise ValueError(f"Unsupported module import: {dependency}")
        result.append(dependency)
    return sorted(set(result))


def download(url, html=False):
    request = Request(url, headers={"User-Agent": "ohenro-map-data/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=90) as response:
        if response.status != 200 or response.url != url:
            raise ValueError(f"Unexpected source response for {url}: {response.status} {response.url}")
        content_type = response.headers.get_content_type()
        allowed = {"text/html"} if html else {"application/javascript", "text/javascript", "application/x-javascript"}
        if content_type not in allowed:
            raise ValueError(f"Unexpected source MIME type: {content_type}: {url}")
        content = response.read()
    if not content or len(content) > 50_000_000:
        raise ValueError(f"Empty or excessively large source: {url}")
    content.decode("utf-8")
    return content


def complete_route(collection, manifest):
    counts = extractor.validate_route(collection, manifest)
    west, south, east, north = counts["bounds"]
    # A complete Shikoku walking circuit must span all four prefectures, not a
    # valid-looking sample Feature array or a partially deployed route subset.
    if (counts["feature_count"] < 88 or not 800_000 < counts["total_length_m"] < 3_000_000 or
            not (west < 133 and south < 33 and east > 134 and north > 34)):
        raise ValueError("Route array does not cover a complete Shikoku walking circuit")
    return counts


def extract_snapshot(snapshot, metadata):
    candidates = []
    for module in metadata["modules"]:
        text = (snapshot / module["file"]).read_text(encoding="utf-8")
        arrays = extractor.route_arrays(text)
        candidates.extend((module, text) for _ in arrays)
    if len(candidates) != 1:
        raise ValueError(f"Expected one unambiguous route array in module graph, found {len(candidates)}")
    module, text = candidates[0]
    collection, manifest = extractor.build_route(text, module["url"])
    complete_route(collection, manifest)
    route = {"bundle_url": module["url"], "bundle_sha256": module["sha256"],
             "route_sha256": identity(collection)}
    return collection, manifest, route


def verify(snapshot):
    metadata = read_json(snapshot / "metadata.json")
    if snapshot.name != identity(metadata):
        raise ValueError("Snapshot metadata identity differs from its content-addressed directory")
    records = [metadata["html"], *metadata["modules"]]
    urls = [record["url"] for record in records]
    if len(urls) != len(set(urls)) or metadata["html"]["url"] != APP_URL:
        raise ValueError("Duplicate or invalid snapshot source URLs")
    for record in records:
        file = Path(record["file"])
        if file.is_absolute() or ".." in file.parts:
            raise ValueError("Unsafe snapshot file path")
        path = snapshot / file
        authoritative_url(APP_URL, record["url"])
        if path.stat().st_size != record["size"] or digest(path) != record["sha256"]:
            raise ValueError(f"Corrupt source snapshot: {file}")
    roots = entrypoints((snapshot / metadata["html"]["file"]).read_text(encoding="utf-8"))
    if roots != metadata["entrypoints"]:
        raise ValueError("Snapshot entrypoint mismatch")
    modules = {record["url"]: record for record in metadata["modules"]}
    reachable, pending = set(), list(roots)
    while pending:
        url = pending.pop()
        if url in reachable:
            continue
        if url not in modules:
            raise ValueError(f"Incomplete source module graph: {url}")
        module = modules[url]
        imports = dependencies((snapshot / module["file"]).read_text(encoding="utf-8"), url)
        if imports != module["imports"]:
            raise ValueError(f"Module dependency mismatch: {url}")
        reachable.add(url)
        pending.extend(imports)
    if reachable != set(modules):
        raise ValueError("Snapshot includes unreachable modules")
    collection, manifest, route = extract_snapshot(snapshot, metadata)
    if route != metadata["route"]:
        raise ValueError("Snapshot route identity mismatch")
    return metadata, collection, manifest


def resolve(raw):
    current = read_json(raw / "current.json")["snapshot"]
    if not isinstance(current, str) or len(current) != 64 or any(c not in "0123456789abcdef" for c in current):
        raise ValueError("Invalid snapshot selector")
    snapshot = raw / "snapshots" / current
    verify(snapshot)
    return snapshot


def fetch(raw):
    raw = Path(raw)
    snapshots = raw / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw) as directory:
        stage = Path(directory)
        html = download(APP_URL, html=True)
        (stage / "index.html").write_bytes(html)
        roots = entrypoints(html.decode("utf-8"))
        modules, pending = {}, list(roots)
        (stage / "modules").mkdir()
        while pending:
            url = pending.pop()
            if url in modules:
                continue
            if len(modules) >= 256:
                raise ValueError("Excessively large source module graph")
            content = download(url)
            checksum = hashlib.sha256(content).hexdigest()
            filename = f"modules/{checksum}.js"
            (stage / filename).write_bytes(content)
            imports = dependencies(content.decode("utf-8"), url)
            modules[url] = {"url": url, "file": filename, "sha256": checksum,
                            "size": len(content), "imports": imports}
            pending.extend(imports)
        metadata = {"source_url": APP_URL,
                    "html": {"url": APP_URL, "file": "index.html", "size": len(html),
                             "sha256": hashlib.sha256(html).hexdigest()},
                    "entrypoints": roots, "modules": [modules[url] for url in sorted(modules)]}
        _, _, route = extract_snapshot(stage, metadata)
        metadata["route"] = route
        atomic_json(stage / "metadata.json", metadata)
        snapshot = snapshots / identity(metadata)
        if snapshot.exists():
            verify(snapshot)
        else:
            os.replace(stage, snapshot)
            verify(snapshot)
        atomic_json(raw / "current.json", {"snapshot": snapshot.name})
    print(f"Source snapshot: {snapshot}", flush=True)
    return snapshot
