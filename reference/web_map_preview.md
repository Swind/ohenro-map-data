Shikoku Henro Map Web Preview Implementation Plan

1. Goal

Build a lightweight web-based map preview environment for the Shikoku Henro map project.

The preview environment should allow us to:

Load the existing Protomaps/Planetiler-generated PMTiles basemap.

Load Henro-specific GeoJSON layers during development.

Preview map colors, line styles, labels, temple markers, route rendering, and zoom behavior.

Iterate on the map style quickly without rebuilding the Android application.

Reuse the same MapLibre style definition on both Web and Android as much as possible.

Keep the web preview as a development/debugging tool rather than a separate map implementation.

The long-term rendering architecture should be:

                     Shared map data
                           │
             ┌─────────────┴─────────────┐
             │                           │
      basemap.pmtiles              henro.pmtiles
             │                           │
             └─────────────┬─────────────┘
                           │
                      style.json
                       /       \
                      /         \
                     ▼           ▼
            MapLibre GL JS   MapLibre Android
                 Web             Android

The web environment should be used for fast visual iteration, while Android emulator/device rendering remains the final validation target.

2. Current Data

The project currently has:

basemap.pmtiles

generated from Protomaps Basemaps / Planetiler.

Henro-specific data is also available as GeoJSON, including at least temple location data.

During early development, do not require all Henro GeoJSON data to be converted into PMTiles.

Use:

basemap.pmtiles
+
temples.geojson
+
henro_routes.geojson
+
style.json

during map-style development.

Once the visual design and data schema become stable, Henro GeoJSON can be converted into a separate:

henro.pmtiles

or incorporated into the existing tile-generation pipeline.

3. Recommended Technology Stack

Use:

Vite

TypeScript

MapLibre GL JS

PMTiles JavaScript library

Protomaps Basemap style as the initial basemap style

Suggested dependencies:

npm install maplibre-gl pmtiles

Optional development tooling:

Maputnik for visual MapLibre style editing

ESLint / Prettier

Vitest if map configuration logic becomes non-trivial

Do not introduce React unless there is an actual need for UI complexity.

A basic Vite + TypeScript project is sufficient for the initial viewer.

4. Project Structure

Recommended project structure:

map-preview/
├── package.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.ts
│   ├── map.ts
│   └── style/
│       └── style.json
│
├── public/
│   ├── data/
│   │   ├── basemap.pmtiles
│   │   ├── temples.geojson
│   │   └── henro_routes.geojson
│   │
│   ├── sprites/
│   └── fonts/
│
└── README.md

If the PMTiles file is very large, it does not need to be copied into the repository.

Instead, support configuration through environment variables.

Example:

VITE_BASEMAP_URL=http://localhost:8080/basemap.pmtiles

or:

VITE_BASEMAP_URL=https://example.com/maps/shikoku.pmtiles

5. Vite Setup

Create a minimal Vite TypeScript project.

Example:

npm create vite@latest map-preview -- --template vanilla-ts
cd map-preview
npm install
npm install maplibre-gl pmtiles

Development command:

npm run dev

The viewer should normally be available at:

http://localhost:5173

6. PMTiles Integration

Register the PMTiles protocol with MapLibre before creating the map.

Example:

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { Protocol } from "pmtiles";

const protocol = new Protocol();

maplibregl.addProtocol(
  "pmtiles",
  protocol.tile
);

The basemap source can then be referenced using:

pmtiles://

Example MapLibre source:

{
  "type": "vector",
  "url": "pmtiles://http://localhost:8080/basemap.pmtiles"
}

Do not attempt to manually unpack PMTiles into XYZ tiles.

PMTiles should remain the canonical tile container.

7. Initial Map Configuration

Use a Shikoku-centered default map position.

For example:

const map = new maplibregl.Map({
  container: "map",
  center: [
    134.206799,
    34.191403
  ],
  zoom: 11,
  style: "/style/style.json"
});

The center above can point to Temple 88, Okubo-ji, for initial testing.

Later, add a configurable initial location.

Possible URL parameters:

?lat=34.191403&lon=134.206799&zoom=14

This is useful when debugging specific temples.

8. Basemap Style

Do not create the complete Protomaps basemap style manually from scratch.

Start from an existing Protomaps MapLibre-compatible style.

The basemap style should provide layers such as:

earth
water
landuse
roads
buildings
boundaries
place labels
transport labels
POIs

Then add Henro-specific layers on top.

Logical layer ordering:

background / earth
water
landuse
roads
buildings
standard labels
--------------------------------
henro route
henro route casing
henro facilities
henro temples
henro temple labels
current user location
navigation overlays

The Henro layers should appear above the basemap.

