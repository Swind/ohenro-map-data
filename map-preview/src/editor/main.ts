/**
 * Browser UI for the offline route editor.
 *
 * Wires the framework-free editor core modules (import, source-layers,
 * hit-test, geometry, validation, draft-layers, project-io, export, history)
 * to a MapLibre map and plain DOM controls. Supports project open/save,
 * deterministic GeoJSON/KML exports, section-level undo/redo, and the same
 * in-memory editing flow. No routing or automatic joins in this MVP.
 */

import { createBaseMap } from "../base-map";
import type { Map as MapLibreMap } from "maplibre-gl";
import type {
  EditorProject,
  EditorSource,
  Position,
  RouteLeg,
  RouteSection,
} from "./model";
import { importSourceFile, importSourceText } from "./import";
import {
  addSourceLayers,
  createEditorSourceRegistry,
  DRAFT_LAYER_BEFORE_ID,
  removeSourceLayers,
  setSourceColor,
  setSourceVisibility,
  type EditorSourceRegistry,
} from "./source-layers";
import { uuidv4 } from "./uuid";
import { hitTestEditor, type EditorHit, type HitTestMap, type LineHit } from "./hit-test";
import { enumerateLineParts, enumeratePointParts, extractLineRange, lineLengthM } from "./geometry";
import { summarizeSection, type SectionSummary } from "./validation";
import { addDraftLayers, DRAFT_ROUTE_LAYER_ID, updateDraft as updateDraftLayers } from "./draft-layers";
import { addHoverLayers, updateHover as updateHoverLayers } from "./hover-layers";
import { autoOrderLegs } from "./auto-order-legs";
import {
  parseProject,
  serializeJson,
  serializeProject,
} from "./project-io";
import { exportProjectToGeoJSON } from "./export-geojson";
import { exportProjectToKML } from "./export-kml";
import {
  listOutputFiles,
  readOutputFile,
  readOutputSource,
  writeOutputFile,
  type OutputFile,
} from "./output-api";
import { pathMatchesQuery } from "./path-filter";
import {
  canRedo,
  canUndo,
  checkpoint,
  createSectionHistory,
  redo,
  resetHistory,
  undo,
  type SectionHistory,
} from "./history";

type ToolKind = "pan" | "poi" | "line-point" | "line-range";

/** A field in the active section armed by the "set start/end POI/anchor" buttons. */
type ArmedTarget =
  | { kind: "poi"; field: "fromPoi" | "toPoi" }
  | { kind: "anchor"; field: "fromAnchor" | "toAnchor" };

interface State {
  project: EditorProject;
  registry: EditorSourceRegistry;
  history: SectionHistory;
  activeSectionId: string | null;
  tool: ToolKind;
  armed: ArmedTarget | null;
  pendingLine: LineHit | null;
  /** Monotonic token advanced whenever pending selection context is invalidated. */
  revision: number;
}

// ---- DOM refs --------------------------------------------------------------
const container = document.getElementById("editor-map");
const statusEl = document.getElementById("editor-status");
const projectFile = document.getElementById("project-file") as HTMLInputElement | null;
const saveProjectBtn = document.getElementById("save-project") as HTMLButtonElement | null;
const exportFinalGeojsonBtn = document.getElementById("export-final-geojson") as HTMLButtonElement | null;
const exportQaGeojsonBtn = document.getElementById("export-qa-geojson") as HTMLButtonElement | null;
const exportFinalKmlBtn = document.getElementById("export-final-kml") as HTMLButtonElement | null;
const exportQaKmlBtn = document.getElementById("export-qa-kml") as HTMLButtonElement | null;
const outputProjectSelect = document.getElementById("output-project-select") as HTMLSelectElement | null;
const outputProjectSearch = document.getElementById("output-project-search") as HTMLInputElement | null;
const outputProjectRefreshBtn = document.getElementById("output-project-refresh") as HTMLButtonElement | null;
const outputProjectOpenBtn = document.getElementById("output-project-open") as HTMLButtonElement | null;
const undoBtn = document.getElementById("undo-btn") as HTMLButtonElement | null;
const redoBtn = document.getElementById("redo-btn") as HTMLButtonElement | null;
const sourceFile = document.getElementById("source-file") as HTMLInputElement | null;
const sourceList = document.getElementById("source-list");
const outputSourceSelect = document.getElementById("output-source-select") as HTMLSelectElement | null;
const outputSourceSearch = document.getElementById("output-source-search") as HTMLInputElement | null;
const outputSourceRefreshBtn = document.getElementById("output-source-refresh") as HTMLButtonElement | null;
const outputSourceLoadBtn = document.getElementById("output-source-load") as HTMLButtonElement | null;
const sectionIdInput = document.getElementById("section-id-input") as HTMLInputElement | null;
const sectionCreateBtn = document.getElementById("section-create-btn");
const sectionSelector = document.getElementById("section-selector");
const activeSectionEl = document.getElementById("active-section");
const toolbar = document.querySelector(".editor-toolbar");
const chooser = document.getElementById("candidate-chooser");

function report(message: string): void {
  if (statusEl) statusEl.textContent = message;
}

/**
 * Guard against overlapping async output/file operations (source import,
 * project open, save/export, output list refresh). Running them concurrently
 * could corrupt project state and the source registry. This flag is set
 * synchronously before the first await in each operation and the operation
 * controls are disabled for the duration; a second invocation while an
 * operation is in flight is reported and ignored without mutating anything.
 * The map-load handler re-enables the controls once the map is ready.
 */
let operationActive = false;

/** All interactive controls whose state is gated behind the operation guard. */
function operationControls(): (HTMLInputElement | HTMLSelectElement | HTMLButtonElement | null)[] {
  return [
    sourceFile,
    projectFile,
    saveProjectBtn,
    exportFinalGeojsonBtn,
    exportQaGeojsonBtn,
    exportFinalKmlBtn,
    exportQaKmlBtn,
    outputProjectSelect,
    outputProjectRefreshBtn,
    outputProjectOpenBtn,
    outputSourceSelect,
    outputSourceRefreshBtn,
    outputSourceLoadBtn,
  ];
}

