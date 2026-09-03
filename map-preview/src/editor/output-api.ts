/**
 * Small fetch-based client for the Vite output API (`/api/output/files` and
 * `/api/output/file`).
 *
 * Paths are always passed URL-encoded via `URLSearchParams`. On a non-2xx
 * response the server's JSON `{error}` message is parsed when possible and
 * wrapped in a useful `Error`; otherwise the HTTP status line is used.
 */

export interface OutputFile {
  path: string;
  size: number;
}

export interface OutputWriteResult {
  path: string;
  size: number;
}

/** Parse a non-2xx response into a useful Error (preferring the JSON body). */
async function responseError(res: Response): Promise<Error> {
  let detail: string | undefined;
  try {
    const data: unknown = await res.json();
    if (data && typeof data === "object" && "error" in data) {
      const message = (data as { error?: unknown }).error;
      if (typeof message === "string") detail = message;
    }
  } catch {
    // Non-JSON body; fall back to the status line below.
  }
  return new Error(detail ?? `HTTP ${res.status} ${res.statusText}`);
}

/** List every output file (path + size). */
export async function listOutputFiles(): Promise<OutputFile[]> {
  const res = await fetch("/api/output/files");
  if (!res.ok) throw await responseError(res);
  const data: unknown = await res.json();
  const files =
    data && typeof data === "object" && Array.isArray((data as { files?: unknown }).files)
      ? (data as { files: OutputFile[] }).files
      : [];
  return files;
}

/** Read an output file's UTF-8 text. */
export async function readOutputFile(path: string): Promise<string> {
  const res = await fetch(`/api/output/file?${new URLSearchParams({ path })}`);
  if (!res.ok) throw await responseError(res);
  return await res.text();
}

/** The lowercase hex SHA-256 of an output source's exact UTF-8 bytes. */
const SHA256_HEX = /^[0-9a-f]{64}$/;

export interface OutputSource {
  text: string;
  sha256: string;
}

/**
 * Read an output file usable as a source, returning its UTF-8 text plus the
 * server-provided SHA-256 of the exact response bytes (in the
 * `X-Ohenro-Content-SHA256` header). The hash lets the import pipeline skip
 * browser `crypto.subtle` (unavailable over plain HTTP on a LAN). The header
 * must be present and a lowercase 64-hex value; anything else is rejected so a
 * hash can never be silently trusted.
 */
export async function readOutputSource(path: string): Promise<OutputSource> {
  const res = await fetch(`/api/output/file?${new URLSearchParams({ path })}`);
  if (!res.ok) throw await responseError(res);
  const sha256 = res.headers.get("X-Ohenro-Content-SHA256") ?? "";
  if (!SHA256_HEX.test(sha256)) {
    throw new Error(`Output source "${path}" is missing a valid X-Ohenro-Content-SHA256 header`);
  }
  return { text: await res.text(), sha256 };
}

/** Write text to an output file (limited to the writable route-editor paths). */
export async function writeOutputFile(path: string, text: string): Promise<OutputWriteResult> {
  const res = await fetch(`/api/output/file?${new URLSearchParams({ path })}`, {
    method: "PUT",
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Ohenro-Output-API": "1",
    },
    body: text,
  });
  if (!res.ok) throw await responseError(res);
  const data: unknown = await res.json();
  const result = (data ?? {}) as { path?: unknown; size?: unknown };
  return {
    path: typeof result.path === "string" ? result.path : path,
    size: typeof result.size === "number" ? result.size : 0,
  };
}
