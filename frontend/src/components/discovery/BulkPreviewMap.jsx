/**
 * BulkPreviewMap — read-only ReactFlow mini-map that shows ghost nodes
 * representing the pending merge results, plus optional cluster/network
 * anchor nodes.  Used inside BulkActionsDrawer to give a visual preview
 * of where the new entities will land on the topology.
 */

import React, { useMemo } from 'react';
import ReactFlow, { Background, ReactFlowProvider } from 'reactflow';
import 'reactflow/dist/style.css';
import PropTypes from 'prop-types';
import { NODE_STYLES, resolveNodeIcon } from '../map/mapConstants';

// ── Tiny custom node for the preview ────────────────────────────────────────
function GhostNode({ data }) {
  const glow = data.glowColor || '#4a7fa5';
  const iconSrc = data.iconSrc;
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
      opacity: data.isGhost ? 0.65 : 1,
      filter: data.isGhost ? 'saturate(0.6)' : 'none',
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: '50%',
        background: `radial-gradient(circle at 40% 35%, ${glow}44, ${glow}11)`,
        border: `2px ${data.isGhost ? 'dashed' : 'solid'} ${glow}`,
        boxShadow: `0 0 10px 2px ${glow}33`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {iconSrc ? (
          <img src={iconSrc} alt="" style={{ width: 20, height: 20, objectFit: 'contain' }} />
        ) : (
          <span style={{ fontSize: 14 }}>🖥</span>
        )}
      </div>
      <span style={{
        fontSize: 9, color: 'var(--color-text-muted)',
        maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        textAlign: 'center',
      }}>
        {data.label}
      </span>
    </div>
  );
}

GhostNode.propTypes = { data: PropTypes.object.isRequired };

function AnchorNode({ data }) {
  const bg = data.bg || '#7c3aed';
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
    }}>
      <div style={{
        width: 44, height: 44, borderRadius: 8,
        background: `${bg}22`, border: `2px solid ${bg}`,
        boxShadow: `0 0 14px 3px ${bg}33`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 18,
      }}>
        {data.emoji}
      </div>
      <span style={{
        fontSize: 10, color: bg, fontWeight: 600,
        maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        textAlign: 'center',
      }}>
        {data.label}
      </span>
    </div>
  );
}

AnchorNode.propTypes = { data: PropTypes.object.isRequired };

const PREVIEW_NODE_TYPES = { ghostNode: GhostNode, anchorNode: AnchorNode };

// ── Layout helpers ──────────────────────────────────────────────────────────
function buildPreviewGraph(results, clusterName, networkName, assignments) {
  const nodes = [];
  const edges = [];
  let yOffset = 0;

  // Cluster anchor
  if (clusterName) {
    nodes.push({
      id: 'cluster-anchor',
      type: 'anchorNode',
      position: { x: 20, y: 20 },
      data: { label: clusterName, emoji: '🗄️', bg: NODE_STYLES.cluster.glowColor },
      draggable: false,
    });
    yOffset = 80;
  }

  // Network anchor
  if (networkName) {
    nodes.push({
      id: 'network-anchor',
      type: 'anchorNode',
      position: { x: 340, y: 20 },
      data: { label: networkName, emoji: '🌐', bg: NODE_STYLES.network.glowColor },
      draggable: false,
    });
    yOffset = Math.max(yOffset, 80);
  }

  // Place result nodes in a grid
  const cols = Math.max(3, Math.ceil(Math.sqrt(results.length)));
  const xGap = 110;
  const yGap = 76;
  const xStart = 20;

  results.forEach((r, i) => {
    const a = assignments?.[r.id] || {};
    const col = i % cols;
    const row = Math.floor(i / cols);

    const role = a.role || '';
    const vendor = a.vendor || r.os_vendor || '';
    const iconSrc = resolveNodeIcon('hardware', a.vendor_icon_slug, vendor, null, role);

    const nodeId = `result-${r.id}`;
    nodes.push({
      id: nodeId,
      type: 'ghostNode',
      position: { x: xStart + col * xGap, y: yOffset + row * yGap },
      data: {
        label: a.name || r.hostname || r.ip_address,
        iconSrc,
        glowColor: NODE_STYLES.hardware.glowColor,
        isGhost: true,
      },
      draggable: false,
    });

    // Edges to cluster
    if (clusterName) {
      edges.push({
        id: `e-cluster-${r.id}`,
        source: 'cluster-anchor',
        target: nodeId,
        type: 'default',
        style: { stroke: NODE_STYLES.cluster.glowColor, strokeDasharray: '4 3', opacity: 0.4 },
        animated: true,
      });
    }

    // Edges to network
    if (networkName) {
      edges.push({
        id: `e-network-${r.id}`,
        source: 'network-anchor',
        target: nodeId,
        type: 'default',
        style: { stroke: NODE_STYLES.network.glowColor, strokeDasharray: '4 3', opacity: 0.4 },
        animated: true,
      });
    }
  });

  return { nodes, edges };
}

// ── Component ───────────────────────────────────────────────────────────────
function BulkPreviewMapInner({ results, clusterName, networkName, assignments }) {
  const { nodes, edges } = useMemo(
    () => buildPreviewGraph(results, clusterName, networkName, assignments),
    [results, clusterName, networkName, assignments],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={PREVIEW_NODE_TYPES}
      fitView
      fitViewOptions={{ padding: 0.3 }}
      panOnDrag={false}
      zoomOnScroll={false}
      zoomOnPinch={false}
      zoomOnDoubleClick={false}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      proOptions={{ hideAttribution: true }}
      style={{ background: 'var(--color-bg)' }}
    >
      <Background variant="dots" gap={16} size={1} color="var(--color-border)" />
    </ReactFlow>
  );
}

BulkPreviewMapInner.propTypes = {
  results:      PropTypes.array.isRequired,
  clusterName:  PropTypes.string,
  networkName:  PropTypes.string,
  assignments:  PropTypes.object,
};

export default function BulkPreviewMap(props) {
  return (
    <ReactFlowProvider>
      <BulkPreviewMapInner {...props} />
    </ReactFlowProvider>
  );
}

BulkPreviewMap.propTypes = BulkPreviewMapInner.propTypes;
