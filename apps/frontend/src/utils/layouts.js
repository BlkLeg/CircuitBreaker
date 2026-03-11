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

// --- Viewport normalizer (fit layout to container) ---

const NODE_HALF_WIDTH = 75;
const NODE_HALF_HEIGHT = 50;
const VIEWPORT_PADDING = 0.05;
/** Minimum center-to-center distance to prevent overlap after scaling. */
const NODE_MIN_CENTER_GAP = 110;

/**
 * Scale and translate node positions so the graph fits inside the viewport.
 * Never scales down so much that nodes would overlap (enforces minimum center gap).
 * @param {Array<{ position: { x: number, y: number }, [key: string]: any }>} nodes
 * @param {{ width: number, height: number }} viewport
 * @returns {Array} New nodes with updated positions
 */
export function scaleAndCenterToViewport(nodes, viewport) {
  if (!nodes.length || !viewport?.width || !viewport?.height) return nodes;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  nodes.forEach((node) => {
    const x = node.position?.x ?? 0;
    const y = node.position?.y ?? 0;
    minX = Math.min(minX, x - NODE_HALF_WIDTH);
    maxX = Math.max(maxX, x + NODE_HALF_WIDTH);
    minY = Math.min(minY, y - NODE_HALF_HEIGHT);
    maxY = Math.max(maxY, y + NODE_HALF_HEIGHT);
  });

  const bboxW = maxX - minX || 1;
  const bboxH = maxY - minY || 1;
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;

  const targetW = viewport.width * (1 - VIEWPORT_PADDING * 2);
  const targetH = viewport.height * (1 - VIEWPORT_PADDING * 2);
  const targetCenterX = viewport.width / 2;
  const targetCenterY = viewport.height / 2;

  let scaleX = targetW / bboxW;
  let scaleY = targetH / bboxH;
  if (nodes.length >= 2) {
    let minDist = Infinity;
    const positions = nodes.map((n) => ({ x: n.position?.x ?? 0, y: n.position?.y ?? 0 }));
    for (let i = 0; i < positions.length; i++) {
      for (let j = i + 1; j < positions.length; j++) {
        /* eslint-disable-next-line security/detect-object-injection -- index in own array */
        const dx = positions[j].x - positions[i].x;
        /* eslint-disable-next-line security/detect-object-injection -- index in own array */
        const dy = positions[j].y - positions[i].y;
        const d = Math.hypot(dx, dy) || 1;
        minDist = Math.min(minDist, d);
      }
    }
    const minScale = minDist < Infinity ? NODE_MIN_CENTER_GAP / minDist : 0;
    scaleX = Math.max(scaleX, minScale);
    scaleY = Math.max(scaleY, minScale);
  }
  const scale = Math.min(scaleX, scaleY, 1);

  return nodes.map((node) => {
    const x = node.position?.x ?? 0;
    const y = node.position?.y ?? 0;
    const translatedX = (x - centerX) * scale + targetCenterX;
    const translatedY = (y - centerY) * scale + targetCenterY;
    return {
      ...node,
      position: { x: translatedX, y: translatedY },
    };
  });
}

// --- Dagre Layout (Hierarchical) ---

/**
 * Build viewport-aware Dagre options from container width (optional).
 * spacingMultiplier scales rankSep/nodeSep for Density (0.5 = compact, 1.5/2 = roomy).
 * @param {number} [viewportWidth]
 * @param {{ width?: number, height?: number }} [viewport] - optional full viewport
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
export function getDagreViewportOptions(viewportWidth, viewport, spacingMultiplier = 1) {
  const w = viewport?.width ?? viewportWidth;
  if (w == null || w <= 0) return null;
  const h = viewport?.height;
  const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
  // Vertical spacing (rankSep) so ranks never overlap; horizontal (nodeSep) for same-rank spacing
  let rankSep = 160;
  if (h != null && h > 0) {
    rankSep = Math.min(220, Math.max(140, h / 6));
  } else if (w > 1200) {
    rankSep = 180;
  }
  const nodeSepBase = Math.max(50, w * 0.04);
  return {
    rankSep: rankSep * mult,
    nodeSep: nodeSepBase * mult,
    edgeSep: 16,
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

  const nodeWidth = 180;
  const nodeHeight = 120;
  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
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
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
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
    /* eslint-disable-next-line security/detect-object-injection -- index in own array */
    const simNode = simulationNodes[index];
    return {
      ...node,
      position: { x: simNode.x, y: simNode.y },
    };
  });

  return { nodes: layoutNodes, edges };
};

