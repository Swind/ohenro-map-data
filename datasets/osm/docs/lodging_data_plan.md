Shikoku Henro Lodging Data Pipeline Plan

1. Goal

Add lodging-related POIs from OpenStreetMap into the Shikoku Henro map application without coupling detailed lodging data directly into the generic basemap.

Recommended architecture:

OSM PBF
  ↓
Lodging extractor
  ↓
Normalized GeoJSON
  ├─→ Web Preview / QA
  ├─→ PMTiles for map rendering
  └─→ SQLite / Room for detailed lodging metadata

Core principle:

GeoJSON = editable / reviewable intermediate format
PMTiles = rendering artifact
SQLite = detailed application data
OSM PBF = raw source

Do not use the basemap PMTiles as the only storage location for lodging metadata.

2. Why Lodging Should Be a Separate Henro Data Layer

The generic basemap should remain focused on:

roads
buildings
water
landuse
boundaries
generic labels
generic POIs

Lodging is application-level data because the Henro app may need to:

filter lodging by subtype;

show lodging details;

support offline search;

display pilgrim-relevant amenities;

enrich OSM data later;

update lodging independently from the basemap;

associate lodging with nearby Henro routes or temples.

Recommended production structure:

basemap.pmtiles
├─ roads
├─ buildings
├─ water
├─ landuse
└─ generic labels

henro.pmtiles
├─ henro_temples
├─ henro_routes
├─ lodging
├─ toilets
├─ convenience_stores
├─ benches
└─ other_henro_pois

Detailed lodging metadata should live in SQLite / Room.

3. Initial OSM Lodging Categories

The first version should extract at least these OSM tourism values:

tourism=hotel
tourism=hostel
tourism=guest_house
tourism=motel
tourism=camp_site
tourism=apartment
tourism=chalet

Normalize these into:

type = lodging
subtype = hotel | hostel | guest_house | motel | camp_site | apartment | chalet

Do not expose raw OSM taxonomy directly to UI code.

Example normalized object:

{
  "id": "lodging-osm-node-123456",
  "type": "lodging",
  "subtype": "hostel",
  "name": "Example Guest House",
  "source": "osm"
}

4. Raw Source

Use the same Shikoku OSM PBF already available for the basemap pipeline.

Suggested layout:

data/
├─ raw/
│  └─ osm/
│     └─ shikoku.osm.pbf
│
├─ normalized/
│  └─ lodging.geojson
│
├─ generated/
│  ├─ henro.pmtiles
│  └─ lodging.sqlite
│
└─ reports/
   └─ lodging-extraction-report.json

Do not modify the original PBF.

5. Extractor Requirements

The extractor must support OSM:

node
way
relation

Lodging may be represented by any of these.

The extractor should:

identify eligible lodging objects by OSM tags;

collect useful metadata;

calculate a representative map point;

generate a canonical application ID;

keep original OSM identity and tags;

write normalized GeoJSON.

6. Representative Point Rules

For map display, normalize lodging geometry to a Point.

Node

Use the node coordinates directly.

OSM node
  ↓
Point

Way

For polygon/building ways, generate a representative point.

Prefer:

point-on-surface

over a naive centroid.

Reason: a polygon centroid can fall outside irregular geometry.

Use a geometry function equivalent to:

ST_PointOnSurface

or a robust point-on-surface algorithm.

Relation

For polygon/multipolygon relations:

relation geometry
  ↓
point-on-surface

Preserve the source type.

Example:

{
  "source": {
    "osm_type": "way",
    "osm_id": 123456789
  }
}

7. Canonical IDs

Do not use raw OSM IDs as the primary application identity.

Use:

lodging-osm-node-123456
lodging-osm-way-123456
lodging-osm-relation-123456

This prevents collisions between OSM object types.

Example:

{
  "id": "lodging-osm-way-123456",
  "source": {
    "provider": "osm",
    "osm_type": "way",
    "osm_id": 123456
  }
}

Later, if multiple sources are merged, the application can introduce stronger internal canonical IDs while preserving source identities.

8. OSM Tags to Normalize

At minimum, attempt to normalize:

tourism
name
name:ja
name:en
addr:*
phone
contact:phone
website
contact:website
email
contact:email
rooms
beds
stars
internet_access
wifi
washing_machine
dryer
wheelchair
opening_hours
check_date

Additional useful tags may include:

breakfast
restaurant
air_conditioning
smoking
pets
payment:*
reservation

Do not require every field to exist. OSM data is sparse by nature.

9. Raw OSM Tags Must Be Preserved

In addition to normalized columns, preserve the full original OSM tags.

Recommended model:

normalized fields
+
raw_tags JSON

Example:

{
  "subtype": "hostel",
  "beds": 18,
  "rooms": 6,
  "washing_machine": true,
  "dryer": true,
  "raw_tags": {
    "tourism": "hostel",
    "name": "Example Hostel",
    "beds": "18",
    "rooms": "6",
    "washing_machine": "yes",
    "dryer": "yes",
    "internet_access": "wlan"
  }
}

