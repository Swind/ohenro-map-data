Henroyado Accommodation Data Extraction & Standardization Plan

1. Goal

The first phase of this project is to extract accommodation data from Henroyado and preserve it as a standardized, re-processable JSON dataset.

The goal is not to design the final application database yet.

The processing pipeline should be:

Henroyado HTML
      ↓
Raw HTML Snapshot
      ↓
DOM Extraction
      ↓
Raw Accommodation Record
      ↓
Normalizer
      ↓
Standardized JSON v1
      ↓
Future Processing
 ┌──────────────┬──────────────┬──────────────┐
 SQLite       GeoJSON       App Model      Other Sources

The main design principle is:

Preserve as much source information as possible first. Normalize conservatively. Do not discard original values.

Later phases can decide how Henroyado data should be merged with OSM, KML/GPX routes, temple data, and other accommodation sources.

2. Scope

Included in Phase 1

Download Henroyado prefecture pages.

Save raw HTML snapshots.

Detect every accommodation record present in the HTML.

Extract all available accommodation information.

Normalize clearly structured values.

Preserve original raw values alongside normalized values.

Extract coordinates from Google Maps embed URLs when available.

Export one JSON record per accommodation.

Export aggregate JSONL.

Produce parsing warnings when individual fields cannot be normalized.

Add regression fixtures/tests for representative accommodation records.

Explicitly Out of Scope

Do not implement the following in Phase 1:

SQLite application schema.

OSM accommodation merge.

Accommodation deduplication across providers.

Geocoding using Google or OSM APIs.

Route matching.

PMTiles generation.

GeoJSON generation.

App UI.

App domain model.

Booking integrations.

Data correction using external sources.

Phase 1 should treat Henroyado as an independent source.

3. Core Design Principles

3.1 Keep Raw HTML

Raw HTML must always be archived.

Example:

data/
├── raw/
│   ├── tokushima.html
│   ├── kochi.html
│   ├── ehime.html
│   └── kagawa.html
│
├── records/
│   ├── <record-id>.json
│   └── ...
│
├── henroyado.jsonl
└── manifest.json

This allows the parser to be rerun later without downloading the website again.

It is especially important because parser logic will likely improve after more accommodation variations are discovered.

3.2 Separate Extraction from Normalization

Do not combine DOM parsing and semantic normalization into a single large parser.

Use two stages:

HTML
 ↓
RawInn
 ↓
Normalizer
 ↓
HenroyadoInnV1

HTML Parser Responsibility

The HTML parser should only answer:

What data does the page contain?

It should extract strings, URLs, icons, sections, and other source values.

Normalizer Responsibility

The normalizer should answer:

Can this source value safely be represented as structured data?

Examples:

"7部屋"
    ↓
room_count = 7

"朝食 (7:00)、夕食"
    ↓
breakfast.available = true
breakfast.time = "07:00"
dinner.available = true

If normalization fails, the original value must still remain available.

3.3 Preserve Raw Values

Normalized data must not replace the original source value.

Example:

{
  "meals": {
    "breakfast": {
      "available": true,
      "time": "07:00"
    },
    "dinner": {
      "available": true,
      "time": null
    },
    "raw_text": "朝食 (7:00)、夕食"
  }
}

This makes future parser improvements possible without re-fetching the website.

3.4 Normalize Conservatively

Do not infer data that is not explicitly present.

For example:

料金

does not imply that a price exists.

If no price appears:

{
  "pricing": {
    "prices": [],
    "raw_text": null
  }
}

Similarly:

Missing values → null

Missing collections → []

Unknown values → keep raw value

Do not guess

4. Example Source Record

The example accommodation is:

旅館.大鳥居苑

The source HTML contains information such as:

accommodation name

description

pilgrimage route section

notice

room type

room count

breakfast

dinner

check-in time

check-out time

facility icons

payment methods

phone number

official website

image URLs

Google Maps embed URL

Google Maps search URL

The Google Maps iframe also contains longitude and latitude information.

Example pattern:

!2d134.4996533152179!3d34.159698980576884!

Interpretation:

!2d = longitude
!3d = latitude

Result:

{
  "latitude": 34.159698980576884,
  "longitude": 134.4996533152179
}

This means Phase 1 does not need a geocoding API when the iframe already contains usable coordinates.

5. Standardized JSON Schema v1

The first JSON format should prioritize completeness and future reprocessing over application convenience.

Example:

