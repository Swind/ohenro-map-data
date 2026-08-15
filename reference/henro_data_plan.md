Shikoku Henro Temple Data Architecture

1. Goal

Build a clean, maintainable data pipeline for a Shikoku Henro map application using temple metadata extracted from:

https://www.seichijunrei-shikokuhenro.jp/

OpenStreetMap (OSM)

Other optional future sources such as Wikidata or manually curated data

The application should support:

Offline map rendering

Temple markers

Temple detail pages

Searching/filtering temples

Future integration of Henro-specific POIs such as benches, cycle stands, toilets, etc.

Stable IDs that do not depend on any external provider

The recommended architecture is:

Raw source data
    ↓
Normalizer
    ↓
Canonical domain model
    ├── SQLite / Room     → detailed offline metadata
    └── GeoJSON           → Planetiler → PMTiles

Do not use the source website's original JSON schema directly inside the Android application.

2. Source Data Example

The Seichijunrei website embeds data directly inside page JavaScript, for example:

var spots = [
  {
    "Spot": {
      "id": "107",
      "spot_category_id": "3",
      "name_ja": "大窪寺",
      "name_en": "Okubo-ji",
      "post_code": "769-2306",
      "pref": "香川県",
      "address_ja": "さぬき市多和兼割96",
      "latitude": "34.191403",
      "longitude": "134.206799",
      "number": "88"
    },
    "SpotCategory": {
      "id": "3",
      "name_ja": "札所情報"
    },
    "SpotContent": {
      "short_name_ja": "大窪寺",
      "short_name_en": "Okubo-ji",
      "short_name_kana_ja": "おおくぼじ",
      "long_name_ja": "第八十八番　医王山　大窪寺",
      "honzon_ja": "薬師如来",
      "syuha_ja": "真言宗単立",
      "kaiki_ja": "行基菩薩、弘法大師",
      "souken_ja": "養老元年（717）",
      "tel_ja": "0879-56-2278",
      "syukubou_ja": "なし"
    }
  }
];

The website schema should be treated as an external source schema, not as the application's domain schema.

3. Canonical ID Strategy

Do not use the source site's Spot.id as the application's primary ID.

For example:

source Spot.id = 107

is an implementation detail of seichijunrei-shikokuhenro.jp.

Use an application-owned canonical identifier instead:

temple-001
temple-002
...
temple-088

For temple 88:

temple-088

Recommended model:

{
  "id": "temple-088",
  "number": 88,
  "sources": {
    "seichijunrei": {
      "spot_id": "107"
    },
    "osm": {
      "type": "way",
      "id": "416330224"
    }
  }
}

This allows multiple external objects to be associated with a single application entity:

                 temple-088
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
Seichijunrei        OSM         Wikidata
   107         way/416330224      Q...

The canonical ID must remain stable even if an external source changes its IDs.

4. Canonical Temple Domain Model

Normalize external data into an application-owned structure.

Example:

{
  "id": "temple-088",
  "number": 88,

  "name": {
    "ja": "大窪寺",
    "en": "Okubo-ji",
    "kana": "おおくぼじ"
  },

  "full_name": {
    "ja": "第八十八番　医王山　大窪寺",
    "en": "No. 88 Iozan Okubo-ji",
    "kana": "いおうざん　おおくぼじ"
  },

  "location": {
    "latitude": 34.191403,
    "longitude": 134.206799,
    "source": "seichijunrei"
  },

  "address": {
    "postal_code": "769-2306",
    "prefecture": "香川県",
    "ja": "さぬき市多和兼割96",
    "en": "96, Kanewari, Tawa, Sanuki-shi"
  },

  "phone": "0879-56-2278",

  "temple": {
    "principal_deity": {
      "ja": "薬師如来",
      "en": "Bhaiṣajyaguru"
    },
    "sect": {
      "ja": "真言宗単立",
      "en": "Shingon sect"
    },
    "founder": {
      "ja": "行基菩薩、弘法大師",
      "en": "Gyoki Bosatsu, Kobo Daishi"
    },
    "founded": {
      "ja": "養老元年（717）",
      "en": "Yoro year 1 (717)"
    },
    "has_lodging": false
  },

  "history": {
    "ja": "...",
    "en": "..."
  },

  "image": {
    "eyecatch": "/uploads/2016/02/05/201602050239423dokgx5y0l.jpg"
  },

  "sources": {
    "seichijunrei": {
      "spot_id": "107",
      "content_id": "102",
      "modified_at": "2016-06-07T10:29:30"
    }
  }
}

This canonical model should be the source of truth for generated outputs.

5. Separate Map Data From Detail Data

Do not store full temple metadata inside vector tiles.

Vector tiles should only contain data needed for map rendering and map interaction.

Recommended map properties:

{
  "id": "temple-088",
  "type": "temple",
  "number": 88,
  "name_ja": "大窪寺",
  "name_en": "Okubo-ji",
  "name_kana": "おおくぼじ"
}

Do not include large text fields such as:

