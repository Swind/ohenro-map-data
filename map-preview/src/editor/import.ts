/**
 * File import entry point for the route editor.
 *
 * `importSourceFile(file)` reads bytes, hashes them (SHA-256 via
 * crypto.subtle), detects geojson/json/kml by extension/MIME, parses via the
 * pure `parseGeoJSON` / `parseKML` functions, assigns deterministic feature
 * IDs, and builds an immutable `EditorSource`. All parsing/ID logic is
 * exposed as pure functions for tests.
 */

import type { EditorSource, GeoJSONFeature } from "./model";
import { parseGeoJSON, type ParsedImport } from "./import-geojson";
import { parseKML } from "./import-kml";

export type SourceFormat = "geojson" | "kml";

export type { ParsedImport } from "./import-geojson";

/** Deterministic palette used to colour imported sources. */
const PALETTE = [
  "#e11d48", "#0ea5e9", "#16a34a", "#f59e0b", "#8b5cf6", "#ec4899",
  "#14b8a6", "#f97316", "#6366f1", "#84cc16", "#d946ef", "#22c55e",
];

/** Detect the source format from a file name and/or MIME type. */
export function detectFormat(filename: string, mime?: string): SourceFormat {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".geojson") || lower.endsWith(".json")) return "geojson";
  if (lower.endsWith(".kml")) return "kml";
  if (mime) {
    const m = mime.toLowerCase();
    if (m === "application/geo+json" || m.includes("json")) return "geojson";
    if (m === "application/vnd.google-earth.kml+xml" || m.includes("kml")) return "kml";
  }
  throw new Error(`Unrecognized source format for "${filename}"`);
}

/** Parse source text for a detected format (pure, testable). */
export function parseSource(text: string, format: SourceFormat): ParsedImport {
  return format === "kml" ? parseKML(text) : parseGeoJSON(text);
}

/** Convert an ArrayBuffer digest to lowercase hex. */
export function hexFromBytes(bytes: Uint8Array): string {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Compute the SHA-256 hex digest of a byte array via crypto.subtle. */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  if (!crypto.subtle) {
    throw new Error("SHA-256 is unavailable; open the editor through http://localhost or HTTPS");
  }
  // Hash exactly this view's bytes (byteOffset..byteOffset+byteLength), never
  // the whole backing buffer. slice() copies just the view's contents.
  const digest = await crypto.subtle.digest("SHA-256", bytes.slice());
  return hexFromBytes(new Uint8Array(digest));
}

/**
 * Assign deterministic feature IDs: prefer `Feature.id`, then
 * `properties.id`, then a `F_<hash prefix>_<zero-padded index>` fallback.
 * Duplicate IDs within one source are rejected (never silently suffixed).
 * The normalized ID is written to both `Feature.id` and `properties.id`,
 * unless a conflicting `properties.id` already exists (which is preserved).
 */
export function assignFeatureIds(features: GeoJSONFeature[], hashPrefix: string): GeoJSONFeature[] {
  const seen = new Map<string, number>();
  const width = String(features.length).length;
  features.forEach((feature, index) => {
    const rawId =
      feature.id !== null && feature.id !== undefined ? String(feature.id) : null;
    const propsId =
      feature.properties && feature.properties.id !== null && feature.properties.id !== undefined
        ? String(feature.properties.id)
        : null;
    const candidate = rawId ?? propsId ?? `F_${hashPrefix}_${String(index).padStart(width, "0")}`;

    const prev = seen.get(candidate);
    if (prev !== undefined) {
      throw new Error(
        `duplicate feature id "${candidate}" (features at index ${prev} and ${index})`,
      );
    }
    seen.set(candidate, index);

    feature.id = candidate;
    const props = feature.properties;
    if (props === null || props === undefined) {
      feature.properties = { id: candidate };
    } else if (
      props.id === null ||
      props.id === undefined ||
      String(props.id) === candidate
    ) {
      props.id = candidate;
    }
    // A conflicting properties.id is left untouched (not overwritten).
  });
  return features;
}

/** Deterministic palette colour derived from a hex seed (source hash). */
export function paletteColor(seed: string): string {
  let n = 0;
  for (let i = 0; i < Math.min(8, seed.length); i++) {
    n = (n * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return PALETTE[n % PALETTE.length];
}

/**
 * Build an immutable EditorSource from raw bytes: hashes them (unless a
 * server-provided precomputed hash is supplied), detects the format, parses
 * via the pure parser, assigns deterministic feature IDs, and colours the
 * layer. Shared by the native file and output-text paths so they exercise the
 * exact same normalization/hash pipeline (never duplicated). Throws on
 * undetectable format, malformed source, or duplicate IDs.
 */
async function buildSourceFromBytes(
  bytes: Uint8Array,
  name: string,
  format: SourceFormat,
  precomputedSha256?: string,
): Promise<EditorSource> {
  const hashHex = precomputedSha256 ?? await sha256Hex(bytes);
  const hashPrefix = hashHex.slice(0, 16);

  const text = new TextDecoder().decode(bytes);
  const parsed = parseSource(text, format);
  const features = assignFeatureIds(parsed.features, hashPrefix);

  return {
    id: `SRC_${hashPrefix}`,
    name,
    sha256: hashHex,
    format,
    color: paletteColor(hashHex),
    visible: true,
    selectable: true,
    data: { type: "FeatureCollection", features },
    importWarnings: parsed.warnings,
  };
}

/**
 * Parse a source file into an immutable EditorSource. Reads bytes, hashes
 * them, detects the format, normalizes geometry, assigns IDs, and colours the
 * layer. Throws on undetectable format, malformed source, or duplicate IDs.
 */
export async function importSourceFile(file: File): Promise<EditorSource> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  return buildSourceFromBytes(bytes, file.name, detectFormat(file.name, file.type));
}

/**
 * Parse source text (e.g. read from the output API) into an immutable
 * EditorSource. Encodes the exact UTF-8 bytes, hashes them (or uses a
 * validated server-provided hash), detects the format from the name, and runs
 * the same normalization/hash pipeline as {@link importSourceFile}. Throws on
 * undetectable format, malformed source, duplicate IDs, or a malformed
 * precomputed hash.
 */
export async function importSourceText(
  name: string,
  text: string,
  precomputedSha256?: string,
): Promise<EditorSource> {
  if (precomputedSha256 !== undefined && !/^[0-9a-f]{64}$/.test(precomputedSha256)) {
    throw new Error(`Invalid precomputed SHA-256 for "${name}"`);
  }
  const bytes = new TextEncoder().encode(text);
  return buildSourceFromBytes(bytes, name, detectFormat(name), precomputedSha256);
}
