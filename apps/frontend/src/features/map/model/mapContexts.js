import React from 'react';

// Stable context for passing edge interaction callbacks to SmartEdge without
// re-rendering every edge when the callback ref changes.
export const MapEdgeCallbacksContext = React.createContext({ current: null });

// Context for display-only view options consumed by edges/nodes without
// requiring edge data re-writes (edgeMode, edgeLabelVisible, nodeSpacing).
export const MapViewOptionsContext = React.createContext({
  edgeMode: 'smoothstep',
  edgeLabelVisible: true,
  nodeSpacing: 1,
});
