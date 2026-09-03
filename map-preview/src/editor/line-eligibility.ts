/**
 * Route-leg eligibility for imported source line features.
 *
 * Not every line on an imported source is usable as a route leg. The derived
 * QA/GeoJSON exports carry POI→anchor `poi_offset` lines and inter-leg `gap`
 * lines that are purely visualisation diagnostics (`visualization_only: true`,
 * sometimes also `review_visualization_only: true`). Those diagnostics remain
 * visible context on screen but must never be added as legs, highlighted on
 * hover, or reported as authoritative line hits.
 *
 * This module centralises that decision as a shared pure predicate plus an
 * equivalent MapLibre expression filter, so the source hitbox (rendered
 * query), the authoritative hit-test branch, and hover highlighting all agree
 * without duplicating the rule. No other line is excluded: every explicit
 * source/synthetic line that is not one of the diagnostics above is eligible —
 * the editor never guesses beyond these markers.
 */

import type { FilterSpecification } from "maplibre-gl";
import type { GeoJSONFeature } from "./model";

/** A line geometry (LineString or MultiLineString) — the only leg candidates. */
export const LINE_GEOMETRY_FILTER: FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "LineString"],
  ["==", ["geometry-type"], "MultiLineString"],
];

/** Diagnostic markers, mirrored in the pure predicate and the MapLibre filter. */
const NOT_VISUALIZATION_ONLY: FilterSpecification = ["!=", ["get", "visualization_only"], true];
const NOT_REVIEW_VISUALIZATION_ONLY: FilterSpecification = [
  "!=",
  ["get", "review_visualization_only"],
  true,
];
const NOT_DIAGNOSTIC_KIND: FilterSpecification = [
  "all",
  ["!=", ["get", "kind"], "poi_offset"],
  ["!=", ["get", "kind"], "gap"],
  ["!=", ["get", "type"], "poi_offset"],
  ["!=", ["get", "type"], "gap"],
];

/**
 * MapLibre filter that accepts only route-eligible line features (geometry +
 * property markers). Used as the hitbox layer filter so rendered candidate
 * discovery never returns a diagnostic as a selectable line, while the display
 * line visual keeps an unfiltered filter so diagnostics remain visible context.
 */
export const ROUTE_ELIGIBLE_LINE_FILTER: FilterSpecification = [
  "all",
  LINE_GEOMETRY_FILTER,
  NOT_VISUALIZATION_ONLY,
  NOT_REVIEW_VISUALIZATION_ONLY,
  NOT_DIAGNOSTIC_KIND,
];

/**
 * Pure predicate mirroring {@link ROUTE_ELIGIBLE_LINE_FILTER}: a feature is
 * route-eligible unless it carries either visualisation-only boolean flag or
 * a `kind`/`type` of `poi_offset`/`gap`. Missing properties (or any other
 * property shape) are eligible — the editor never excludes beyond these
 * explicit markers. Accepts a feature-like object; pass the authoritative
 * feature or just its properties.
 */
export function isRouteEligibleFeature(
  feature: Pick<GeoJSONFeature, "properties"> | { properties: GeoJSONFeature["properties"] } | null,
): boolean {
  const p = feature?.properties;
  if (!p) return true;
  if (p.visualization_only === true || p.review_visualization_only === true) return false;
  if (p.kind === "poi_offset" || p.kind === "gap") return false;
  if (p.type === "poi_offset" || p.type === "gap") return false;
  return true;
}