{
  "schema_version": 1,

  "source": {
    "provider": "henroyado",
    "source_id": null,
    "source_url": null,
    "prefecture_page": "https://henroyado.com/inns?pref=tokushima",
    "retrieved_at": "2026-08-16T00:00:00+09:00"
  },

  "identity": {
    "name": "旅館.大鳥居苑",
    "name_kana": null
  },

  "description": "大鳥居苑は一番札所霊山寺に隣接した荘厳で静寂な宿です。\nこれから始まる遍路旅の情報が得られますよ。",

  "henro": {
    "from_temple": {
      "number": 1,
      "name": "霊山寺"
    },
    "to_temple": {
      "number": 2,
      "name": "極楽寺"
    },
    "raw_route_text": "こちらは1番霊山寺から2番極楽寺へのお宿です。"
  },

  "notice": "下記の公式サイトから予約できます。",

  "rooms": {
    "types": [
      "個室"
    ],
    "room_count": 7,
    "raw_text": "個室\n7部屋"
  },

  "meals": {
    "breakfast": {
      "available": true,
      "time": "07:00"
    },
    "dinner": {
      "available": true,
      "time": null
    },
    "raw_text": "朝食 (7:00)、夕食"
  },

  "check_in": {
    "time": "15:00",
    "notes": "15:00以前対応可、要事前連絡",
    "raw_text": "15:00 15:00以前対応可、要事前連絡"
  },

  "check_out": {
    "time": "10:00",
    "notes": null,
    "raw_text": "10:00"
  },

  "facilities": [
    {
      "type": "washing_machine",
      "available": true,
      "label": "お接待",
      "source_icon": "wash_g.png"
    },
    {
      "type": "dryer",
      "available": true,
      "label": "お接待",
      "source_icon": "dry_g.png"
    },
    {
      "type": "wifi",
      "available": true,
      "label": "有り",
      "source_icon": "wifi_g.png"
    },
    {
      "type": "toilet",
      "available": true,
      "label": "ウオシュレット",
      "source_icon": "wc_g.png"
    },
    {
      "type": "bath",
      "available": true,
      "label": "浴槽",
      "source_icon": "bathtub_g.png"
    },
    {
      "type": "shuttle",
      "available": false,
      "label": null,
      "source_icon": "sougei_g.png"
    },
    {
      "type": "parking",
      "available": true,
      "label": "無料",
      "source_icon": "parking_g.png"
    },
    {
      "type": "card_payment",
      "available": true,
      "label": "可",
      "source_icon": "card_g.png"
    }
  ],

  "pricing": {
    "prices": [],
    "raw_text": null
  },

  "payment": {
    "methods": [
      "cash",
      "card"
    ],
    "cards": [
      "VISA",
      "JCB",
      "Mastercard",
      "UC",
      "AE"
    ],
    "raw_text": "現金、カード（VISA/JCB/Mastercard/UC/AE）"
  },

  "contact": {
    "phone": "088-689-3523",
    "website": "https://ootoriien.com/"
  },

  "location": {
    "prefecture": "徳島県",
    "address": null,

    "coordinates": {
      "latitude": 34.159698980576884,
      "longitude": 134.4996533152179,
      "source": "google_maps_embed"
    },

    "google_maps_search_url": "http://maps.google.com/maps?q=旅館.大鳥居苑+徳島県",
    "google_maps_embed_url": "https://www.google.com/maps/embed?pb=..."
  },

  "images": [
    {
      "url": "https://henroyado.com/storage/inns/HYT_02011.jpg",
      "original_url": "https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836"
    }
  ],

  "raw": {
    "room": "個室\n7部屋",
    "meal": "朝食 (7:00)、夕食",
    "route": "こちらは1番霊山寺から2番極楽寺へのお宿です。",
    "payment": "現金、カード（VISA/JCB/Mastercard/UC/AE）"
  },

  "_warnings": []
}

6. Source Metadata

Every record must contain source metadata.

Recommended structure:

{
  "source": {
    "provider": "henroyado",
    "source_id": null,
    "source_url": null,
    "prefecture_page": "https://henroyado.com/inns?pref=tokushima",
    "retrieved_at": "2026-08-16T00:00:00+09:00"
  }
}

Do not invent source_id.

If a stable Henroyado accommodation identifier is discovered later in:

data-* attributes

JavaScript payload

DOM IDs

API payloads

then populate it.

Image names such as:

HYT_02011.jpg
HYT_02012.png
HYT_02013.png
HYT_02014.png

suggest a possible accommodation identifier prefix such as HYT_0201, but this must not be treated as confirmed until verified against the page structure.

