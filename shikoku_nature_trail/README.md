# Shikoku Nature Trail Archive Pipeline

Reproducible crawler for the Shikoku Nature Trail official site
(https://shikoku-nature-trail.com/). Phase 1 is a **raw archive only** — it
saves the four prefecture course lists, every course detail HTML page, its
content images, and the embedded Google My Maps KML, together with source
metadata and SHA-256 checksums. Phase 2 normalizes that archive into one
deterministic offline JSON dataset. Phase 3 exports routes and POIs and builds
the MapLibre-ready PMTiles archive.

Plan: `reference/shikoku-nature-trail-crawler-plan.md`

## Commands

```bash
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail crawl-index
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail crawl-details
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail download-assets
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail download-kml
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail crawl-all
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail verify
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail report
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail normalize --output output/shikoku-nature-trail.json
python3 -m shikoku_nature_trail export-map --input output/shikoku-nature-trail.json --routes output/shikoku-nature-trail.geojson --pois output/shikoku-nature-trail-pois.geojson --report output/shikoku-nature-trail-report.json
./scripts/build-shikoku-nature-trail.sh
```

`crawl-all` runs index -> details -> assets -> kml -> report in sequence.
`normalize` is strictly offline and does not construct an HTTP client. It
atomically creates the output parent directory and file. A missing
`course-index.json` is fatal; a malformed or missing per-course HTML, assets
manifest, or KML adds a warning while other courses continue.
`export-map` is also strictly offline and reads only the normalized JSON. It
atomically writes deterministic route/POI GeoJSON and a data-quality report.

Flags: `--force` to refetch already-downloaded files, `--concurrency`,
`--delay` (rate limit, seconds), `--timeout`, `--log-level`.

## Raw layout

```text
source/shikoku-nature-trail/
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
└── crawl-state.json
```

Course directories use the site's own `post_id` (`/archives/119` -> `119`).

## Normalized schema (version 1)

`output/shikoku-nature-trail.json` has stable top-level keys:

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

## Map export (Phase 3)

Each course has stable route ID `SNT_<source_post_id>` and one feature per KML
LineString. Point IDs are `SNT_<source_post_id>_P####` in source order. Tourism
content IDs are `SNT_<source_post_id>_S###`; a POI receives one only when NFKC,
whitespace, bracket, and conservative punctuation normalization produces a
unique one-to-one name match inside that course. Fuzzy and duplicate matches
are intentionally left unresolved in `shikoku-nature-trail-report.json`.

The build creates `shikoku_nature_trail` routes at z0-14 and `shikoku_nature_trail_pois`
points at z10-14 in `output/shikoku-nature-trail.pmtiles`, with official
`shikoku-nature-trail.com` attribution. Real-data result: 123 route IDs, 145
segments, 65,753 route coordinates, 1,568 POIs, and 394/686 linked tourism
spots. There are 292 unmatched tourism spots, 1,174 unmatched POIs, and 34
ambiguous name groups for manual resolution.

## Design notes

- **Download first, parse second** (plan §11): raw HTML is always written to
  disk before parsing, so the archive can be re-parsed offline.
- **Atomic writes** (plan §35): temp file -> fsync -> rename for all JSON and
  downloaded assets; a failed re-download never clobbers a valid previous file.
- **Resume / --force** (plan §21): already-downloaded files are skipped unless
  `--force`; `crawl-state.json` records per-course status but real
  completeness is judged by checking file existence + checksums.
- **KML validation** (plan §15): HTTP 200 is not trusted; the body must be
  non-empty and contain `<kml`. Invalid responses are saved as
  `map.kml.failed` and never overwrite a valid KML.
- **Rate limiting** (plan §19): default 3 concurrent requests with a 0.3s
  delay; retries on 429/5xx/timeouts with exponential backoff (plan §20).

## Tests

```bash
python3 -m unittest discover shikoku_nature_trail/tests
```

Parser fixtures in `tests/fixtures/` are trimmed from live pages
(`ehime-list.html`, `course-119.html`, `course-many-images.html`,
`course-without-map.html`).