// --- Tree Layout (D3-Hierarchy) ---
/**
 * @param {Array} nodes
 * @param {Array} edges
 * @param {{ width?: number, height?: number }} [viewport] - optional; tightens dx/dy when small
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
export const getTreeLayout = (nodes, edges, viewport, spacingMultiplier = 1) => {
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

    const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
    const hasViewportWidth = viewport?.width != null;
    const hasViewportHeight = viewport?.height != null;
    // Tree: spread vertically (dy) more than horizontally (dx) so levels are clearly separated
    const baseDx = hasViewportWidth ? Math.min(280, Math.max(120, viewport.width / 6)) : 200;
    const baseDy = hasViewportHeight ? Math.min(320, Math.max(180, viewport.height / 5)) : 280;
    const dx = baseDx * mult;
    const dy = baseDy * mult;

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
/**
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
const RANK_MAP = new Map([
  ['network', 0],
  ['docker_network', 0],
  ['cluster', 0],
  ['rack', 0],
  ['external', 0],
  ['hardware', 1],
  ['compute', 1],
  ['docker_container', 2],
  ['service', 2],
  ['storage', 3],
  ['misc', 3],
]);

export const getHierarchicalNetworkLayout = (nodes, edges, spacingMultiplier = 1) => {
  const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
  // Clear vertical layering: networks top, hardware middle, services/storage below
  const RANK_Y = [0, 420, 840, 1260].map((y) => y * mult);
  const RANK_SPACING_X = 280 * mult;

  const rankGroups = new Map();
  nodes.forEach((node) => {
    const rank = RANK_MAP.get(node.type) ?? 2;
    if (!rankGroups.has(rank)) rankGroups.set(rank, []);
    rankGroups.get(rank).push(node);
  });

  const layoutNodes = nodes.map((node) => {
    const rank = RANK_MAP.get(node.type) ?? 2;
    const group = rankGroups.get(rank) ?? [];
    const idx = group.findIndex((n) => n.id === node.id);
    const total = group.length;
    const startX = -(total - 1) * RANK_SPACING_X * 0.5;
    const rankY = RANK_Y.at(rank) ?? rank * 280;
    return {
      ...node,
      position: { x: startX + idx * RANK_SPACING_X, y: rankY },
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
    /* eslint-disable-next-line security/detect-object-injection -- index in own array */
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
      'elk.spacing.nodeNode': '100',
      'elk.layered.spacing.nodeNodeBetweenLayers': '180',
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
    const posMap = new Map();
    result.children.forEach((child) => {
      posMap.set(child.id, { x: child.x, y: child.y });
    });
    const layoutNodes = nodes.map((n) => ({
      ...n,
      position: posMap.get(n.id) ?? n.position ?? { x: 0, y: 0 },
    }));
    return { nodes: layoutNodes, edges };
  } catch (err) {
    console.error('ELK layered layout failed:', err);
    return { nodes, edges };
  }
};

