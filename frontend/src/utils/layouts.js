import { Position } from 'reactflow';
import dagre from '@dagrejs/dagre';
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import { stratify, tree } from 'd3-hierarchy';

// --- Dagre Layout (Hierarchical) ---
export const getDagreLayout = (nodes, edges, direction = 'TB') => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  const isHorizontal = direction === 'LR';
  dagreGraph.setGraph({ rankdir: direction });

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
  const simulationNodes = nodes.map((node) => ({ ...node, x: node.position.x || 0, y: node.position.y || 0 }));
  const simulationEdges = edges.map((edge) => ({ ...edge, source: edge.source, target: edge.target }));

  const simulation = forceSimulation(simulationNodes)
    .force('link', forceLink(simulationEdges).id((d) => d.id).distance(200))
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
  edges.forEach(e => {
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
  const roots = nodes.filter(n => !parentMap.has(n.id) && connectedNodes.has(n.id));
  
  // Create a flat data structure for d3.stratify
  const hierarchicalData = [];
  hierarchicalData.push({ id: 'virtual_root', parentId: null, data: null });
  
  // Assign all true roots to the virtual root to ensure a connected graph
  roots.forEach(r => parentMap.set(r.id, 'virtual_root'));

  nodes.forEach(n => {
    if (connectedNodes.has(n.id) || !parentMap.has(n.id)) {
      hierarchicalData.push({
        id: n.id,
        parentId: parentMap.has(n.id) ? parentMap.get(n.id) : 'virtual_root',
        data: n
      });
    }
  });

  try {
    const root = stratify()
      .id(d => d.id)
      .parentId(d => d.parentId)(hierarchicalData);

    // Apply the tree layout algorithm
    // width determines horizontal scaling (e.g. 200px per node), height determines vertical (200px per level)
    const dx = 200;
    const dy = 200;

    const treeLayout = tree().nodeSize([dx, dy]);
    treeLayout(root);

    // Map the computed positions back to the React Flow nodes
    const positionMap = new Map();
    root.descendants().forEach(d => {
      // Rotate Tree from left-to-right or top-to-bottom. We use top-to-bottom (x, y)
      positionMap.set(d.id, { x: d.x, y: d.y }); 
    });

    const layoutNodes = nodes.map(node => {
      const pos = positionMap.get(node.id);
      return {
        ...node,
        position: pos || { x: 0, y: 0 } 
      };
    });

    return { nodes: layoutNodes, edges };
  } catch (error) {
    console.error('Tree layout failed, reverting to nodes as-is:', error);
    return { nodes, edges };
  }
};
