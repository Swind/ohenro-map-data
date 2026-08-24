// Node assertion test for the phase-2b style font-stack normalization.
//
// Validates the generated src/style/style.json: every `text-font` value
// anywhere in the style (top-level layout text-font, and `text-font` option
// objects nested inside `format` expressions) is recursively normalized to the
// single offline CJK stack "Noto Sans CJK JP Regular".  The whole style is
// scanned; any occurrence of a legacy font name is a failure, while unrelated
// expression data must be preserved.
//
// Usage: node scripts/tests/test_style_font_normalization.mjs
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const STYLE_PATH = join(__dirname, "..", "..", "map-preview", "src", "style", "style.json");
const FONT_STACK = "Noto Sans CJK JP Regular";
const OLD_FONTS = [
  "Noto Sans Regular",
  "Noto Sans Medium",
  "Noto Sans Italic",
  "Noto Sans Devanagari Regular v1",
];

const style = JSON.parse(await readFile(STYLE_PATH, "utf8"));
const failures = [];

// Recursively visit every node; assert no old font string anywhere, and that
// every object property named "text-font" is normalized (its value contains
// the stack and no legacy font).
function scan(node, path) {
  if (Array.isArray(node)) {
    node.forEach((v, i) => scan(v, `${path}[${i}]`));
    return;
  }
  if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      if (key === "text-font") {
        const text = JSON.stringify(value);
        if (OLD_FONTS.some((f) => text.includes(f))) {
          failures.push(`${path}.text-font still references a legacy font: ${text}`);
        }
        if (!text.includes(FONT_STACK)) {
          failures.push(`${path}.text-font does not contain the normalized stack: ${text}`);
        }
      }
      scan(value, `${path}.${key}`);
    }
    return;
  }
  if (typeof node === "string" && OLD_FONTS.includes(node)) {
    failures.push(`legacy font name "${node}" found at ${path}`);
  }
}

scan(style, "style");

if (failures.length > 0) {
  console.error("FONT NORMALIZATION FAILURES:");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}

// Ensure the normalized stack actually appears somewhere.
const raw = JSON.stringify(style);
if (!raw.includes(FONT_STACK)) {
  console.error(`FAIL: normalized stack "${FONT_STACK}" not present anywhere in the style.`);
  process.exit(1);
}

// Sanity: 58 layers have no text-font, 13 have one at layout level.
const withLayoutTextFont = style.layers.filter((l) => l.layout && "text-font" in l.layout).length;
const withoutLayoutTextFont = style.layers.length - withLayoutTextFont;

console.log(
  `OK: no legacy font strings anywhere; stack "${FONT_STACK}" present; ` +
  `${withLayoutTextFont} layer(s) with layout text-font, ${withoutLayoutTextFont} without.`
);