import React, { useCallback, useEffect, useRef, useState } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import { graphApi } from '../../api/client';

const SIGMA_LAYOUTS = [
  { id: 'forceatlas2', label: 'Force Atlas 2' },
  { id: 'circular', label: 'Circular' },
  { id: 'random', label: 'Random' },
];

function applyCircularLayout(graph) {
  const nodes = graph.nodes();
  const total = nodes.length;
  const radius = Math.max(100, total * 12);
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / total;
    graph.setNodeAttribute(node, 'x', radius * Math.cos(angle));
    graph.setNodeAttribute(node, 'y', radius * Math.sin(angle));
  });
}

function applyRandomLayout(graph) {
  const size = Math.max(500, graph.order * 20);
  graph.nodes().forEach((node) => {
    graph.setNodeAttribute(node, 'x', (Math.random() - 0.5) * size);
    graph.setNodeAttribute(node, 'y', (Math.random() - 0.5) * size);
  });
}

function applyLayout(graph, layoutId) {
  if (layoutId === 'circular') {
    applyCircularLayout(graph);
  } else if (layoutId === 'random') {
    applyRandomLayout(graph);
  } else {
    // forceatlas2 — ensure positions exist first
    graph.nodes().forEach((node) => {
      if (!graph.hasNodeAttribute(node, 'x')) {
        graph.setNodeAttribute(node, 'x', Math.random() * 100);
        graph.setNodeAttribute(node, 'y', Math.random() * 100);
      }
    });
    forceAtlas2.assign(graph, { iterations: 100 });
  }
}

export default function SigmaMap({ envFilter, includeTypes }) {
  const containerRef = useRef(null);
  const sigmaRef = useRef(null);
  const graphRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [sigmaLayout, setSigmaLayout] = useState('forceatlas2');

  const renderWithLayout = useCallback((layoutId) => {
    if (!graphRef.current || !containerRef.current) return;
    try {
      applyLayout(graphRef.current, layoutId);
      if (sigmaRef.current) {
        sigmaRef.current.refresh();
      }
    } catch {
      // layout errors are non-fatal
    }
  }, []);

  useEffect(() => {
    let active = true;
    const loadGraph = async () => {
      try {
        setLoading(true);
        const includeCSV = Array.from(includeTypes.entries())
          .filter(([, v]) => v)
          .map(([k]) => k)
          .join(',');

        const res = await graphApi.topology({
          environment_id: envFilter || undefined,
          include: includeCSV,
          format: 'sigma',
        });

        if (!active) return;

        const graph = new Graph();
        graph.import(res.data);
        graphRef.current = graph;

        applyLayout(graph, sigmaLayout);

        if (sigmaRef.current) {
          sigmaRef.current.kill();
        }

        sigmaRef.current = new Sigma(graph, containerRef.current, {
          renderEdgeLabels: true,
        });

        setLoading(false);
      } catch (err) {
        console.error('Sigma map load failed:', err);
        if (active) setLoading(false);
      }
    };

    loadGraph();

    return () => {
      active = false;
      if (sigmaRef.current) {
        sigmaRef.current.kill();
        sigmaRef.current = null;
      }
      graphRef.current = null;
    };
    // sigmaLayout intentionally excluded — layout changes are handled by the effect below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [envFilter, includeTypes]);

  // Re-apply layout when user changes the layout selector (without reloading data)
  useEffect(() => {
    if (!graphRef.current) return;
    renderWithLayout(sigmaLayout);
  }, [sigmaLayout, renderWithLayout]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      {loading && (
        <div style={{ position: 'absolute', top: 20, left: 20, color: 'white', zIndex: 10 }}>
          Loading massive graph...
        </div>
      )}

      {/* Layout selector */}
      <div
        style={{
          position: 'absolute',
          top: 12,
          right: 12,
          zIndex: 20,
          display: 'flex',
          gap: 4,
          alignItems: 'center',
        }}
      >
        {SIGMA_LAYOUTS.map((l) => (
          <button
            key={l.id}
            onClick={() => setSigmaLayout(l.id)}
            style={{
              padding: '4px 10px',
              borderRadius: 6,
              border: `1px solid ${sigmaLayout === l.id ? '#00d4aa' : 'rgba(255,255,255,0.2)'}`,
              background: sigmaLayout === l.id ? 'rgba(0,212,170,0.15)' : 'rgba(0,0,0,0.55)',
              color: sigmaLayout === l.id ? '#00d4aa' : 'rgba(255,255,255,0.7)',
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              backdropFilter: 'blur(6px)',
            }}
          >
            {l.label}
          </button>
        ))}
      </div>

      <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#1c1e1f' }} />
    </div>
  );
}
