import { afterEach, describe, expect, it, vi } from "vitest";
import { listOutputFiles, readOutputFile, readOutputSource, writeOutputFile } from "./output-api";

function mockResponse(opts: {
  status?: number;
  statusText?: string;
  json?: unknown;
  text?: string;
  headers?: Record<string, string>;
}): Response {
  const status = opts.status ?? 200;
  const statusText = opts.statusText ?? "OK";
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => opts.json,
    text: async () => opts.text ?? "",
    headers: {
      get: (name: string) => {
        const key = name.toLowerCase();
        const found = Object.entries(opts.headers ?? {}).find(([k]) => k.toLowerCase() === key);
        return found ? found[1] : null;
      },
    },
  } as unknown as Response;
}

function stubFetch(impl: (url: string, init?: RequestInit) => Promise<Response>): void {
  vi.stubGlobal("fetch", impl);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listOutputFiles", () => {
  it("returns the file list", async () => {
    const files = [
      { path: "route-editor/projects/ohenro-project-1.json", size: 42 },
      { path: "route-editor/final/ohenro-final-1.geojson", size: 7 },
    ];
    stubFetch(async () => mockResponse({ json: { files } }));
    await expect(listOutputFiles()).resolves.toEqual(files);
  });

  it("throws the parsed server error on non-2xx", async () => {
    stubFetch(async () =>
      mockResponse({ status: 500, statusText: "Internal Server Error", json: { error: "Could not list output" } }),
    );
    await expect(listOutputFiles()).rejects.toThrow(/Could not list output/);
  });

  it("falls back to the status line when there is no JSON body", async () => {
    stubFetch(async () => mockResponse({ status: 500, statusText: "Internal Server Error" }));
    await expect(listOutputFiles()).rejects.toThrow(/HTTP 500/);
  });
});

describe("readOutputFile", () => {
  it("URL-encodes the path and returns the text", async () => {
    let requested = "";
    stubFetch(async (url) => {
      requested = url;
      return mockResponse({ text: "content" });
    });
    await expect(readOutputFile("route-editor/final/ohenro-final-1.geojson")).resolves.toBe("content");
    expect(requested).toContain("path=");
    expect(requested).toContain("route-editor%2Ffinal%2Fohenro-final-1.geojson");
  });

  it("throws the parsed server error on non-2xx", async () => {
    stubFetch(async () =>
      mockResponse({ status: 404, statusText: "Not Found", json: { error: "Output file not found" } }),
    );
    await expect(readOutputFile("missing.geojson")).rejects.toThrow(/Output file not found/);
  });
});

describe("readOutputSource", () => {
  const hash = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824";

  it("URL-encodes the path and returns text plus the SHA-256 header", async () => {
    let requested = "";
    stubFetch(async (url) => {
      requested = url;
      return mockResponse({ text: "content", headers: { "X-Ohenro-Content-SHA256": hash } });
    });
    await expect(readOutputSource("route-editor/final/ohenro-final-1.geojson")).resolves.toEqual({
      text: "content",
      sha256: hash,
    });
    expect(requested).toContain("route-editor%2Ffinal%2Fohenro-final-1.geojson");
  });

  it("throws the parsed server error on non-2xx", async () => {
    stubFetch(async () =>
      mockResponse({ status: 500, statusText: "Internal Server Error", json: { error: "Output file not found" } }),
    );
    await expect(readOutputSource("missing.geojson")).rejects.toThrow(/Output file not found/);
  });

  it("rejects when the SHA-256 header is missing", async () => {
    stubFetch(async () => mockResponse({ text: "content" }));
    await expect(readOutputSource("a.geojson")).rejects.toThrow(/X-Ohenro-Content-SHA256/);
  });

  it("rejects a malformed SHA-256 header (uppercase / wrong length)", async () => {
    stubFetch(async () =>
      mockResponse({ text: "content", headers: { "X-Ohenro-Content-SHA256": hash.toUpperCase() } }),
    );
    await expect(readOutputSource("a.geojson")).rejects.toThrow(/X-Ohenro-Content-SHA256/);
    stubFetch(async () =>
      mockResponse({ text: "content", headers: { "X-Ohenro-Content-SHA256": "abcd" } }),
    );
    await expect(readOutputSource("a.geojson")).rejects.toThrow(/X-Ohenro-Content-SHA256/);
  });
});

describe("writeOutputFile", () => {
  it("PUTs the text body and returns the written file", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | undefined;
    stubFetch(async (url, init) => {
      capturedUrl = url;
      capturedInit = init;
      return mockResponse({ json: { path: "route-editor/projects/ohenro-project-1.json", size: 5 } });
    });
    await expect(writeOutputFile("route-editor/projects/ohenro-project-1.json", "hello")).resolves.toEqual({
      path: "route-editor/projects/ohenro-project-1.json",
      size: 5,
    });
    expect(capturedInit?.method).toBe("PUT");
    expect(capturedInit?.body).toBe("hello");
    expect(capturedInit?.headers).toMatchObject({ "X-Ohenro-Output-API": "1" });
    expect(capturedUrl).toContain("path=");
    expect(capturedUrl).toContain("route-editor%2Fprojects%2Fohenro-project-1.json");
  });

  it("throws the parsed server error on non-2xx", async () => {
    stubFetch(async () =>
      mockResponse({ status: 403, statusText: "Forbidden", json: { error: "Writes are limited to route-editor/" } }),
    );
    await expect(writeOutputFile("forbidden.json", "x")).rejects.toThrow(/Writes are limited/);
  });
});
