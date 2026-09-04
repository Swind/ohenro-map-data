"""Point-to-point day planning over the 88sekaiisan effective route graph.

Consumes the Phase 3 ``anchored_route_graph`` (``build-anchors`` output) and
answers day-planning queries: pick any two (or more) points on/near the route
and get the shortest path between them over the effective undirected graph of
``traversal_edges`` (weight = ``length_m``) + ``synthetic_joins`` (weight =
``distance_m``), plus distance / cumulative elevation gain-loss / time stats.

This is deliberately NOT navigation: it never labels the result resolved,
official or navigable, never invents geometry, and route candidates remain
derived from source linework exactly as the graph describes them.

Mechanics:

* Each user point is snapped to the nearest ``traversal_edge`` (shapely
  ``project``/``interpolate``); the snapped edge is split at the projection
  into virtual sub-edges (accurate metre weights via the local equirectangular
  projection), so several points on the same edge stay correctly connected.
* Routing is the same weighted stdlib-heapq Dijkstra used by ``build-sections``
  (deterministic lexicographic tie-break, simple paths only). With waypoints
  the path is the concatenation of the per-leg shortest paths, so each
  intermediate point is forced.
* Elevation is sampled from the GSI DEM SQLite (``output/shikoku-elevation.sqlite``),
  decoding the zstd int16 tiles directly (DEM5 then DEM10 fallback, same
  semantics as ``gsi-dem query-db``); stats are cumulative gain/loss, min/max
  and a Naismith time estimate (5 km/h base + 1 h per 600 m ascent).

Output is deterministic (no timestamp) and written atomically via the shared
``normalize.write_atomic``; on failure the prior output is untouched.
"""

from __future__ import annotations

import json
import math
import sqlite3
import struct
import subprocess

from shapely.geometry import LineString, Point
from shapely.ops import substring

from sekaiisan_henro import normalize, projection, sections

try:
    import zstandard
    _HAS_ZSTD = True
except ImportError:  # pragma: no cover - optional dependency
    zstandard = None
    _HAS_ZSTD = False

# No-data sentinels used by the DEM tile codec (plan §20 + legacy GSI -9999).
_ELEV_NODATA = -32768
_LEGACY_ELEV_NODATA = -9999

# Default sample spacing for the elevation profile along the path.
_SAMPLE_INTERVAL_M = 200.0
# Default maximum snapping distance (metres) from a user point to the route.
_SNAP_MAX_M = 500.0


# --- elevation sampling ------------------------------------------------------


