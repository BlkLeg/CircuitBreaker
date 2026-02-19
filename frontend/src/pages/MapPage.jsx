import React, { useCallback, useEffect, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Panel,
  Position,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from '@dagrejs/dagre';
import ELK from 'elkjs/lib/elk.bundled.js';
import { useNavigate } from 'react-router-dom';
import { X, ExternalLink } from 'lucide-react';
import { graphApi, hardwareApi, computeUnitsApi, servicesApi, storageApi, networksApi, miscApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import { getIconEntry } from '../components/common/IconPickerModal';
import { getVendorIcon } from '../icons/vendorIcons';

const elk = new ELK();

// ── Node Styles ─────────────────────────────────────────────────────────────
const NODE_STYLES = {
  hardware: { background: '#4a7fa5', borderColor: '#2c5f7a', glowColor: '#4a7fa5' },  // steel blue
  compute:  { background: '#3a7d44', borderColor: '#1f5c2c', glowColor: '#3a7d44' },  // green
  service:  { background: '#c2601e', borderColor: '#8f4012', glowColor: '#e07030' },  // orange
  storage:  { background: '#7b4fa0', borderColor: '#5a3278', glowColor: '#7b4fa0' },  // purple
  network:  { background: '#0e8a8a', borderColor: '#0a6060', glowColor: '#0eb8b8' },  // cyan
  misc:     { background: '#4a5568', borderColor: '#2d3748', glowColor: '#6b7a96' },  // gray
};

// Per-relation edge accent colours
const EDGE_COLORS = {
  hosts:           '#4a7fa5',
  runs:            '#3a7d44',
  connects_to:     '#0eb8b8',
  depends_on:      '#e07030',
  uses:            '#7b4fa0',
  integrates_with: '#6b7a96',
  routes:          '#ff6b35',
  on_network:      '#00d4aa',
};

const NODE_TYPE_LABELS = {
  hardware: 'Hardware',
  compute: 'Compute',
  service: 'Service',
  storage: 'Storage',
  network: 'Network',
  misc: 'Misc',
};

// Map node type → page route for "Open in HUD"
const NODE_TYPE_ROUTES = {
  hardware: '/hardware',
  compute: '/compute-units',
  service: '/services',
  storage: '/storage',
  network: '/networks',
  misc: '/misc',
};

const BASE_NODE_STYLE = {
  background: 'transparent',
  border: 'none',
  boxShadow: 'none',
  padding: 0,
  width: 140,
};

// ── Icon Resolution ──────────────────────────────────────────────────────────

function resolveNodeIcon(type, icon_slug, vendor) {
  if (icon_slug) return getIconEntry(icon_slug)?.path ?? null;
  if (type === 'hardware' && vendor) return getVendorIcon(vendor)?.path ?? null;
  return null;
}

// ── Custom Node ──────────────────────────────────────────────────────────────

function IconNode({ data }) {
  const glow = data.glowColor || '#4a7fa5';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0, userSelect: 'none', cursor: 'pointer' }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0 }} />

      {/* Glow ring + icon */}
      <div style={{
        width: 64,
        height: 64,
        borderRadius: '50%',
        background: `radial-gradient(circle, ${glow}28 0%, ${glow}0a 70%, transparent 100%)`,
        boxShadow: `0 0 20px 5px ${glow}44, 0 0 6px 1px ${glow}88, inset 0 0 10px ${glow}15`,
        border: `1.5px solid ${glow}99`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 8,
        flexShrink: 0,
        transition: 'box-shadow 0.2s ease',
      }}>
        {data.iconSrc ? (
          <img
            src={data.iconSrc}
            alt=""
            width={38}
            height={38}
            style={{ objectFit: 'contain', filter: 'drop-shadow(0 2px 6px rgba(0,0,0,0.7)) drop-shadow(0 0 8px rgba(255,255,255,0.1))' }}
            onError={(e) => { e.target.style.display = 'none'; }}
          />
        ) : (
          <span style={{ fontSize: 24, fontWeight: 700, color: '#fff', textShadow: `0 0 14px ${glow}` }}>
            {data.label?.[0]?.toUpperCase() || '?'}
          </span>
        )}
      </div>

      {/* Label */}
      <div style={{
        fontSize: 12,
        fontWeight: 600,
        color: '#ffffff',
        textShadow: '0 1px 8px rgba(0,0,0,1), 0 0 16px rgba(0,0,0,0.9)',
        textAlign: 'center',
        maxWidth: 130,
        lineHeight: 1.3,
        letterSpacing: '0.01em',
        whiteSpace: 'normal',
        wordBreak: 'break-word',
      }}>
        {data.label}
      </div>

      {/* IP address (compute) or CIDR (network) */}
      {(data.ip_address || data.cidr) && (
        <div style={{
          fontSize: 10,
          color: '#00d4ff',
          marginTop: 3,
          fontFamily: 'monospace',
          textShadow: '0 0 8px rgba(0,212,255,0.7)',
          letterSpacing: '0.02em',
        }}>
          {data.ip_address || data.cidr}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0 }} />
    </div>
  );
}