9. Shared Style Strategy

The project should aim to maintain one MapLibre-style-compatible configuration for both:

Web
Android

The core map appearance should be driven by:

style.json

rather than hardcoded separately inside Web JavaScript and Android Kotlin code.

Shared style concepts should include:

fill color

line color

line width

line opacity

circle color

circle radius

text size

text color

icon size

filters

minzoom

maxzoom

visibility

layer ordering

Example:

{
  "id": "henro-route",
  "type": "line",
  "source": "henro-route",
  "paint": {
    "line-color": "#8f4b32",
    "line-width": 4,
    "line-opacity": 0.9
  }
}

Avoid implementing the same style twice.

10. Web vs Android Rendering Expectations

Web and Android should look very similar if both use MapLibre and the same style definition.

However, do not expect pixel-perfect rendering.

Potential differences include:

font rendering
Japanese font fallback
kerning
text width
label collision
glyph shaping
anti-aliasing
GPU differences
device pixel ratio
line joins
symbol placement

Therefore, define the workflow as:

Web Preview
    ↓
fast style iteration

Android Emulator
    ↓
platform validation

Android Physical Device
    ↓
final visual validation

The Web preview should be considered approximately 90–95% representative of the final design, not a replacement for Android testing.

11. Henro Temple Layer

During development, load temple data directly from GeoJSON.

Example source:

{
  "temples": {
    "type": "geojson",
    "data": "/data/temples.geojson"
  }
}

Example temple feature:

{
  "type": "Feature",
  "id": "temple-088",
  "geometry": {
    "type": "Point",
    "coordinates": [
      134.206799,
      34.191403
    ]
  },
  "properties": {
    "id": "temple-088",
    "number": 88,
    "name_ja": "大窪寺",
    "name_en": "Okubo-ji",
    "name_kana": "おおくぼじ"
  }
}

Remember:

GeoJSON coordinates = [longitude, latitude]

not:

[latitude, longitude]

12. Temple Marker Style

Use a separate symbol/circle layer for temples.

Suggested first version:

{
  "id": "henro-temples",
  "type": "circle",
  "source": "temples",
  "paint": {
    "circle-radius": 7,
    "circle-stroke-width": 2
  }
}

Do not over-design the first version.

The purpose of the web preview is to iterate.

Later versions may use:

custom temple icon
numbered icon
temple gate symbol
pilgrimage-specific marker

13. Temple Label Style

Temple labels should not display the full formal temple name at normal zoom levels.

Prefer:

88 大窪寺

instead of:

第八十八番 医王山 大窪寺

Suggested label fields:

number
name_ja

Example:

{
  "id": "henro-temple-label",
  "type": "symbol",
  "source": "temples",
  "minzoom": 9,
  "layout": {
    "text-field": [
      "format",
      ["get", "number"],
      {},
      " ",
      {},
      ["get", "name_ja"],
      {}
    ],
    "text-size": 13
  }
}

Suggested zoom behavior:

z6+
  temple marker only

z9+
  number + short temple name

z13+
  larger icon / richer temple styling

These values should be tuned visually.

14. Henro Route Layer

Load the Henro walking route as GeoJSON during development.

Example source:

{
  "henro-route": {
    "type": "geojson",
    "data": "/data/henro_routes.geojson"
  }
}

Use at least two route layers:

route casing
route foreground

Example conceptual styling:

wide dark/neutral casing
+
slightly thinner route color

This improves visibility across:

roads
forest
urban areas
water-adjacent areas

Do not make the Henro route visually indistinguishable from normal road geometry.

15. Other Henro POIs

Future GeoJSON sources may include:

benches.geojson
cycle_stands.geojson
toilets.geojson
lodging.geojson
water.geojson
rest_areas.geojson

The web preview should be designed so these can easily be added as independent MapLibre sources/layers.

Example conceptual source structure:

temples
henro-routes
benches
cycle-stands
toilets
lodging

Do not combine every POI into one large source unless the final tile pipeline benefits from doing so.

16. GeoJSON First, PMTiles Later

During development:

GeoJSON

should be preferred for Henro-specific data because it makes debugging easy.

Advantages:

easy to inspect
easy to modify
easy to regenerate
easy to diff
easy to debug
no tile rebuild required

Use this workflow:

raw source
    ↓
normalized JSON
    ↓
GeoJSON
    ↓
Web Preview

Only after the data model and rendering are stable:

GeoJSON
    ↓
Planetiler
    ↓
henro.pmtiles

This avoids unnecessary tile rebuilds while style development is still active.

17. Final Tile Architecture

Recommended production architecture:

basemap.pmtiles
+
henro.pmtiles

Do not necessarily merge them into one file.

