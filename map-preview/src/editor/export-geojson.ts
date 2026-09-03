/**
 * Derived GeoJSON export for the route editor.
 *
 * Builds a single GeoJSON FeatureCollection from project sections. Continuous,
 * valid sections become one LineString section feature (legs merged only at
 * exact shared boundaries) plus selected endpoint POI and anchor Point
 * features. POI offsets are never added to route geometry or length.
 *
 * The final export (qa=false) rejects any empty/has_gaps section or a section
 * with validation issues, missing POIs or missing anchors. A QA export
 * (qa=true) may emit has_gaps sections as MultiLineString and adds
 * visualization-only POI-offset and gap LineStrings with explicit properties.
 * Feature ids/properties are stable; section order follows the project.
 */

import type {
  EditorProject,
  GeoJSONFeature,
  GeoJSONFeatureCollection,
  GeoJSONGeometry,
  Position,
  RouteLeg,
  RouteSection,
} from "./model";
import { distanceM } from "./geometry";
import { parseProject, serializeProject } from "./project-io";
import { structuralLegIssues, summarizeSection, type SectionSummary } from "./validation";

/** Export options: `qa` enables visualization-only diagnostics. */
export interface GeoJSONExportOptions {
  qa?: boolean;
}

/** The stable `type` property used to route features into KML folders. */
export type ExportFeatureType =
  | "section"
  | "poi"
  | "anchor"
  | "gap"
  | "poi_offset";

/** Exact WGS84 coordinate equality (the only automatic merge boundary). */
function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

function isExportable(summary: SectionSummary): boolean {
  return summary.status === "continuous" && summary.issues.length === 0;
}

/** Merge leg coordinates at exact shared boundaries only. */
function mergeLegs(legs: RouteLeg[]): Position[] {
  if (legs.length === 0) return [];
  const out: Position[] = [...legs[0].coordinates];
  for (let i = 1; i < legs.length; i++) {
    const cur = legs[i].coordinates;
    if (cur.length === 0) continue;
    const prev = out[out.length - 1];
    // Continuous sections meet at an exact shared boundary; drop the duplicate.
    out.push(...(samePosition(prev, cur[0]) ? cur.slice(1) : cur));
  }
  return out;
}

function pointFeature(
  id: string,
  coordinate: Position,
  type: ExportFeatureType,
  sectionId: string,
  props: Record<string, unknown>,
): GeoJSONFeature {
  return {
    type: "Feature",
    id,
    geometry: { type: "Point", coordinates: coordinate },
    properties: { section_id: sectionId, type, ...props },
  };
}

function lineFeature(
  id: string,
  geometry: GeoJSONGeometry,
  sectionId: string,
  props: Record<string, unknown>,
): GeoJSONFeature {
  return {
    type: "Feature",
    id,
    geometry,
    properties: { section_id: sectionId, ...props },
  };
}

/** Unique source/feature ids referenced by a section's legs (stable order). */
function legSourceIds(section: RouteSection): string[] {
  return [...new Set(section.legs.map((l) => l.sourceId))];
}
function legFeatureIds(section: RouteSection): string[] {
  return [...new Set(section.legs.map((l) => l.featureId))];
}

/** Endpoint POI + anchor Point features for a section. */
function endpointFeatures(section: RouteSection): GeoJSONFeature[] {
  const out: GeoJSONFeature[] = [];
  if (section.fromPoi) {
    out.push(
      pointFeature(`section:${section.id}:poi:from`, section.fromPoi.coordinate, "poi", section.id, {
        role: "from_poi",
        source_id: section.fromPoi.sourceId,
        feature_id: section.fromPoi.featureId,
      }),
    );
  }
  if (section.toPoi) {
    out.push(
      pointFeature(`section:${section.id}:poi:to`, section.toPoi.coordinate, "poi", section.id, {
        role: "to_poi",
        source_id: section.toPoi.sourceId,
        feature_id: section.toPoi.featureId,
      }),
    );
  }
  if (section.fromAnchor) {
    out.push(
      pointFeature(`section:${section.id}:anchor:from`, section.fromAnchor.coordinate, "anchor", section.id, {
        role: "from_anchor",
        source_id: section.fromAnchor.sourceId,
        feature_id: section.fromAnchor.featureId,
        part_index: section.fromAnchor.partIndex,
        segment_index: section.fromAnchor.segmentIndex,
        fraction: section.fromAnchor.fraction,
      }),
    );
  }
  if (section.toAnchor) {
    out.push(
      pointFeature(`section:${section.id}:anchor:to`, section.toAnchor.coordinate, "anchor", section.id, {
        role: "to_anchor",
        source_id: section.toAnchor.sourceId,
        feature_id: section.toAnchor.featureId,
        part_index: section.toAnchor.partIndex,
        segment_index: section.toAnchor.segmentIndex,
        fraction: section.toAnchor.fraction,
      }),
    );
  }
  return out;
}

/**
 * QA-only visualization LineStrings from each POI to its anchor. Emitted
 * whenever a POI and its anchor both exist, regardless of section continuity
 * (POIs are discrete points and may legitimately be offset from the route).
 */