7. HTML Parsing Strategy

7.1 Parse Sections by Heading

Avoid relying on DOM position.

Bad:

section:nth-child(4)

Preferred:

find section
    ↓
extract heading text
    ↓
normalize whitespace
    ↓
dispatch parser by heading

Example headings:

宿詳細
料金
お問い合わせ
マップ

Possible dispatch:

宿詳細
    → parseDetails()

料金
    → parsePricing()

お問い合わせ
    → parseContact()

マップ
    → parseMap()

This is more resilient to layout changes.

8. Detail Field Parsing

Inside 宿詳細, parse entries using their labels instead of list position.

Example:

部屋
食事
チェックイン
チェックアウト

Parser strategy:

for each detail item:
    label = normalized heading
    value = remaining text

    match label:
        "部屋"             → parseRoom()
        "食事"             → parseMeals()
        "チェックイン"     → parseCheckIn()
        "チェックアウト"   → parseCheckOut()
        unknown            → preserve raw field

Unknown fields must not be discarded.

Prefer storing unknown items:

{
  "extra_details": [
    {
      "label": "未知の項目",
      "value": "..."
    }
  ]
}

9. Room Parsing

Example source:

個室
7部屋

Possible normalized output:

{
  "rooms": {
    "types": [
      "個室"
    ],
    "room_count": 7,
    "raw_text": "個室\n7部屋"
  }
}

Room parsing should be conservative.

Possible regex:

(\d+)\s*部屋

If no recognizable room count exists:

{
  "room_count": null,
  "raw_text": "..."
}

10. Meal Parsing

Example:

朝食 (7:00)、夕食

Output:

{
  "breakfast": {
    "available": true,
    "time": "07:00"
  },
  "dinner": {
    "available": true,
    "time": null
  },
  "raw_text": "朝食 (7:00)、夕食"
}

The parser should be prepared for future formats such as:

朝食 6:30〜7:30
夕食 要予約
素泊まり可

Do not force unsupported formats into an inaccurate model.

Keep the source text and emit a warning if necessary.

11. Check-In and Check-Out Parsing

Example:

15:00
15:00以前対応可、要事前連絡

Output:

{
  "time": "15:00",
  "notes": "15:00以前対応可、要事前連絡",
  "raw_text": "15:00 15:00以前対応可、要事前連絡"
}

Another example:

10:00

Output:

{
  "time": "10:00",
  "notes": null,
  "raw_text": "10:00"
}

12. Facility Parsing

Facility data is represented primarily through icon filenames and optional remarks.

This is useful because icon filenames are more stable than visual order.

Example mapping:

wash_g.png
    → washing_machine

dry_g.png
    → dryer

wifi_g.png
    → wifi

wc_g.png
    → toilet

bathtub_g.png
    → bath

sougei_g.png
    → shuttle

parking_g.png
    → parking

card_g.png
    → card_payment

Do not use positional assumptions such as:

first icon = washing machine
second icon = dryer

Instead:

basename(icon src)
    ↓
facility mapping

13. Facility Availability

Some unavailable facilities use an additional cross.png image.

Parser logic:

facility icon exists
      +
cross.png exists in same facility wrapper
      ↓
available = false

Otherwise:

available = true

Example:

{
  "type": "shuttle",
  "available": false,
  "label": null,
  "source_icon": "sougei_g.png"
}

Remarks should remain source text.

Examples:

お接待
有り
無料
可
ウオシュレット
浴槽

Do not over-normalize these remarks during Phase 1.

14. Henro Route Parsing

Example source:

こちらは1番霊山寺から2番極楽寺へのお宿です。

Possible regex:

(\d+)番(.+?)\s*から\s*(\d+)番(.+?)へのお宿

Output:

{
  "from_temple": {
    "number": 1,
    "name": "霊山寺"
  },
  "to_temple": {
    "number": 2,
    "name": "極楽寺"
  },
  "raw_route_text": "こちらは1番霊山寺から2番極楽寺へのお宿です。"
}

The parser must remain conservative because future records may contain:

番外

別格

alternative route descriptions

route segments without two temple numbers

walking-distance descriptions

When a route cannot be parsed safely:

{
  "from_temple": null,
  "to_temple": null,
  "raw_route_text": "..."
}

and add a warning.

15. Contact Parsing

Extract contact values directly from anchors.

Phone example:

<a href="tel:088-689-3523">

Normalize into:

{
  "phone": "088-689-3523"
}

Official website example:

