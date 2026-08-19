"""Export the normalized Shikoku Nature Trail dataset for vector tiles."""

from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter, defaultdict

from shikoku_nature_trail.storage import atomic_write_json, read_json


_PUNCTUATION = str.maketrans("", "", "()（）[]［］「」『』【】〔〕〈〉《》・･、，,。．.")
_COUNT_KEYS = (
    "courses", "route_ids", "route_segments", "route_coordinate_points",
    "kml_pois", "linked_tourism_spots", "unmatched_tourism_spots",
    "unmatched_pois", "ambiguous_names", "photo_points", "matched_photo_points",
)


def normalize_name(value):
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).translate(_PUNCTUATION)
    return re.sub(r"\s+", "", value).casefold()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _validate_position(position, context):
    _require(isinstance(position, list) and len(position) >= 2,
             "%s: coordinate must contain longitude and latitude" % context)
    _require(all(isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) for value in position),
             "%s: coordinate values must be finite numbers" % context)
    _require(-180 <= position[0] <= 180 and -90 <= position[1] <= 90,
             "%s: longitude/latitude out of range" % context)


def _geometry_parts(geometry, context):
    _require(isinstance(geometry, dict), "%s: geometry must be an object" % context)
    kind = geometry.get("type")
    if kind == "Point":
        coordinates = geometry.get("coordinates")
        _validate_position(coordinates, context)
        return [(kind, {"type": kind, "coordinates": coordinates[:2]})]
    if kind == "LineString":
        coordinates = geometry.get("coordinates")
        _require(isinstance(coordinates, list) and len(coordinates) >= 2,
                 "%s: LineString must contain at least two coordinates" % context)
        for index, position in enumerate(coordinates, 1):
            _validate_position(position, "%s coordinate %d" % (context, index))
        return [(kind, {"type": kind,
                        "coordinates": [position[:2] for position in coordinates]})]
    if kind == "GeometryCollection":
        geometries = geometry.get("geometries")
        _require(isinstance(geometries, list) and geometries,
                 "%s: GeometryCollection must not be empty" % context)
        parts = []
        for index, child in enumerate(geometries, 1):
            parts.extend(_geometry_parts(child, "%s geometry %d" % (context, index)))
        return parts
    raise ValueError("%s: unsupported geometry type %r" % (context, kind))


def _content_id(post_id, index):
    return "SNT_%s_S%03d" % (post_id, index)