const NODE_TYPES = { iconNode: IconNode };

// ── Entity field definitions for the sidebar ────────────────────────────────
const ENTITY_FIELDS = {
  hardware: [
    { key: 'role',       label: 'Role' },
    { key: 'vendor',     label: 'Vendor' },
    { key: 'model',      label: 'Model' },
    { key: 'ip_address', label: 'IP Address' },
    { key: 'wan_uplink', label: 'WAN / Uplink' },
    { key: 'cpu',        label: 'CPU' },
    { key: 'memory_gb',  label: 'Memory',   fmt: v => `${v} GB` },
    { key: 'location',   label: 'Location' },
    { key: 'notes',      label: 'Notes' },
  ],
  compute: [
    { key: 'kind',       label: 'Kind' },
    { key: 'os',         label: 'OS' },
    { key: 'ip_address', label: 'IP Address' },
    { key: 'cpu_cores',  label: 'CPU Cores' },
    { key: 'memory_mb',  label: 'Memory',  fmt: v => `${v} MB` },
    { key: 'disk_gb',    label: 'Disk',    fmt: v => `${v} GB` },
    { key: 'environment',label: 'Env' },
    { key: 'notes',      label: 'Notes' },
  ],
  service: [
    { key: 'slug',        label: 'Slug' },
    { key: 'category',    label: 'Category' },
    { key: 'status',      label: 'Status' },
    { key: 'url',         label: 'URL' },
    { key: 'ports',       label: 'Ports' },
    { key: 'environment', label: 'Env' },
    { key: 'description', label: 'Description' },
  ],
  storage: [
    { key: 'kind',        label: 'Kind' },
    { key: 'capacity_gb', label: 'Capacity', fmt: v => `${v} GB` },
    { key: 'path',        label: 'Path' },
    { key: 'protocol',    label: 'Protocol' },
    { key: 'notes',       label: 'Notes' },
  ],
  network: [
    { key: 'cidr',        label: 'CIDR' },
    { key: 'vlan_id',     label: 'VLAN ID' },
    { key: 'gateway',     label: 'Gateway' },
    { key: 'description', label: 'Description' },
  ],
  misc: [
    { key: 'kind',        label: 'Kind' },
    { key: 'url',         label: 'URL' },
    { key: 'description', label: 'Description' },
  ],
};

const ENTITY_API_GET = {
  hardware: (id) => hardwareApi.get(id),
  compute:  (id) => computeUnitsApi.get(id),
  service:  (id) => servicesApi.get(id),
  storage:  (id) => storageApi.get(id),
  network:  (id) => networksApi.get(id),
  misc:     (id) => miscApi.get(id),
};

// ── Layout Algorithms ───────────────────────────────────────────────────────

