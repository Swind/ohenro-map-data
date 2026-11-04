import { mkdtemp, mkdir, writeFile, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "vite";
import { expect, test } from "vitest";
import { outputApiPlugin } from "./output-api-plugin";

test("source outputs are readable, archives stay private, and writes stay in route-editor", async () => {
  const root = await mkdtemp(join(tmpdir(), "ohenro-layout-"));
  const output = join(root, "output");
  const datasets = join(root, "datasets");
  await mkdir(output);
  await mkdir(join(datasets, "sample", "output"), { recursive: true });
  await mkdir(join(datasets, "sample", "raw"));
  await writeFile(join(datasets, "sample", "output", "routes.geojson"), "{}");
  await writeFile(join(datasets, "sample", "raw", "private.json"), "secret");
  await symlink(join(datasets, "sample", "raw", "private.json"), join(datasets, "sample", "output", "link.json"));
  const server = await createServer({
    configFile: false,
    root,
    plugins: [outputApiPlugin(output, datasets)],
    server: { host: "127.0.0.1", port: 0 },
  });
  try {
    await server.listen();
    const address = server.httpServer!.address() as { port: number };
    const base = `http://127.0.0.1:${address.port}/api/output`;
    const list = await (await fetch(`${base}/files`)).json();
    expect(list.files.map((f: { path: string }) => f.path)).toEqual(["datasets/sample/output/routes.geojson"]);
    const file = (path: string, method = "GET") => fetch(`${base}/file?${new URLSearchParams({ path })}`, {
      method,
      ...(method === "PUT" ? { headers: { "x-ohenro-output-api": "1" }, body: "{}" } : {}),
    });
    expect(await (await file("datasets/sample/output/routes.geojson")).text()).toBe("{}");
    expect((await file("datasets/sample/raw/private.json")).status).toBe(404);
    expect((await file("datasets/sample/output/../raw/private.json")).status).toBe(400);
    expect((await file("datasets/sample/output/link.json")).status).toBe(403);
    expect((await file("datasets/sample/output/routes.geojson", "PUT")).status).toBe(403);
    expect((await file("route-editor/projects/test.json", "PUT")).status).toBe(200);
    expect(await readFile(join(output, "route-editor/projects/test.json"), "utf8")).toBe("{}");
  } finally {
    await server.close();
    await rm(root, { recursive: true, force: true });
  }
});