def export_map(normalized_path, routes_path, pois_path, report_path):
    dataset = read_json(normalized_path)
    _require(isinstance(dataset, dict), "normalized input must be an object")
    _require(dataset.get("schema_version") == 1, "normalized input schema_version must be 1")
    courses = dataset.get("courses")
    _require(isinstance(courses, list), "normalized input courses must be an array")

    routes = []
    pois = []
    prefectures = defaultdict(Counter)
    unresolved_spots = []
    unresolved_pois = []
    ambiguous = []
    photo_matches = 0
    route_points = 0
    seen_posts = set()

    for course_index, course in enumerate(courses, 1):
        context = "course %d" % course_index
        _require(isinstance(course, dict), "%s must be an object" % context)
        post_id = course.get("source_post_id")
        _require(isinstance(post_id, (str, int)) and not isinstance(post_id, bool)
                 and str(post_id), "%s source_post_id is required" % context)
        post_id = str(post_id)
        _require(post_id not in seen_posts, "duplicate source_post_id: %s" % post_id)
        seen_posts.add(post_id)
        pref = course.get("prefecture")
        _require(isinstance(pref, str) and pref, "course %s prefecture is required" % post_id)
        placemarks = course.get("kml", {}).get("placemarks")
        _require(isinstance(placemarks, list), "course %s kml.placemarks must be an array" % post_id)

        line_parts = []
        point_parts = []
        for placemark_index, placemark in enumerate(placemarks, 1):
            pcontext = "course %s placemark %d" % (post_id, placemark_index)
            _require(isinstance(placemark, dict), "%s must be an object" % pcontext)
            for kind, geometry in _geometry_parts(placemark.get("geometry"), pcontext):
                item = (placemark.get("name"), geometry)
                (line_parts if kind == "LineString" else point_parts).append(item)
        _require(line_parts, "course %s has no LineString route geometry" % post_id)

        route_id = "SNT_%s" % post_id
        common = {
            "route_id": route_id,
            "source_post_id": course.get("source_post_id"),
            "name": course.get("name_ja") or course.get("title"),
            "pref": pref,
            "course_number": course.get("course_number"),
            "distance_km": course.get("distance_km"),
            "difficulty": course.get("difficulty"),
            "kind": "main",
        }
        for segment, (_, geometry) in enumerate(line_parts, 1):
            route_points += len(geometry["coordinates"])
            routes.append({
                "type": "Feature",
                "properties": {**common, "segment_id": "%s_L%03d" % (route_id, segment),
                               "seg": segment, "seg_count": len(line_parts)},
                "geometry": geometry,
            })

        spots = course.get("tourism_spots")
        _require(isinstance(spots, list), "course %s tourism_spots must be an array" % post_id)
        spot_groups = defaultdict(list)
        point_groups = defaultdict(list)
        for spot_index, spot in enumerate(spots, 1):
            _require(isinstance(spot, dict), "course %s tourism spot %d must be an object" %
                     (post_id, spot_index))
            spot_groups[normalize_name(spot.get("title"))].append(spot_index)
        for point_index, (name, _) in enumerate(point_parts, 1):
            point_groups[normalize_name(name)].append(point_index)

        linked_spots = {}
        linked_points = {}
        for name in sorted(set(spot_groups) | set(point_groups)):
            spot_indexes = spot_groups.get(name, [])
            point_indexes = point_groups.get(name, [])
            if name and len(spot_indexes) == len(point_indexes) == 1:
                spot_index, point_index = spot_indexes[0], point_indexes[0]
                linked_spots[spot_index] = point_index
                linked_points[point_index] = spot_index
            elif name and (len(spot_indexes) > 1 or len(point_indexes) > 1):
                prefectures[pref]["ambiguous_names"] += 1
                ambiguous.append({
                    "route_id": route_id,
                    "normalized_name": name,
                    "tourism_spots": [spots[i - 1].get("title") for i in spot_indexes],
                    "pois": [point_parts[i - 1][0] for i in point_indexes],
                })

        photo = course.get("photo_point")
        if isinstance(photo, dict):
            prefectures[pref]["photo_points"] += 1
            photo_name = normalize_name(photo.get("title"))
            if photo_name and len(point_groups.get(photo_name, [])) == 1:
                photo_matches += 1
                prefectures[pref]["matched_photo_points"] += 1

        for point_index, (name, geometry) in enumerate(point_parts, 1):
            poi_id = "%s_P%04d" % (route_id, point_index)
            properties = {
                "poi_id": poi_id,
                "route_id": route_id,
                "source_post_id": course.get("source_post_id"),
                "name": name,
                "kind": "tourism_spot" if point_index in linked_points else "kml_poi",
                "content_id": (_content_id(post_id, linked_points[point_index])
                               if point_index in linked_points else None),
            }
            pois.append({"type": "Feature", "properties": properties, "geometry": geometry,
                         "tippecanoe": {"minzoom": 10}})
            if point_index not in linked_points:
                unresolved_pois.append({"poi_id": poi_id, "route_id": route_id, "name": name})
        for spot_index, spot in enumerate(spots, 1):
            if spot_index not in linked_spots:
                unresolved_spots.append({
                    "content_id": _content_id(post_id, spot_index),
                    "route_id": route_id,
                    "number": spot.get("number"),
                    "name": spot.get("title"),
                })

        counts = prefectures[pref]
        counts["courses"] += 1
        counts["route_ids"] += 1
        counts["route_segments"] += len(line_parts)
        counts["route_coordinate_points"] += sum(len(g["coordinates"]) for _, g in line_parts)
        counts["kml_pois"] += len(point_parts)
        counts["linked_tourism_spots"] += len(linked_spots)
        counts["unmatched_tourism_spots"] += len(spots) - len(linked_spots)
        counts["unmatched_pois"] += len(point_parts) - len(linked_points)

    totals = Counter()
    for counts in prefectures.values():
        totals.update(counts)
    _require(totals["ambiguous_names"] == len(ambiguous), "ambiguous name count mismatch")
    _require(totals["matched_photo_points"] == photo_matches, "photo point count mismatch")
    report = {
        "schema_version": 1,
        "source": dataset.get("source"),
        "totals": dict(totals),
        "by_prefecture": {
            pref: {key: counts[key] for key in _COUNT_KEYS}
            for pref, counts in prefectures.items()
        },
        "unmatched_tourism_spots": unresolved_spots,
        "unmatched_pois": unresolved_pois,
        "ambiguous_names": ambiguous,
    }
    atomic_write_json(os.path.abspath(routes_path), {"type": "FeatureCollection", "features": routes})
    atomic_write_json(os.path.abspath(pois_path), {"type": "FeatureCollection", "features": pois})
    atomic_write_json(os.path.abspath(report_path), report)
    return report["totals"]
