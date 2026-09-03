/**
 * Validation and summary for route editor sections.
 *
 * Exact coordinate equality is the only automatic connection recognised
 * between legs: two consecutive legs are considered continuous only when the
 * end coordinate of one is exactly equal to the start coordinate of the
 * next. Gaps are reported with their metric distance. POI offsets and gaps
 * are never part of any leg, so they are automatically excluded from route
 * length.
 */

import type { EditorProject, Position, RouteLeg, RouteSection } from "./model";
import { distanceM, isValidPosition } from "./geometry";

/** A gap between two consecutive legs (exact-coordinate inequality). */
export interface LegGap {
  /** Index of the leg before the gap (gap sits between legs[i] and legs[i+1]). */
  betweenLegIndex: number;
  /** End coordinate of the preceding leg. */
  from: Position;
  /** Start coordinate of the following leg. */
  to: Position;
  /** Metric distance between `from` and `to`. */
  distanceM: number;
}

export type SectionStatus = "empty" | "continuous" | "has_gaps";

/** Summary of a single route section. */
export interface SectionSummary {
  sectionId: string;
  status: SectionStatus;
  legCount: number;
  /** Total route length (metres), the sum of leg lengths (offsets/gaps excluded). */
  routeLengthM: number;
  /** Total metric length of all gaps between legs. */
  totalGapM: number;
  gaps: LegGap[];
  /** Human-readable issues: missing endpoints/anchors, invalid numbers/refs. */
  issues: string[];
}

/** Summary of a whole project. */
export interface ProjectSummary {
  projectId: string;
  sectionCount: number;
  /** Total route length across all sections (offsets/gaps excluded). */
  totalRouteLengthM: number;
  sections: SectionSummary[];
}

/** End coordinate of a leg (its last coordinate), or null if empty. */
function legStart(leg: RouteLeg): Position | null {
  return leg.coordinates.length > 0 ? leg.coordinates[0] : null;
}

/** End coordinate of a leg (its last coordinate), or null if empty. */
function legEnd(leg: RouteLeg): Position | null {
  return leg.coordinates.length > 0 ? leg.coordinates[leg.coordinates.length - 1] : null;
}

/** Exact WGS84 coordinate equality (the only automatic connection). */
function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/**
 * Derive the gaps between consecutive legs of a section. A gap exists
 * whenever the end coordinate of a leg is not exactly equal to the start
 * coordinate of the next.
 */
export function deriveLegGaps(legs: RouteLeg[]): LegGap[] {
  const gaps: LegGap[] = [];
  for (let i = 0; i < legs.length - 1; i++) {
    const end = legEnd(legs[i]);
    const start = legStart(legs[i + 1]);
    if (end === null || start === null || !samePosition(end, start)) {
      gaps.push({
        betweenLegIndex: i,
        from: end ?? legs[i].start.coordinate,
        to: start ?? legs[i + 1].end.coordinate,
        distanceM: end !== null && start !== null ? distanceM(end, start) : 0,
      });
    }
  }
  return gaps;
}

/**
 * Structural leg issues for a section: problems with leg geometry, numbers,
 * or start/end references. These are independent of endpoint POI/anchor
 * metadata, so an exporter can still emit useful route geometry for a section
 * whose endpoints are simply missing. Returns an array of human-readable
 * issue strings (empty when every leg is structurally valid).
 */