const getDagreLayout = (nodes, edges, direction = 'TB') => {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: direction, ranksep: 120, nodesep: 100 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((node) => {
    g.setNode(node.id, { width: node.style?.width || 140, height: 120 });
  });
  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target);
  });
  dagre.layout(g);
  return {
    nodes: nodes.map((node) => {
      const { x, y } = g.node(node.id);
      return { ...node, position: { x: x - (node.style?.width || 140) / 2, y: y - 60 } };
    }),
    edges,
  };
};

const getElkLayout = async (nodes, edges, algorithm = 'layered') => {
  const graph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': algorithm,
      'elk.direction': 'DOWN',
      'elk.spacing.nodeNode': '80',
      'elk.layered.spacing.nodeNodeBetweenLayers': '100',
    },
    children: nodes.map((n) => ({ id: n.id, width: 140, height: 120 })),
    edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  const layout = await elk.layout(graph);
  const layoutMap = {};
  layout.children.forEach((node) => { layoutMap[node.id] = { x: node.x, y: node.y }; });
  return {
    nodes: nodes.map((node) => ({ ...node, position: layoutMap[node.id] || { x: 0, y: 0 } })),
    edges,
  };
};

const getGridLayout = (nodes, edges) => {
  const groups = { hardware: [], compute: [], service: [], storage: [], network: [], misc: [] };
  nodes.forEach(n => { if (groups[n.originalType]) groups[n.originalType].push(n); });
  const ORDER = ['hardware', 'compute', 'service', 'network', 'storage', 'misc'];
  let y = 0;
  const newNodes = [];
  ORDER.forEach(type => {
    const group = groups[type] || [];
    if (group.length === 0) return;
    group.forEach((node, i) => { newNodes.push({ ...node, position: { x: i * 220, y } }); });
    y += 150;
  });
  return { nodes: newNodes, edges };
};

// ── Main Component ──────────────────────────────────────────────────────────