// --- Circular Cluster Layout (Docker networks as rings) ---
/**
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
export const getCircularClusterLayout = (nodes, edges, spacingMultiplier = 1) => {
  const CLUSTER_TYPES = new Set(['network', 'docker_network']);
  const clusterNodes = nodes.filter((n) => CLUSTER_TYPES.has(n.type));

  const buildAdjacency = () => {
    const adj = new Map();
    edges.forEach((e) => {
      if (!adj.has(e.source)) adj.set(e.source, []);
      if (!adj.has(e.target)) adj.set(e.target, []);
      adj.get(e.source).push(e.target);
      adj.get(e.target).push(e.source);
    });
    return adj;
  };
  const adj = buildAdjacency();

  const totalClusters = Math.max(clusterNodes.length, 1);
  const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
  const CLUSTER_RADIUS = 380 * mult;
  const MEMBER_RADIUS = 140 * mult;
  const positions = new Map();

  clusterNodes.forEach((cNode, ci) => {
    const angle = (2 * Math.PI * ci) / totalClusters - Math.PI / 2;
    const cx = CLUSTER_RADIUS * Math.cos(angle);
    const cy = CLUSTER_RADIUS * Math.sin(angle);
    positions.set(cNode.id, { x: cx, y: cy });

    const members = (adj.get(cNode.id) || []).filter(
      (id) => !CLUSTER_TYPES.has(nodes.find((n) => n.id === id)?.type ?? '')
    );
    members.forEach((memberId, mi) => {
      const mAngle = (2 * Math.PI * mi) / Math.max(members.length, 1);
      positions.set(memberId, {
        x: cx + MEMBER_RADIUS * Math.cos(mAngle),
        y: cy + MEMBER_RADIUS * Math.sin(mAngle),
      });
    });
  });

  // Place any unpositioned nodes in a fallback grid
  let gridX = 0;
  const layoutNodes = nodes.map((n) => {
    const pos = positions.get(n.id);
    if (pos) return { ...n, position: pos };
    const fallbackPos = { x: gridX * 200, y: 800 };
    gridX += 1;
    return { ...n, position: fallbackPos };
  });

  return { nodes: layoutNodes, edges };
};

// --- Grid Rack Layout (rack U-position aware) ---
/**
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
export const getGridRackLayout = (nodes, edges, spacingMultiplier = 1) => {
  const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
  const RACK_SPACING_X = 320 * mult;
  const UNIT_HEIGHT = 72 * mult;
  const COL_WIDTH = 260 * mult;

  const racked = nodes.filter((n) => n.rack_id || n.data?.rack_id);
  const unracked = nodes.filter((n) => !n.rack_id && !n.data?.rack_id);

  // Group by rack_id
  const racks = new Map();
  racked.forEach((n) => {
    const rid = n.rack_id ?? n.data?.rack_id ?? 'default';
    if (!racks.has(rid)) racks.set(rid, []);
    racks.get(rid).push(n);
  });

  const positions = new Map();
  let ri = 0;
  for (const [, rackNodes] of racks) {
    const rackX = ri * RACK_SPACING_X;
    rackNodes
      .slice()
      .sort(
        (a, b) => (a.rack_unit ?? a.data?.rack_unit ?? 0) - (b.rack_unit ?? b.data?.rack_unit ?? 0)
      )
      .forEach((n, ui) => {
        positions.set(n.id, { x: rackX, y: ui * UNIT_HEIGHT });
      });
    ri += 1;
  }

  // Place unracked nodes in a grid below the racks
  const rackCount = Math.max(racks.size, 1);
  const maxRackHeight = Math.max(...[...racks.values()].map((r) => r.length), 1) * UNIT_HEIGHT;
  const unrackedRowGap = 140 * mult;
  unracked.forEach((n, idx) => {
    const col = idx % rackCount;
    const row = Math.floor(idx / rackCount);
    positions.set(n.id, {
      x: col * COL_WIDTH,
      y: maxRackHeight + unrackedRowGap + row * unrackedRowGap,
    });
  });

  const layoutNodes = nodes.map((n) => ({
    ...n,
    position: positions.get(n.id) ?? n.position ?? { x: 0, y: 0 },
  }));

  return { nodes: layoutNodes, edges };
};

// --- Concentric Rings Layout (external → hardware → services → storage) ---
const CONCENTRIC_RING_MAP = new Map([
  ['external', 0],
  ['cluster', 1],
  ['rack', 1],
  ['hardware', 2],
  ['compute', 2],
  ['network', 2],
  ['docker_network', 2],
  ['service', 3],
  ['docker_container', 3],
  ['storage', 4],
  ['misc', 4],
]);
const RING_RADII = [0, 180, 360, 540, 720];

export const getConcentricLayout = (nodes, edges) => {
  const rings = new Map();
  nodes.forEach((n) => {
    const ring = CONCENTRIC_RING_MAP.get(n.type) ?? 3;
    if (!rings.has(ring)) rings.set(ring, []);
    rings.get(ring).push(n);
  });

  const layoutNodes = nodes.map((n) => {
    const ring = CONCENTRIC_RING_MAP.get(n.type) ?? 3;
    const group = rings.get(ring) ?? [];
    const idx = group.findIndex((x) => x.id === n.id);
    const total = group.length;
    const radius = RING_RADII.at(ring) ?? ring * 200;

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

// --- Cortex Layout (compact hierarchical rings) ---
/**
 * Dense hierarchical layout: nodes stratified by depth, each level on a ring.
 * Viewport-centered; suitable for large graphs.
 * @param {Array} nodes
 * @param {Array} edges
 * @param {{ width?: number, height?: number }} [viewport] - optional; defaults to 800x600
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
export function getCortexLayout(nodes, edges, viewport, spacingMultiplier = 1) {
  if (!nodes.length) return { nodes, edges };

  const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
  const vp = viewport ?? {};
  const width = vp.width ?? 800;
  const height = vp.height ?? 600;
  const centerX = width / 2;
  const centerY = height / 2;
  const ringSpacing = Math.min(width, height) * 0.14 * mult;

  const childrenMap = new Map();
  const inDegree = new Map();
  nodes.forEach((n) => {
    inDegree.set(n.id, 0);
    childrenMap.set(n.id, []);
  });
  edges.forEach((e) => {
    if (e.source && e.target && e.source !== e.target) {
      childrenMap.get(e.source).push(e.target);
      inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
    }
  });

  const roots = nodes.filter((n) => inDegree.get(n.id) === 0);
  if (roots.length === 0) {
    roots.push(nodes[0]);
  }

  const depthMap = new Map();
  const queue = roots.map((r) => ({ id: r.id, depth: 0 }));
  while (queue.length > 0) {
    const { id, depth } = queue.shift();
    if (depthMap.has(id)) continue;
    depthMap.set(id, depth);
    const children = childrenMap.get(id) ?? [];
    children.forEach((cid) => queue.push({ id: cid, depth: depth + 1 }));
  }

  nodes.forEach((n) => {
    if (!depthMap.has(n.id)) depthMap.set(n.id, 0);
  });

  const levels = [];
  depthMap.forEach((depth, id) => {
    while (levels.length <= depth) levels.push([]);
    /* eslint-disable-next-line security/detect-object-injection -- index in own array */
    levels[depth].push(id);
  });

  const positionMap = new Map();
  levels.forEach((levelIds, depth) => {
    const radius = ringSpacing * (depth + 1);
    const count = levelIds.length;
    const angleStep = count > 0 ? (2 * Math.PI) / count : 0;
    levelIds.forEach((id, i) => {
      const angle = angleStep * i - Math.PI / 2;
      positionMap.set(id, {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      });
    });
  });

  const layoutNodes = nodes.map((n) => ({
    ...n,
    position: positionMap.get(n.id) ?? { x: centerX, y: centerY },
  }));

  return { nodes: layoutNodes, edges };
}

