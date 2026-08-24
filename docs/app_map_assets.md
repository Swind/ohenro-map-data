# App Map Assets (phase 2b)

Builds the deterministic offline asset bundle an Android app installs alongside
the phase-2 map pack: glyph (font) PBFs, sprite sheets, and their license
texts.  Everything lands under `output/app-map-assets/`.

```text
output/app-map-assets/
├── sprites/
│   ├── light.json
│   ├── light.png
│   ├── light@2x.json
│   └── light@2x.png
├── fonts/
│   └── Noto Sans CJK JP Regular/
│       └── <start>-<start+255>.pbf      (exactly the 103 required ranges)
└── licenses/
    ├── Noto-Sans-CJK-OFL.txt
    └── Tangram-Icons-MIT.txt
```

The glyph hierarchy follows the MapLibre glyph template `fonts/{fontstack}/{range}.pbf`:
on disk `{fontstack}` percent-decodes to `Noto Sans CJK JP Regular`, so glyph PBFs
nest under `fonts/Noto Sans CJK JP Regular/`.  (Do not flatten them.)

The manifest (`scripts/build-app-map-manifest.py`, schema_version 2) enumerates
these deterministically with repeated `sprite` / `glyph` / `license` roles.

## Generator

```bash
python3 scripts/build-app-map-assets.py \
  --font-maker /tmp/opencode/font-maker/build/font-maker \
  --font-file /tmp/opencode/NotoSansCJKjp-Regular-2.004.otf
# -> output/app-map-assets/
```

It is stdlib-only.  It invokes two external tools:

* `--font-maker` — a build of maplibre/font-maker patched to emit glyph PBFs for
  the full Unicode range (`0x000000`–`0x10FFFF`) instead of the BMP only.
* `--spritegen` — the existing Protomaps basemaps sprite generator Cargo binary
  (default `basemaps/sprites/target/release/spritegen`; build with
  `cargo build --release --manifest-path basemaps/sprites/Cargo.toml`).

### Options

| Option | Default | Notes |
| --- | --- | --- |
| `--font-maker` | *(required)* | Patched font-maker binary. |
| `--font-file` | *(required)* | Pinned Noto Sans CJK JP Regular OTF. SHA-256 is verified against the pinned hash. |
| `--spritegen` | `basemaps/sprites/target/release/spritegen` | basemaps sprite generator binary. |
| `--output` | `output/app-map-assets` | Output directory. |

## Font

* Immutable font: `NotoSansCJKjp-Regular-2.004.otf`
  (Noto Sans CJK JP Regular, version 2.004).
* SHA-256: `68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5`
  (pinned and verified by the builder).
* Source: notofonts/noto-cjk tag `Sans2.004`, commit
  `523d033d6cb47f4a80c58a35753646f5c3608a78`.
* License: SIL Open Font License 1.1 (see `licenses/Noto-Sans-CJK-OFL.txt`).

The builder invokes font-maker with `--name "Noto Sans CJK JP Regular"` into a
temporary directory, then copies exactly the required ranges.

### Required ranges

The deterministic required-range inventory lives in
`scripts/app-map-assets/noto-sans-cjk-jp-required-ranges.txt`: 103 ranges,
numeric order, no duplicates, each start a multiple of 256 and end = start+255.
This is the union needed for the current data/style (all style text now uses the
single CJK stack), and includes `159744-159999` for U+270F4.  The builder fails
on a missing or empty PBF.

### font-maker patch

The upstream maplibre/font-maker loops over the BMP only (65536 codepoints).
Phase 2b needs supplementary-plane glyphs, so we carry a patch:

* `scripts/app-map-assets/font-maker-unicode.patch` — against maplibre/font-maker
  commit `714ccaea67d384717890a3c2c27143dfdd4189b7`, changing the range loop
  from `i < 65536` to `i < 0x110000` in `main.cpp`.

Apply and build:

```bash
git clone https://github.com/maplibre/font-maker.git
cd font-maker
git checkout 714ccaea67d384717890a3c2c27143dfdd4189b7
git apply /path/to/ohenro-map-data/scripts/app-map-assets/font-maker-unicode.patch
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
# binary at build/font-maker
```

Build dependencies (see font-maker's own README): a C++17 compiler, CMake,
FreeType, fontconfig, zlib and libpng; the repo vendors cxxopts, protozero and
`ghc::filesystem`.  The patched binary is not vendored or committed into this
repo — only the patch and these instructions are.

## Sprites

Sprites reuse the existing basemaps sprite generator (`basemaps/sprites`).  A
custom flavor config is stored *outside* the imported `basemaps/` git tree at
`scripts/app-map-assets/sprites-light.json`: it is the current `light` flavor
plus `townhall` mapped to the existing `slategray` palette (the source SVG
already contains `_townhall`).

The builder runs `spritegen refill.svg <flavor> <dest>/light`, producing
`light.json` / `light.png` / `light@2x.json` / `light@2x.png`, then validates
each index contains every `icon-image` key reachable by the current style —
including `townhall` and the road-shield variants.

## Licenses

Exact license texts are committed at
`scripts/app-map-assets/licenses/` and copied verbatim:

* `Noto-Sans-CJK-OFL.txt` — SIL OFL 1.1, as distributed by notofonts/noto-cjk at
  the pinned `Sans2.004` commit `523d033d6cb47f4a80c58a35753646f5c3608a78`
  (file `LICENSE`).
* `Tangram-Icons-MIT.txt` — the icon set that the sprite SVGs derive from:
  tangrams/icons at commit
  `92510779634f4a006c61ea70e50cb8c52c765a81` (MIT, retained copyright/license).

## Output swap

The full bundle is assembled into a temporary directory in the same parent
(thus the same filesystem) as the target, and only swapped into
`output/app-map-assets/` (via `rename`) after every step succeeds.  This is a
**transactional, rollback-safe** same-filesystem swap: a previous valid output
is moved aside first and restored if the final rename fails, and a previous
valid output is never deleted on failure.  It is not a crash-atomic guarantee —
a process that dies mid-swap can leave the temporary/backup directories behind.

## Tests

```bash
python3 -m unittest discover scripts/tests
node scripts/tests/test_style_font_normalization.mjs
```