function setControlsDisabled(disabled: boolean): void {
  for (const c of operationControls()) {
    if (c) c.disabled = disabled;
  }
  document
    .querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>(
      ".editor-sidebar input, .editor-sidebar select, .editor-sidebar button",
    )
    .forEach((control) => {
      control.disabled = disabled;
    });
  if (!disabled) renderHistoryButtons();
}

/** Run an async operation under the shared guard; ignores overlapping calls. */
async function runOperation(fn: () => Promise<void>): Promise<void> {
  if (operationActive) {
    report("An operation is already in progress; try again when it finishes.");
    return;
  }
  operationActive = true;
  invalidatePendingSelection();
  setControlsDisabled(true);
  try {
    await fn();
  } catch (err) {
    report(`Operation failed: ${(err as Error).message}`);
  } finally {
    operationActive = false;
    setControlsDisabled(false);
  }
}

function editingBlocked(): boolean {
  if (!operationActive) return false;
  report("Wait for the current file operation to finish before editing.");
  return true;
}

if (!container) {
  report("Editor map container not found.");
  throw new Error("Missing #editor-map element in editor.html");
}

// ---- State ----------------------------------------------------------------
const state: State = {
  project: {
    schema_version: 1,
    kind: "ohenro_route_editor_project",
    projectId: uuidv4(),
    sources: [],
    sections: [],
  },
  registry: createEditorSourceRegistry(),
  history: createSectionHistory(100),
  activeSectionId: null,
  tool: "pan",
  armed: null,
  pendingLine: null,
  revision: 0,
};

const map: MapLibreMap = createBaseMap(container);

// ---- Small DOM helpers -----------------------------------------------------
function el(tag: string, className?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function textLi(text: string): HTMLLIElement {
  const li = document.createElement("li");
  li.textContent = text;
  return li;
}

function placeholder(text: string): HTMLElement {
  const p = el("div", "editor-placeholder");
  p.textContent = text;
  return p;
}

function checkboxField(labelText: string, checked: boolean, onChange: (checked: boolean) => void): HTMLElement {
  const label = document.createElement("label");
  label.className = "editor-check-field";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  label.appendChild(input);
  label.appendChild(document.createTextNode(labelText));
  return label;
}

function button(text: string, onClick: (e: MouseEvent) => void, className?: string): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
}

function refRow(labelText: string, value: string): HTMLElement {
  const wrapper = el("div", "editor-ref-row");
  const dt = el("dt");
  dt.textContent = labelText;
  const dd = el("dd");
  dd.textContent = value;
  wrapper.appendChild(dt);
  wrapper.appendChild(dd);
  return wrapper;
}

function stat(labelText: string, value: string): HTMLElement {
  const div = el("div", "editor-stat");
  const span = el("span", "editor-stat-label");
  span.textContent = labelText;
  const val = el("span", "editor-stat-value");
  val.textContent = value;
  div.appendChild(span);
  div.appendChild(val);
  return div;
}