class ElevationSampler:
    """Nearest-cell elevation samples from the tiled GSI DEM SQLite database.

    Decodes the zstd(int16[256*256] LE) tiles directly and mirrors the Rust
    ``gsi-dem query-db`` semantics: DEM5 first, DEM10 fallback on no data.
    """

    def __init__(self, db_path: str):
        if not _HAS_ZSTD:
            raise ImportError(
                "planner elevation sampling requires the 'zstandard' package "
                "(or pass --elevation-bin to use gsi-dem query-db instead)")
        self._conn = sqlite3.connect(db_path)
        meta = dict(self._conn.execute("SELECT key, value FROM metadata"))
        self._grids = {}
        for prefix in ("dem5", "dem10"):
            self._grids[prefix] = (
                float(meta[prefix + ".origin_lat"]),
                float(meta[prefix + ".origin_lon"]),
                float(meta[prefix + ".step_lat"]),
                float(meta[prefix + ".step_lon"]),
            )
        self._tile_size = int(meta.get("tile_size", "256"))
        self._dctx = zstandard.ZstdDecompressor()
        self._cache: dict = {}

    def sample(self, lat: float, lon: float) -> float | None:
        for layer, prefix in ((5, "dem5"), (10, "dem10")):
            origin_lat, origin_lon, step_lat, step_lon = self._grids[prefix]
            gx = math.floor((lon - origin_lon) / step_lon)
            gy = math.floor((origin_lat - lat) / step_lat)
            if gx < 0 or gy < 0:
                continue
            tx, ty, px, py = (gx // 256, gy // 256, gx % 256, gy % 256)
            key = (layer, tx, ty)
            if key not in self._cache:
                row = self._conn.execute(
                    "SELECT data FROM elevation_tiles WHERE layer=? AND "
                    "tile_x=? AND tile_y=?", key).fetchone()
                self._cache[key] = self._dctx.decompress(row[0]) if row else None
            blob = self._cache[key]
            if blob is None:
                continue
            value = struct.unpack_from("<h", blob, (py * 256 + px) * 2)[0]
            if value in (_ELEV_NODATA, _LEGACY_ELEV_NODATA):
                continue
            return float(value)
        return None


class SubprocessElevationSampler:
    """Fallback sampler that shells out to ``gsi-dem query-db`` per point."""

    def __init__(self, db_path: str, binary: str):
        self._db = db_path
        self._binary = binary

    def sample(self, lat: float, lon: float) -> float | None:
        result = subprocess.run(
            [self._binary, "query-db", self._db, "--lat", str(lat), "--lon", str(lon)],
            capture_output=True, text=True, check=False)
        for line in result.stdout.splitlines():
            if line.startswith("Elevation: "):
                body = line[len("Elevation: "):]
                text = body.split()[0]
                if text == "no":
                    return None
                return float(text)
        return None


def _open_sampler(db_path: str, binary: str | None) -> ElevationSampler | SubprocessElevationSampler:
    if _HAS_ZSTD:
        return ElevationSampler(db_path)
    if binary is None:
        raise ImportError("planner elevation sampling needs 'zstandard' or --elevation-bin")
    return SubprocessElevationSampler(db_path, binary)


# --- snapping + virtual edges -------------------------------------------------


def _line_meters(coords) -> float:
    pts = [projection.project_point(lon, lat) for lon, lat in coords]
    return sum(math.hypot(x2 - x1, y2 - y1)
               for (x1, y1), (x2, y2) in zip(pts, pts[1:]))


def _distance_m(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    ax, ay = projection.project_point(lon_a, lat_a)
    bx, by = projection.project_point(lon_b, lat_b)
    return math.hypot(bx - ax, by - ay)


def _snap_point(lines, lon: float, lat: float):
    """Return (edge, fraction, projection_lonlat) for the nearest traversal edge."""
    point = Point(lon, lat)
    best = None
    for edge, line in lines:
        measure = line.project(point)
        frac = measure / line.length if line.length > 0 else 0.0
        proj = line.interpolate(measure)
        dist_m = _distance_m(lon, lat, proj.x, proj.y)
        if best is None or dist_m < best[0]:
            best = (dist_m, edge, frac, (proj.x, proj.y))
    return best


def _build_virtual_graph(graph: dict, points: list[tuple[float, float]],
                         snap_max_m: float) -> tuple[dict, list, dict, dict]:
    """Snap user points and return (adjacency, geometry_map, waypoint_nodes, snaps).

    ``adjacency`` is the effective undirected graph with snapped edges split
    into virtual sub-edges; ``geometry_map`` maps every edge id (including
    virtual sub-edges) to its coordinate list; ``waypoint_nodes`` is the
    routing node id per input point; ``snaps`` documents each projection.
    """
    traversal = sorted(graph["traversal_edges"], key=lambda e: e["id"])
    joins = sorted(graph["synthetic_joins"], key=lambda j: j["id"])
    lines = [(edge, LineString(edge["coordinates"])) for edge in traversal]

    # Snap each point, group by snapped edge (sorted by fraction along edge).
    by_edge: dict = {}
    snaps = []
    for index, (lon, lat) in enumerate(points):
        best = _snap_point(lines, lon, lat)
        if best is None:
            raise ValueError("no routable traversal edge found for point %d" % index)
        dist_m, edge, frac, proj = best
        if dist_m > snap_max_m:
            raise ValueError(
                "point %d (%.5f,%.5f) is %.1fm from the nearest route edge "
                "(max %.0fm); pick a point closer to the route" % (
                    index, lon, lat, dist_m, snap_max_m))
        # Clamp fraction away from the exact endpoints so the projection stays
        # an interior virtual node.
        frac = min(max(frac, 1e-9), 1.0 - 1e-9)
        by_edge.setdefault(edge["id"], []).append({
            "index": index, "frac": frac, "proj": proj,
            "edge": edge, "distance_m": dist_m,
        })
        snaps.append({
            "index": index, "lon": lon, "lat": lat,
            "edge_id": edge["id"], "distance_m": dist_m,
            "projection": [proj[0], proj[1]],
        })

    # Build virtual nodes/edges per snapped edge (several points per edge OK).
    virtual_edges: list[dict] = []
    waypoint_nodes: dict = {}
    snapped_edge_ids: set = set()
    geometry_map: dict = {}
    for edge in traversal:
        geometry_map[edge["id"]] = edge["coordinates"]
    # Joins may lack `coordinates` (endpoint_to_line joins carry only
    # `projected_coordinates`); derive their connector geometry from the
    # anchored node coordinates, exactly as the review-pack exporter does.
    node_coords = {
        node["id"]: list(node["coordinates"])
        for node in graph["nodes"] + graph["synthetic_nodes"] + graph["anchor_nodes"]
        if node.get("coordinates")
    }
    for join in joins:
        if join.get("coordinates"):
            geometry_map[join["id"]] = join["coordinates"]
        elif join["from"] in node_coords and join["to"] in node_coords:
            geometry_map[join["id"]] = [node_coords[join["from"]], node_coords[join["to"]]]
        else:
            raise ValueError("synthetic join %s has no coordinates and no "
                             "anchored node endpoints" % join["id"])

    counter = 0
    for edge_id, snaps_on_edge in by_edge.items():
        edge = snaps_on_edge[0]["edge"]
        snapped_edge_ids.add(edge_id)
        line = LineString(edge["coordinates"])
        ordered = sorted(snaps_on_edge, key=lambda s: s["frac"])
        # node chain: edge.from -> v0 -> v1 -> ... -> edge.to
        chain = [edge["from"]]
        for snap in ordered:
            node_id = "PLN_%s_%02d" % (edge_id, snap["index"])
            waypoint_nodes[snap["index"]] = node_id
            chain.append(node_id)
        chain.append(edge["to"])
        measures = [0.0] + [s["frac"] * line.length for s in ordered] + [line.length]
        for i in range(len(chain) - 1):
            geom = substring(line, measures[i], measures[i + 1])
            coords = [[x, y] for x, y in geom.coords]
            virtual_edges.append({
                "id": "PLV_%d" % counter, "from": chain[i], "to": chain[i + 1],
                "coordinates": coords, "length_m": _line_meters(coords),
            })
            counter += 1
            geometry_map[virtual_edges[-1]["id"]] = coords

    adj = sections._adjacency(
        [e for e in traversal if e["id"] not in snapped_edge_ids], joins)
    for virtual in virtual_edges:
        adj.setdefault(virtual["from"], []).append(
            (virtual["to"], virtual["length_m"], virtual["id"], "forward"))
        adj.setdefault(virtual["to"], []).append(
            (virtual["from"], virtual["length_m"], virtual["id"], "reverse"))

    return adj, geometry_map, waypoint_nodes, snaps


# --- path stitching + elevation -------------------------------------------------


def _stitch_leg(path: dict, geometry_map: dict) -> list:
    coords: list = []
    for i, edge_id in enumerate(path["edge_ids"]):
        pts = [list(c) for c in geometry_map[edge_id]]
        if path["directions"][i] == "reverse":
            pts.reverse()
        if coords and coords[-1] == pts[0]:
            pts = pts[1:]
        coords.extend(pts)
    return coords


def _elevation_profile(sampler, coords: list, interval_m: float) -> tuple[list, list]:
    """Return (sampled_m, profile) where profile is [lon, lat, elev] per sample."""
    metres = [projection.project_point(lon, lat) for lon, lat in coords]
    cum = [0.0]
    for (x1, y1), (x2, y2) in zip(metres, metres[1:]):
        cum.append(cum[-1] + math.hypot(x2 - x1, y2 - y1))
    total = cum[-1]
    offsets = [i * interval_m for i in range(int(total / interval_m) + 1)]
    if not offsets or offsets[-1] < total:
        offsets.append(total)
    profile = []
    sampled = []
    for offset in offsets:
        i = 0
        while i < len(cum) - 1 and cum[i + 1] < offset:
            i += 1
        if cum[i + 1] - cum[i] > 0:
            t = (offset - cum[i]) / (cum[i + 1] - cum[i])
        else:
            t = 0.0
        x = metres[i][0] + (metres[i + 1][0] - metres[i][0]) * t
        y = metres[i][1] + (metres[i + 1][1] - metres[i][1]) * t
        lon, lat = projection.unproject_point(x, y)
        elev = sampler.sample(lat, lon)
        profile.append([round(lon, 6), round(lat, 6), elev])
        sampled.append(elev)
    return sampled, profile


def _elevation_stats(sampled: list) -> dict:
    values = [e for e in sampled if e is not None]
    gain = 0.0
    loss = 0.0
    prev = None
    for value in values:
        if prev is not None:
            delta = value - prev
            if delta > 0:
                gain += delta
            else:
                loss += -delta
        prev = value
    stats = {
        "samples": len(sampled),
        "samples_with_data": len(values),
        "start_m": values[0] if values else None,
        "end_m": values[-1] if values else None,
        "min_m": min(values) if values else None,
        "max_m": max(values) if values else None,
        "gain_m": round(gain, 1),
        "loss_m": round(loss, 1),
    }
    if values:
        stats["net_m"] = round(values[-1] - values[0], 1)
    return stats


def _naismith_hours(distance_m: float, gain_m: float) -> float:
    return distance_m / 1000.0 / 5.0 + gain_m / 600.0


# --- planning -------------------------------------------------------------------


def plan_route(graph: dict, points: list[tuple[float, float]],
               sampler, sample_interval_m: float = _SAMPLE_INTERVAL_M,
               snap_max_m: float = _SNAP_MAX_M) -> tuple[dict, list]:
    """Run the day-planning query over the effective graph.

    ``points`` is an ordered list of ``(lon, lat)`` (start, optional waypoints,
    end). Returns ``(report, profile)`` where ``profile`` is the sparse
    elevation profile ``[lon, lat, elev]`` used for stats and where ``report``
    additionally carries ``dense_path`` (every route vertex with per-vertex
    elevation) for full-resolution geometry rendering.
    """
    sections.validate_anchored_graph(graph)
    if len(points) < 2:
        raise ValueError("plan requires at least two points (start and end)")
    adj, geometry_map, waypoint_nodes, snaps = _build_virtual_graph(
        graph, points, snap_max_m)

    legs = []
    path_coords: list = []
    disconnected = False
    for i in range(len(points) - 1):
        start = waypoint_nodes[i]
        goal = waypoint_nodes[i + 1]
        result = sections._shortest_path(adj, start, goal, frozenset())
        leg = {"from_index": i, "to_index": i + 1,
               "from_node": start, "to_node": goal}
        if result is None:
            leg["status"] = "disconnected"
            disconnected = True
        else:
            leg["status"] = "candidate"
            leg["length_m"] = round(result["weight"], 3)
            leg["edge_ids"] = list(result["edge_ids"])
            leg["node_ids"] = list(result["node_ids"])
            leg_coords = _stitch_leg(result, geometry_map)
            if path_coords and path_coords[-1] == leg_coords[0]:
                leg_coords = leg_coords[1:]
            path_coords.extend(leg_coords)
        legs.append(leg)

    if disconnected or not path_coords:
        path_status = "disconnected"
        length_m = None
        elevation = {"samples": 0, "samples_with_data": 0}
        time_estimate = None
        profile = []
        dense = []
    else:
        path_status = "candidate"
        length_m = _line_meters(path_coords)
        sampled, profile = _elevation_profile(sampler, path_coords, sample_interval_m)
        elevation = _elevation_stats(sampled)
        elevation["interval_m"] = sample_interval_m
        gain = elevation.get("gain_m", 0.0)
        time_estimate = {"hours_naismith": round(_naismith_hours(length_m, gain), 2)}
        # Full path geometry with per-vertex elevation (the sampled `profile`
        # stays the sparse stats grid; the drawn line uses every route vertex).
        dense = [[round(lon, 6), round(lat, 6), sampler.sample(lat, lon)]
                 for lon, lat in path_coords]

    return {
        "schema_version": 1,
        "kind": "day_plan",
        "dataset_id": graph["dataset_id"],
        "snapshot_sha256": graph["snapshot_sha256"],
        "projection": dict(graph["projection"]),
        "limitation": graph["limitation"],
        "note": "point-to-point candidate over the effective undirected graph of "
                "traversal_edges + synthetic_joins only (source edges and temple "
                "offset distances are never routed). Shortest by metre weight with "
                "deterministic tie-break; waypoints force the path through them. "
                "Not resolved, official or navigable.",
        "points": snaps,
        "waypoint_nodes": [waypoint_nodes[i] for i in range(len(points))],
        "legs": legs,
        "path": {
            "status": path_status,
            "length_m": round(length_m, 3) if length_m is not None else None,
            "length_km": round(length_m / 1000.0, 2) if length_m is not None else None,
        },
        "elevation": elevation,
        "time_estimate": time_estimate,
        "snap_max_m": snap_max_m,
        "sample_interval_m": sample_interval_m,
        "dense_path": dense,
        "accounting": {
            "points": len(points),
            "legs": len(legs),
            "virtual_edges": sum(1 for l in legs if l.get("status") == "candidate"),
            "disconnected_legs": sum(1 for l in legs if l.get("status") == "disconnected"),
            "note": "deterministic output; no timestamp.",
        },
    }, profile


def build_plan_geojson(report: dict, profile: list) -> dict:
    """GeoJSON feature collection with the planned path (line) + points."""
    features = []
    if report["path"]["status"] == "candidate":
        coords = report.get("dense_path")
        if not coords:
            coords = [[lon, lat, elev] for lon, lat, elev in profile] if profile else []
        if coords:
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "planned_route",
                    "status": report["path"]["status"],
                    "length_m": report["path"]["length_m"],
                    "gain_m": report["elevation"].get("gain_m"),
                    "loss_m": report["elevation"].get("loss_m"),
                    "min_m": report["elevation"].get("min_m"),
                    "max_m": report["elevation"].get("max_m"),
                    "start_m": report["elevation"].get("start_m"),
                    "end_m": report["elevation"].get("end_m"),
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            })
    for point in report["points"]:
        features.append({
            "type": "Feature",
            "properties": {
                "kind": "waypoint",
                "index": point["index"],
                "snap_edge_id": point["edge_id"],
                "snap_distance_m": round(point["distance_m"], 1),
            },
            "geometry": {"type": "Point",
                         "coordinates": [point["lon"], point["lat"]]},
        })
    return {"type": "FeatureCollection", "name": "sekaiisan-henro-plan",
            "features": features}


def run_plan(input_path: str, points: list[tuple[float, float]],
             elevation_db: str, elevation_bin: str | None,
             sample_interval_m: float, snap_max_m: float,
             output_path: str, geojson_path: str) -> dict:
    with open(input_path, encoding="utf-8") as stream:
        graph = json.load(stream)
    sampler = _open_sampler(elevation_db, elevation_bin)
    report, profile = plan_route(graph, points, sampler, sample_interval_m, snap_max_m)
    normalize.write_atomic(output_path, report)
    if geojson_path:
        geojson = build_plan_geojson(report, profile)
        normalize.write_atomic(geojson_path, geojson)
    return report


if __name__ == "__main__":
    raise SystemExit("use: python3 -m sekaiisan_henro plan --help")