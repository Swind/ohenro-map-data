# App Map Pack Manifest

The data repo exposes a single deterministic JSON manifest describing the
offline map-pack files an Android app must install for the Shikoku henro map.
This is the phase-2/phase-2b (manifest/generator) contract in the data pipeline
only; it does not define or describe the Android-side consumption.

Schema version 2 adds the phase-2b generated assets (sprites, glyphs, licenses)
as repeated roles alongside the seven unique core roles, and raises the minimum
Android app version code to 2.

## Generator

```bash
python3 scripts/build-app-map-manifest.py --version dev-20260824-v2
```

Outputs `output/app-map-manifest.json` (default). It is stdlib-only, streams
SHA-256 (never loads the ~117MB basemap into RAM), writes the manifest
atomically (temp file in the same directory, then `os.replace`), and is fully
deterministic (sorted keys, no timestamps). It reads the same required glyph
range inventory as the asset builder
(`scripts/app-map-assets/noto-sans-cjk-jp-required-ranges.txt`).

### Options

| Option | Default | Notes |
| --- | --- | --- |
| `--version` | *(required)* | Schema `version`; ASCII letters/digits/dot/underscore/hyphen only. |
| `--minimum-app-version-code` | `2` | Integer `>= 2` (phase-2b requirement). |
| `--output` | `output/app-map-manifest.json` | Manifest path (repo-root relative). |
| `--base-url` | *(none)* | `http`/`https` URL; turns relative `url`s into absolute ones. |

The manifest is normally generated after
`scripts/build-app-map-assets.py` has produced `output/app-map-assets/`; the
builder fails if any enumerated asset file is missing.

### Relative dev server (no `--base-url`)

Serve the data repo root with any HTTP server, e.g.:

```bash
python3 -m http.server 8000 --directory .   # from the data repo root
# manifest at http://localhost:8000/output/app-map-manifest.json
```

Without `--base-url`, each file `url` is relative to the manifest location:

- output pack files use their filename (e.g. `shikoku-basemap.pmtiles`);
- generated assets resolve into `app-map-assets/...`
  (e.g. `app-map-assets/sprites/light.png`);
- the style file resolves to `../map-preview/src/style/style.json`.

### Absolute hosting (with `--base-url`)

Pass the URL of the directory where the manifest will be served (i.e. the
`output/` directory), so relative paths resolve correctly:

```bash
python3 scripts/build-app-map-manifest.py \
  --version dev-20260824-v2 \
  --base-url https://example.com/mapdata/output/
```

Each `url` then becomes an absolute `http(s)` URL rooted at that base.

## Schema

Top-level object:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | integer | `2`. |
| `version` | string | Restricted to ASCII letters/digits/dot/underscore/hyphen. |
| `minimum_app_version_code` | integer | `>= 2`. |
| `total_size` | integer | Sum of all file `size` values (bytes). |
| `files` | array | One entry per installable file. |

Each `files[]` item:

| Field | Type | Notes |
| --- | --- | --- |
| `path` | string | Install-relative path (matches source filename). |
| `url` | string | Relative to the manifest, or absolute when `--base-url` given. |
| `size` | integer | Nonnegative file size in bytes. |
| `sha256` | string | Lowercase 64-char hex SHA-256. |
| `role` | string | Semantic role of the file (see below). |

## Roles

### Seven unique core roles

| Role | Install path | Source |
| --- | --- | --- |
| `style` | `style.json` | `map-preview/src/style/style.json` |
| `basemap` | `shikoku-basemap.pmtiles` | `output/shikoku-basemap.pmtiles` |
| `mizutani` | `shikoku-mizutani-henro.pmtiles` | `output/shikoku-mizutani-henro.pmtiles` |
| `nature_trail` | `shikoku-nature-trail.pmtiles` | `output/shikoku-nature-trail.pmtiles` |
| `henroyado` | `shikoku-henroyado-lodging.pmtiles` | `output/shikoku-henroyado-lodging.pmtiles` |
| `min88` | `shikoku-min88-lodging.pmtiles` | `output/shikoku-min88-lodging.pmtiles` |
| `temples` | `temples.geojson` | `output/temples.geojson` |

### Repeated generated roles (phase 2b)

These are enumerated deterministically after the core roles.  Their install
paths live under `sprites/`, `fonts/` and `licenses/` (the `app-map-assets`
prefix is *not* part of the install path), and their `url`s are manifest-relative
into `output/app-map-assets/...`.

| Role | Count | Install paths | Source (under `output/app-map-assets/`) |
| --- | --- | --- | --- |
| `sprite` | 4 | `sprites/light.json`, `sprites/light.png`, `sprites/light@2x.json`, `sprites/light@2x.png` | `sprites/...` |
| `glyph` | 103 | `fonts/Noto Sans CJK JP Regular/<range>.pbf` (numeric order) | `fonts/Noto Sans CJK JP Regular/<range>.pbf` |
| `license` | 2 | `licenses/Noto-Sans-CJK-OFL.txt`, `licenses/Tangram-Icons-MIT.txt` | `licenses/...` |

The glyph install paths mirror the MapLibre glyph template
`fonts/{fontstack}/{range}.pbf` (`{fontstack}` percent-decodes to the font stack
name).  The glyph ranges match
`scripts/app-map-assets/noto-sans-cjk-jp-required-ranges.txt`.

## Style font stack

Since phase 2b every generated layer layout's `text-font` is normalized to the
single offline CJK stack `Noto Sans CJK JP Regular` (see
`map-preview/scripts/generate-style.mjs`). The source `style.json` keeps the
remote sprite/glyph URL strings; the Android app replaces them for v2 packs, and
the web preview is expected to point at a local asset base that serves this
stack (the remote Protomaps CDN does not contain it). See
`docs/app_map_assets.md` for the assets.

## Tests

```bash
python3 -m unittest discover scripts/tests
node scripts/tests/test_style_font_normalization.mjs
```