import { createHash, randomBytes } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readdir,
  realpath,
  rename,
  rm,
  stat,
} from "node:fs/promises";
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const ALLOWED_EXTENSIONS = new Set([".json", ".geojson", ".kml"]);
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const WRITABLE_PATH = /^route-editor\/(projects|final|qa)\/[A-Za-z0-9][A-Za-z0-9._-]*\.(json|geojson|kml)$/;

interface OutputFile {
  path: string;
  size: number;
}

function json(res: ServerResponse, status: number, value: unknown): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(value));
}

function error(res: ServerResponse, status: number, message: string): void {
  json(res, status, { error: message });
}

function validRelativePath(value: string): boolean {
  if (!value || value.includes("\0") || value.includes("\\") || isAbsolute(value)) return false;
  return value.split("/").every((part) => part !== "" && part !== "." && part !== "..");
}

function inside(root: string, target: string): boolean {
  const rel = relative(root, target);
  return rel === "" || (!rel.startsWith(`..${sep}`) && rel !== ".." && !isAbsolute(rel));
}

async function listFiles(directory: string, prefix = ""): Promise<OutputFile[]> {
  const out: OutputFile[] = [];
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isSymbolicLink()) continue;
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolutePath = join(directory, entry.name);
    if (entry.isDirectory()) {
      out.push(...await listFiles(absolutePath, relativePath));
    } else if (entry.isFile() && ALLOWED_EXTENSIONS.has(extname(entry.name).toLowerCase())) {
      const info = await stat(absolutePath);
      out.push({ path: relativePath, size: info.size });
    }
  }
  return out;
}

async function readBody(req: IncomingMessage): Promise<Buffer> {
  const declared = Number(req.headers["content-length"] ?? 0);
  if (Number.isFinite(declared) && declared > MAX_FILE_BYTES) throw new Error("FILE_TOO_LARGE");
  const chunks: Buffer[] = [];
  let size = 0;
  let tooLarge = false;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_FILE_BYTES) {
      tooLarge = true;
      continue;
    }
    chunks.push(buffer);
  }
  if (tooLarge) throw new Error("FILE_TOO_LARGE");
  return Buffer.concat(chunks);
}

async function atomicWrite(path: string, body: Buffer): Promise<void> {
  const temporary = join(
    dirname(path),
    `.${path.split(sep).pop()}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`,
  );
  try {
    const handle = await open(temporary, "wx", 0o644);
    try {
      await handle.writeFile(body);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, path);
    const parent = await open(dirname(path), "r");
    try {
      await parent.sync();
    } finally {
      await parent.close();
    }
  } catch (cause) {
    try {
      await rm(temporary, { force: true });
    } catch {
      // Preserve the actual write failure; temporary cleanup is best effort.
    }
    throw cause;
  }
}

async function ensureDirectory(parent: string, name: string, root: string): Promise<string> {
  const path = join(parent, name);
  try {
    await mkdir(path);
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code !== "EEXIST") throw cause;
  }
  const info = await lstat(path);
  const canonical = await realpath(path);
  if (!info.isDirectory() || info.isSymbolicLink() || !inside(root, canonical)) {
    throw new Error(`Unsafe output directory: ${path}`);
  }
  return canonical;
}