<a href="https://ootoriien.com/">

Output:

{
  "website": "https://ootoriien.com/"
}

Keep the original URL exactly as supplied by the source.

16. Google Maps Parsing

Google Maps Search URL

The page may contain:

http://maps.google.com/maps?q=旅館.大鳥居苑+徳島県

This is useful source metadata but does not itself contain latitude/longitude.

Store it as:

{
  "google_maps_search_url": "..."
}

Google Maps Embed URL

The iframe URL may contain:

!2d134.4996533152179!3d34.159698980576884!

Coordinate extraction regex:

!2d(-?\d+(?:\.\d+)?)!3d(-?\d+(?:\.\d+)?)

Mapping:

group 1 → longitude
group 2 → latitude

Store:

{
  "coordinates": {
    "latitude": 34.159698980576884,
    "longitude": 134.4996533152179,
    "source": "google_maps_embed"
  }
}

If extraction fails:

{
  "coordinates": null
}

Do not call an external geocoder during Phase 1.

17. Image Parsing

Henroyado image URLs may contain cache/version query parameters.

Example:

https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836

Store both:

{
  "url": "https://henroyado.com/storage/inns/HYT_02011.jpg",
  "original_url": "https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836"
}

original_url preserves the exact source.

url is the canonical URL with the query removed.

Do not download image binaries during the first parser implementation unless separately required.

18. Pricing and Payment

Do not assume a 料金 section necessarily contains a room price.

Possible structure:

{
  "pricing": {
    "prices": [],
    "raw_text": null
  },

  "payment": {
    "methods": [
      "cash",
      "card"
    ],
    "cards": [
      "VISA",
      "JCB",
      "Mastercard",
      "UC",
      "AE"
    ],
    "raw_text": "現金、カード（VISA/JCB/Mastercard/UC/AE）"
  }
}

Future records may reveal additional pricing formats.

The schema can evolve after enough representative records are collected.

19. Raw Intermediate Model

Before normalization, create a RawInn model.

Example:

{
  "name": "旅館.大鳥居苑",
  "description": "大鳥居苑は...",
  "route": "こちらは1番霊山寺から2番極楽寺へのお宿です。",
  "notice": "下記の公式サイトから予約できます。",
  "room": "個室\n7部屋",
  "meal": "朝食 (7:00)、夕食",
  "check_in": "15:00 15:00以前対応可、要事前連絡",
  "check_out": "10:00",
  "payment": "現金、カード（VISA/JCB/Mastercard/UC/AE）",
  "phone": "088-689-3523",
  "website": "https://ootoriien.com/",
  "google_maps_search_url": "...",
  "google_maps_embed_url": "...",
  "images": [],
  "facilities": []
}

This model should be close to the website representation.

The standardized model should be generated from it.

20. Parser Module Design

Recommended module layout:

henroyado/
├── fetcher/
│   └── Download HTML snapshots
│
├── html_parser/
│   ├── inn
│   ├── section
│   ├── detail
│   ├── facility
│   ├── contact
│   └── map
│
├── normalize/
│   ├── text
│   ├── room
│   ├── meal
│   ├── time
│   ├── route
│   ├── payment
│   ├── facility
│   └── image
│
├── model/
│   ├── raw
│   └── v1
│
├── validation/
│
├── writer/
│   ├── json
│   └── jsonl
│
└── cli/

The actual programming language can be chosen separately.

21. Suggested Main Parser Flow

parseInn(element)
│
├── parseIdentity()
├── parseDescription()
├── parseHenroRoute()
├── parseNotice()
├── parseDetails()
│   ├── parseRoom()
│   ├── parseMeals()
│   ├── parseCheckIn()
│   └── parseCheckOut()
│
├── parseFacilities()
├── parsePricing()
├── parsePayment()
├── parseContact()
├── parseLocation()
└── parseImages()

Each parser should fail independently.

One malformed field must not discard the complete accommodation record.

22. Error Handling

Use best-effort parsing.

Bad behavior:

room count parser failed
    ↓
drop entire accommodation

Correct behavior:

{
  "rooms": {
    "types": [],
    "room_count": null,
    "raw_text": "特殊房型..."
  },

  "_warnings": [
    {
      "field": "rooms.room_count",
      "code": "UNRECOGNIZED_FORMAT",
      "raw_value": "特殊房型..."
    }
  ]
}

Only critical structural failures should reject an accommodation.

Example critical failure:

Accommodation name is missing and the element cannot be identified.

23. Warning Model

Recommended structure:

