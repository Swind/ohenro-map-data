# App Map Pack Manifest

The data repo exposes a single deterministic JSON manifest describing the
offline map-pack files an Android app must install for the Shikoku henro map.
This is the phase-2/phase-2b (manifest/generator) contract in the data pipeline
only; it does not define or describe the Android-side consumption.

Schema version 2 adds the phase-2b generated assets (sprites, glyphs, licenses)
as repeated roles alongside the seven unique core roles, and raises the minimum
Android app version code to 2.

Schema version 3 adds an eighth core role, `content` (`content.sqlite`), and
raises the minimum Android app version code to 3.

Schema version 4 replaces the `mizutani` core role with two new
personal-use/licensing-limited assets — `henrohub`
(`shikoku-henrohub.pmtiles`) and `info_pois` (`shikoku-info-pois.pmtiles`) —
and raises the minimum Android app version code to 4. This gives nine unique
core roles total. The v4 manifest generated here is for personal/dev use only;
the Henro Hub and info-POI assets are personal-use/licensing-limited and must
not be publicly redistributed without rights clearance.

Schema version 5 removes the `min88` core role
(`shikoku-min88-lodging.pmtiles`) and raises the minimum Android app version
code to 5. Per product policy the core app map pack keeps only Henroyado
lodging; min88 stays available as a separate personal-use dataset but is not
part of the app pack. This leaves eight unique core roles. `henrohub` and
`info_pois` remain in the pack as personal-use/licensing-limited assets.

> **Legacy v4 note**: schema v4 was already committed and its contract
> (nine unique core roles **including `min88`**, `minimum_app_version_code >=
> 4`, version `dev-20260911-v4`) is a historical artifact. It is not edited or
> reinterpreted; any new pack must use schema v5. v4 manifests remain valid
> references only for apps that shipped the v4 pack.

## Generator

```bash
python3 scripts/build-app-map-manifest.py --version dev-20260911-v5
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
| `--minimum-app-version-code` | `5` | Integer `>= 5` (phase-5 requirement). |
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

- source-specific files use `../datasets/<source>/output/<filename>`;
- generated assets resolve into `app-map-assets/...`
  (e.g. `app-map-assets/sprites/light.png`);
- the style file resolves to `../map-preview/src/style/style.json`.

After the source-folder migration, serve the repository root so these relative
URLs can reach `datasets/`. Install paths and asset content hashes are unchanged.

### Absolute hosting (with `--base-url`)

Pass the URL of the directory where the manifest will be served (i.e. the
`output/` directory), so relative paths resolve correctly:

```bash
python3 scripts/build-app-map-manifest.py \
  --version dev-20260911-v5 \
  --base-url https://example.com/mapdata/output/
```

Each `url` then becomes an absolute `http(s)` URL rooted at that base.

## Schema

Top-level object:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | integer | `5`. |
| `version` | string | Restricted to ASCII letters/digits/dot/underscore/hyphen. |
| `minimum_app_version_code` | integer | `>= 5`. |
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

### Eight unique core roles

| Role | Install path | Source |
| --- | --- | --- |
| `style` | `style.json` | `map-preview/src/style/style.json` |
| `basemap` | `shikoku-basemap.pmtiles` | `datasets/osm/output/shikoku-basemap.pmtiles` |
| `henrohub` | `shikoku-henrohub.pmtiles` | `datasets/henrohub/output/shikoku-henrohub.pmtiles` |
| `info_pois` | `shikoku-info-pois.pmtiles` | `datasets/info_pois/output/shikoku-info-pois.pmtiles` |
| `nature_trail` | `shikoku-nature-trail.pmtiles` | `datasets/shikoku_nature_trail/output/shikoku-nature-trail.pmtiles` |
| `henroyado` | `shikoku-henroyado-lodging.pmtiles` | `datasets/henroyado/output/shikoku-henroyado-lodging.pmtiles` |
| `temples` | `temples.geojson` | `datasets/seichijunrei/output/temples.geojson` |
| `content` | `content.sqlite` | `datasets/seichijunrei/output/content.sqlite` |

The `henrohub` and `info_pois` assets are personal-use/licensing-limited
(Henro Hub is a commercial product asset without ODbL; info-POI data aggregates
several licensed sources). The v5 manifest is therefore for personal/dev use
and must not be publicly redistributed without rights clearance. `min88`
(`shikoku-min88-lodging.pmtiles`) is **not** a core role in schema v5: per
product policy the core app map pack keeps only Henroyado lodging. min88 data
remains available in this repo as a separate personal-use dataset
(`datasets/min88_lodging/output/`, `datasets/min88_lodging/output/shikoku-min88-lodging.pmtiles`) but is not
referenced by the app manifest.

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
remote sprite/glyph URL strings; the Android app replaces them for the offline
pack, and the web preview is expected to point at a local asset base that serves
this stack (the remote Protomaps CDN does not contain it). See
`docs/app_map_assets.md` for the assets.

## Tests

```bash
python3 -m unittest discover scripts/tests
node scripts/tests/test_style_font_normalization.mjs
```
