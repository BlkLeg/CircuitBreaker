import React from 'react';
import PropTypes from 'prop-types';
import ReactFlow, { Background, Controls } from 'reactflow';
import LegendPanel from './LegendPanel';
import PrivacyScoreWidget from '../../../components/security/PrivacyScoreWidget';
import HostileNetworkBanner from '../../../components/security/HostileNetworkBanner';
import { CONNECTION_LINE_STYLE, DEFAULT_EDGE_OPTIONS } from '../../../lib/constants';
import {
  getMapViewportStorageKey,
  MAP_MIN_ZOOM,
  VIEWPORT_FIT_DEFAULTS,
} from '../../../utils/viewportFit';

/**
 * The map's renderer. Picks between the Sigma canvas and React Flow and wires
 * the graph to the interaction handlers — it draws, it does not fetch.
 *
 * `nodeTypes` / `edgeTypes` are passed in rather than imported so this module
 * does not depend on the node and edge components directly; React Flow needs
 * those objects to be referentially stable, which is the page's job.
 *
 * It takes no `route`: now that neither renderer fetches, nothing here needs to
 * know which map is active.
 */
export default function MapCanvas({
  SigmaMap,
  mapId,
  nodes,
  edges,
  nodeTypes,
  edgeTypes,
  flow,
  editorUi,
  view,
  filters,
  persistence,
  legendOpen,
  onLegendToggle,
}) {
  const {
    handleNodesChange,
    onEdgesChange,
    handleConnect,
    onConnectStart,
    onConnectEnd,
    handleNodeClick,
    handleNodeContextMenu,
    handleNodeDragStart,
    handleNodeDragStop,
    handleNodeMouseEnter,
    handleNodeMouseLeave,
    handlePaneClick,
    handlePaneContextMenu,
    handlePanePointerMove,
    handleEdgeContextMenu,
    handleEdgeUpdate,
    setEdgeMenu,
    setPendingConnection,
  } = flow;
  const { boundaryDrawMode, lineDrawMode } = editorUi;
  const { useSigma, bgGridColor } = view;
  const { includeTypes } = filters;
  const { loading } = persistence;
  const NODE_TYPES = nodeTypes;
  const EDGE_TYPES = edgeTypes;
  const setLegendOpen = onLegendToggle;

  return useSigma ? (
    <React.Suspense fallback={null}>
      <SigmaMap nodes={nodes} edges={edges} />
    </React.Suspense>
  ) : (
    <ReactFlow
      onlyRenderVisibleElements={true}
      className={boundaryDrawMode || lineDrawMode ? 'map-draw-mode' : ''}
      style={{
        zIndex: 5,
        cursor: boundaryDrawMode || lineDrawMode ? 'crosshair' : 'default',
      }}
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      nodes={nodes}
      edges={edges}
      onNodesChange={handleNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeDragStart={handleNodeDragStart}
      onNodeDragStop={handleNodeDragStop}
      onNodeMouseEnter={handleNodeMouseEnter}
      onNodeMouseLeave={handleNodeMouseLeave}
      onNodeClick={handleNodeClick}
      onNodeContextMenu={handleNodeContextMenu}
      onPaneContextMenu={handlePaneContextMenu}
      onEdgeContextMenu={handleEdgeContextMenu}
      onConnect={handleConnect}
      onConnectStart={onConnectStart}
      onConnectEnd={onConnectEnd}
      onEdgeUpdate={handleEdgeUpdate}
      onMoveEnd={(event, vp) => {
        if (event) {
          localStorage.setItem(getMapViewportStorageKey(mapId), JSON.stringify(vp));
        }
      }}
      onPaneMouseMove={handlePanePointerMove}
      connectionLineType="smoothstep"
      connectionMode="loose"
      connectionRadius={14}
      connectionLineStyle={CONNECTION_LINE_STYLE}
      defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
      onPaneClick={() => {
        setEdgeMenu(null);
        setPendingConnection(null);
        handlePaneClick();
      }}
      fitView
      fitViewOptions={VIEWPORT_FIT_DEFAULTS}
      minZoom={MAP_MIN_ZOOM}
      maxZoom={2.5}
      panOnDrag={!boundaryDrawMode && !lineDrawMode}
      panOnScroll={!boundaryDrawMode && !lineDrawMode}
      zoomOnScroll={!boundaryDrawMode && !lineDrawMode}
      zoomOnPinch={!boundaryDrawMode && !lineDrawMode}
      zoomOnDoubleClick={!boundaryDrawMode && !lineDrawMode}
      preventScrolling /* keep page from scrolling when pointer is over map */
      deleteKeyCode={null}
    >
      {/* Loading overlay */}
      {loading && nodes.length === 0 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--color-bg)',
            zIndex: 100,
          }}
        >
          <div
            className="login-spin"
            style={{
              width: 48,
              height: 48,
              border: '4px solid var(--color-border)',
              borderTopColor: 'var(--color-primary)',
              borderRadius: '50%',
            }}
          />
          <p style={{ marginTop: 16, color: 'var(--color-text-muted)', fontSize: 14 }}>
            Loading topology…
          </p>
        </div>
      )}

      {/* Legend */}
      <LegendPanel
        legendOpen={legendOpen}
        setLegendOpen={setLegendOpen}
        includeTypes={includeTypes}
      />
      <PrivacyScoreWidget />
      <HostileNetworkBanner />
      <Controls style={{ zIndex: 35 }} />
      <Background color={bgGridColor} gap={24} size={1} />
    </ReactFlow>
  );
}

MapCanvas.propTypes = {
  SigmaMap: PropTypes.elementType.isRequired,
  mapId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  nodes: PropTypes.array.isRequired,
  edges: PropTypes.array.isRequired,
  nodeTypes: PropTypes.object.isRequired,
  edgeTypes: PropTypes.object.isRequired,
  flow: PropTypes.object.isRequired,
  editorUi: PropTypes.object.isRequired,
  view: PropTypes.object.isRequired,
  filters: PropTypes.object.isRequired,
  persistence: PropTypes.object.isRequired,
  legendOpen: PropTypes.bool,
  onLegendToggle: PropTypes.func.isRequired,
};