Reason: future app features may need OSM tags that were not normalized initially.

Keeping raw tags avoids having to re-run the full extraction just to recover a forgotten field.

10. Normalized GeoJSON Format

Example:

{
  "type": "Feature",
  "id": "lodging-osm-way-123456",
  "geometry": {
    "type": "Point",
    "coordinates": [
      134.123456,
      33.987654
    ]
  },
  "properties": {
    "id": "lodging-osm-way-123456",
    "type": "lodging",
    "subtype": "hostel",
    "name": "Example Guest House",
    "name_ja": "Example Guest House",
    "name_en": "Example Guest House",
    "phone": "+81...",
    "website": "https://example.com",
    "rooms": 6,
    "beds": 18,
    "stars": null,
    "internet_access": "wlan",
    "washing_machine": "yes",
    "dryer": "yes",
    "wheelchair": "limited",
    "source": "osm",
    "osm_type": "way",
    "osm_id": 123456,
    "raw_tags": {
      "tourism": "hostel"
    }
  }
}

Remember:

GeoJSON coordinates = [longitude, latitude]

11. Boolean and Enum Normalization

OSM values can be inconsistent.

Normalize common values where useful:

yes → true
no → false

But do not destroy unknown states.

Prefer nullable enums when a tag may have values such as:

yes
no
limited
customers
private
unknown

Example:

wheelchair = yes | no | limited | null

Do not force all such tags into booleans.

12. SQLite / Room Model

SQLite should store detailed lodging information.

Suggested table:

CREATE TABLE lodging (
    id TEXT PRIMARY KEY,

    subtype TEXT NOT NULL,

    name TEXT,
    name_ja TEXT,
    name_en TEXT,

    latitude REAL NOT NULL,
    longitude REAL NOT NULL,

    address TEXT,
    phone TEXT,
    website TEXT,
    email TEXT,

    rooms INTEGER,
    beds INTEGER,
    stars INTEGER,

    internet_access TEXT,
    washing_machine TEXT,
    dryer TEXT,
    wheelchair TEXT,

    opening_hours TEXT,

    source TEXT NOT NULL,
    osm_type TEXT,
    osm_id INTEGER,

    raw_osm_tags_json TEXT
);

Adjust exact types based on the Android Room implementation.

13. Recommended Future Domain Fields

The app may later enrich lodging records with Henro-specific attributes not present in OSM.

Examples:

pilgrim_friendly
laundry_available
dryer_available
breakfast_available
dinner_available
early_checkout
luggage_storage
near_henro_route
distance_to_henro_route
nearest_temple_id
distance_to_nearest_temple
verified_at
data_quality

Do not mix these into the raw OSM extractor. They belong in a later enrichment phase.

14. PMTiles Lodging Layer

The production PMTiles layer should remain small.

Suggested layer:

lodging

Recommended properties:

id
subtype
name
name_ja
name_en

Optional:

washing_machine
internet_access

Only include extra fields if they directly affect map rendering or filtering.

Do not include large metadata such as:

raw_tags
phone
website
address
description
all amenities

inside vector tiles.

15. Map Interaction

Expected application interaction:

MapLibre feature
    ↓
id = lodging-osm-way-123456
    ↓
SQLite / Room query
    ↓
lodging detail screen

The PMTiles feature and SQLite row must use the same canonical ID.

16. Web Preview / QA

Before generating PMTiles, load:

lodging.geojson

into the existing Web Map Preview.

Add a temporary lodging layer.

The QA viewer should help validate:

point locations;

missing names;

subtype classification;

duplicate objects;

strange point-on-surface results;

malformed addresses;

OSM tag completeness;

geographic coverage.

Suggested symbol differentiation:

hotel
hostel
guest_house
camp_site

Use visually distinct temporary styles during QA. Production icon design is not required yet.

17. QA Reports

Generate a report with at least:

total lodging count
count by subtype
node count
way count
relation count
missing-name count
missing-coordinate count
missing-phone count
missing-website count
records with laundry tags
records with internet tags

Example:

{
  "total": 1420,
  "by_subtype": {
    "hotel": 500,
    "hostel": 90,
    "guest_house": 510,
    "camp_site": 220
  }
}

This helps detect extractor bugs and data gaps.

18. Duplicate Handling

OSM may contain overlapping lodging objects.

Example:

node with tourism=hotel
inside
building way with tourism=hotel

Do not silently deduplicate initially.

Instead:

preserve both objects;

generate a duplicate-candidate report;

apply heuristics later.

Potential duplicate signals:

same normalized name
very close coordinates
same phone
same website
node located inside lodging polygon

Future deduplication should produce a canonical lodging entity while preserving source identities.

19. Address Handling

OSM addresses may be stored as:

addr:postcode
addr:prefecture
addr:city
addr:suburb
addr:neighbourhood
addr:street
addr:housenumber
addr:full

The extractor should preserve individual address components where available.

SQLite may store either:

