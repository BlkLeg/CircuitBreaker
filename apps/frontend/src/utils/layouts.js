import { Position } from 'reactflow';
import dagre from '@dagrejs/dagre';
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceRadial,
} from 'd3-force';
import { stratify, tree } from 'd3-hierarchy';

// --- Dagre Layout (Hierarchical) ---

/** Build viewport-aware Dagre options from container width (optional). */
export function getDagreViewportOptions(viewportWidth) {
  if (viewportWidth == null || viewportWidth <= 0) return null;
  return {
    rankSep: viewportWidth > 1200 ? 100 : 60,
    nodeSep: Math.max(10, viewportWidth * 0.02),
    edgeSep: 10,
  };
}

/**
 * @param {object} [options] - Optional viewport-aware spacing (rankSep, nodeSep in px).
 */
export const getDagreLayout = (nodes, edges, direction = 'TB', options = null) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  const isHorizontal = direction === 'LR';
  const graphOpts = { rankdir: direction };
  if (options) {
    if (options.rankSep != null) graphOpts.ranksep = options.rankSep;
    if (options.nodeSep != null) graphOpts.nodesep = options.nodeSep;
    if (options.edgeSep != null) graphOpts.edgesep = options.edgeSep;
  }
  dagreGraph.setGraph(graphOpts);

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: 150, height: 100 });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      targetPosition: isHorizontal ? Position.Left : Position.Top,
      sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
      position: {
        x: nodeWithPosition.x - 75, // Center offset
        y: nodeWithPosition.y - 50,
      },
    };
  });

  return { nodes: layoutNodes, edges };
};

// --- Force Directed Layout ---
export const getForceLayout = (nodes, edges) => {
  const simulationNodes = nodes.map((node) => ({
    ...node,
    x: node.position.x || 0,
    y: node.position.y || 0,
  }));
  const simulationEdges = edges.map((edge) => ({
    ...edge,
    source: edge.source,
    target: edge.target,
  }));

  const simulation = forceSimulation(simulationNodes)
    .force(
      'link',
      forceLink(simulationEdges)
        .id((d) => d.id)
        .distance(200)
    )
    .force('charge', forceManyBody().strength(-1000))
    .force('center', forceCenter(500, 300))
    .force('collide', forceCollide(100))
    .stop();

  // Run simulation for a fixed number of ticks to stabilize
  for (let i = 0; i < 300; ++i) simulation.tick();

  const layoutNodes = nodes.map((node, index) => {
    const simNode = simulationNodes[index];
    return {
      ...node,
      position: { x: simNode.x, y: simNode.y },
    };
  });

  return { nodes: layoutNodes, edges };
};

// --- Tree Layout (D3-Hierarchy) ---
export const getTreeLayout = (nodes, edges) => {
  // First, we need to convert the graph structure to a hierarchical one suitable for d3.
  // We identify root nodes (nodes with no incoming edges or the first node if circular).

  const connectedNodes = new Set();
  const childrenMap = new Map();
  const parentMap = new Map();

  // Build basic child/parent mappings to find roots
  edges.forEach((e) => {
    connectedNodes.add(e.source);
    connectedNodes.add(e.target);
    if (!childrenMap.has(e.source)) childrenMap.set(e.source, []);
    childrenMap.get(e.source).push(e.target);

    // Only set first parent to avoid DAG circles during strict Tree building
    if (!parentMap.has(e.target)) parentMap.set(e.target, e.source);
  });

  // Root node is often an 'external' node, or anything with no parent.
  // If no edges exist, just use a grid fallback.
  if (edges.length === 0) return { nodes, edges };

  // Determine an absolute root (could be multiple, but we'll use a virtual root to hold them)
  const roots = nodes.filter((n) => !parentMap.has(n.id) && connectedNodes.has(n.id));

  // Create a flat data structure for d3.stratify
  const hierarchicalData = [];
  hierarchicalData.push({ id: 'virtual_root', parentId: null, data: null });

  // Assign all true roots to the virtual root to ensure a connected graph
  roots.forEach((r) => parentMap.set(r.id, 'virtual_root'));

  nodes.forEach((n) => {
    if (connectedNodes.has(n.id) || !parentMap.has(n.id)) {
      hierarchicalData.push({
        id: n.id,
        parentId: parentMap.has(n.id) ? parentMap.get(n.id) : 'virtual_root',
        data: n,
      });
    }
  });

  try {
    const root = stratify()
      .id((d) => d.id)
      .parentId((d) => d.parentId)(hierarchicalData);

    // Apply the tree layout algorithm
    // width determines horizontal scaling (e.g. 200px per node), height determines vertical (200px per level)
    const dx = 200;
    const dy = 200;

    const treeLayout = tree().nodeSize([dx, dy]);
    treeLayout(root);

    // Map the computed positions back to the React Flow nodes
    const positionMap = new Map();
    root.descendants().forEach((d) => {
      // Rotate Tree from left-to-right or top-to-bottom. We use top-to-bottom (x, y)
      positionMap.set(d.id, { x: d.x, y: d.y });
    });

    const layoutNodes = nodes.map((node) => {
      const pos = positionMap.get(node.id);
      return {
        ...node,
        position: pos || { x: 0, y: 0 },
      };
    });

    return { nodes: layoutNodes, edges };
  } catch (error) {
    console.error('Tree layout failed, reverting to nodes as-is:', error);
    return { nodes, edges };
  }
};