function MapInternal() {
  const { fitView } = useReactFlow();
  const { settings } = useSettings();
  const navigate = useNavigate();

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [layoutEngine, setLayoutEngine] = useState('dagre');
  const [lastSaved, setLastSaved] = useState(null);
  const [dirty, setDirty] = useState(false);

  // Filters
  const [envFilter, setEnvFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [includeTypes, setIncludeTypes] = useState({
    hardware: true, compute: true, service: true,
    storage: true, network: true, misc: true,
  });

  // Tooltip state
  const [tooltip, setTooltip] = useState(null); // { x, y, node }

  // Entity details for the selected node
  const [nodeDetails, setNodeDetails] = useState(null);
  const [nodeDetailsLoading, setNodeDetailsLoading] = useState(false);

  // Selected node side panel
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    if (!selectedNode) { setNodeDetails(null); return; }
    const fetcher = ENTITY_API_GET[selectedNode.originalType];
    if (!fetcher || !selectedNode._refId) return;
    setNodeDetails(null);
    setNodeDetailsLoading(true);
    fetcher(selectedNode._refId)
      .then(res => setNodeDetails(res.data))
      .catch(() => setNodeDetails(null))
      .finally(() => setNodeDetailsLoading(false));
  }, [selectedNode]);

  // Debounce tag filter
  const tagDebounceRef = useRef(null);
  const [debouncedTag, setDebouncedTag] = useState('');

  // Settings initialization (run once after settings load)
  const settingsApplied = useRef(false);
  useEffect(() => {
    if (settings && !settingsApplied.current) {
      settingsApplied.current = true;
      if (settings.default_environment) setEnvFilter(settings.default_environment);
      if (settings.map_default_filters && typeof settings.map_default_filters === 'object') {
        const f = settings.map_default_filters;
        if (f.include && typeof f.include === 'object') {
          setIncludeTypes(prev => ({ ...prev, ...f.include }));
        }
      }
    }
  }, [settings]);

  useEffect(() => {
    clearTimeout(tagDebounceRef.current);
    tagDebounceRef.current = setTimeout(() => setDebouncedTag(tagFilter), 300);
    return () => clearTimeout(tagDebounceRef.current);
  }, [tagFilter]);

  // Re-apply tag filter client-side (preserves positions via hidden property)
  useEffect(() => {
    const trimmedTag = debouncedTag.trim().toLowerCase();
    setNodes(prev => prev.map(n => ({
      ...n,
      hidden: trimmedTag ? !(n._tags || []).some(t => t.toLowerCase().includes(trimmedTag)) : false,
    })));
    setEdges(prev => prev.map(e => {
      if (!trimmedTag) return { ...e, hidden: false };
      return e; // edge visibility handled by ReactFlow when both nodes are hidden
    }));
  }, [debouncedTag, setNodes, setEdges]);

  const getIncludeCSV = (types) => {
    const MAP = { hardware: 'hardware', compute: 'compute', service: 'services', storage: 'storage', network: 'networks', misc: 'misc' };
    return Object.entries(types).filter(([, v]) => v).map(([k]) => MAP[k]).join(',') || 'hardware';
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const includeCSV = getIncludeCSV(includeTypes);
      const res = await graphApi.topology({
        environment: envFilter || undefined,
        include: includeCSV,
      });

      const rawN = res.data.nodes.map(n => ({
        id: n.id,
        type: 'iconNode',
        data: {
          label: n.label,
          iconSrc: resolveNodeIcon(n.type, n.icon_slug, n.vendor),
          glowColor: NODE_STYLES[n.type]?.glowColor,
          ip_address: n.ip_address || null,
          cidr: n.cidr || null,
        },
        position: { x: 0, y: 0 },
        style: { ...BASE_NODE_STYLE },
        originalType: n.type,
        _tags: n.tags || [],
        _refId: n.ref_id,
      }));

      const rawE = res.data.edges.map(e => {
        const color = EDGE_COLORS[e.relation] || '#6c7086';
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.relation,
          animated: e.relation === 'depends_on' || e.relation === 'runs',
          style: { stroke: color, strokeWidth: 1.5, opacity: 0.75 },
          labelStyle: { fill: '#cdd6f4', fontSize: 9, fontWeight: 500 },
          labelBgStyle: { fill: 'rgba(6,10,20,0.88)', rx: 6 },
          labelBgPadding: [3, 7],
          labelBgBorderRadius: 6,
          _relation: e.relation,
        };
      });

      // Try to load saved layout
      let savedPositions = null;
      try {
        const layoutRes = await graphApi.getLayout('default');
        if (layoutRes.data.layout_data) {
          savedPositions = JSON.parse(layoutRes.data.layout_data);
          setLastSaved(layoutRes.data.updated_at);
        }
      } catch { /* no saved layout */ }

      if (savedPositions) {
        const mergedNodes = rawN.map(n => ({
          ...n, position: savedPositions[n.id] || { x: 0, y: 0 },
        }));
        setNodes(mergedNodes);
        setEdges(rawE);
        setLayoutEngine('manual');
      } else {
        const layout = getDagreLayout(rawN, rawE);
        setNodes(layout.nodes);
        setEdges(layout.edges);
      }

      setTimeout(() => fitView({ padding: 0.2 }), 50);
    } catch (err) {
      setError(err.message || 'Failed to load topology');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [envFilter, includeTypes, fitView]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const applyLayout = useCallback(async (engine) => {
    setLoading(true);
    setTimeout(async () => {
      let layout;
      if (engine === 'dagre') layout = getDagreLayout(nodes, edges, 'TB');
      else if (engine === 'dagre-lr') layout = getDagreLayout(nodes, edges, 'LR');
      else if (engine === 'elk') layout = await getElkLayout(nodes, edges, 'layered');
      else if (engine === 'grid') layout = getGridLayout(nodes, edges);
      if (layout) {
        setNodes([...layout.nodes]);
        setEdges([...layout.edges]);
        setTimeout(() => fitView({ duration: 800, padding: 0.2 }), 10);
      }
      setLayoutEngine(engine);
      setDirty(true);
      setLoading(false);
    }, 50);
  }, [nodes, edges, setNodes, setEdges, fitView]);

  const saveLayout = async () => {
    const positions = {};
    nodes.forEach(n => { positions[n.id] = n.position; });
    try {
      await graphApi.saveLayout('default', JSON.stringify(positions));
      setLastSaved(new Date().toISOString());
      setDirty(false);
    } catch (err) {
      setError('Failed to save layout: ' + err.message);
    }
  };

  // ── Node interactions ──────────────────────────────────────────────────────

  const handleNodeMouseEnter = useCallback((event, node) => {
    setTooltip({ x: event.clientX + 14, y: event.clientY - 10, node });
  }, []);

  const handleNodeMouseLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  const handleNodeClick = useCallback((event, node) => {
    setTooltip(null);

    // Highlight connected edges
    const connectedEdgeIds = new Set(
      edges.filter(e => e.source === node.id || e.target === node.id).map(e => e.id)
    );
    setEdges(prev => prev.map(e => ({
      ...e,
      style: connectedEdgeIds.has(e.id)
        ? { stroke: '#00d4ff', strokeWidth: 2.5, opacity: 1 }
        : { stroke: EDGE_COLORS[e._relation] || '#6c7086', strokeWidth: 1.5, opacity: 0.25 },
      animated: connectedEdgeIds.has(e.id) ? true : (e._relation === 'depends_on' || e._relation === 'runs'),
    })));

    // Build related nodes info
    const related = [];
    edges.forEach(e => {
      if (e.source === node.id) {
        const target = nodes.find(n => n.id === e.target);
        if (target) related.push({ direction: 'out', relation: e._relation || e.label, node: target });
      } else if (e.target === node.id) {
        const source = nodes.find(n => n.id === e.source);
        if (source) related.push({ direction: 'in', relation: e._relation || e.label, node: source });
      }
    });

    setSelectedNode({ ...node, related });
  }, [edges, nodes, setEdges]);

  const handlePaneClick = useCallback(() => {
    if (selectedNode) {
      // Reset edge highlight
      setEdges(prev => prev.map(e => ({
        ...e,
        style: { stroke: EDGE_COLORS[e._relation] || '#6c7086', strokeWidth: 1.5, opacity: 0.75 },
        animated: e._relation === 'depends_on' || e._relation === 'runs',
      })));
      setSelectedNode(null);
    }
  }, [selectedNode, setEdges]);

  const focusNode = (nodeId) => {
    fitView({ nodes: [{ id: nodeId }], duration: 600, padding: 0.5 });
  };

  return (
    <div className="page map-page" style={{ height: 'calc(100vh - 60px)', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      {/* Header + Toolbar */}
      <div className="page-header" style={{ marginBottom: 0, paddingBottom: 10, borderBottom: '1px solid var(--color-border)', flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ marginRight: 16 }}>Topology</h2>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flex: 1 }}>
          {/* Environment */}
          <select
            value={envFilter}
            onChange={(e) => setEnvFilter(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            <option value="">All Environments</option>
            {(settings?.environments ?? ['prod', 'staging', 'dev']).map(e => (
              <option key={e} value={e}>{e}</option>
            ))}
          </select>

          {/* Tag filter */}
          <input
            type="text"
            placeholder="Filter by tag…"
            value={tagFilter}
            onChange={e => setTagFilter(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12, width: 130 }}
          />

          {/* Node type toggles */}
          <span style={{ color: 'var(--color-text-muted)', fontSize: 11, borderLeft: '1px solid var(--color-border)', paddingLeft: 8 }}>Show:</span>
          {Object.entries(NODE_STYLES).map(([type, style]) => (
            <button
              key={type}
              onClick={() => setIncludeTypes(prev => ({ ...prev, [type]: !prev[type] }))}
              style={{
                padding: '3px 8px',
                borderRadius: 4,
                border: `1px solid ${style.borderColor}`,
                background: includeTypes[type] ? style.background : 'transparent',
                color: includeTypes[type] ? '#fff' : style.background,
                fontSize: 11,
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              {NODE_TYPE_LABELS[type]}
            </button>
          ))}

          {/* Divider */}
          <span style={{ color: 'var(--color-text-muted)', borderLeft: '1px solid var(--color-border)', paddingLeft: 8, fontSize: 11 }}>Layout:</span>
          <select
            value={layoutEngine}
            onChange={(e) => applyLayout(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            <option value="manual">Manual / Saved</option>
            <option value="dagre">Hierarchical (Down)</option>
            <option value="dagre-lr">Hierarchical (Right)</option>
            <option value="elk">ELK Layered</option>
            <option value="grid">Grid</option>
          </select>

          <button className="btn btn-primary" onClick={saveLayout} disabled={loading} style={{ fontSize: 12, padding: '5px 12px' }}>
            {loading ? 'Loading…' : 'Save Positions'}
          </button>
          <button className="btn" onClick={fetchData} disabled={loading} style={{ fontSize: 12, padding: '5px 12px' }}>
            Refresh
          </button>
          {lastSaved && <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Saved: {new Date(lastSaved).toLocaleTimeString()}</span>}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{ background: 'rgba(243,139,168,0.15)', border: '1px solid #f38ba8', color: '#f38ba8', padding: '6px 12px', fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{error}</span>
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#f38ba8', cursor: 'pointer' }}><X size={14} /></button>
        </div>
      )}

      {/* Graph canvas */}
      <div style={{ flex: 1, position: 'relative', background: '#060a12' }}>
        <ReactFlow
          nodeTypes={NODE_TYPES}
          nodes={nodes}
          edges={edges}
          onNodesChange={(changes) => {
            onNodesChange(changes);
            if (changes.some(c => c.type === 'position' && c.dragging)) setDirty(true);
          }}
          onEdgesChange={onEdgesChange}
          onNodeMouseEnter={handleNodeMouseEnter}
          onNodeMouseLeave={handleNodeMouseLeave}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          fitView
          minZoom={0.1}
        >
          {/* Legend */}
          <Panel position="top-right" style={{ background: 'rgba(8,12,20,0.85)', padding: 10, borderRadius: 8, fontSize: 11, color: '#fff', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-text-muted)' }}>Legend</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {Object.entries(NODE_STYLES).map(([type, style]) => (
                <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 12, height: 12, background: style.background, borderRadius: 2, border: `1px solid ${style.borderColor}` }} />
                  <span style={{ textTransform: 'capitalize', color: includeTypes[type] ? '#fff' : 'var(--color-text-muted)' }}>{type}</span>
                </div>
              ))}
            </div>
          </Panel>
          <Controls />
          <Background color="#1a2035" gap={24} size={1} />
        </ReactFlow>

        {/* Hover tooltip */}
        {tooltip && (
          <div
            style={{
              position: 'fixed',
              left: tooltip.x,
              top: tooltip.y,
              background: 'rgba(8,12,20,0.95)',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: 6,
              padding: '8px 12px',
              fontSize: 12,
              color: '#cdd6f4',
              pointerEvents: 'none',
              zIndex: 9999,
              maxWidth: 220,
              boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{tooltip.node.data.label}</div>
            <div style={{ color: 'var(--color-text-muted)', marginBottom: tooltip.node._tags?.length ? 4 : 0 }}>
              Type: <span style={{ color: NODE_STYLES[tooltip.node.originalType]?.background }}>{NODE_TYPE_LABELS[tooltip.node.originalType] || tooltip.node.originalType}</span>
            </div>
            {tooltip.node._tags?.length > 0 && (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {tooltip.node._tags.map(t => (
                  <span key={t} style={{ background: 'rgba(0,212,255,0.12)', color: '#00d4ff', borderRadius: 3, padding: '1px 5px', fontSize: 10 }}>{t}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Side panel */}
        {selectedNode && (
          <div
            style={{
              position: 'absolute',
              top: 0,
              right: 0,
              width: 280,
              height: '100%',
              background: 'var(--color-surface)',
              borderLeft: '1px solid var(--color-border)',
              zIndex: 100,
              display: 'flex',
              flexDirection: 'column',
              overflowY: 'auto',
            }}
          >
            {/* Panel header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--color-border)' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--color-text)' }}>{selectedNode.data.label}</div>
                <div style={{ fontSize: 11, marginTop: 2 }}>
                  <span style={{
                    background: NODE_STYLES[selectedNode.originalType]?.background,
                    color: '#fff',
                    borderRadius: 3,
                    padding: '1px 6px',
                    fontSize: 10,
                    textTransform: 'capitalize',
                  }}>{NODE_TYPE_LABELS[selectedNode.originalType] || selectedNode.originalType}</span>
                </div>
              </div>
              <button
                onClick={() => {
                  setEdges(prev => prev.map(e => ({ ...e, style: { stroke: '#6c7086' }, animated: e._relation === 'depends_on' || e._relation === 'runs' })));
                  setSelectedNode(null);
                }}
                style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', padding: 4 }}
              >
                <X size={16} />
              </button>
            </div>

            {/* Entity Details */}
            <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--color-border)' }}>
              {nodeDetailsLoading && (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Loading details…</div>
              )}
              {nodeDetails && !nodeDetailsLoading && (() => {
                const fields = ENTITY_FIELDS[selectedNode.originalType] || [];
                const rows = fields.filter(f => nodeDetails[f.key] != null && nodeDetails[f.key] !== '');
                if (rows.length === 0) return null;
                return (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                    <tbody>
                      {rows.map(f => (
                        <tr key={f.key}>
                          <td style={{ color: 'var(--color-text-muted)', paddingBottom: 4, paddingRight: 8, whiteSpace: 'nowrap', verticalAlign: 'top', width: '40%' }}>{f.label}</td>
                          <td style={{ color: 'var(--color-text)', paddingBottom: 4, wordBreak: 'break-word', verticalAlign: 'top' }}>
                            {f.fmt ? f.fmt(nodeDetails[f.key]) : String(nodeDetails[f.key])}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                );
              })()}
            </div>

            {/* Tags */}
            {selectedNode._tags?.length > 0 && (
              <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 6 }}>Tags</div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {selectedNode._tags.map(t => (
                    <span key={t} style={{ background: 'rgba(0,212,255,0.12)', color: '#00d4ff', borderRadius: 3, padding: '2px 7px', fontSize: 11 }}>{t}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Related nodes */}
            {selectedNode.related?.length > 0 && (
              <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--color-border)', flex: 1 }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>Connected Nodes</div>
                {selectedNode.related.map((r) => (
                  <div
                    key={r.node.id}
                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                  >
                    <div style={{ fontSize: 12 }}>
                      <span style={{ color: 'var(--color-text-muted)', fontSize: 10, marginRight: 4 }}>{r.relation}</span>
                      <span style={{ color: 'var(--color-text)' }}>{r.node.data.label}</span>
                    </div>
                    <button
                      onClick={() => focusNode(r.node.id)}
                      style={{ background: 'none', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)', borderRadius: 4, padding: '2px 6px', fontSize: 10, cursor: 'pointer' }}
                    >
                      Focus
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Actions */}
            <div style={{ padding: '12px 16px' }}>
              <button
                className="btn btn-primary"
                style={{ width: '100%', fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
                onClick={() => navigate(NODE_TYPE_ROUTES[selectedNode.originalType] || '/')}
              >
                <ExternalLink size={13} />
                Open in HUD
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function MapPage() {
  return (
    <ReactFlowProvider>
      <MapInternal />
    </ReactFlowProvider>
  );
}