function formatM(m: number): string {
  if (!Number.isFinite(m)) return "—";
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${m.toFixed(1)} m`;
}

// ---- Output browser --------------------------------------------------------
/** The latest successfully fetched output file list (deterministic server order). */
let outputFilesCache: OutputFile[] = [];

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Output files that are project JSON documents (route-editor/projects/*.json). */
function projectOutputFiles(files: OutputFile[]): OutputFile[] {
  return files.filter((f) => /^route-editor\/projects\/[^/]+\.json$/i.test(f.path));
}

/** Output files usable as sources (everything except route-editor/projects/*). */
function sourceOutputFiles(files: OutputFile[]): OutputFile[] {
  return files.filter((f) => !/^route-editor\/projects\/[^/]+\.json$/i.test(f.path));
}

function optionFor(file: OutputFile): HTMLOptionElement {
  const option = document.createElement("option");
  option.value = file.path;
  option.textContent = `${file.path} (${formatBytes(file.size)})`;
  return option;
}

function renderOutputProjectList(): void {
  if (!outputProjectSelect) return;
  outputProjectSelect.textContent = "";
  const query = outputProjectSearch?.value ?? "";
  for (const file of projectOutputFiles(outputFilesCache)) {
    if (pathMatchesQuery(file.path, query)) {
      outputProjectSelect.appendChild(optionFor(file));
    }
  }
}

function renderOutputSourceList(): void {
  if (!outputSourceSelect) return;
  outputSourceSelect.textContent = "";
  const query = outputSourceSearch?.value ?? "";
  for (const file of sourceOutputFiles(outputFilesCache)) {
    if (pathMatchesQuery(file.path, query)) {
      outputSourceSelect.appendChild(optionFor(file));
    }
  }
}

/** Refresh both output browsers; reports an unavailable API but keeps local reads working. */
async function refreshOutputLists(): Promise<void> {
  let files: OutputFile[];
  try {
    files = await listOutputFiles();
  } catch (err) {
    report(`Output API unavailable: ${(err as Error).message}`);
    outputFilesCache = [];
    renderOutputProjectList();
    renderOutputSourceList();
    return;
  }
  outputFilesCache = files;
  renderOutputProjectList();
  renderOutputSourceList();
}

// ---- Project / section helpers --------------------------------------------
function activeSection(): RouteSection | null {
  if (!state.activeSectionId) return null;
  return state.project.sections.find((s) => s.id === state.activeSectionId) ?? null;
}

function activeSummary(): SectionSummary | null {
  const section = activeSection();
  return section ? summarizeSection(section) : null;
}

/**
 * After any sections mutation or history restore, repair the active selection:
 * the active section must resolve to an existing section. Whenever the current
 * activeSectionId is null OR does not resolve, fall back to the first section;
 * keep it null only when no sections exist.
 */
function repairActiveSection(): void {
  if (state.project.sections.length === 0) {
    state.activeSectionId = null;
    return;
  }
  const currentResolves =
    state.activeSectionId != null &&
    state.project.sections.some((s) => s.id === state.activeSectionId);
  if (!currentResolves) {
    state.activeSectionId = state.project.sections[0].id;
  }
}

// ---- History ---------------------------------------------------------------
function renderHistoryButtons(): void {
  if (undoBtn) undoBtn.disabled = !canUndo(state.history);
  if (redoBtn) redoBtn.disabled = !canRedo(state.history);
}

/**
 * Record a checkpoint, run a section mutation, then repair selection and
 * re-render everything that depends on sections/draft/history.
 */
function applySectionChange(mutator: () => void): void {
  if (editingBlocked()) return;
  invalidatePendingSelection();
  checkpoint(state.project.sections, state.history);
  mutator();
  repairActiveSection();
  renderSectionSelector();
  renderActiveSection();
  refreshDraft();
  renderHistoryButtons();
}

function doUndo(): void {
  if (editingBlocked()) return;
  const restored = undo(state.project.sections, state.history);
  if (!restored) return;
  invalidatePendingSelection();
  state.project.sections = restored;
  repairActiveSection();
  renderSectionSelector();
  renderActiveSection();
  refreshDraft();
  renderHistoryButtons();
  report("Undo.");
}

function doRedo(): void {
  if (editingBlocked()) return;
  const restored = redo(state.project.sections, state.history);
  if (!restored) return;
  invalidatePendingSelection();
  state.project.sections = restored;
  repairActiveSection();
  renderSectionSelector();
  renderActiveSection();
  refreshDraft();
  renderHistoryButtons();
  report("Redo.");
}

// ---- Draft refresh ---------------------------------------------------------
function refreshDraft(): void {
  updateDraftLayers(map, activeSection(), activeSummary());
}

// ---- Toolbar ---------------------------------------------------------------
function renderToolbar(): void {
  if (!toolbar) return;
  toolbar.querySelectorAll("[data-tool]").forEach((node) => {
    const tool = (node as HTMLElement).dataset.tool as ToolKind;
    node.setAttribute("aria-pressed", String(state.tool === tool));
  });
  map.getCanvas().style.cursor = state.tool === "pan" ? "" : "crosshair";
}

function arm(target: ArmedTarget): void {
  if (editingBlocked()) return;
  invalidatePendingSelection();
  state.armed = target;
  state.tool = target.kind === "poi" ? "poi" : "line-point";
  state.pendingLine = null;
  renderToolbar();
  report(`Arming ${target.kind} → ${target.field}. Click the map.`);
}

// ---- Source list -----------------------------------------------------------
function sourceReferenced(sourceId: string): boolean {
  return state.project.sections.some((s) =>
    (s.fromPoi !== null && s.fromPoi.sourceId === sourceId) ||
    (s.toPoi !== null && s.toPoi.sourceId === sourceId) ||
    (s.fromAnchor !== null && s.fromAnchor.sourceId === sourceId) ||
    (s.toAnchor !== null && s.toAnchor.sourceId === sourceId) ||
    s.waypoints.some((w) => w.sourceId === sourceId) ||
    s.legs.some((l) => l.sourceId === sourceId),
  );
}

function buildSourceItem(source: EditorSource): HTMLElement {
  const li = document.createElement("li");
  li.className = "editor-source-item";

  const name = el("div", "editor-source-name");
  name.textContent = source.name;
  li.appendChild(name);

  const controls = el("div", "editor-source-controls");
  controls.appendChild(
    checkboxField("Visible", source.visible, (checked) => {
      if (editingBlocked()) return;
      source.visible = checked;
      setSourceVisibility(map, source.id, state.registry, checked);
      invalidatePendingSelection();
    }),
  );
  controls.appendChild(
    checkboxField("Selectable", source.selectable, (checked) => {
      if (editingBlocked()) return;
      source.selectable = checked;
      invalidatePendingSelection();
    }),
  );

  const colorLabel = document.createElement("label");
  colorLabel.className = "editor-check-field";
  colorLabel.appendChild(document.createTextNode("Color "));
  const colorInput = document.createElement("input");
  colorInput.type = "color";
  colorInput.value = source.color;
  colorInput.addEventListener("input", () => {
    if (editingBlocked()) return;
    source.color = colorInput.value;
    setSourceColor(map, source.id, state.registry, source.color);
  });
  colorLabel.appendChild(colorInput);
  controls.appendChild(colorLabel);

  controls.appendChild(
    button("Remove", () => {
      if (editingBlocked()) return;
      if (sourceReferenced(source.id)) {
        report(`Cannot remove source ${source.name}; it is referenced by a section.`);
        return;
      }
      removeSourceLayers(map, source.id, state.registry);
      state.project.sources = state.project.sources.filter((s) => s.id !== source.id);
      // Removing a source leaves any recorded undo snapshots dangling (they may
      // reference it), so reset the section history atomically.
      invalidatePendingSelection();
      resetHistory(state.history);
      renderHistoryButtons();
      renderSourceList();
      report(`Removed source ${source.name}.`);
    }),
  );
  li.appendChild(controls);

  if (source.importWarnings.length > 0) {
    const details = document.createElement("details");
    details.className = "editor-warnings";
    const summaryEl = document.createElement("summary");
    summaryEl.textContent = `${source.importWarnings.length} warning(s)`;
    details.appendChild(summaryEl);
    const list = document.createElement("ul");
    source.importWarnings.forEach((w) => list.appendChild(textLi(w)));
    details.appendChild(list);
    li.appendChild(details);
  }

  return li;
}

function renderSourceList(): void {
  if (!sourceList) return;
  sourceList.textContent = "";
  if (state.project.sources.length === 0) {
    sourceList.appendChild(placeholder("No sources loaded."));
    return;
  }
  for (const source of state.project.sources) {
    sourceList.appendChild(buildSourceItem(source));
  }
}

// ---- Sections --------------------------------------------------------------
function renderSectionSelector(): void {
  if (!sectionSelector) return;
  sectionSelector.textContent = "";
  if (state.project.sections.length === 0) {
    sectionSelector.appendChild(placeholder("No sections."));
    return;
  }
  for (const section of state.project.sections) {
    const wrapper = el("div", "editor-section-row");
    const item = document.createElement("button");
    item.type = "button";
    item.className = "editor-section-item";
    item.classList.toggle("active", section.id === state.activeSectionId);
    item.textContent = section.id;
    item.addEventListener("click", () => {
      state.activeSectionId = section.id;
      invalidatePendingSelection();
      renderSectionSelector();
      renderActiveSection();
      refreshDraft();
    });
    const del = button(
      "Delete",
      (e) => {
        e.stopPropagation();
        applySectionChange(() => {
          state.project.sections = state.project.sections.filter((s) => s.id !== section.id);
          if (state.activeSectionId === section.id) state.activeSectionId = null;
        });
      },
      "editor-section-delete",
    );
    wrapper.appendChild(item);
    wrapper.appendChild(del);
    sectionSelector.appendChild(wrapper);
  }
}

// ---- Active section detail -------------------------------------------------
function buildLegItem(section: RouteSection, leg: RouteLeg, index: number): HTMLElement {
  const li = document.createElement("li");
  li.className = "editor-leg";

  const label = el("span", "editor-leg-label");
  label.textContent = `${index}: ${leg.sourceId}/${leg.featureId} part ${leg.partIndex} ${leg.direction} ${formatM(leg.lengthM)}`;
  li.appendChild(label);

  const actions = el("div", "editor-leg-actions");
  actions.appendChild(
    button("Reverse", () => {
      applySectionChange(() => {
        section.legs[index] = {
          ...leg,
          start: leg.end,
          end: leg.start,
          direction: leg.direction === "forward" ? "reverse" : "forward",
          coordinates: [...leg.coordinates].reverse(),
        };
      });
    }),
  );
  actions.appendChild(
    button("↑", () => {
      if (index === 0) return;
      applySectionChange(() => {
        const [moved] = section.legs.splice(index, 1);
        section.legs.splice(index - 1, 0, moved);
      });
    }),
  );
  actions.appendChild(
    button("↓", () => {
      if (index >= section.legs.length - 1) return;
      applySectionChange(() => {
        const [moved] = section.legs.splice(index, 1);
        section.legs.splice(index + 1, 0, moved);
      });
    }),
  );
  actions.appendChild(
    button("Delete", () => {
      applySectionChange(() => {
        section.legs.splice(index, 1);
      });
    }),
  );
  li.appendChild(actions);
  return li;
}

function renderActiveSection(): void {
  if (!activeSectionEl) return;
  activeSectionEl.textContent = "";
  const section = activeSection();
  if (!section) {
    activeSectionEl.appendChild(placeholder("No active section."));
    return;
  }

  const summary = summarizeSection(section);

  const controls = el("div", "editor-anchor-controls");
  controls.appendChild(button("Set start POI", () => arm({ kind: "poi", field: "fromPoi" })));
  controls.appendChild(button("Set end POI", () => arm({ kind: "poi", field: "toPoi" })));
  controls.appendChild(button("Set start anchor", () => arm({ kind: "anchor", field: "fromAnchor" })));
  controls.appendChild(button("Set end anchor", () => arm({ kind: "anchor", field: "toAnchor" })));
  activeSectionEl.appendChild(controls);

  const refs = document.createElement("dl");
  refs.className = "editor-refs";
  refs.appendChild(
    refRow("From POI", section.fromPoi ? `${section.fromPoi.sourceId} ${section.fromPoi.featureId}` : "—"),
  );
  refs.appendChild(
    refRow("To POI", section.toPoi ? `${section.toPoi.sourceId} ${section.toPoi.featureId}` : "—"),
  );
  refs.appendChild(
    refRow("From anchor", section.fromAnchor ? `${section.fromAnchor.sourceId} ${section.fromAnchor.featureId} p${section.fromAnchor.partIndex}` : "—"),
  );
  refs.appendChild(
    refRow("To anchor", section.toAnchor ? `${section.toAnchor.sourceId} ${section.toAnchor.featureId} p${section.toAnchor.partIndex}` : "—"),
  );
  activeSectionEl.appendChild(refs);

  const summaryBlock = el("div", "editor-summary");
  summaryBlock.appendChild(stat("Status", summary.status));
  summaryBlock.appendChild(stat("Legs", String(summary.legCount)));
  summaryBlock.appendChild(stat("Route length", formatM(summary.routeLengthM)));
  summaryBlock.appendChild(stat("Total gap", formatM(summary.totalGapM)));
  if (summary.issues.length > 0) {
    const issues = el("ul", "editor-issues");
    summary.issues.forEach((issue) => issues.appendChild(textLi(issue)));
    summaryBlock.appendChild(issues);
  }
  activeSectionEl.appendChild(summaryBlock);

  if (summary.gaps.length > 0) {
    const gaps = el("ul", "editor-gaps");
    gaps.appendChild(textLi("Exact gaps:"));
    summary.gaps.forEach((gap) => {
      gaps.appendChild(
        textLi(`between legs ${gap.betweenLegIndex} → ${gap.betweenLegIndex + 1}: ${formatM(gap.distanceM)}`),
      );
    });
    activeSectionEl.appendChild(gaps);
  }

  // Exact-only auto-order of the selected legs (never routing).
  const autoOrder = el("div", "editor-auto-order");
  autoOrder.appendChild(
    button("Auto-order selected legs (exact only)", () => {
      if (editingBlocked()) return;
      const result = autoOrderLegs(section);
      if (!result.ok) {
        report(`Auto-order: ${result.reason}`);
        return;
      }
      if (!result.changed) {
        report(`Auto-order: ${result.legs.length} leg(s) already ordered from→to; no change.`);
        return;
      }
      applySectionChange(() => {
        section.legs = result.legs;
      });
      report(`Auto-order: ordered ${result.legs.length} leg(s), reversed ${result.reversedCount}.`);
    }),
  );
  activeSectionEl.appendChild(autoOrder);

  const legs = el("ol", "editor-legs");
  section.legs.forEach((leg, index) => legs.appendChild(buildLegItem(section, leg, index)));
  activeSectionEl.appendChild(legs);
}

// ---- Hit resolution --------------------------------------------------------
function queryHits(click: Position, kind: "poi" | "line"): EditorHit[] {
  // MapLibre's overloaded queryRenderedFeatures signature is not structurally
  // assignable to the minimal HitTestMap surface; the map is behaviourally
  // compatible so this is a narrow, call-site-only cast.
  const all = hitTestEditor(map as unknown as HitTestMap, click, state.project.sources, state.registry);
  return all.filter((h) => h.kind === kind);
}

function describeHit(hit: EditorHit): string {
  if (hit.kind === "poi") {
    return `POI ${hit.sourceId}/${hit.featureId} · ${formatM(hit.distanceM)}`;
  }
  return `Line ${hit.sourceId}/${hit.featureId} part ${hit.partIndex} seg ${hit.segmentIndex} · ${formatM(hit.distanceM)}`;
}

function hideChooser(): void {
  if (chooser) chooser.hidden = true;
}

// ---- Authoritative hover highlight ----------------------------------------
let hoverRafPending = false;
let hoverLngLat: Position | null = null;

/**
 * The kind of feature to hover in the current editing state, or null to clear.
 * Only the currently operable kind is highlighted: a line-range selection or an
 * armed anchor hovers lines; an armed POI hovers POIs; panning (or any unarmed
 * state) hovers nothing.
 */
function hoverKindForState(): "line" | "poi" | null {
  if (state.tool === "line-range") return "line";
  if (state.armed) return state.armed.kind === "poi" ? "poi" : "line";
  return null;
}

/** Set the canvas cursor: pointer over a hit, otherwise the tool cursor. */
function paintHoverCursor(hit: boolean): void {
  const canvas = map.getCanvas();
  if (hit) canvas.style.cursor = "pointer";
  else canvas.style.cursor = state.tool === "pan" ? "" : "crosshair";
}

/** Compute and render the hover highlight for the latest throttled position. */
function runHover(): void {
  hoverRafPending = false;
  const p = hoverLngLat;
  if (p === null) return; // cleared since scheduling
  const kind = hoverKindForState();
  if (!kind) {
    updateHoverLayers(map, null, state.project.sources);
    paintHoverCursor(false);
    return;
  }
  const hits = queryHits(p, kind);
  // Multi-candidate: visually highlight only the deterministic first hit; a
  // click still opens the chooser. Hover never auto-commits.
  const first = hits[0] ?? null;
  updateHoverLayers(map, first, state.project.sources);
  paintHoverCursor(first !== null);
}

/** Throttle hover to one query per animation frame. */
function scheduleHover(p: Position): void {
  hoverLngLat = p;
  if (hoverRafPending) return;
  hoverRafPending = true;
  requestAnimationFrame(runHover);
}

/** Clear any hover highlight (and the pointer cursor). Never revs history. */
function clearHover(): void {
  hoverLngLat = null;
  if (hoverRafPending) {
    hoverRafPending = false;
  }
  updateHoverLayers(map, null, state.project.sources);
  paintHoverCursor(false);
}

/**
 * Central invalidation of any pending selection context (armed target, in-progress
 * line-range first point, open candidate chooser) and advance the monotonic
 * revision token. Call whenever the selection context may have changed so stale
 * commits cannot leak across section/source/tool/undo boundaries. Also clears
 * any hover highlight — without incrementing the revision or checkpointing.
 */
function invalidatePendingSelection(): void {
  clearHover();
  state.armed = null;
  state.pendingLine = null;
  state.revision += 1;
  hideChooser();
}

/** Whether a previously displayed hit still resolves in the current project. */
function hitStillValid(hit: EditorHit): boolean {
  const source = state.project.sources.find((s) => s.id === hit.sourceId);
  if (!source || !source.selectable) return false;
  const feature = source.data.features.find(
    (f) => f.id !== undefined && f.id !== null && String(f.id) === hit.featureId,
  );
  if (!feature || !feature.geometry) return false;
  if (hit.kind === "line") {
    const parts = enumerateLineParts(feature.geometry);
    return parts[hit.partIndex] != null;
  }
  // POI: the chosen coordinate must still be a point part of the feature.
  return enumeratePointParts(feature.geometry).some(
    (p) => p[0] === hit.coordinate[0] && p[1] === hit.coordinate[1],
  );
}

function showChooser(hits: EditorHit[]): void {
  if (!chooser) return;
  chooser.hidden = false;
  chooser.textContent = "";
  const title = el("div", "editor-chooser-title");
  title.textContent = `${hits.length} candidates — choose one:`;
  chooser.appendChild(title);
  // Capture the selection context at display time so a commit that happens
  // after the context changed is rejected rather than applied.
  const displayRevision = state.revision;
  const displaySectionId = state.activeSectionId;
  hits.forEach((hit) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "editor-chooser-option";
    btn.textContent = describeHit(hit);
    btn.addEventListener("click", () => {
      hideChooser();
      commitHit(hit, { revision: displayRevision, sectionId: displaySectionId });
    });
    // Optional: hovering a candidate option highlights that exact candidate;
    // leaving it clears the highlight (no commit).
    btn.addEventListener("mouseenter", () => {
      updateHoverLayers(map, hit, state.project.sources);
      map.getCanvas().style.cursor = "pointer";
    });
    btn.addEventListener("mouseleave", () => {
      clearHover();
    });
    chooser.appendChild(btn);
  });
  chooser.appendChild(
    button("Cancel (Esc)", () => {
      invalidatePendingSelection();
      report("Selection cancelled.");
    }, "editor-chooser-cancel"),
  );
  const first = chooser.querySelector("button");
  if (first) (first as HTMLElement).focus();
}

function lookupPart(sourceId: string, featureId: string, partIndex: number): Position[] | null {
  const source = state.project.sources.find((s) => s.id === sourceId);
  if (!source) return null;
  const feature = source.data.features.find(
    (f) => f.id !== undefined && f.id !== null && String(f.id) === featureId,
  );
  if (!feature || !feature.geometry) return null;
  const parts = enumerateLineParts(feature.geometry);
  return parts[partIndex] ?? null;
}

function handleLineRangeHit(hit: LineHit): void {
  if (!state.pendingLine) {
    state.pendingLine = hit;
    report(`First line point (${hit.sourceId}/${hit.featureId} part ${hit.partIndex}). Click second.`);
    return;
  }
  const first = state.pendingLine;
  const second = hit;
  if (
    first.sourceId !== second.sourceId ||
    first.featureId !== second.featureId ||
    first.partIndex !== second.partIndex
  ) {
    report("Line-range endpoints must be on the same source feature part.");
    state.pendingLine = null;
    return;
  }
  const section = activeSection();
  if (!section) {
    report("No active section.");
    state.pendingLine = null;
    return;
  }
  const coords = lookupPart(second.sourceId, second.featureId, second.partIndex);
  if (!coords) {
    report("Could not resolve the authoritative line part.");
    state.pendingLine = null;
    return;
  }
  let range;
  try {
    range = extractLineRange(
      coords,
      { segmentIndex: first.segmentIndex, fraction: first.fraction },
      { segmentIndex: second.segmentIndex, fraction: second.fraction },
    );
  } catch (err) {
    report(`extractLineRange failed: ${(err as Error).message}`);
    state.pendingLine = null;
    return;
  }
  // Review fix: a zero-length / one-coordinate range (start == end) would add
  // an invalid leg, so reject it instead.
  if (range.coordinates.length < 2) {
    report("Rejected zero-length line range (start and end are the same point).");
    state.pendingLine = null;
    return;
  }
  applySectionChange(() => {
    section.legs.push({
      id: uuidv4(),
      sourceId: second.sourceId,
      featureId: second.featureId,
      partIndex: second.partIndex,
      start: {
        sourceId: first.sourceId,
        featureId: first.featureId,
        partIndex: first.partIndex,
        segmentIndex: first.segmentIndex,
        fraction: first.fraction,
        coordinate: range.coordinates[0],
      },
      end: {
        sourceId: second.sourceId,
        featureId: second.featureId,
        partIndex: second.partIndex,
        segmentIndex: second.segmentIndex,
        fraction: second.fraction,
        coordinate: range.coordinates[range.coordinates.length - 1],
      },
      direction: range.direction,
      coordinates: range.coordinates,
      lengthM: lineLengthM(range.coordinates),
    });
  });
  state.pendingLine = null;
  report(`Appended leg (${formatM(lineLengthM(range.coordinates))}).`);
}

function applyArmedHit(hit: EditorHit): void {
  const armed = state.armed;
  const section = activeSection();
  if (!armed || !section) {
    report("No active section or armed target.");
    state.armed = null;
    return;
  }
  if (armed.kind === "poi" && hit.kind === "poi") {
    applySectionChange(() => {
      section[armed.field] = {
        sourceId: hit.sourceId,
        featureId: hit.featureId,
        coordinate: hit.coordinate,
      };
    });
  } else if (armed.kind === "anchor" && hit.kind === "line") {
    applySectionChange(() => {
      section[armed.field] = {
        sourceId: hit.sourceId,
        featureId: hit.featureId,
        partIndex: hit.partIndex,
        segmentIndex: hit.segmentIndex,
        fraction: hit.fraction,
        coordinate: hit.coordinate,
      };
    });
  } else {
    report(`Hit kind (${hit.kind}) does not match the armed target (${armed.kind}).`);
    return;
  }
  state.armed = null;
  report(`Set ${armed.field}.`);
}

function commitHit(
  hit: EditorHit,
  captured: { revision: number; sectionId: string | null },
): void {
  // Reject the commit if the selection context changed since the candidate was
  // displayed (e.g. active section switched, source removed, tool changed).
  if (captured.revision !== state.revision || captured.sectionId !== state.activeSectionId) {
    report("Stale candidate ignored: the selection context changed.");
    return;
  }
  // Reject stale candidates whose source/feature is no longer present.
  if (!hitStillValid(hit)) {
    report("Stale candidate ignored: the source/feature is no longer available.");
    return;
  }
  if (state.tool === "line-range") {
    handleLineRangeHit(hit as LineHit);
  } else {
    applyArmedHit(hit);
  }
}

function handleMapClick(click: Position): void {
  if (state.tool === "pan") return;

  if (state.tool === "line-range") {
    const hits = queryHits(click, "line");
    if (hits.length === 0) {
      report("No line hit.");
      return;
    }
    if (hits.length > 1) {
      showChooser(hits);
      return;
    }
    handleLineRangeHit(hits[0] as LineHit);
    return;
  }

  // POI / line-point require an armed target field.
  if (!state.armed) {
    report("Select a target field (set start/end POI or anchor) first.");
    return;
  }
  const kind = state.armed.kind === "poi" ? "poi" : "line";
  const hits = queryHits(click, kind);
  if (hits.length === 0) {
    report("No hit.");
    return;
  }
  if (hits.length > 1) {
    showChooser(hits);
    return;
  }
  applyArmedHit(hits[0]);
}

// ---- Project / export ------------------------------------------------------
/**
 * Replace the active project with a parsed one using a rollback-safe path:
 * remove the current source layers, install the parsed sources into a fresh
 * registry (addSourceLayers is transactional per source), and only swap the
 * project atomically after complete success. On install failure the previous
 * project is restored into a fresh registry; on a mid-restore failure both
 * states are left as authoritative as possible and reported.
 */
function replaceProject(parsed: EditorProject): void {
  const previousProject = state.project;
  const previousSources = state.project.sources;

  // Source/layer ids are derived deterministically from source hashes, so
  // remove the current project's source layers first to free those ids for
  // the parsed sources. Only after complete success do we swap the project.
  for (const source of previousSources) {
    removeSourceLayers(map, source.id, state.registry);
  }

  // Install every parsed source into a fresh registry.
  const newRegistry = createEditorSourceRegistry();
  try {
    for (const source of parsed.sources) {
      addSourceLayers(map, source, newRegistry, DRAFT_LAYER_BEFORE_ID);
    }
  } catch (installErr) {
    // Clean every newly added layer (the failing source already rolled back
    // itself via addSourceLayers' transaction).
    for (const sourceId of Object.keys(newRegistry.bySourceId)) {
      removeSourceLayers(map, sourceId, newRegistry);
    }
    // Restore the previous project by re-adding every previous source into a
    // fresh registry. addSourceLayers is transactional per source, so a
    // mid-restore failure leaves only whatever sources re-added successfully.
    const restoreRegistry = createEditorSourceRegistry();
    try {
      for (const source of previousSources) {
        addSourceLayers(map, source, restoreRegistry, DRAFT_LAYER_BEFORE_ID);
      }
    } catch (restoreErr) {
      report(
        `Open failed: ${(installErr as Error).message}; ` +
          `rollback restore failed: ${(restoreErr as Error).message}`,
      );
      state.project = previousProject;
      state.registry = restoreRegistry;
      return;
    }
    state.project = previousProject;
    state.registry = restoreRegistry;
    report(`Open failed: ${(installErr as Error).message}`);
    return;
  }
  // Install succeeded: swap in the parsed project atomically.
  state.project = parsed;
  state.registry = newRegistry;
  // Reset selection/tooling and history, then choose the first section.
  state.activeSectionId = state.project.sections.length > 0 ? state.project.sections[0].id : null;
  state.tool = "pan";
  resetHistory(state.history);
  invalidatePendingSelection();
  renderToolbar();
  renderSourceList();
  renderSectionSelector();
  renderActiveSection();
  refreshDraft();
  renderHistoryButtons();
  report(`Opened project ${state.project.projectId}.`);
}

/** Parse untrusted project text and replace the active project (rollback-safe). */
function openProjectFromText(text: string): void {
  try {
    replaceProject(parseProject(text));
  } catch (err) {
    report(`Open failed: ${(err as Error).message}`);
  }
}

function projectOutputPath(): string {
  return `route-editor/projects/ohenro-project-${state.project.projectId}.json`;
}
function geojsonOutputPath(qa: boolean): string {
  return `route-editor/${qa ? "qa" : "final"}/ohenro-${qa ? "qa" : "final"}-${state.project.projectId}.geojson`;
}
function kmlOutputPath(qa: boolean): string {
  return `route-editor/${qa ? "qa" : "final"}/ohenro-${qa ? "qa" : "final"}-${state.project.projectId}.kml`;
}

function saveProject(): void {
  void runOperation(async () => {
    try {
      // Normalize by round-tripping through parse; throws on any inconsistency.
      const normalized = parseProject(serializeProject(state.project));
      const path = projectOutputPath();
      await writeOutputFile(path, serializeProject(normalized));
      report(`Saved project to ${path}.`);
      await refreshOutputLists();
    } catch (err) {
      report(`Save failed: ${(err as Error).message}`);
    }
  });
}

function exportGeoJSON(qa: boolean): void {
  void runOperation(async () => {
    try {
      const fc = exportProjectToGeoJSON(state.project, { qa });
      const path = geojsonOutputPath(qa);
      await writeOutputFile(path, serializeJson(fc));
      report(`Saved ${qa ? "QA" : "final"} GeoJSON to ${path}.`);
      await refreshOutputLists();
    } catch (err) {
      report(`Export failed: ${(err as Error).message}`);
    }
  });
}

function exportKML(qa: boolean): void {
  void runOperation(async () => {
    try {
      // KML derives from the same GeoJSON export (throws identically).
      const fc = exportProjectToGeoJSON(state.project, { qa });
      const kml = exportProjectToKML(fc);
      const path = kmlOutputPath(qa);
      await writeOutputFile(path, kml);
      report(`Saved ${qa ? "QA" : "final"} KML to ${path}.`);
      await refreshOutputLists();
    } catch (err) {
      report(`Export failed: ${(err as Error).message}`);
    }
  });
}

// ---- Wire up events --------------------------------------------------------
map.on("load", () => {
  addDraftLayers(map);
  // Hover highlight sits above imported sources but below the draft route.
  addHoverLayers(map, DRAFT_ROUTE_LAYER_ID);
  // Review fix: enable import/open controls only once the map is ready.
  setControlsDisabled(operationActive);
  renderSourceList();
  renderSectionSelector();
  renderActiveSection();
  renderHistoryButtons();
  report("Map ready. Open a project or load source files, then create a section.");
  // Populate the output browsers (best-effort; local reads keep working if down).
  void runOperation(refreshOutputLists);
});

map.on("click", (e) => {
  if (editingBlocked()) return;
  handleMapClick([e.lngLat.lng, e.lngLat.lat]);
});

map.on("mousemove", (e) => {
  if (editingBlocked()) return;
  scheduleHover([e.lngLat.lng, e.lngLat.lat]);
});

map.getCanvas().addEventListener("mouseleave", () => {
  clearHover();
});

document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === "z" || e.key === "Z")) {
    e.preventDefault();
    if (editingBlocked()) return;
    if (e.shiftKey) doRedo();
    else doUndo();
    return;
  }
  if (e.key !== "Escape") return;
  invalidatePendingSelection();
  renderToolbar();
  report("Cancelled pending selection.");
});

toolbar?.addEventListener("click", (e) => {
  if (editingBlocked()) return;
  const node = (e.target as HTMLElement).closest("[data-tool]") as HTMLElement | null;
  if (!node) return;
  const tool = node.dataset.tool as ToolKind;
  state.tool = tool;
  invalidatePendingSelection();
  renderToolbar();
});

undoBtn?.addEventListener("click", doUndo);
redoBtn?.addEventListener("click", doRedo);

sectionCreateBtn?.addEventListener("click", () => {
  const id = (sectionIdInput?.value ?? "").trim();
  if (!id) {
    report("Enter a section ID.");
    return;
  }
  if (state.project.sections.some((s) => s.id === id)) {
    report(`Section "${id}" already exists.`);
    return;
  }
  applySectionChange(() => {
    state.project.sections.push({
      id,
      humanSelected: true,
      fromPoi: null,
      toPoi: null,
      fromAnchor: null,
      toAnchor: null,
      waypoints: [],
      legs: [],
    });
    state.activeSectionId = id;
  });
  if (sectionIdInput) sectionIdInput.value = "";
  report(`Created section "${id}".`);
});

sectionIdInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sectionCreateBtn?.click();
});

sourceFile?.addEventListener("change", () => {
  void runOperation(async () => {
    const files = Array.from(sourceFile?.files ?? []);
    if (files.length === 0) return;
    let imported = 0;
    let rejected = 0;
    const errors: string[] = [];
    for (const file of files) {
      try {
        const src = await importSourceFile(file);
        if (state.project.sources.some((s) => s.id === src.id)) {
          rejected++;
          const detail = `Duplicate source ${src.name} (${src.id})`;
          errors.push(detail);
          report(`Rejected ${detail}.`);
          continue;
        }
        // Add the source to the map first; addSourceLayers is transactional and
        // cleans up after itself on failure, so the project is only mutated once
        // the source is fully installed (no half-added project.sources entry).
        addSourceLayers(map, src, state.registry, DRAFT_LAYER_BEFORE_ID);
        state.project.sources.push(src);
        imported++;
      } catch (err) {
        rejected++;
        const detail = (err as Error).message;
        errors.push(detail);
        report(`Failed to import ${file.name}: ${detail}`);
      }
    }
    if (imported > 0) invalidatePendingSelection();
    renderSourceList();
    if (rejected > 0 && errors.length > 0) {
      report(`Imported ${imported} source(s), rejected ${rejected}. First error: ${errors[0]}`);
    } else {
      report(`Imported ${imported} source(s), rejected ${rejected}.`);
    }
  }).finally(() => {
    if (sourceFile) sourceFile.value = "";
  });
});

projectFile?.addEventListener("change", () => {
  void runOperation(async () => {
    const file = projectFile?.files?.[0];
    if (!file) return;
    const text = await file.text();
    openProjectFromText(text);
  }).finally(() => {
    if (projectFile) projectFile.value = "";
  });
});

outputSourceSearch?.addEventListener("input", () => {
  renderOutputSourceList();
});

outputSourceRefreshBtn?.addEventListener("click", () => {
  void runOperation(refreshOutputLists);
});

outputSourceLoadBtn?.addEventListener("click", () => {
  void runOperation(async () => {
    const selected = Array.from(outputSourceSelect?.selectedOptions ?? []).map((o) => o.value);
    if (selected.length === 0) {
      report("Select one or more output sources to load.");
      return;
    }
    let imported = 0;
    let rejected = 0;
    const errors: string[] = [];
    for (const path of selected) {
      try {
        const { text, sha256 } = await readOutputSource(path);
        const src = await importSourceText(path, text, sha256);
        if (state.project.sources.some((s) => s.id === src.id)) {
          rejected++;
          const detail = `Duplicate source ${src.name} (${src.id})`;
          errors.push(detail);
          report(`Rejected ${detail}.`);
          continue;
        }
        // Same transactional install as the native file path.
        addSourceLayers(map, src, state.registry, DRAFT_LAYER_BEFORE_ID);
        state.project.sources.push(src);
        imported++;
      } catch (err) {
        rejected++;
        const detail = (err as Error).message;
        errors.push(detail);
        report(`Failed to load ${path}: ${detail}`);
      }
    }
    if (imported > 0) invalidatePendingSelection();
    renderSourceList();
    if (rejected > 0 && errors.length > 0) {
      report(`Loaded ${imported} source(s) from output, rejected ${rejected}. First error: ${errors[0]}`);
    } else {
      report(`Loaded ${imported} source(s) from output, rejected ${rejected}.`);
    }
  });
});

outputProjectSearch?.addEventListener("input", () => {
  renderOutputProjectList();
});

outputProjectRefreshBtn?.addEventListener("click", () => {
  void runOperation(refreshOutputLists);
});

outputProjectOpenBtn?.addEventListener("click", () => {
  void runOperation(async () => {
    const path = outputProjectSelect?.selectedOptions[0]?.value;
    if (!path) {
      report("Select an output project to open.");
      return;
    }
    const text = await readOutputFile(path);
    openProjectFromText(text);
  });
});

saveProjectBtn?.addEventListener("click", saveProject);
exportFinalGeojsonBtn?.addEventListener("click", () => exportGeoJSON(false));
exportQaGeojsonBtn?.addEventListener("click", () => exportGeoJSON(true));
exportFinalKmlBtn?.addEventListener("click", () => exportKML(false));
exportQaKmlBtn?.addEventListener("click", () => exportKML(true));
