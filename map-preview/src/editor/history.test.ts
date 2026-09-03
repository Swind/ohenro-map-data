import { describe, expect, it } from "vitest";
import type { RouteSection } from "./model";
import {
  canRedo,
  canUndo,
  checkpoint,
  createSectionHistory,
  redo,
  resetHistory,
  undo,
} from "./history";

function section(id: string, legs = 0): RouteSection {
  return {
    id,
    fromPoi: null,
    toPoi: null,
    fromAnchor: null,
    toAnchor: null,
    waypoints: [],
    legs: Array.from({ length: legs }, (_, i) => ({
      id: `${id}-leg-${i}`,
      sourceId: "s",
      featureId: "f",
      partIndex: 0,
      start: { sourceId: "s", featureId: "f", partIndex: 0, segmentIndex: 0, fraction: 0, coordinate: [134, 33] },
      end: { sourceId: "s", featureId: "f", partIndex: 0, segmentIndex: 0, fraction: 1, coordinate: [134, 34] },
      direction: "forward" as const,
      coordinates: [[134, 33], [134, 34]],
      lengthM: 100,
    })),
  };
}

describe("section history", () => {
  it("tracks undo/redo availability", () => {
    const history = createSectionHistory();
    expect(canUndo(history)).toBe(false);
    expect(canRedo(history)).toBe(false);

    const sections = [section("A")];
    checkpoint(sections, history);
    expect(canUndo(history)).toBe(true);
    expect(canRedo(history)).toBe(false);

    const next = undo(sections, history);
    expect(next).not.toBeNull();
    expect(canRedo(history)).toBe(true);
  });

  it("undo restores a checkpoint and deep-clones it", () => {
    const history = createSectionHistory();
    const sections = [section("A", 1)];
    checkpoint(sections, history);
    // Simulate a mutation that adds a leg to the live section.
    sections[0].legs.push({
      ...sections[0].legs[0],
      id: `${sections[0].id}-leg-1`,
      coordinates: [[134, 34], [134, 35]],
    });

    const restored = undo(sections, history);
    expect(restored).toHaveLength(1);
    expect(restored![0].legs).toHaveLength(1);
    // The undo result is independent of the mutated live object...
    expect(sections[0].legs).toHaveLength(2);
    // ...and the redo snapshot (a clone of the 2-leg current state) is
    // likewise unaffected by mutating the restored result afterwards.
    restored![0].legs.push(sections[0].legs[0]);
    expect(history.redoStack[0][0].legs).toHaveLength(2);
  });

  it("redo restores the undone mutation", () => {
    const history = createSectionHistory();
    const sections = [section("A")];
    checkpoint(sections, history);
    const afterMut = [section("A", 2)];
    const undone = undo(afterMut, history);
    expect(undone![0].legs).toHaveLength(0);
    const redone = redo(undone!, history);
    expect(redone![0].legs).toHaveLength(2);
  });

  it("returns null when there is nothing to undo/redo", () => {
    const history = createSectionHistory();
    expect(undo([], history)).toBeNull();
    expect(redo([], history)).toBeNull();
  });

  it("bounded undo depth drops the oldest checkpoint", () => {
    const history = createSectionHistory(2);
    let sections = [section("A")];
    for (let i = 0; i < 3; i++) {
      checkpoint(sections, history);
      sections = [section(String.fromCharCode(65 + i + 1))];
    }
    expect(history.undoStack).toHaveLength(2);
  });

  it("checkpoint clears the redo stack", () => {
    const history = createSectionHistory();
    const sections = [section("A")];
    checkpoint(sections, history);
    undo([section("A", 1)], history);
    expect(canRedo(history)).toBe(true);
    checkpoint([section("A", 1)], history);
    expect(canRedo(history)).toBe(false);
  });

  it("reset clears all history", () => {
    const history = createSectionHistory();
    const sections = [section("A")];
    checkpoint(sections, history);
    checkpoint(sections, history);
    resetHistory(history);
    expect(canUndo(history)).toBe(false);
    expect(canRedo(history)).toBe(false);
  });
});