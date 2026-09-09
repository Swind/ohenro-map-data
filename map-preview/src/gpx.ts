export interface GpxPointInput {
  lon: number;
  lat: number;
  ele?: number | null;
  name?: string;
}

export interface GpxBuildOptions {
  name?: string;
  desc?: string;
  maxPoints?: number;
  smoothElevation?: boolean;
  smoothingWindow?: number;
}

export interface GpxCoord {
  lon: number;
  lat: number;
  ele: number | null;
}

const XML_NS =
  "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd";

function finiteOrNull(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function esc(s: string): string {
  const text = String(s).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

export function fillElevationGaps(coords: GpxCoord[]): GpxCoord[] {
  const out = coords.map((c) => ({ ...c }));
  const known = out
    .map((c, i) => (c.ele !== null ? i : -1))
    .filter((i) => i >= 0);
  if (known.length === 0 || known.length === out.length) return out;
  const first = known[0];
  const last = known[known.length - 1];
  for (let i = 0; i < first; i++) out[i].ele = out[first].ele;
  for (let i = last + 1; i < out.length; i++) out[i].ele = out[last].ele;
  for (let k = 0; k < known.length - 1; k++) {
    const a = known[k];
    const b = known[k + 1];
    if (b - a <= 1) continue;
    const ea = out[a].ele as number;
    const eb = out[b].ele as number;
    for (let i = a + 1; i < b; i++) {
      const t = (i - a) / (b - a);
      out[i].ele = ea + (eb - ea) * t;
    }
  }
  return out;
}

export function smoothElevation(coords: GpxCoord[], window = 5): GpxCoord[] {
  const out = coords.map((c) => ({ ...c }));
  const n = out.length;
  if (n < 3 || window < 3) return out;
  const half = Math.floor(window / 2);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    let count = 0;
    const lo = Math.max(0, i - half);
    const hi = Math.min(n - 1, i + half);
    for (let j = lo; j <= hi; j++) {
      const e = coords[j].ele;
      if (e === null) continue;
      sum += e;
      count++;
    }
    if (count > 0) out[i].ele = sum / count;
  }
  return out;
}

function triAreaAt(
  xs: number[],
  ys: number[],
  prev: number,
  mid: number,
  next: number,
): number {
  const px = xs[prev];
  const py = ys[prev];
  const mx = xs[mid];
  const my = ys[mid];
  const nx = xs[next];
  const ny = ys[next];
  return Math.abs((mx - px) * (ny - py) - (my - py) * (nx - px));
}

export function simplifyToBudget(coords: GpxCoord[], maxPoints: number): GpxCoord[] {
  const n = coords.length;
  if (maxPoints < 2) return coords.slice();
  if (n <= maxPoints) return coords.slice();
  const xs = new Array<number>(n);
  const ys = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    xs[i] = coords[i].lon;
    ys[i] = coords[i].lat;
  }
  const prev = new Array<number>(n);
  const next = new Array<number>(n);
  const area = new Float64Array(n);
  const alive = new Array<boolean>(n).fill(true);
  for (let i = 0; i < n; i++) {
    prev[i] = i - 1;
    next[i] = i + 1;
  }
  const heap: Array<{ area: number; i: number }> = [];
  const lt = (a: { area: number; i: number }, b: { area: number; i: number }): boolean =>
    a.area < b.area || (a.area === b.area && a.i < b.i);
  const push = (entry: { area: number; i: number }): void => {
    heap.push(entry);
    let i = heap.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!lt(heap[i], heap[parent])) break;
      [heap[i], heap[parent]] = [heap[parent], heap[i]];
      i = parent;
    }
  };
  const pop = (): { area: number; i: number } | undefined => {
    if (heap.length === 0) return undefined;
    const top = heap[0];
    const tail = heap.pop()!;
    if (heap.length > 0) {
      heap[0] = tail;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let smallest = i;
        if (l < heap.length && lt(heap[l], heap[smallest])) smallest = l;
        if (r < heap.length && lt(heap[r], heap[smallest])) smallest = r;
        if (smallest === i) break;
        [heap[i], heap[smallest]] = [heap[smallest], heap[i]];
        i = smallest;
      }
    }
    return top;
  };
  const update = (i: number): void => {
    const p = prev[i];
    const q = next[i];
    const a = triAreaAt(xs, ys, p, i, q);
    area[i] = a;
    push({ area: a, i });
  };
  for (let i = 1; i < n - 1; i++) {
    area[i] = triAreaAt(xs, ys, i - 1, i, i + 1);
    push({ area: area[i], i });
  }
  let remaining = n;
  const target = maxPoints;
  while (remaining > target) {
    const entry = pop();
    if (!entry) break;
    const i = entry.i;
    if (!alive[i]) continue;
    if (area[i] !== entry.area) {
      push({ area: area[i], i });
      continue;
    }
    alive[i] = false;
    remaining--;
    const p = prev[i];
    const q = next[i];
    if (p >= 0) next[p] = q;
    if (q < n) prev[q] = p;
    if (p >= 1 && alive[p]) update(p);
    if (q <= n - 2 && alive[q]) update(q);
  }
  const out: GpxCoord[] = [];
  for (let i = 0; i < n; i++) {
    if (alive[i]) out.push(coords[i]);
  }
  return out;
}

function pointXml(
  tag: string,
  p: GpxPointInput & { name?: string },
  withEle: boolean,
): string {
  const lat = p.lat.toFixed(7);
  const lon = p.lon.toFixed(7);
  let inner = "";
  if (p.name !== undefined && p.name !== "") inner += `<name>${esc(p.name)}</name>`;
  if (withEle) {
    const ele = finiteOrNull(p.ele);
    if (ele !== null) inner += `<ele>${ele.toFixed(1)}</ele>`;
  }
  return `<${tag} lat="${lat}" lon="${lon}">${inner}</${tag}>`;
}

export function buildGpx(
  coords: GpxPointInput[],
  waypoints: GpxPointInput[] = [],
  options: GpxBuildOptions = {},
): string {
  const maxPoints = options.maxPoints ?? 4000;
  const smooth = options.smoothElevation ?? true;
  const window = options.smoothingWindow ?? 5;
  let pts: GpxCoord[] = coords.map((c) => ({
    lon: c.lon,
    lat: c.lat,
    ele: finiteOrNull(c.ele),
  }));
  pts = fillElevationGaps(pts);
  if (smooth) pts = smoothElevation(pts, window);
  pts = simplifyToBudget(pts, maxPoints);

  const lines: string[] = [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<gpx version="1.1" creator="ohenro-map-preview" xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="${XML_NS}">`,
  ];
  if (options.name !== undefined || options.desc !== undefined) {
    lines.push("  <metadata>");
    if (options.name !== undefined) lines.push(`    <name>${esc(options.name)}</name>`);
    if (options.desc !== undefined) lines.push(`    <desc>${esc(options.desc)}</desc>`);
    lines.push("  </metadata>");
  }
  for (const w of waypoints) {
    lines.push(`  ${pointXml("wpt", w, false)}`);
  }
  lines.push("  <trk>");
  if (options.name !== undefined) lines.push(`    <name>${esc(options.name)}</name>`);
  lines.push("    <trkseg>");
  for (const p of pts) {
    lines.push(`      ${pointXml("trkpt", p, true)}`);
  }
  lines.push("    </trkseg>");
  lines.push("  </trk>");
  lines.push("</gpx>");
  return lines.join("\n") + "\n";
}