export function structuralLegIssues(legs: RouteLeg[], sectionId: string): string[] {
  const issues: string[] = [];
  const label = `section "${sectionId}"`;
  for (let i = 0; i < legs.length; i++) {
    const leg = legs[i];
    const legLabel = `${label} leg ${leg.id ?? i}`;
    if (!Array.isArray(leg.coordinates) || leg.coordinates.length < 2) {
      issues.push(`${legLabel}: has fewer than 2 coordinates`);
    } else if (!leg.coordinates.every(isValidPosition)) {
      issues.push(`${legLabel}: contains an invalid coordinate`);
    }
    if (!Number.isFinite(leg.lengthM) || leg.lengthM < 0) {
      issues.push(`${legLabel}: invalid lengthM (${String(leg.lengthM)})`);
    }
    if (leg.start === undefined || leg.start === null) {
      issues.push(`${legLabel}: missing start ref`);
    } else if (
      !Number.isFinite(leg.start.fraction) ||
      leg.start.fraction < 0 ||
      leg.start.fraction > 1 ||
      !Number.isInteger(leg.start.segmentIndex) ||
      leg.start.segmentIndex < 0
    ) {
      issues.push(`${legLabel}: invalid start ref (segmentIndex/fraction)`);
    }
    if (leg.end === undefined || leg.end === null) {
      issues.push(`${legLabel}: missing end ref`);
    } else if (
      !Number.isFinite(leg.end.fraction) ||
      leg.end.fraction < 0 ||
      leg.end.fraction > 1 ||
      !Number.isInteger(leg.end.segmentIndex) ||
      leg.end.segmentIndex < 0
    ) {
      issues.push(`${legLabel}: invalid end ref (segmentIndex/fraction)`);
    }
    // Endpoint refs must match the leg's own coordinates exactly.
    const start = legStart(leg);
    const end = legEnd(leg);
    if (start !== null && leg.start?.coordinate !== undefined) {
      const ref = leg.start.coordinate;
      if (!isValidPosition(ref) || !samePosition(ref, start)) {
        issues.push(`${legLabel}: start ref coordinate does not match first coordinate`);
      }
    }
    if (end !== null && leg.end?.coordinate !== undefined) {
      const ref = leg.end.coordinate;
      if (!isValidPosition(ref) || !samePosition(ref, end)) {
        issues.push(`${legLabel}: end ref coordinate does not match last coordinate`);
      }
    }
  }
  return issues;
}

/** Compute the summary for one route section, validating its structure. */
export function summarizeSection(section: RouteSection): SectionSummary {
  const issues: string[] = [];
  const label = `section "${section.id}"`;

  if (section.fromPoi === undefined || section.fromPoi === null) {
    issues.push(`${label}: missing fromPoi`);
  }
  if (section.toPoi === undefined || section.toPoi === null) {
    issues.push(`${label}: missing toPoi`);
  }
  if (section.fromAnchor === undefined || section.fromAnchor === null) {
    issues.push(`${label}: missing fromAnchor`);
  }
  if (section.toAnchor === undefined || section.toAnchor === null) {
    issues.push(`${label}: missing toAnchor`);
  }

  issues.push(...structuralLegIssues(section.legs, section.id));

  // When a section has legs, its anchors must sit exactly on the derived
  // section endpoints: the fromAnchor on the first leg's first coordinate and
  // the toAnchor on the last leg's final coordinate. POIs are discrete points
  // and are allowed to be offset from the anchors, so only anchors are checked.
  if (section.legs.length > 0) {
    const first = section.legs[0].coordinates[0];
    const lastLeg = section.legs[section.legs.length - 1].coordinates;
    const last = lastLeg[lastLeg.length - 1];
    if (section.fromAnchor && first !== undefined && !samePosition(section.fromAnchor.coordinate, first)) {
      issues.push(
        `${label}: fromAnchor coordinate does not match the first leg's first coordinate`,
      );
    }
    if (section.toAnchor && last !== undefined && !samePosition(section.toAnchor.coordinate, last)) {
      issues.push(
        `${label}: toAnchor coordinate does not match the last leg's final coordinate`,
      );
    }
  }

  let routeLengthM = 0;
  for (const leg of section.legs) {
    if (Number.isFinite(leg.lengthM) && leg.lengthM >= 0) routeLengthM += leg.lengthM;
  }

  const gaps = deriveLegGaps(section.legs);
  const totalGapM = gaps.reduce((sum, g) => sum + g.distanceM, 0);
  const status: SectionStatus =
    section.legs.length === 0 ? "empty" : gaps.length === 0 ? "continuous" : "has_gaps";

  return {
    sectionId: section.id,
    status,
    legCount: section.legs.length,
    routeLengthM,
    totalGapM,
    gaps,
    issues,
  };
}

/** Summarize every section of a project. */
export function summarizeProject(project: EditorProject): ProjectSummary {
  const sections = project.sections.map(summarizeSection);
  return {
    projectId: project.projectId,
    sectionCount: sections.length,
    totalRouteLengthM: sections.reduce((sum, s) => sum + s.routeLengthM, 0),
    sections,
  };
}