history
rekishiyurai_ja
rekishiyurai_en

in PMTiles.

Reasons:

increases tile size

duplicates data across tiles

increases download/storage overhead

makes metadata updates harder

Instead, use the feature id to load the full record from SQLite.

6. GeoJSON Output

Generate GeoJSON from normalized temple data before feeding it into Planetiler.

Example:

{
  "type": "Feature",
  "id": "temple-088",
  "geometry": {
    "type": "Point",
    "coordinates": [134.206799, 34.191403]
  },
  "properties": {
    "id": "temple-088",
    "type": "temple",
    "number": 88,
    "name_ja": "大窪寺",
    "name_en": "Okubo-ji",
    "name_kana": "おおくぼじ"
  }
}

Important:

GeoJSON coordinate order = [longitude, latitude]

Correct:

[134.206799, 34.191403]

Incorrect:

[34.191403, 134.206799]

7. SQLite / Room Storage

Use SQLite as the offline metadata store in the Android application.

Suggested database:

henro.db

Example schema:

CREATE TABLE temples (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL UNIQUE,

    name_ja TEXT NOT NULL,
    name_en TEXT,
    name_kana TEXT,

    full_name_ja TEXT,
    full_name_en TEXT,
    full_name_kana TEXT,

    latitude REAL NOT NULL,
    longitude REAL NOT NULL,

    postal_code TEXT,
    prefecture TEXT,
    address_ja TEXT,
    address_en TEXT,

    phone TEXT,

    honzon_ja TEXT,
    honzon_en TEXT,

    sect_ja TEXT,
    sect_en TEXT,

    founder_ja TEXT,
    founder_en TEXT,

    founded_ja TEXT,
    founded_en TEXT,

    has_lodging INTEGER,

    history_ja TEXT,
    history_en TEXT,

    image_url TEXT,

    source_seichijunrei_id TEXT,
    source_modified_at TEXT
);

The Android app should normally access this using Room.

Example lookup:

SELECT *
FROM temples
WHERE id = 'temple-088';

or:

SELECT *
FROM temples
WHERE number = 88;

8. PMTiles Responsibilities

Recommended files:

assets/
├── shikoku.pmtiles
└── henro.db

PMTiles should contain map-oriented data such as:

basemap
henro_routes
henro_temples
henro_benches
henro_cycle_stands
other_henro_pois

SQLite should contain detailed application metadata.

Runtime flow:

PMTiles
   │
   │ feature id = temple-088
   ▼
Map marker
   │
   │ user taps marker
   ▼
Room / SQLite
   │
   └── temple-088
       ├── history
       ├── phone
       ├── sect
       ├── principal deity
       ├── address
       ├── lodging
       └── image

9. Planetiler Layer Design

Create a dedicated layer:

henro_temples

Recommended properties:

id
number
name_ja
name_en
name_kana

Possible zoom behavior:

z6+
    show temple number

z9+
    show number + short name

z13+
    show detailed POI styling

Example visual label:

88 大窪寺

Avoid using the full long name on the map:

第八十八番 医王山 大窪寺

because it is too long for normal map labeling.

10. Location Semantics

Do not assume one coordinate can represent every location-related use case.

A temple may have multiple useful positions:

official marker position

OSM building centroid

temple entrance

parking entrance

navigation destination

Recommended model:

{
  "locations": {
    "canonical": {
      "lat": 34.191403,
      "lon": 134.206799,
      "source": "seichijunrei"
    },
    "osm": {
      "lat": 34.191,
      "lon": 134.207,
      "osm_type": "way",
      "osm_id": "416330224"
    },
    "entrance": null
  }
}

Possible future behavior:

Map marker      → canonical temple position
Navigation      → entrance position
Building render → OSM geometry

This avoids forcing a single coordinate to satisfy different use cases.

11. Source Data Retention

Always keep raw data separately from normalized/generated data.

Recommended directory structure:

data/
├── raw/
│   └── seichijunrei/
│       ├── spots.json
│       ├── benches.json
│       └── source-metadata.json
│
├── normalized/
│   ├── temples.json
│   ├── benches.json
│   └── cycle_stands.json
│
└── generated/
    ├── temples.geojson
    ├── benches.geojson
    └── henro.db

Do not modify files under raw/ after extraction.

All transformation should happen from raw → normalized → generated.

12. Recommended Extraction Pipeline

Suggested flow:

seichijunrei HTML
        │
        ▼
Extractor
        │
        ├── parse var spots = [...]
        ├── parse var benches = [...]
        └── parse other discovered POI arrays
        │
        ▼
raw JSON
        │
        ▼
Normalizer
        │
        ├── validate coordinates
        ├── convert strings to correct types
        ├── trim whitespace
        ├── convert "なし" to boolean/null where appropriate
        ├── build canonical IDs
        └── preserve source IDs
        │
        ▼
Canonical domain JSON
        │
        ├─────────────┐
        ▼             ▼
GeoJSON            SQLite
        │
        ▼