// --- Hierarchical Network Layout (networks at top, hardware middle, services bottom) ---
export const getHierarchicalNetworkLayout = (nodes, edges) => {
  const RANK_MAP = {
    network: 0,
    docker_network: 0,
    hardware: 1,
    compute: 1,
    cluster: 0,
    rack: 0,
    docker_container: 2,
    service: 2,
    storage: 3,
    external: 0,
    misc: 3,
  };
  const RANK_Y = [0, 280, 560, 840];
  const RANK_SPACING_X = 220;

  const rankGroups = {};
  nodes.forEach((node) => {
    const rank = RANK_MAP[node.type] ?? 2;
    if (!rankGroups[rank]) rankGroups[rank] = [];
    rankGroups[rank].push(node);
  });

  const layoutNodes = nodes.map((node) => {
    const rank = RANK_MAP[node.type] ?? 2;
    const group = rankGroups[rank];
    const idx = group.findIndex((n) => n.id === node.id);
    const total = group.length;
    const startX = -(total - 1) * RANK_SPACING_X * 0.5;
    return {
      ...node,
      position: { x: startX + idx * RANK_SPACING_X, y: RANK_Y[rank] ?? rank * 280 },
    };
  });

  return { nodes: layoutNodes, edges };
};

// --- Radial Service-Centric Layout ---
export const getRadialLayout = (nodes, edges) => {
  const simulationNodes = nodes.map((node) => ({
    ...node,
    x: node.position?.x || 0,
    y: node.position?.y || 0,
  }));
  const simulationEdges = edges.map((edge) => ({ ...edge }));

  // Services cluster towards centre; networks pushed outward
  const typeRadius = (type) => {
    if (type === 'service' || type === 'docker_container') return 150;
    if (type === 'hardware' || type === 'compute') return 320;
    if (type === 'network' || type === 'docker_network') return 520;
    return 420;
  };

  const sim = forceSimulation(simulationNodes)
    .force(
      'link',
      forceLink(simulationEdges)
        .id((d) => d.id)
        .distance(160)
        .strength(0.4)
    )
    .force('charge', forceManyBody().strength(-600))
    .force('center', forceCenter(0, 0))
    .force('collide', forceCollide(80))
    .force('radial', forceRadial((d) => typeRadius(d.type), 0, 0).strength(0.6))
    .stop();

  for (let i = 0; i < 300; ++i) sim.tick();

  const layoutNodes = nodes.map((node, idx) => {
    const sn = simulationNodes[idx];
    return { ...node, position: { x: sn.x, y: sn.y } };
  });

  return { nodes: layoutNodes, edges };
};

// --- ELK Layered Layout (VLAN Flow) ---
export const getElkLayeredLayout = async (nodes, edges) => {
  const ELK = (await import('elkjs/lib/elk.bundled.js')).default;
  const elk = new ELK();

  const elkGraph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '60',
      'elk.layered.spacing.nodeNodeBetweenLayers': '120',
    },
    children: nodes.map((n) => ({
      id: n.id,
      width: 160,
      height: 80,
    })),
    edges: edges
      .filter((e) => e.source && e.target)
      .map((e) => ({
        id: e.id || `e-${e.source}-${e.target}`,
        sources: [e.source],
        targets: [e.target],
      })),
  };

  try {
    const result = await elk.layout(elkGraph);
    const posMap = {};
    result.children.forEach((child) => {
      posMap[child.id] = { x: child.x, y: child.y };
    });
    const layoutNodes = nodes.map((n) => ({
      ...n,
      position: posMap[n.id] ?? n.position ?? { x: 0, y: 0 },
    }));
    return { nodes: layoutNodes, edges };
  } catch (err) {
    console.error('ELK layered layout failed:', err);
    return { nodes, edges };
  }
};