{
  "field": "henro.route",
  "code": "UNRECOGNIZED_FORMAT",
  "message": "Could not safely parse temple route.",
  "raw_value": "..."
}

Potential warning codes:

MISSING_FIELD
UNRECOGNIZED_FORMAT
INVALID_NUMBER
INVALID_TIME
UNKNOWN_FACILITY
MAP_COORDINATES_NOT_FOUND
UNKNOWN_DETAIL_FIELD

Warnings should be included in individual records and optionally summarized in the manifest.

24. Output Files

Recommended result:

data/
├── raw/
│   └── tokushima.html
│
├── records/
│   ├── record-000001.json
│   ├── record-000002.json
│   └── ...
│
├── henroyado.jsonl
└── manifest.json

Individual JSON

Useful for:

debugging

diff review

manual inspection

regression tests

JSONL

Useful for:

later transformation

data pipelines

batch imports

scripting

25. Manifest

Example:

{
  "schema_version": 1,
  "provider": "henroyado",
  "generated_at": "2026-08-16T00:00:00+09:00",

  "sources": [
    {
      "prefecture": "tokushima",
      "url": "https://henroyado.com/inns?pref=tokushima",
      "raw_file": "raw/tokushima.html"
    }
  ],

  "statistics": {
    "records": 0,
    "records_with_coordinates": 0,
    "records_with_warnings": 0,
    "parse_failures": 0
  }
}

The parser should fill these values automatically.

26. CLI Design

Keep downloading and parsing independent.

Example:

henroyado-crawler fetch \
  --pref tokushima \
  --output data/raw/tokushima.html

Parse existing HTML:

henroyado-crawler parse \
  data/raw/tokushima.html \
  --output data/records/

Aggregate:

henroyado-crawler parse-all \
  data/raw/ \
  --jsonl data/henroyado.jsonl \
  --manifest data/manifest.json

Useful additional command:

henroyado-crawler validate \
  data/henroyado.jsonl

Optional:

henroyado-crawler stats \
  data/henroyado.jsonl

27. Testing Strategy

Use HTML fixtures from real records.

Suggested fixtures:

fixtures/
├── ootoriien.html
├── kiyoumi.html
├── no_wifi.html
├── no_meal.html
├── shuttle_disabled.html
├── unusual_price.html
└── unusual_route.html

Expected JSON:

expected/
├── ootoriien.json
├── kiyoumi.json
└── ...

Test model:

HTML fixture
    ↓
Parser
    ↓
Normalized JSON
    ↓
Compare with expected JSON

This gives regression protection when parser logic changes.

28. Parser Tests

At minimum test:

Identity

name extraction

missing name behavior

Route

normal numbered temple route

whitespace differences

unsupported route format

Rooms

room type

room count

missing count

Meals

breakfast

dinner

meal time

unsupported format

Check-in / Check-out

standard time

notes

missing time

Facilities

facility icon mapping

remarks

unavailable facility via cross.png

unknown icon

Maps

coordinate extraction

missing iframe

unexpected Google Maps format

Images

original URL

canonical URL

duplicate images

Payment

cash

card

supported card brands

unknown format

29. Unknown Fields

The crawler should be forward-compatible.

If the website introduces a new detail field, do not silently discard it.

Example:

{
  "extra_details": [
    {
      "label": "送迎時間",
      "value": "要相談"
    }
  ]
}

Also emit:

{
  "field": "details",
  "code": "UNKNOWN_DETAIL_FIELD",
  "raw_value": "送迎時間"
}

This makes website changes easy to discover.

30. Deduplication Policy

Do not perform cross-provider deduplication in Phase 1.

Henroyado data should remain:

Henroyado Record

Later:

Henroyado
     \
      \
       → Canonical Accommodation
      /
     /
OSM

Possible future inputs:

Henroyado
OSM
Google/KML
Official websites
Other pilgrim datasets
User corrections

Identity resolution belongs in a separate reconciliation phase.

31. Future Data Architecture

Eventually the project may look like:

                 ┌──────────────┐
                 │  Henroyado   │
                 └──────┬───────┘
                        │
                 standardized JSON
                        │
                        ▼
                ┌───────────────┐
OSM ───────────▶│ Reconciliation│◀──────── KML / GPX
                └───────┬───────┘
                        │
                        ▼
              Canonical Accommodation
                        │
           ┌────────────┼─────────────┐
           ▼            ▼             ▼
        SQLite       GeoJSON        App

Henroyado's primary value is not only generic accommodation information.

