import { beforeAll, describe, expect, it, vi } from "vitest";
import type { GeoJSONFeature } from "./model";
import { DOMParser } from "@xmldom/xmldom";
import {
  assignFeatureIds,
  detectFormat,
  hexFromBytes,
  importSourceFile,
  importSourceText,
  paletteColor,
  parseSource,
  sha256Hex,
} from "./import";

// KML parsing needs a DOMParser; Node lacks one, so install @xmldom/xmldom
// (dev-only) for tests. Production code never imports it.
beforeAll(() => {
  (globalThis as Record<string, unknown>).DOMParser = DOMParser as unknown as typeof DOMParser;
});

describe("detectFormat", () => {
  it("detects by extension", () => {
    expect(detectFormat("routes.geojson")).toBe("geojson");
    expect(detectFormat("routes.json")).toBe("geojson");
    expect(detectFormat("track.kml")).toBe("kml");
  });

  it("detects by MIME when the extension is unknown", () => {
    expect(detectFormat("data", "application/geo+json")).toBe("geojson");
    expect(detectFormat("data", "application/vnd.google-earth.kml+xml")).toBe("kml");
  });

  it("throws for unrecognized formats", () => {
    expect(() => detectFormat("routes.txt")).toThrow(/Unrecognized source format/);
  });
});

describe("assignFeatureIds", () => {
  const hashPrefix = "0123456789abcdef";

  function feat(id?: string | number, propsId?: unknown): GeoJSONFeature {
    const f: GeoJSONFeature = { type: "Feature", geometry: null, properties: {} };
    if (id !== undefined) f.id = id;
    if (propsId !== undefined) (f.properties as Record<string, unknown>).id = propsId;
    return f;
  }

  it("prefers Feature.id, then properties.id, then a zero-padded fallback", () => {
    const features = [
      feat("a"), // Feature.id wins
      feat(undefined, "b"), // properties.id
      feat(), // fallback
      feat(), // fallback index 3
    ];
    const out = assignFeatureIds(features, hashPrefix);
    expect(out[0].id).toBe("a");
    expect(out[1].id).toBe("b");
    expect(out[2].id).toBe("F_0123456789abcdef_2");
    expect(out[3].id).toBe("F_0123456789abcdef_3");
  });

  it("writes the normalized id into both Feature.id and properties.id", () => {
    const out = assignFeatureIds([feat(undefined, "b")], hashPrefix);
    expect(out[0].id).toBe("b");
    expect((out[0].properties as Record<string, unknown>).id).toBe("b");
  });

  it("materializes properties when null to hold the id", () => {
    const f: GeoJSONFeature = { type: "Feature", geometry: null, properties: null };
    const out = assignFeatureIds([f], hashPrefix);
    expect(out[0].id).toMatch(/^F_/);
    expect((out[0].properties as Record<string, unknown>).id).toBe(out[0].id);
  });

  it("does not overwrite a conflicting properties.id", () => {
    // Feature.id wins, but properties.id differs and must be preserved.
    const out = assignFeatureIds([feat("a", "keep")], hashPrefix);
    expect(out[0].id).toBe("a");
    expect((out[0].properties as Record<string, unknown>).id).toBe("keep");
  });

  it("rejects duplicate ids within one source (does not suffix silently)", () => {
    expect(() => assignFeatureIds([feat("x"), feat("x")], hashPrefix)).toThrow(/duplicate feature id "x"/);
    // Cross-field collisions are also duplicates.
    expect(() => assignFeatureIds([feat("x"), feat(undefined, "x")], hashPrefix)).toThrow(/duplicate feature id "x"/);
  });

  it("zero-pads fallback indices to the feature-count width", () => {
    const many = Array.from({ length: 100 }, () => feat());
    const out = assignFeatureIds(many, hashPrefix);
    expect(out[0].id).toBe("F_0123456789abcdef_000");
    expect(out[42].id).toBe("F_0123456789abcdef_042");
    expect(out[99].id).toBe("F_0123456789abcdef_099");
  });
});

