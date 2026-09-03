/**
 * Bounded undo/redo history for section edits.
 *
 * Stores `structuredClone` snapshots of the project's `sections` array.
 * Sources are intentionally NOT snapshotted (they stay fixed during section
 * edits). A checkpoint is recorded immediately before a mutating section
 * operation; undo/redo swap the current sections against the stacks and return
 * the restored array for the caller to install and re-render.
 */

import type { RouteSection } from "./model";

export interface SectionHistory {
  undoStack: RouteSection[][];
  redoStack: RouteSection[][];
  maxDepth: number;
}

/** Create an empty history with a bounded undo depth. */
export function createSectionHistory(maxDepth = 100): SectionHistory {
  return { undoStack: [], redoStack: [], maxDepth };
}

/** Deep-clone a sections array (independent of the live project objects). */
export function snapshotSections(sections: RouteSection[]): RouteSection[] {
  return structuredClone(sections);
}

/**
 * Record a checkpoint of the current sections BEFORE a mutating section
 * operation. Clears the redo stack (any future is invalidated). The undo stack
 * is bounded by `maxDepth` (oldest entries are dropped).
 */
export function checkpoint(sections: RouteSection[], history: SectionHistory): void {
  history.undoStack.push(snapshotSections(sections));
  if (history.undoStack.length > history.maxDepth) history.undoStack.shift();
  history.redoStack = [];
}

/** Whether an undo step is available. */
export function canUndo(history: SectionHistory): boolean {
  return history.undoStack.length > 0;
}

/** Whether a redo step is available. */
export function canRedo(history: SectionHistory): boolean {
  return history.redoStack.length > 0;
}

/**
 * Undo one section edit: move the current sections onto the redo stack and
 * return the previous (deep-cloned) sections. Returns null when nothing to undo.
 */
export function undo(current: RouteSection[], history: SectionHistory): RouteSection[] | null {
  const prev = history.undoStack.pop();
  if (!prev) return null;
  history.redoStack.push(snapshotSections(current));
  return snapshotSections(prev);
}

/**
 * Redo one section edit: move the current sections onto the undo stack and
 * return the next (deep-cloned) sections. Returns null when nothing to redo.
 */
export function redo(current: RouteSection[], history: SectionHistory): RouteSection[] | null {
  const next = history.redoStack.pop();
  if (!next) return null;
  history.undoStack.push(snapshotSections(current));
  return snapshotSections(next);
}

/** Clear all undo/redo history (used when a project is opened/replaced). */
export function resetHistory(history: SectionHistory): void {
  history.undoStack = [];
  history.redoStack = [];
}