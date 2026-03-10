/**
 * Viewport-aware fit options for the topology map.
 * Used so large graphs fill the viewport at a readable zoom (no ant-sized view).
 */
export const VIEWPORT_FIT_DEFAULTS = {
  padding: 0.1,
  minZoom: 0.2,
  maxZoom: 2.5,
  duration: 800,
};

/**
 * Call ReactFlow fitView with viewport-aware defaults.
 * @param {Function} fitView - ReactFlow's fitView
 * @param {Object} [overrides] - Override defaults (e.g. { duration: 400 } for resize)
 */
export function viewportFit(fitView, overrides = {}) {
  fitView({ ...VIEWPORT_FIT_DEFAULTS, ...overrides });
}
