# Shikoku Nature Trail Crawler (Phase 1)

Reproducible crawler for the Shikoku Nature Trail official site
(https://shikoku-nature-trail.com/). Phase 1 is a **raw archive only** — it
saves the four prefecture course lists, every course detail HTML page, its
content images, and the embedded Google My Maps KML, together with source
metadata and SHA-256 checksums. No normalization, GIS processing, or App DB
import yet (that's phase 2).

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
```

`crawl-all` runs index -> details -> assets -> kml -> report in sequence.

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
