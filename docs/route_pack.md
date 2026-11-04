# Route Pack (phase 4)

The **route pack** is the agreed phase-4 unit of downloadable, updatable and
deletable offline data for the henro map app. It is distinct from the core app
map pack (`docs/app_map_manifest.md`, schema_version 1/2/3): a route pack
carries **route geometry + elevation profile** for one or more routes, and is
installed/versioned independently **per pack_id**.

This document is the authoritative contract for the phase-4 route-pack data
pipeline. It covers the route-pack manifest, the pack SQLite schema, the ID
tuple namespace and the generic pack builder. It does **not** define the
Android-side consumption (the Android multi-pack installer/UI is later phase-4
work and out of scope for this first builder).

## Contract decisions

- The downloadable/update/delete unit is a **route pack**, not one SQLite per
  route.
- Each pack may hold **1..many routes** and contains exactly:
  - `manifest.json`
  - `routes.pmtiles`
  - `content.sqlite`
- Each `pack_id` has an **independent installed version**; activation is
  staged, checksummed and atomically activated.
- The existing **core app map schema-v3 remains unchanged**; route packs are a
  separate, additive mechanism.

## Scope of this first builder

- The generic pack builder consumes canonical LineString GeoJSON plus an
  already-built, provider-specific PMTiles, and produces the profile
  `content.sqlite` and the pack `manifest.json`.
- **PMTiles generation remains provider-specific** (layers/POIs/licensing
  vary); the generic builder does not build the PMTiles.
- **Later phase-4 work, not part of this first builder**: catalog/discovery
  and the Android multi-pack installer/UI.

## Generic pack builder CLI

`scripts/build-route-pack.py` builds one route pack from canonical LineString
GeoJSON, an already-built provider PMTiles and a build-time elevation DB:

```bash
python3 scripts/build-route-pack.py \
  --pack-id <id> --version <v> --name <name> \
  --provider <provider> --attribution <text> --usage <usage> \
  --input <route.geojson> --routes-pmtiles <routes.pmtiles> \
  --elevation-db <elevation.sqlite> --output-dir <dir>
```

Required: `--pack-id`, `--version`, `--name`, `--provider`, `--attribution`,
`--usage`, `--input` (canonical route GeoJSON), `--routes-pmtiles`
(provider-built), `--elevation-db`, `--output-dir`.

Optional: `--base-url` (http(s) root for absolute file URLs; otherwise relative
`routes.pmtiles` / `content.sqlite`); `--minimum-app-version-code` (default `4`,
rejects `<4`); `--interval-m` (default `20`, positive finite);
`--gsi-dem-bin` (default `datasets/gsi/gsi-dem/target/release/gsi-dem`).

The builder invokes the existing GSI-DEM profile tool directly as
`<bin> profile <elevation-db> --input <input> --output <tmp> --interval-m <m>`
and strictly validates its output before writing anything.  Output is built
atomically into a new directory and refused if the directory already exists.

## Manifest (schema_version = 1)

Top-level object:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | integer | `1`. |
| `pack_id` | string | Stable identifier for the pack; independent version per pack. |
| `version` | string | Pack version; ASCII letters/digits/dot/underscore/hyphen. |
| `name` | string | Human-readable pack name. |
| `provider` | string | Data provider. |
| `attribution` | string | Required attribution text. |
| `usage` | string | Usage restriction (e.g. `personal-use`); must remain explicit. |
| `minimum_app_version_code` | integer | `>= 4`. |
| `total_size` | integer | Sum of all file `size` values (bytes). |
| `files` | array | Exactly two entries (routes + content). |

Each `files[]` item:

| Field | Type | Notes |
| --- | --- | --- |
| `role` | string | Exactly one `routes` and one `content` per pack. |
| `path` | string | `routes.pmtiles` for `routes`; `content.sqlite` for `content`. |
| `url` | string | Download URL for the file. |
| `size` | integer | Nonnegative file size in bytes. |
| `sha256` | string | Lowercase 64-char hex SHA-256. |