It contains pilgrimage-specific metadata such as:

1番霊山寺 → 2番極楽寺

This relationship is likely valuable for future route planning and accommodation discovery.

32. Definition of Done — Phase 1

Phase 1 is complete when:

Henroyado HTML can be downloaded and saved locally.

Fetching is independent from parsing.

Every detected accommodation becomes a record.

Every record contains source metadata.

Accommodation name is extracted.

Description is extracted.

Notice is extracted when available.

Henro route raw text is preserved.

Temple route is normalized when safely possible.

Room information is extracted.

Meal information is extracted.

Check-in information is extracted.

Check-out information is extracted.

Facility icons are extracted.

Facility remarks are extracted.

Disabled facilities are detected.

Pricing information is preserved.

Payment information is extracted.

Phone is extracted.

Official website is extracted.

Images are extracted.

Original image URLs are preserved.

Canonical image URLs are generated.

Google Maps search URL is preserved.

Google Maps embed URL is preserved.

Latitude/longitude are extracted from the embed URL when possible.

Parsing failures produce warnings instead of dropping records.

Individual JSON files are generated.

Aggregate JSONL is generated.

Manifest/statistics are generated.

Real HTML fixtures are included in tests.

Parser regression tests pass.

33. Recommended Implementation Order

Step 1 — Archive HTML

Implement only:

URL → HTML file

Do not parse yet.

Step 2 — Detect Accommodation Records

Confirm that every accommodation element can be identified reliably.

Output only:

{
  "name": "...",
  "raw_html": "..."
}

during development if useful.

Step 3 — Build RawInn

Extract source values without semantic normalization.

Step 4 — Implement Independent Normalizers

Recommended order:

text
time
room
meal
route
facility
payment
map coordinates
images

Step 5 — Generate HenroyadoInnV1

Combine normalized and raw information.

Step 6 — Add Warnings

Unknown values must be visible rather than silently ignored.

Step 7 — Add JSON / JSONL Writers

Generate stable deterministic output.

Prefer consistent property ordering if the language/library supports it.

Step 8 — Add Fixtures

Start with 旅館.大鳥居苑.

Then add records representing different data variations.

Step 9 — Run Against Tokushima

Process:

https://henroyado.com/inns?pref=tokushima

Review:

parsing warnings

unknown facilities

unknown detail fields

unusual route descriptions

unusual pricing formats

Use those discoveries to improve v1.

Step 10 — Expand to All Shikoku Prefectures

After Tokushima is stable:

Tokushima
Kochi
Ehime
Kagawa

Only after collecting all prefectures should the canonical application data model be designed.

34. Non-Goals for the AI Agent

The implementation agent must not prematurely:

design the final SQLite schema

merge OSM records

deduplicate accommodation names

rewrite coordinates from OSM

add Google Places API

generate PMTiles

implement Android code

design UI

modify route data

classify accommodations beyond what Henroyado explicitly provides

If additional data would be useful, record it as a future task rather than expanding Phase 1.

35. Final Architecture for Phase 1

                    henroyado.com
                         │
                         ▼
                  ┌─────────────┐
                  │ HTTP Fetcher│
                  └──────┬──────┘
                         │
                         ▼
                  Raw HTML Archive
                         │
                         ▼
                 ┌───────────────┐
                 │  DOM Parser   │
                 └───────┬───────┘
                         │
                         ▼
                      RawInn
                         │
                         ▼
                ┌────────────────┐
                │ Normalizer v1  │
                └───────┬────────┘
                        │
                        ▼
                HenroyadoInnV1
                  │           │
                  ▼           ▼
           records/*.json   henroyado.jsonl
                  │
                  ▼
              manifest.json

──────────────────────────────────────────────
             End of Phase 1
──────────────────────────────────────────────

                  Future Phase
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
          OSM       KML/GPX     Temple Data
           │           │           │
           └───────────┼───────────┘
                       ▼
               Data Reconciliation
                       │
                       ▼
              Canonical App Dataset

36. Summary

The first implementation should be intentionally simple:

Fetch everything, preserve everything, normalize only what is safe, and postpone application-specific decisions.

The key output of this phase is not a database.

The key output is a reliable, versioned, reproducible Henroyado dataset.

Once the complete Shikoku dataset has been collected, the real-world data variations can be inspected before deciding:

canonical accommodation schema

OSM matching

deduplication rules

route relationships

SQLite structure

Android application usage

This avoids designing the application model based on only one or two example accommodations and gives future processing stages a stable source dataset to work from.