// --- Circular Cluster Layout (Docker networks as rings) ---
export const getCircularClusterLayout = (nodes, edges) => {
  const CLUSTER_TYPES = new Set(['network', 'docker_network']);
  const clusterNodes = nodes.filter((n) => CLUSTER_TYPES.has(n.type));

  const buildAdjacency = () => {
    const adj = {};
    edges.forEach((e) => {
      if (!adj[e.source]) adj[e.source] = [];
      if (!adj[e.target]) adj[e.target] = [];
      adj[e.source].push(e.target);
      adj[e.target].push(e.source);
    });
    return adj;
  };
  const adj = buildAdjacency();

  const totalClusters = Math.max(clusterNodes.length, 1);
  const CLUSTER_RADIUS = 380;
  const MEMBER_RADIUS = 140;
  const positions = {};

  clusterNodes.forEach((cNode, ci) => {
    const angle = (2 * Math.PI * ci) / totalClusters - Math.PI / 2;
    const cx = CLUSTER_RADIUS * Math.cos(angle);
    const cy = CLUSTER_RADIUS * Math.sin(angle);
    positions[cNode.id] = { x: cx, y: cy };

    const members = (adj[cNode.id] || []).filter(
      (id) => !CLUSTER_TYPES.has(nodes.find((n) => n.id === id)?.type ?? '')
    );
    members.forEach((memberId, mi) => {
      const mAngle = (2 * Math.PI * mi) / Math.max(members.length, 1);
      positions[memberId] = {
        x: cx + MEMBER_RADIUS * Math.cos(mAngle),
        y: cy + MEMBER_RADIUS * Math.sin(mAngle),
      };
    });
  });

  // Place any unpositioned nodes in a fallback grid
  let gridX = 0;
  const layoutNodes = nodes.map((n) => {
    if (positions[n.id]) return { ...n, position: positions[n.id] };
    const pos = { x: gridX * 200, y: 800 };
    gridX += 1;
    return { ...n, position: pos };
  });

  return { nodes: layoutNodes, edges };
};

// --- Grid Rack Layout (rack U-position aware) ---
export const getGridRackLayout = (nodes, edges) => {
  const RACK_SPACING_X = 240;
  const UNIT_HEIGHT = 60;
  const COL_WIDTH = 200;

  const racked = nodes.filter((n) => n.rack_id || n.data?.rack_id);
  const unracked = nodes.filter((n) => !n.rack_id && !n.data?.rack_id);

  // Group by rack_id
  const racks = {};
  racked.forEach((n) => {
    const rid = n.rack_id ?? n.data?.rack_id ?? 'default';
    if (!racks[rid]) racks[rid] = [];
    racks[rid].push(n);
  });

  const positions = {};
  Object.keys(racks).forEach((rid, ri) => {
    const rackX = ri * RACK_SPACING_X;
    racks[rid]
      .slice()
      .sort(
        (a, b) => (a.rack_unit ?? a.data?.rack_unit ?? 0) - (b.rack_unit ?? b.data?.rack_unit ?? 0)
      )
      .forEach((n, ui) => {
        positions[n.id] = { x: rackX, y: ui * UNIT_HEIGHT };
      });
  });

  // Place unracked nodes in a grid below the racks
  const rackCount = Math.max(Object.keys(racks).length, 1);
  const maxRackHeight = Math.max(...Object.values(racks).map((r) => r.length), 1) * UNIT_HEIGHT;
  unracked.forEach((n, idx) => {
    const col = idx % rackCount;
    const row = Math.floor(idx / rackCount);
    positions[n.id] = { x: col * COL_WIDTH, y: maxRackHeight + 120 + row * 120 };
  });

  const layoutNodes = nodes.map((n) => ({
    ...n,
    position: positions[n.id] ?? n.position ?? { x: 0, y: 0 },
  }));

  return { nodes: layoutNodes, edges };
};

// --- Concentric Rings Layout (external → hardware → services → storage) ---
export const getConcentricLayout = (nodes, edges) => {
  const RING_MAP = {
    external: 0,
    cluster: 1,
    rack: 1,
    hardware: 2,
    compute: 2,
    network: 2,
    docker_network: 2,
    service: 3,
    docker_container: 3,
    storage: 4,
    misc: 4,
  };
  const RING_RADII = [0, 180, 360, 540, 720];

  const rings = {};
  nodes.forEach((n) => {
    const ring = RING_MAP[n.type] ?? 3;
    if (!rings[ring]) rings[ring] = [];
    rings[ring].push(n);
  });

  const layoutNodes = nodes.map((n) => {
    const ring = RING_MAP[n.type] ?? 3;
    const group = rings[ring];
    const idx = group.findIndex((x) => x.id === n.id);
    const total = group.length;
    const radius = RING_RADII[ring] ?? ring * 200;

    if (ring === 0 && total === 1) {
      return { ...n, position: { x: 0, y: 0 } };
    }
    const angle = (2 * Math.PI * idx) / Math.max(total, 1) - Math.PI / 2;
    return {
      ...n,
      position: { x: radius * Math.cos(angle), y: radius * Math.sin(angle) },
    };
  });

  return { nodes: layoutNodes, edges };
};
