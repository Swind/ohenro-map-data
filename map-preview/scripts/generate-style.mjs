// Generates src/style/style.json from the Protomaps basemap style package.
//
// Usage: node scripts/generate-style.mjs [flavor] [lang]
//   flavor default: light, lang default: ja
//
// The generated source URL is a placeholder; map.ts overrides it at runtime
// from VITE_BASEMAP_URL (pmtiles://...).
import { writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { layers, namedFlavor } from "@protomaps/basemaps";

const __dirname = dirname(fileURLToPath(import.meta.url));
const flavorName = process.argv[2] ?? "light";
const lang = process.argv[3] ?? "ja";

const flavor = namedFlavor(flavorName);
const baseLayers = layers("protomaps", flavor, { lang });

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
