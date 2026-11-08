# Shikoku Nature Trail Archive Pipeline

Reproducible crawler for the Shikoku Nature Trail official site
(https://shikoku-nature-trail.com/). Phase 1 is a **raw archive only** — it
saves the four prefecture course lists, every course detail HTML page, its
content images, and the embedded Google My Maps KML, together with source
metadata and SHA-256 checksums. Phase 2 normalizes that archive into one
deterministic offline JSON dataset. Phase 3 exports routes and POIs and builds
the MapLibre-ready PMTiles archive.

Plan: `datasets/shikoku_nature_trail/docs/shikoku-nature-trail-crawler-plan.md`

## Commands

The default command refreshes the official archive and builds **all** outputs:

```bash
python3 -m datasets.shikoku_nature_trail
python3 -m datasets.shikoku_nature_trail fetch
python3 -m datasets.shikoku_nature_trail run --local
python3 -m datasets.shikoku_nature_trail build --force
python3 -m datasets.shikoku_nature_trail validate
```

`run` always refreshes the four lists, all detail pages, and all KML. Images
are reused only from a verified archive when their source URL and owning
detail HTML are unchanged. A refresh must account for every list row,
course, map and image; missing data, failed images, malformed geometry or
checksums fail without selecting an incomplete archive. No replacement
images or coordinates are fabricated.

Validated archives are immutable `raw/snapshots/<content-sha256>/` trees,
selected atomically by `raw/current.json`. `build` and `run --local` also
accept the older flat raw layout and never perform HTTP requests.
`--raw-dir` (alias `--data-dir`), `--output-dir`, and `--reports-dir` override
the default source-local directories. `--local` applies only to `run`;
`--force` applies to `run`/`build` and rebuilds unchanged outputs. HTTP
options are `--timeout`, `--concurrency`, and `--delay`; defaults remain 30s,
at most 3 concurrent requests and 0.3s between requests.

The normalized JSON, route GeoJSON, POI GeoJSON, quality report and PMTiles
are staged and validated together before per-file atomic publication;
`reports/pipeline.json` is written last with input identities, code/settings
and output hashes. Retrieval timestamps do not change the input identity.
Identical inputs/settings and intact published outputs skip rebuilding.
Normalization warnings representing missing source data are fatal, while
conservative unmatched/ambiguous tourism-name matches remain in the quality
report and do not discard KML POIs.

PMTiles requires `pmtiles`/`go-pmtiles` and either local `tippecanoe` or Docker
with `ohenro-elevation-visuals:latest` (built automatically if absent).
`--image` or `TRAIL_IMAGE` selects the Docker image. The shell script below
is an offline `build` wrapper and forwards pipeline options.

The legacy individual archive/normalization commands remain available for
inspection and manual acquisition; they operate on a flat archive:

```bash
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw crawl-index
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw crawl-details
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw download-assets
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw download-kml
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw crawl-all
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw verify
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw report
python3 -m datasets.shikoku_nature_trail --data-dir datasets/shikoku_nature_trail/raw normalize --output datasets/shikoku_nature_trail/output/shikoku-nature-trail.json
python3 -m datasets.shikoku_nature_trail export-map --input datasets/shikoku_nature_trail/output/shikoku-nature-trail.json --routes datasets/shikoku_nature_trail/output/shikoku-nature-trail.geojson --pois datasets/shikoku_nature_trail/output/shikoku-nature-trail-pois.geojson --report datasets/shikoku_nature_trail/output/shikoku-nature-trail-report.json
./datasets/shikoku_nature_trail/scripts/build-shikoku-nature-trail.sh
```

`crawl-all` runs index -> details -> assets -> kml -> report in sequence.
`normalize` is strictly offline and does not construct an HTTP client. It
atomically creates the output parent directory and file. A missing
`course-index.json` is fatal; a malformed or missing per-course HTML, assets
manifest, or KML adds a warning while other courses continue.
`export-map` is also strictly offline and reads only the normalized JSON. It
atomically writes deterministic route/POI GeoJSON and a data-quality report.

Legacy flags: `--force` to refetch already-downloaded files, `--concurrency`,
`--delay` (rate limit, seconds), `--timeout`, `--log-level`.

## Raw layout

```text
datasets/shikoku_nature_trail/raw/
├── current.json
└── snapshots/<content-sha256>/
    ├── indexes/{tokushima,kagawa,ehime,kochi}.html
    ├── courses/<post_id>/
    │   ├── page.html
    │   ├── metadata.json
    │   ├── assets.json
    │   ├── images/001.jpg ...
    │   └── map/
    │       ├── map.kml
    │       └── metadata.json
    ├── course-index.json
    ├── manifest.json
    ├── crawl-state.json
    └── snapshot.json
```

Course directories use the site's own `post_id` (`/archives/119` -> `119`).

## Normalized schema (version 1)

`datasets/shikoku_nature_trail/output/shikoku-nature-trail.json` has stable top-level keys:

```text
schema_version: 1
source: official site URL
summary: course/photo-point/tourism-spot/placemark/warning counts
warnings: ordered per-course warning strings
courses: source index fields plus the normalized fields below
```

Each course preserves all `course-index.json` fields and adds `title`,
`description`, nullable `photo_point`, ordered `tourism_spots`,
`google_my_maps`, `images`, and `kml`. A tourism spot contains nullable
`number`, `title`, `description`, and `image`; image objects retain
`source_url` and resolve `local_path` relative to the raw archive when listed
in `assets.json`. `kml` contains document `name`/`description` and ordered
Placemarks with nullable `name`/`description`/`geometry`. Geometries use
GeoJSON-compatible `Point`, `LineString`, or `GeometryCollection` structures,
with `[longitude, latitude, optional altitude]` coordinates.

Missing scalar values are `null`; missing collections are empty arrays. HTML
layout whitespace and plain KML description markup are conservatively
collapsed. No generated timestamp is included, so identical archives produce
byte-identical JSON.

Full archive result (2026-08-19): 123 courses, 123 photo points, 686 tourism
spots, 1,713 Placemarks, and 0 warnings. All 672 tourism spot images resolved
to archived local paths. The reproducible ~9.6 MB output is gitignored.

The complete 2026-11-09 source refresh acquired 123 course detail pages,
123 valid route KMLs and 1,040 actual content images, with no pending images,
checksum failures or source-validation warnings. This is archive accounting;
the historical normalization/export counts above are not a new build claim.

## Map export (Phase 3)

Each course has stable route ID `SNT_<source_post_id>` and one feature per KML
LineString. Point IDs are `SNT_<source_post_id>_P####` in source order. Tourism
content IDs are `SNT_<source_post_id>_S###`; a POI receives one only when NFKC,
whitespace, bracket, and conservative punctuation normalization produces a
unique one-to-one name match inside that course. Fuzzy and duplicate matches
are intentionally left unresolved in `shikoku-nature-trail-report.json`.

The build creates `shikoku_nature_trail` routes at z0-14 and `shikoku_nature_trail_pois`
points at z10-14 in `datasets/shikoku_nature_trail/output/shikoku-nature-trail.pmtiles`, with official
`shikoku-nature-trail.com` attribution. Real-data result: 123 route IDs, 145
segments, 65,753 route coordinates, 1,568 POIs, and 394/686 linked tourism
spots. There are 292 unmatched tourism spots, 1,174 unmatched POIs, and 34
ambiguous name groups for manual resolution.

## Design notes

- **Download first, parse second** (plan §11): raw HTML is always written to
  disk before parsing, so the archive can be re-parsed offline.
- **Atomic writes** (plan §35): temp file -> fsync -> rename for all JSON and
  downloaded assets; a failed re-download never clobbers a valid previous file.
- **Refresh vs resume**: the default pipeline refreshes remote HTML/KML.
  Only the legacy individual crawler commands use resume/`--force`.
  Source completeness is determined from actual bytes, provenance and
  parser accounting, never solely from `crawl-state.json`.
- **KML validation**: HTTP 200 is not trusted; XML parsing, complete
  placemark accounting, finite Shikoku coordinates and a real route
  LineString are required before selecting an archive.
- **Rate limiting** (plan §19): default 3 concurrent requests with a 0.3s
  delay; retries on 429/5xx/timeouts with exponential backoff (plan §20).

## Tests

```bash
python3 -m unittest discover datasets/shikoku_nature_trail/tests
```

Parser fixtures in `tests/fixtures/` are trimmed from live pages
(`ehime-list.html`, `course-119.html`, `course-many-images.html`,
`course-without-map.html`).
