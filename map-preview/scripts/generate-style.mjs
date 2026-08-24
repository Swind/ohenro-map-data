// Generates src/style/style.json from the Protomaps basemap style package.
//
// Usage: node scripts/generate-style.mjs [flavor] [lang]
//   flavor default: light, lang default: ja
//
// The generated source URL is a placeholder; map.ts overrides it at runtime
// from VITE_BASEMAP_URL (pmtiles://...).
//
// Font stack: every layer layout's `text-font` is recursively normalized to the
// single offline CJK stack `Noto Sans CJK JP Regular`.  Layers without a
// `text-font` are left untouched.
//
// Sprite / glyph URLs stay remote (the Protomaps assets CDN) in the source
// style.  NOTE: that remote host does NOT serve the `Noto Sans CJK JP Regular`
// stack, so the unmodified web preview would not find these glyphs.  The
// Android app replaces these URLs for v2 packs (see
// docs/app_map_manifest.md); the web preview is expected to point `sprite` /
// `glyphs` at a local asset base that serves this stack.  This mismatch is
// intentional and not hidden.
import { writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { layers, namedFlavor } from "@protomaps/basemaps";

const __dirname = dirname(fileURLToPath(import.meta.url));
const flavorName = process.argv[2] ?? "light";
const lang = process.argv[3] ?? "ja";

const FONT_STACK = "Noto Sans CJK JP Regular";

// A literal font stack is an array of font-name strings.  Within an expression
// such stacks appear wrapped as `['literal', [...]]`; a top-level `text-font`
// value that is itself an array of strings is also a literal stack.  Other
// all-string arrays that appear inside expressions (e.g. `['get', 'min_zoom']`)
// are data, not font stacks, and must be left untouched.
function normalizeExpr(value) {
  if (!Array.isArray(value)) {
    return value;
  }
  if (
    value[0] === "literal" &&
    Array.isArray(value[1]) &&
    value[1].length > 0 &&
    value[1].every((item) => typeof item === "string")
  ) {
    return ["literal", [FONT_STACK]];
  }
  return value.map(normalizeExpr);
}

function normalizeFontStack(value) {
  if (Array.isArray(value)) {
    if (value.length > 0 && value.every((item) => typeof item === "string")) {
      return [FONT_STACK];
    }
    return normalizeExpr(value);
  }
  return value;
}

// Recursively walk every layer object and normalize the value of any property
// named `text-font`, wherever it appears (layout, paint, or inside nested
// `format` expression option objects).  All other expression data is preserved.
function normalizeTree(node) {
  if (Array.isArray(node)) {
    return node.map(normalizeTree);
  }
  if (node && typeof node === "object") {
    const out = {};
    for (const [key, value] of Object.entries(node)) {
      out[key] = key === "text-font" ? normalizeFontStack(value) : normalizeTree(value);
    }
    return out;
  }
  return node;
}

const flavor = namedFlavor(flavorName);
const baseLayers = layers("protomaps", flavor, { lang });

for (let i = 0; i < baseLayers.length; i++) {
  baseLayers[i] = normalizeTree(baseLayers[i]);
}

const style = {
  version: 8,
  sources: {
    protomaps: {
      type: "vector",
      attribution:
        '<a href="https://github.com/protomaps/basemaps">Protomaps</a> © <a href="https://osm.org/copyright">OpenStreetMap</a>',
      url: "https://place.holder/tilejson.json",
    },
  },
  layers: baseLayers,
  sprite: `https://protomaps.github.io/basemaps-assets/sprites/v4/${flavorName}`,
  glyphs: "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
};

const outDir = join(__dirname, "..", "src", "style");
await mkdir(outDir, { recursive: true });
await writeFile(join(outDir, "style.json"), JSON.stringify(style, null, 2));
console.log(`generated src/style/style.json (flavor=${flavorName}, lang=${lang}, layers=${baseLayers.length})`);