Planetiler
        │
        ▼
PMTiles

13. Normalization Rules

The normalizer should explicitly perform the following transformations.

Numeric fields

Convert:

"number": "88"

to:

"number": 88

Convert:

"latitude": "34.191403"
"longitude": "134.206799"

to numeric values.

Trim source whitespace

Source data sometimes contains trailing spaces:

"Shingon sect "

Normalize to:

"Shingon sect"

Empty strings

Convert empty strings to null where semantically appropriate.

Example:

"parking_ja": ""

becomes:

"parking": null

Booleans

Example:

syukubou_ja = "なし"

can become:

"has_lodging": false

Keep the original source text as an optional raw/source field if needed.

Preserve original source values

Do not discard source IDs or timestamps.

Keep at minimum:

source provider
source Spot.id
source SpotContent.id
source modified timestamp

14. Additional POI Categories

The same architecture should support non-temple POIs.

Known example:

SpotCategory.id = 4
SpotCategory.name_ja = ベンチ情報

Example normalized model:

{
  "id": "bench-seichijunrei-44",
  "type": "bench",
  "name": "文化の森総合公園内",
  "location": {
    "latitude": 34.039817,
    "longitude": 134.526707
  },
  "count": 3,
  "sources": {
    "seichijunrei": {
      "spot_id": "44"
    }
  }
}

Keep POI types separate from temple entities.

Possible layers:

henro_temples
henro_benches
henro_cycle_stands
henro_toilets
henro_facilities

Do not assume that all source POIs are current. Some source records were last modified around 2016, so transient infrastructure such as benches or cycle stands should be treated as supplemental data unless independently verified.

15. Recommended Responsibilities by Data Source

Use each source for what it is good at.

Seichijunrei website

Best suited for:

temple number
temple identity
official-style marker coordinate
temple names
temple history
sect
principal deity
founder
founded year
phone
lodging
Henro-specific POIs

OpenStreetMap

Best suited for:

roads
footpaths
buildings
landuse
entrances
public amenities
route relations
transport topology

Do not rely on OSM alone to decide which OSM object is the canonical representation of temple number 1–88.

Instead, map OSM objects to the application's canonical temple IDs.

16. Android Architecture Recommendation

Suggested responsibilities:

Domain
└── Temple

Data
├── TempleRepository
├── RoomTempleDataSource
└── MapFeatureDataSource

Presentation
├── MapScreen
└── TempleDetailScreen

Map interaction:

MapLibre feature selected
        │
        ▼
read feature property "id"
        │
        ▼
TempleRepository.getById("temple-088")
        │
        ▼
Room
        │
        ▼
Temple detail UI

The map SDK should never need to know about source-specific fields such as:

SpotContent
rekishiyurai_ja
syuha_ja
spot_category_id

17. Implementation Tasks for AI Agent

Implement this in phases.

Phase 1 — Extract

Build an extractor for Seichijunrei HTML.

Locate JavaScript declarations such as:

var spots = [...];
var benches = [...];

Parse JSON arrays without executing arbitrary page JavaScript.

Save the raw data exactly as extracted.

Phase 2 — Normalize

Introduce application-owned models.

Create stable canonical temple IDs.

Convert data types.

Normalize empty values and whitespace.

Preserve external source metadata.

Phase 3 — Generate GeoJSON

Generate:

temples.geojson
benches.geojson

Include only map-relevant properties.

Phase 4 — Generate SQLite

Generate an offline SQLite database containing full temple metadata.

Ensure data can later be consumed through Android Room.

Phase 5 — Planetiler Integration

Create dedicated Planetiler layers:

henro_temples
henro_benches

Keep vector tile attributes minimal.

Phase 6 — Android Integration

Read PMTiles through the chosen map stack.

Display temple markers.

On marker selection, use the canonical ID to query Room.

Display the complete temple detail page from SQLite.

18. Design Constraints

The implementation should follow these constraints:

External source schemas must not leak into the Android domain layer.

External IDs must not be used as primary application IDs.

Raw source data must be retained for reproducibility.

Generated vector tiles must remain lightweight.

Full metadata must be available offline.

GeoJSON coordinates must use longitude/latitude order.

Source attribution and source IDs must be preserved.

The architecture must allow additional sources and POI categories later.

Temple coordinates and navigation coordinates must be allowed to differ.

The pipeline must be deterministic: the same raw input should produce the same normalized/generated output.

19. Target Output

A successful implementation should produce something similar to:

data/
├── raw/
│   └── seichijunrei/
│       ├── spots.json
│       └── benches.json
│
├── normalized/
│   ├── temples.json
│   └── benches.json
│
└── generated/
    ├── temples.geojson
    ├── benches.geojson
    └── henro.db

tiles/
└── henro.pmtiles

Android assets may ultimately contain:

assets/
├── shikoku.pmtiles
└── henro.db

The final principle is:

Use PMTiles for map rendering and spatial interaction, and SQLite/Room for complete application metadata. Connect both using stable application-owned canonical IDs.