The manifest must contain **exactly one** `routes` file (role/path
`routes.pmtiles`) and **exactly one** `content` file (role/path
`content.sqlite`), each with its own `url`/`size`/`sha256`.

## `routes.pmtiles` source-layer contract

The route-pack `routes.pmtiles` must expose **exactly one** vector source-layer,
named **`routes`**, built only from the route LineString GeoJSON. Its line
features must preserve **`route_id`** and **`segment_id`** (so the map can join
geometry to the profile `content.sqlite`). The route-pack PMTiles is a
provider-specific artifact distinct from the core app map pack: it contains only
the `routes` layer (no POI/other layers), is built `z0-14` with no line
simplification, and carries explicit `personal-use` metadata/attribution.

For Mizutani the provider builds this artifact at
`datasets/mizutani_henro_map/output/mizutani-henro-routes.pmtiles` from
`datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson`.

## ID tuple namespace

Route-pack identifiers are a tuple namespace:

```text
(pack_id, route_id, segment_id)
```

- `pack_id` scopes all routes within the pack.
- `route_id` and `segment_id` are the in-pack identifiers.
- **PMTiles route features must preserve `route_id` and `segment_id`** so the
  map can join geometry to the profile `content.sqlite`.

## Route-pack SQLite schema (`content.sqlite`)

```sql
CREATE TABLE metadata (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE routes (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE route_segments (
  id                 TEXT PRIMARY KEY,
  route_id           TEXT NOT NULL REFERENCES routes(id),
  sequence           INTEGER NOT NULL,
  distance_m         REAL NOT NULL,
  ascent_m           REAL NOT NULL,
  descent_m          REAL NOT NULL,
  elevation_min_m    REAL,
  elevation_max_m    REAL,
  missing_distance_m REAL NOT NULL,
  payload_json       TEXT NOT NULL
);

CREATE TABLE route_profile_samples (
  segment_id  TEXT NOT NULL REFERENCES route_segments(id),
  sequence    INTEGER NOT NULL,
  distance_m  REAL NOT NULL,
  elevation_m REAL,
  latitude    REAL NOT NULL,
  longitude   REAL NOT NULL,
  layer       INTEGER,
  source_code INTEGER,
  PRIMARY KEY (segment_id, sequence)
);
```

Primary keys are as stated above; `route_segments.route_id` and
`route_profile_samples.segment_id` are foreign keys. `elevation_min_m` /
`elevation_max_m` and `elevation_m` are nullable. `metadata.value`, `routes.name`,
`routes.payload_json` and `route_segments.payload_json` are NOT NULL.
`layer`/`source_code` are nullable INTEGER sample fields: for a real DEM sample
they hold the DEM layer (`5` = DEM5, `10` = DEM10) and per-pixel source code
(`1` = DEM10B, `2` = DEM5C, `3` = DEM5B, `4` = DEM5A); for a nodata sample all of
`elevation_m`/`layer`/`source_code` are NULL together.

## Data pipeline

- Profiles use the **existing generic GSI-DEM profile** at **20 m** nearest-cell
  sampling with **DEM5 -> DEM10 fallback** (no resample; DEM5 value wins, DEM10
  fills nodata).
- The DEM database is **build-time only**; it is not shipped to the device.

## First consumer: Mizutani

- Mizutani is the first consumer of the generic pack builder.
- Because the source has no reliable conceptual grouping, each `feature_id` is
  initially **both** `route_id` and `segment_id`; **do not guess grouping**.
- The **personal-use** usage restriction must remain explicit in the pack
  manifest.
- Nature Trail is expected to validate **multi-segment reuse** later.

## First-build validation (2026-09-03)

- `mizutani-henro` version `2026-09-03` (pack_id `mizutani-henro`, usage
  `personal-use`).
- 127 routes/segments, 75,983 samples.
- `routes.pmtiles` 867,177 bytes; `content.sqlite` 6,979,584 bytes; total
  manifest payload 7,846,761 bytes.
- Integrity / FK / PMTiles / hash checks all pass.
- 2,526 nodata samples; elevation range -1..929 m after the legacy `-9999`
  sentinel compatibility fix.
- Personal-use output; not for distribution.