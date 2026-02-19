import React, { useState, useEffect } from 'react';
import ReactFlow, { Controls, Background } from 'reactflow';
import 'reactflow/dist/style.css';
import { graphApi } from '../api/client';

const NODE_COLORS = {
  hardware: '#f97316',
  compute_unit: '#3b82f6',
  service: '#10b981',
  storage: '#8b5cf6',
  network: '#06b6d4',
};

function toReactFlowNodes(nodes) {
  return nodes.map((n, i) => ({
    id: n.id,
    data: { label: `${n.label}` },
    position: { x: (i % 6) * 220, y: Math.floor(i / 6) * 130 },
    style: {
      background: NODE_COLORS[n.type] || '#555',
      color: '#fff',
      borderRadius: 8,
      border: 'none',
      padding: '8px 12px',
      fontSize: 12,
      fontWeight: 500,
    },
  }));
}

function toReactFlowEdges(edges) {
  return edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.relation,
    animated: e.relation === 'depends_on',
    style: { stroke: '#6c7086' },
    labelStyle: { fill: '#cdd6f4', fontSize: 10 },
  }));
}

function MapPage() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [environment, setEnvironment] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    graphApi
      .topology({ environment: environment || undefined })
      .then((res) => {
        setNodes(toReactFlowNodes(res.data.nodes));
        setEdges(toReactFlowEdges(res.data.edges));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [environment]);

  return (
    <div className="page map-page">
      <div className="page-header">
        <h2>Topology Map</h2>
        <select value={environment} onChange={(e) => setEnvironment(e.target.value)}>
          <option value="">All environments</option>
          <option value="prod">prod</option>
          <option value="lab">lab</option>
          <option value="dev">dev</option>
        </select>
      </div>

      <div
        style={{
          display: 'flex',
          gap: 12,
          marginBottom: 12,
          fontSize: 12,
          color: 'var(--color-text-muted)',
        }}
      >
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span key={type} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span
              style={{
                display: 'inline-block',
                width: 10,
                height: 10,
                borderRadius: 2,
                background: color,
              }}
            />
            {type.replace('_', ' ')}
          </span>
        ))}
      </div>

      <div className="map-container">
        {loading ? (
          <p style={{ padding: 20 }}>Loading topology...</p>
        ) : (
          <ReactFlow nodes={nodes} edges={edges} fitView>
            <Controls />
            <Background color="#3b3b52" gap={16} />
          </ReactFlow>
        )}
      </div>
    </div>
  );
}

export default MapPage;