structured address fields

or:

normalized display address
+
raw address tags

Prefer not to discard structured data.

20. Contact Normalization

OSM may use both:

phone
contact:phone

website
contact:website

email
contact:email

Normalization precedence should be deterministic.

Suggested:

phone:
  contact:phone
  fallback phone

website:
  contact:website
  fallback website

email:
  contact:email
  fallback email

Preserve originals in raw tags.

21. Data Pipeline

Recommended pipeline:

shikoku.osm.pbf
       │
       ▼
OSM lodging extractor
       │
       ▼
normalized records
       │
       ▼
lodging.geojson
       │
       ├──────────────► Web Preview / QA
       │
       ├──────────────► SQLite / Room seed DB
       │
       ▼
Planetiler
       │
       ▼
henro.pmtiles

22. Separation from Basemap Build

Do not make lodging extraction dependent on rebuilding the basemap.

Prefer independent build steps:

basemap pipeline

and:

Henro POI pipeline

Example:

make basemap
make lodging
make henro-tiles
make app-data

This allows lodging updates without rebuilding the full basemap.

23. Suggested Build Commands

The exact tool implementation is flexible, but expose commands with clear responsibilities.

Examples:

./gradlew extractLodging

or:

make extract-lodging

or:

cargo run --bin lodging-extractor

Expected outputs:

normalized/lodging.geojson
generated/lodging.sqlite
reports/lodging-extraction-report.json

Use the toolchain that best matches the existing repository.

24. Error Handling

The extractor should not fail the whole build because one OSM object contains malformed optional metadata.

Hard failures:

invalid PBF
unreadable geometry
missing required source data
output write failure

Soft warnings:

missing name
invalid phone
invalid website
unknown tourism subtype
malformed optional address

Soft problems should be reported in QA output.

25. Source Metadata

Every lodging record must retain:

provider = osm
osm_type
osm_id

Recommended additional metadata where available:

osm_version
osm_timestamp
changeset

Do not depend on optional metadata for rendering.

26. Update Strategy

Future update flow:

download newer Shikoku PBF
       ↓
run lodging extractor
       ↓
compare normalized GeoJSON
       ↓
QA
       ↓
regenerate SQLite
       ↓
regenerate henro.pmtiles

Because basemap and Henro data are separate, lodging can be updated independently.

27. Production Architecture

                     Shikoku OSM PBF
                            │
                 ┌──────────┴──────────┐
                 │                     │
                 ▼                     ▼
          Basemap Profile       Henro POI Extractor
                 │                     │
                 ▼                     ▼
        basemap.pmtiles        lodging.geojson
                                      │
                           ┌──────────┴──────────┐
                           ▼                     ▼
                     henro.pmtiles          SQLite
                           │                     │
                           └──────────┬──────────┘
                                      ▼
                                Android App

28. Implementation Phases

Phase 1 — Extraction

Implement OSM lodging extraction from the existing Shikoku PBF.

Support:

node
way
relation

Output:

lodging.geojson

Phase 2 — Web QA

Add the GeoJSON to the existing Web Map Preview.

Verify:

locations
subtypes
names
duplicates
coverage

Generate QA statistics.

Phase 3 — SQLite

Create the lodging domain schema.

Import normalized GeoJSON or normalized records into SQLite.

Ensure canonical IDs match map features.

Phase 4 — PMTiles

Create a lodging vector tile layer.

Only include map-visible fields.

Add lodging styling to the shared MapLibre style.

Phase 5 — Android Integration

Implement:

tap lodging feature
      ↓
read canonical ID
      ↓
Room lookup
      ↓
lodging detail screen

Verify offline behavior.

Phase 6 — Enrichment

Add Henro-specific values such as:

distance to route
nearest temple
pilgrim-friendly flags
manual verification

This phase should not modify raw OSM data.

29. Definition of Done

The first implementation is complete when:

lodging can be extracted from the existing Shikoku OSM PBF;

node, way, and relation objects are supported;

polygon lodging objects have valid representative points;

supported tourism subtypes are normalized;

full OSM tags are preserved;

lodging.geojson is generated;

the existing Web Map Preview can display lodging;

QA statistics are generated;

SQLite lodging data can be generated;

map features and SQLite rows share the same canonical ID;

a minimal lodging vector tile layer can be generated;

no basemap rebuild is required to update lodging data.

30. Key Design Rules

The AI agent must follow these rules:

Do not store all lodging details only in PMTiles.

Do not use raw OSM IDs alone as canonical application IDs.

Preserve full raw OSM tags.

Normalize useful fields without destroying unknown values.

Treat GeoJSON as an intermediate and QA format.

Treat PMTiles as a generated rendering artifact.

Treat SQLite as the detailed application data store.

Keep lodging extraction separate from the generic basemap build.

Support node, way, and relation inputs.

Use point-on-surface or equivalent for polygon representative points.

Do not silently deduplicate potentially duplicate OSM objects.

Validate data in the Web Map Preview before production tile generation.