export function outputApiPlugin(outputDirectory: string, datasetDirectory?: string): Plugin {
  const outputRoot = resolve(outputDirectory);
  return {
    name: "ohenro-output-api",
    async configureServer(server) {
      const root = await realpath(outputRoot);
      const datasetOutputs = new Map<string, string>();
      if (datasetDirectory) {
        const datasetRoot = await realpath(datasetDirectory);
        for (const entry of await readdir(datasetRoot, { withFileTypes: true })) {
          if (!entry.isDirectory()) continue;
          const directory = join(datasetRoot, entry.name, "output");
          try {
            const info = await lstat(directory);
            const canonical = await realpath(directory);
            if (info.isDirectory() && !info.isSymbolicLink() && inside(datasetRoot, canonical)) {
              datasetOutputs.set(`datasets/${entry.name}/output/`, canonical);
            }
          } catch (cause) {
            if ((cause as NodeJS.ErrnoException).code !== "ENOENT") throw cause;
          }
        }
      }
      const routeEditor = await ensureDirectory(root, "route-editor", root);
      await Promise.all([
        ensureDirectory(routeEditor, "projects", root),
        ensureDirectory(routeEditor, "final", root),
        ensureDirectory(routeEditor, "qa", root),
      ]);
      server.middlewares.use(async (req, res, next) => {
        const requestUrl = new URL(req.url ?? "/", "http://localhost");
        if (requestUrl.pathname === "/api/output/files" && req.method === "GET") {
          try {
            const files = await listFiles(outputRoot);
            for (const [prefix, directory] of datasetOutputs) {
              files.push(...await listFiles(directory, prefix.slice(0, -1)));
            }
            files.sort((a, b) => a.path.localeCompare(b.path));
            json(res, 200, { files });
          } catch (cause) {
            error(res, 500, `Could not list output: ${(cause as Error).message}`);
          }
          return;
        }

        if (requestUrl.pathname !== "/api/output/file") {
          next();
          return;
        }

        const path = requestUrl.searchParams.get("path") ?? "";
        if (!validRelativePath(path) || !ALLOWED_EXTENSIONS.has(extname(path).toLowerCase())) {
          error(res, 400, "Invalid output path");
          return;
        }

        if (req.method === "GET") {
          try {
            const source = [...datasetOutputs].find(([prefix]) => path.startsWith(prefix));
            const readRoot = source?.[1] ?? outputRoot;
            const readPath = source ? path.slice(source[0].length) : path;
            const root = await realpath(readRoot);
            const target = resolve(readRoot, readPath);
            const targetInfo = await lstat(target);
            const canonicalTarget = await realpath(target);
            if (!targetInfo.isFile() || targetInfo.isSymbolicLink() || !inside(root, canonicalTarget)) {
              error(res, 403, "Output path is not a regular in-tree file");
              return;
            }
            if (targetInfo.size > MAX_FILE_BYTES) {
              error(res, 413, `Output file exceeds ${MAX_FILE_BYTES} bytes`);
              return;
            }
            const handle = await open(canonicalTarget, "r");
            try {
              const body = await handle.readFile();
              res.statusCode = 200;
              res.setHeader("Content-Type", "text/plain; charset=utf-8");
              res.setHeader("Cache-Control", "no-store");
              res.setHeader("X-Ohenro-Content-SHA256", createHash("sha256").update(body).digest("hex"));
              res.end(body);
            } finally {
              await handle.close();
            }
          } catch (cause) {
            const code = (cause as NodeJS.ErrnoException).code;
            error(res, code === "ENOENT" ? 404 : 500, code === "ENOENT" ? "Output file not found" : (cause as Error).message);
          }
          return;
        }

        if (req.method === "PUT") {
          if (req.headers["x-ohenro-output-api"] !== "1") {
            error(res, 403, "Missing output API request header");
            return;
          }
          if (!WRITABLE_PATH.test(path)) {
            error(res, 403, "Writes are limited to route-editor/{projects,final,qa}/");
            return;
          }
          try {
            const body = await readBody(req);
            const root = await realpath(outputRoot);
            const target = resolve(outputRoot, path);
            const parent = dirname(target);
            const canonicalParent = await realpath(parent);
            if (!inside(root, canonicalParent)) {
              error(res, 403, "Output write escaped the output directory");
              return;
            }
            await atomicWrite(target, body);
            json(res, 200, { path, size: body.length });
          } catch (cause) {
            if ((cause as Error).message === "FILE_TOO_LARGE") {
              error(res, 413, `Output file exceeds ${MAX_FILE_BYTES} bytes`);
            } else {
              error(res, 500, `Could not write output: ${(cause as Error).message}`);
            }
          }
          return;
        }

        res.setHeader("Allow", "GET, PUT");
        error(res, 405, "Method not allowed");
      });
    },
  };
}