describe("paletteColor and hashing", () => {
  it("is deterministic for a given seed", () => {
    expect(paletteColor("aabbccddeeff00112233")).toBe(paletteColor("aabbccddeeff00112233"));
  });

  it("hexFromBytes produces lowercase hex", () => {
    expect(hexFromBytes(new Uint8Array([0, 255, 16, 1]))).toBe("00ff1001");
  });

  it("sha256Hex matches a known digest", async () => {
    const digest = await sha256Hex(new TextEncoder().encode("hello"));
    // SHA-256 of "hello"
    expect(digest).toBe("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
  });
});

describe("parseSource", () => {
  it("routes by format", () => {
    const g = parseSource(JSON.stringify({ type: "Feature", geometry: null, properties: null }), "geojson");
    expect(g.features).toHaveLength(1);
    const k = parseSource('<kml><Placemark><name>P</name><Point><coordinates>134,33</coordinates></Point></Placemark></kml>', "kml");
    expect(k.features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
  });
});

describe("importSourceFile", () => {
  it("builds an EditorSource from a GeoJSON File", async () => {
    const geojson = JSON.stringify({
      type: "FeatureCollection",
      features: [
        { type: "Feature", id: "way1", geometry: { type: "LineString", coordinates: [[134, 33], [134, 34]] }, properties: { name: "a" } },
      ],
    });
    const file = new File([geojson], "routes.geojson", { type: "application/geo+json" });
    const source = await importSourceFile(file);

    expect(source.name).toBe("routes.geojson");
    expect(source.format).toBe("geojson");
    expect(source.id).toBe(`SRC_${source.sha256.slice(0, 16)}`);
    expect(source.sha256).toHaveLength(64);
    expect(source.visible).toBe(true);
    expect(source.selectable).toBe(true);
    expect(source.color).toBe(paletteColor(source.sha256));
    expect(source.importWarnings).toEqual([]);
    expect(source.data.type).toBe("FeatureCollection");
    expect(source.data.features[0].id).toBe("way1");
    expect((source.data.features[0].properties as Record<string, unknown>).id).toBe("way1");
  });

  it("detects KML by MIME and normalizes geometry", async () => {
    const kml = '<kml><Document><Placemark id="p1"><name>P</name><Point><coordinates>134,33</coordinates></Point></Placemark></Document></kml>';
    const file = new File([kml], "markers.kml", { type: "application/vnd.google-earth.kml+xml" });
    const source = await importSourceFile(file);
    expect(source.format).toBe("kml");
    expect(source.id).toBe(`SRC_${source.sha256.slice(0, 16)}`);
    expect(source.data.features[0].id).toBe("p1");
    expect(source.data.features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
  });
});

describe("importSourceText", () => {
  it("builds an EditorSource with the same pipeline as importSourceFile", async () => {
    const geojson = JSON.stringify({
      type: "FeatureCollection",
      features: [
        { type: "Feature", id: "way1", geometry: { type: "LineString", coordinates: [[134, 33], [134, 34]] }, properties: { name: "a" } },
      ],
    });
    const source = await importSourceText("routes.geojson", geojson);

    expect(source.name).toBe("routes.geojson");
    expect(source.format).toBe("geojson");
    expect(source.sha256).toHaveLength(64);
    expect(source.id).toBe(`SRC_${source.sha256.slice(0, 16)}`);
    expect(source.visible).toBe(true);
    expect(source.selectable).toBe(true);
    expect(source.color).toBe(paletteColor(source.sha256));
    expect(source.data.features[0].id).toBe("way1");

    // Deterministic: identical text/name produce an identical source id.
    const again = await importSourceText("routes.geojson", geojson);
    expect(again.id).toBe(source.id);
    expect(again.sha256).toBe(source.sha256);
  });

  it("detects KML from the name and normalizes geometry", async () => {
    const kml = '<kml><Document><Placemark id="p1"><name>P</name><Point><coordinates>134,33</coordinates></Point></Placemark></Document></kml>';
    const source = await importSourceText("markers.kml", kml);
    expect(source.format).toBe("kml");
    expect(source.data.features[0].id).toBe("p1");
    expect(source.data.features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
  });

  it("hashes the exact UTF-8 bytes of the text", async () => {
    const source = await importSourceText("a.json", JSON.stringify({ type: "Feature", geometry: null, properties: null }));
    const expected = await sha256Hex(new TextEncoder().encode(JSON.stringify({ type: "Feature", geometry: null, properties: null })));
    expect(source.sha256).toBe(expected);
  });

  it("rejects an unrecognized source format", async () => {
    await expect(importSourceText("routes.txt", "data")).rejects.toThrow(/Unrecognized source format/);
  });

  it("uses a validated precomputed SHA-256 without needing crypto.subtle", async () => {
    const geojson = JSON.stringify({
      type: "FeatureCollection",
      features: [
        { type: "Feature", id: "way1", geometry: { type: "LineString", coordinates: [[134, 33], [134, 34]] }, properties: { name: "a" } },
      ],
    });
    const realHash = await sha256Hex(new TextEncoder().encode(geojson));
    // Simulate an insecure (plain-HTTP) context where crypto.subtle is absent.
    vi.stubGlobal("crypto", { subtle: undefined });
    try {
      const source = await importSourceText("routes.geojson", geojson, realHash);
      // Exact same pipeline result, but hashed server-side (no crypto.subtle).
      expect(source.sha256).toBe(realHash);
      expect(source.id).toBe(`SRC_${realHash.slice(0, 16)}`);
      expect(source.format).toBe("geojson");
      expect(source.data.features[0].id).toBe("way1");
      expect(source.color).toBe(paletteColor(realHash));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("rejects a malformed precomputed SHA-256", async () => {
    await expect(importSourceText("routes.geojson", "{}", "not-a-hash")).rejects.toThrow(/Invalid precomputed SHA-256/);
    await expect(importSourceText("routes.geojson", "{}", "abcd")).rejects.toThrow(/Invalid precomputed SHA-256/);
    // Uppercase hex must be rejected (must be lowercase 64-hex).
    await expect(
      importSourceText("routes.geojson", "{}", "2CF24DBA5FB0A30E26E83B2AC5B9E29E1B161E5C1FA7425E73043362938B9824"),
    ).rejects.toThrow(/Invalid precomputed SHA-256/);
  });
});