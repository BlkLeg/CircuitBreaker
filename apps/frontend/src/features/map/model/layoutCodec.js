/**
 * Read and write the stored map layout document.
 *
 * The only module that knows how a layout is persisted. Three shapes exist in
 * the wild:
 *
 *   v0  a bare `{ nodeId: {x, y} }` map, pre-dating structured layouts
 *   v1  the structured document, no version marker, view options at top level
 *   v2  the same, plus `schemaVersion` and a nested `view` object
 *
 * v2 writes the view options **twice** — nested under `view` and flat at the
 * top level. That duplication is deliberate. A self-hoster can run a rebuilt
 * frontend against a server they have not restarted, or roll back a release,
 * and an older parser reads `edgeMode` and friends from the top level. Moving
 * them would silently reset the user's view options on the older build, which
 * the project's compatibility rule forbids: add fields alongside old ones
 * rather than renaming or dropping.
 */

/** Version stamped on documents this codec writes. */
export const LAYOUT_SCHEMA_VERSION = 2;

const VIEW_DEFAULTS = Object.freeze({
  edgeMode: 'smoothstep',
  edgeLabelVisible: true,
  nodeSpacing: 1,
  groupBy: 'none',
});

const EMPTY_DOCUMENT = Object.freeze({
  nodes: {},
  edges: {},
  boundaries: [],
  labels: [],
  visualLines: [],
  nodeShapes: {},
  ...VIEW_DEFAULTS,
});

/** True when `parsed` is a structured document rather than a bare position map. */
function isStructured(parsed) {
  return Boolean(parsed) && typeof parsed.nodes === 'object' && !Array.isArray(parsed.nodes);
}

/**
 * Reads any stored layout shape into the flat document the app works with.
 *
 * @param {string|object} raw - the stored `layout_data`, JSON or parsed
 * @returns {object} nodes, edges, boundaries, labels, visualLines, nodeShapes
 *   and the four view options, always populated
 */
export function decodeLayout(raw) {
  const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;

  if (!isStructured(parsed)) {
    // v0: the whole payload was the node-position map.
    return { ...EMPTY_DOCUMENT, nodes: parsed || {} };
  }

  const view = parsed.view && typeof parsed.view === 'object' ? parsed.view : {};
  /* eslint-disable-next-line security/detect-object-injection -- `key` is one of this module's own literal view-option names */
  const pick = (key) => view[key] ?? parsed[key];

  return {
    nodes: parsed.nodes || {},
    edges: parsed.edges || {},
    boundaries: Array.isArray(parsed.boundaries) ? parsed.boundaries : [],
    labels: Array.isArray(parsed.labels) ? parsed.labels : [],
    visualLines: Array.isArray(parsed.visualLines) ? parsed.visualLines : [],
    nodeShapes: parsed.nodeShapes && typeof parsed.nodeShapes === 'object' ? parsed.nodeShapes : {},
    edgeMode: pick('edgeMode') || VIEW_DEFAULTS.edgeMode,
    edgeLabelVisible: pick('edgeLabelVisible') ?? VIEW_DEFAULTS.edgeLabelVisible,
    nodeSpacing: pick('nodeSpacing') || VIEW_DEFAULTS.nodeSpacing,
    groupBy: pick('groupBy') || VIEW_DEFAULTS.groupBy,
  };
}

/**
 * Builds the document to persist. See the module note on why the view options
 * are written both nested and flat.
 *
 * @param {object} doc - the in-memory layout
 * @returns {object} the versioned document to serialize
 */
export function encodeLayout(doc) {
  const view = {
    edgeMode: doc.edgeMode,
    edgeLabelVisible: doc.edgeLabelVisible,
    nodeSpacing: doc.nodeSpacing,
    groupBy: doc.groupBy,
  };
  return {
    schemaVersion: LAYOUT_SCHEMA_VERSION,
    nodes: doc.nodes,
    nodeShapes: doc.nodeShapes,
    edges: doc.edges,
    boundaries: doc.boundaries,
    labels: doc.labels,
    visualLines: doc.visualLines,
    view,
    // Flat mirror for older readers — see the module note.
    ...view,
  };
}