Keeping separate files provides several advantages:

basemap changes less frequently
Henro data can be updated independently
smaller update downloads
easier debugging
clear source ownership

Suggested Henro vector tile layers:

henro_temples
henro_routes
henro_benches
henro_cycle_stands
henro_toilets
henro_lodging

Example temple vector tile properties:

id
number
name_ja
name_en
name_kana

Do not store full temple history or other long metadata inside PMTiles.

Detailed temple information should remain in SQLite / Room.

18. Interaction Debugging

The web preview should support clicking map features.

For temple clicks:

click temple
    ↓
read feature.properties.id
    ↓
display debug popup

Example popup fields:

temple-088
88
大窪寺
Okubo-ji

This provides a useful way to verify:

feature IDs
properties
tile source
layer visibility
coordinates

The web viewer does not need to reproduce the final Android UI.

A simple debug popup is enough.

19. Debug Panel

Add a small optional debug panel.

Useful information:

current zoom
latitude
longitude
bearing
pitch
clicked feature ID
clicked source
clicked source-layer

Optional toggles:

show/hide basemap labels
show/hide temples
show/hide Henro route
show/hide benches
show/hide other POIs

This significantly improves map-style development.

Avoid building a large application around the preview tool.

20. Maputnik

Maputnik may be used as a visual MapLibre Style editor.

Recommended workflow:

existing style.json
       ↓
    Maputnik
       ↓
visual adjustments
       ↓
export style.json
       ↓
Web Preview
       ↓
Android

Maputnik can be useful for adjusting:

road widths
land colors
water colors
building colors
label sizes
layer visibility
zoom ranges

However, keep the repository's style.json as the source-controlled result.

Do not treat Maputnik itself as the source of truth.

21. Fonts and Japanese Labels

Japanese rendering should be tested carefully.

Potential issues:

missing glyphs
incorrect fallback fonts
different Web/Android font metrics
label collision differences

The final Android map must be tested with:

大窪寺
霊山寺
金剛頂寺
善通寺

and other Japanese labels.

If custom glyph/font infrastructure is introduced, ensure it works offline.

Do not depend on an internet-only font endpoint for the final offline Android app.

22. Offline Considerations

The final Android application is expected to support offline usage.

Therefore the Web preview must not encourage accidental dependencies on:

Google Maps
online raster tiles
remote vector tiles
remote fonts
remote sprites

unless those resources are explicitly development-only.

Production map assets should eventually be available locally:

basemap.pmtiles
henro.pmtiles
sprites
icons
fonts/glyphs
style.json

23. Remote Development Workflow

The development environment may run on a remote Linux server.

Run:

npm run dev

on the remote machine.

Access it through SSH port forwarding:

ssh -L 5173:localhost:5173 user@server

Then open locally:

http://localhost:5173

If the PMTiles file is served by another port:

ssh \
  -L 5173:localhost:5173 \
  -L 8080:localhost:8080 \
  user@server

This allows map development through a local desktop browser while keeping the data/build environment remote.

24. Large PMTiles Files

Do not place a very large PMTiles file inside Vite's normal bundled asset pipeline.

Serve it as a static file.

Possible approaches:

public/data/basemap.pmtiles

for small/local tests, or preferably:

python3 -m http.server 8080

from the directory containing the PMTiles file.

Example URL:

http://localhost:8080/shikoku.pmtiles

The MapLibre source can then use:

pmtiles://http://localhost:8080/shikoku.pmtiles

Ensure the HTTP server supports byte range requests.

PMTiles relies on HTTP range requests for efficient random access.

25. Development Configuration

Create environment configuration such as:

.env.development

Example:

VITE_BASEMAP_URL=http://localhost:8080/shikoku.pmtiles
VITE_TEMPLES_URL=/data/temples.geojson
VITE_HENRO_ROUTE_URL=/data/henro_routes.geojson

Do not hardcode machine-specific paths inside main.ts.

26. Recommended Implementation Phases

Phase 1 — Minimal Viewer

Implement:

Vite
MapLibre GL JS
PMTiles protocol
basemap.pmtiles
basic navigation controls

Success criteria:

Map loads.

Pan works.

Zoom works.

PMTiles source works.

Basemap renders correctly.

Phase 2 — Temple GeoJSON

Add:

temples.geojson

Implement:

temple markers
temple numbers
Japanese temple labels
click popup

Success criteria:

All 88 temples are visible.

Temple 88 appears at the expected position.

Canonical temple IDs are accessible from feature properties.

Phase 3 — Henro Route

Add:

henro_routes.geojson

Implement:

route casing
route foreground
zoom-dependent width

Success criteria:

Route is visually distinct from normal roads.