// --- Mindmap Layout (root-centered, left/right branches) ---
/**
 * Root at center; children split into left and right branches with decreasing spread.
 * @param {Array} nodes
 * @param {Array} edges
 * @param {{ width?: number, height?: number }} [viewport] - optional; defaults to 800x600
 * @param {number} [spacingMultiplier] - default 1 (Density control)
 */
export function getMindmapLayout(nodes, edges, viewport, spacingMultiplier = 1) {
  if (!nodes.length) return { nodes, edges };

  const mult = Math.max(0.5, Number(spacingMultiplier) || 1);
  const vp = viewport ?? {};
  const width = vp.width ?? 800;
  const height = vp.height ?? 600;
  const centerX = width / 2;
  const centerY = height / 2;

  const childrenMap = new Map();
  const inDegree = new Map();
  nodes.forEach((n) => {
    inDegree.set(n.id, 0);
    childrenMap.set(n.id, []);
  });
  edges.forEach((e) => {
    if (e.source && e.target && e.source !== e.target) {
      childrenMap.get(e.source).push(e.target);
      inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
    }
  });

  const roots = nodes.filter((n) => inDegree.get(n.id) === 0);
  const rootId = roots.length > 0 ? roots[0].id : nodes[0].id;

  const positionMap = new Map();
  positionMap.set(rootId, { x: centerX, y: centerY });

  const BRANCH_DX = 200 * mult;
  const BRANCH_DY = 90 * mult;

  function placeBranch(parentId, depth, direction) {
    const children = childrenMap.get(parentId) ?? [];
    if (children.length === 0) return;
    const parentPos = positionMap.get(parentId) ?? { x: centerX, y: centerY };
    const stepY = BRANCH_DY / (depth + 1);
    const stepX = (BRANCH_DX / (depth + 1)) * direction;
    children.forEach((childId, i) => {
      const total = children.length;
      const offsetY = total === 1 ? 0 : (i - (total - 1) / 2) * stepY;
      const x = parentPos.x + stepX;
      const y = parentPos.y + offsetY;
      positionMap.set(childId, { x, y });
      placeBranch(childId, depth + 1, direction);
    });
  }

  const rootChildren = childrenMap.get(rootId) ?? [];
  const half = Math.ceil(rootChildren.length / 2);
  const leftIds = rootChildren.slice(0, half);
  const rightIds = rootChildren.slice(half);

  leftIds.forEach((id, i) => {
    const stepY = leftIds.length === 1 ? 0 : BRANCH_DY * (i - (leftIds.length - 1) / 2);
    positionMap.set(id, { x: centerX - BRANCH_DX, y: centerY + stepY });
    placeBranch(id, 1, -1);
  });
  rightIds.forEach((id, i) => {
    const stepY = rightIds.length === 1 ? 0 : BRANCH_DY * (i - (rightIds.length - 1) / 2);
    positionMap.set(id, { x: centerX + BRANCH_DX, y: centerY + stepY });
    placeBranch(id, 1, 1);
  });

  const layoutNodes = nodes.map((n) => ({
    ...n,
    position: positionMap.get(n.id) ?? { x: centerX, y: centerY },
  }));

  return { nodes: layoutNodes, edges };
}
