/**
 * Viewport-aware fit options for the topology map.
 * Automatic fits must keep the complete topology visible. Users can zoom in
 * afterward when they want to focus on a node or group.
 */
export const MAP_MIN_ZOOM = 0.01;

export const VIEWPORT_FIT_DEFAULTS = {
  padding: 0.15,
  minZoom: MAP_MIN_ZOOM,
  maxZoom: 2.5,
  duration: 800,
};

export function getMapViewportStorageKey(mapId) {
  return `cb_map_viewport_${mapId}`;
}

/**
 * Call ReactFlow fitView with viewport-aware defaults.
 * @param {Function} fitView - ReactFlow's fitView
 * @param {Object} [overrides] - Override defaults (e.g. { duration: 400 } for resize)
 */
export function viewportFit(fitView, overrides = {}) {
  fitView({ ...VIEWPORT_FIT_DEFAULTS, ...overrides });
}