function offsetDiagnostics(section: RouteSection): GeoJSONFeature[] {
  const out: GeoJSONFeature[] = [];
  if (section.fromPoi && section.fromAnchor) {
    out.push(
      lineFeature(
        `section:${section.id}:offset:from`,
        { type: "LineString", coordinates: [section.fromPoi.coordinate, section.fromAnchor.coordinate] },
        section.id,
        {
          type: "poi_offset",
          kind: "poi_offset",
          role: "from",
          distance_m: distanceM(section.fromPoi.coordinate, section.fromAnchor.coordinate),
          visualization_only: true,
        },
      ),
    );
  }
  if (section.toPoi && section.toAnchor) {
    out.push(
      lineFeature(
        `section:${section.id}:offset:to`,
        { type: "LineString", coordinates: [section.toPoi.coordinate, section.toAnchor.coordinate] },
        section.id,
        {
          type: "poi_offset",
          kind: "poi_offset",
          role: "to",
          distance_m: distanceM(section.toPoi.coordinate, section.toAnchor.coordinate),
          visualization_only: true,
        },
      ),
    );
  }
  return out;
}

/**
 * Build the derived features for one section; empty array when none export.
 *
 * Structurally invalid legs (bad geometry/numbers/refs) are always skipped.
 * Missing endpoint POI/anchors are only metadata: their Point/offset features
 * are simply omitted, but a valid non-empty route is still exported (QA only;
 * the final path rejects the section via `isExportable` before this runs).
 */
function buildSectionFeatures(
  section: RouteSection,
  summary: SectionSummary,
  qa: boolean,
): GeoJSONFeature[] {
  // Structurally invalid legs can never be exported safely (even in QA).
  if (structuralLegIssues(section.legs, section.id).length > 0) return [];

  const baseProps: Record<string, unknown> = {
    status: summary.status,
    length_m: summary.routeLengthM,
    human_selected: section.humanSelected === true,
    source_ids: legSourceIds(section),
    feature_ids: legFeatureIds(section),
  };

  if (summary.status === "continuous") {
    const merged = mergeLegs(section.legs);
    const sectionFeature = lineFeature(
      `section:${section.id}`,
      { type: "LineString", coordinates: merged },
      section.id,
      { type: "section", ...baseProps },
    );
    // Continuous QA exports also carry POI->anchor offsets; final does not.
    return qa
      ? [sectionFeature, ...endpointFeatures(section), ...offsetDiagnostics(section)]
      : [sectionFeature, ...endpointFeatures(section)];
  }

  // QA-only handling for gapped sections.
  if (summary.status === "has_gaps" && qa) {
    const sectionFeature = lineFeature(
      `section:${section.id}`,
      { type: "MultiLineString", coordinates: section.legs.map((l) => l.coordinates) },
      section.id,
      { type: "section", ...baseProps },
    );
    const diagnostics: GeoJSONFeature[] = [
      sectionFeature,
      ...endpointFeatures(section),
      ...offsetDiagnostics(section),
    ];
    for (const gap of summary.gaps) {
      diagnostics.push(
        lineFeature(
          `section:${section.id}:gap:${gap.betweenLegIndex}`,
          { type: "LineString", coordinates: [gap.from, gap.to] },
          section.id,
          {
            type: "gap",
            kind: "gap",
            between_leg_index: gap.betweenLegIndex,
            distance_m: gap.distanceM,
            visualization_only: true,
          },
        ),
      );
    }
    return diagnostics;
  }

  // empty (or other non-exportable) status.
  return [];
}

/**
 * Build the derived GeoJSON FeatureCollection for a project. Section order
 * follows the project; only legs (never freehand or synthetic joins) are
 * emitted. The final export throws when any section is empty/has_gaps or has
 * validation issues/missing POIs/anchors.
 */
export function exportProjectToGeoJSON(
  project: EditorProject,
  options: GeoJSONExportOptions = {},
): GeoJSONFeatureCollection {
  const qa = options.qa === true;
  // Validate every project ref against the embedded authoritative sources and
  // reconstruct derived leg geometry at the export trust boundary. Both final
  // and QA exports reject invalid/dangling refs. We export from this freshly
  // parsed, normalized copy (never the caller's objects), so the caller's
  // state is never mutated.
  const normalized = parseProject(serializeProject(project));
  const features: GeoJSONFeature[] = [];
  const rejected: string[] = [];

  for (const section of normalized.sections) {
    const summary = summarizeSection(section);
    if (!qa) {
      if (isExportable(summary)) {
        features.push(...buildSectionFeatures(section, summary, qa));
      } else {
        const reason =
          summary.issues.length > 0
            ? summary.issues.join("; ")
            : summary.status === "empty"
              ? "section has no legs"
              : "section has gaps";
        rejected.push(`"${section.id}" (${reason})`);
      }
    } else {
      features.push(...buildSectionFeatures(section, summary, qa));
    }
  }

  if (rejected.length > 0) {
    throw new Error(
      `Cannot export final GeoJSON; ${rejected.length} section(s) not exportable: ${rejected.join("; ")}`,
    );
  }
  // A final (non-QA) export with no sections at all is never meaningful; it
  // would silently produce an empty map. QA exports may legitimately be empty.
  if (!qa && normalized.sections.length === 0) {
    throw new Error("Cannot export final GeoJSON; project has no sections");
  }
  return { type: "FeatureCollection", features };
}