Route remains visible over forests and urban areas.

Phase 4 — Style Refinement

Tune:

basemap colors
road hierarchy
land colors
water
buildings
label visibility
temple styling
Henro route styling

Use Web preview and optionally Maputnik.

Success criteria:

Visual hierarchy is suitable for a walking pilgrimage map.

Henro route and temples remain more visually prominent than generic POIs.

Phase 5 — Android Validation

Load the same or equivalent MapLibre style in the Android app.

Compare:

colors
line widths
temple symbols
Japanese labels
zoom behavior
layer ordering

Document rendering differences.

Do not duplicate styling unnecessarily in Kotlin.

Phase 6 — Henro PMTiles

Once the schema is stable:

temples.geojson
henro_routes.geojson
benches.geojson
...
       ↓
Planetiler
       ↓
henro.pmtiles

Replace development GeoJSON sources with vector tile sources.

Success criteria:

Web rendering remains visually equivalent.

Android rendering remains equivalent.

Feature IDs remain stable.

App can link map features to SQLite records.

27. Separation of Responsibilities

Maintain the following boundaries.

PMTiles

Responsible for:

geometry
map rendering
feature positioning
small map-visible properties

Example temple properties:

id
number
name_ja
name_en

SQLite / Room

Responsible for:

full temple metadata
history
address
phone
sect
principal deity
founder
founded year
lodging
images
source metadata

MapLibre Style

Responsible for:

colors
icons
line widths
label styles
visibility
zoom rules
layer ordering

Android UI

Responsible for:

detail screens
navigation UI
search
user state
route progress
offline application behavior

Do not move Android UI concerns into map tile data.

28. Canonical Feature IDs

Map features must use the same canonical IDs as the local domain database.

Example:

temple-001
temple-002
...
temple-088

Map feature:

{
  "properties": {
    "id": "temple-088"
  }
}

SQLite:

id = temple-088

Interaction:

user taps map
      ↓
feature.id = temple-088
      ↓
Room query
      ↓
Temple detail

Do not use third-party source IDs such as:

107

as the application's primary identity.

Those IDs should be retained only as source metadata.

29. Expected Final Architecture

                     Data pipeline
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
     Basemap                             Henro data
        │                                   │
        ▼                                   ▼
 basemap.pmtiles                       henro.pmtiles
        │                                   │
        └───────────────┬───────────────────┘
                        │
                   style.json
                        │
        ┌───────────────┴─────────────────┐
        │                                 │
        ▼                                 ▼
 MapLibre GL JS                    MapLibre Android
 Web preview                           production
        │                                 │
        │                                 ▼
        │                            SQLite / Room
        │                                 │
        └──────────── visual ──────────────┘
                   validation

The Web viewer exists to speed up development.

The Android renderer remains the final production target.

30. Agent Implementation Requirements

The AI agent implementing this should follow these rules:

Start with a minimal Vite + TypeScript application.

Use MapLibre GL JS, not Google Maps or Leaflet.

Register PMTiles through the official PMTiles protocol adapter.

Load the existing basemap PMTiles without modifying it.

Load temple and route data as GeoJSON during early development.

Keep map styling in MapLibre style configuration rather than hardcoding visual values throughout TypeScript.

Keep Henro-specific layers above normal basemap layers.

Preserve canonical IDs such as temple-088.

Add a basic feature inspection/debug popup.

Make URLs configurable through environment variables.

Keep the viewer lightweight and development-focused.

Do not introduce a backend server unless required for static file/range serving.

Do not make the production Android map depend on online map services.

Validate Japanese text rendering.

Later migrate stable Henro GeoJSON into henro.pmtiles.

Re-test the final style on Android emulator and physical Android devices.

31. Definition of Done for the Initial Version

The first usable implementation is complete when:

npm run dev starts the map viewer.

The existing Shikoku PMTiles basemap loads.

The map can be panned and zoomed.

temples.geojson loads.

Temple markers appear.

Temple labels appear at appropriate zoom levels.

Clicking a temple shows its canonical ID and basic metadata.

henro_routes.geojson loads.

Henro routes are visually distinguishable from normal roads.

Map source URLs can be changed without editing TypeScript.

The style can later be reused/adapted for MapLibre Android.

The README explains how to run the viewer locally and through SSH port forwarding.

32. Recommended Next Step

Implement only:

basemap.pmtiles
+
temples.geojson
+
MapLibre GL JS

first.

Do not add all facility categories immediately.

Once this works and the basemap source-layer names are confirmed, add:

henro route
temple labels
POIs
style refinements

incrementally.

This keeps failures easy to isolate and allows the Web viewer to become a stable map-development tool before the production Android integration begins.
