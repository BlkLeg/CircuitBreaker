/**
 * Pure geometry helpers for the topology map.
 * No React dependencies — safe to import from any module.
 */

/**
 * Determine the optimal side for an edge to exit/enter based on the relative
 * positions of the source and target nodes.
 */
export function computeSide(sourcePos, targetPos) {
  const dx = targetPos.x - sourcePos.x;
  const dy = targetPos.y - sourcePos.y;
  if (Math.abs(dx) > Math.abs(dy)) {
    return { sourceSide: dx > 0 ? 'right' : 'left', targetSide: dx > 0 ? 'left' : 'right' };
  }
  return { sourceSide: dy > 0 ? 'bottom' : 'top', targetSide: dy > 0 ? 'top' : 'bottom' };
}

/**
 * Apply sourceHandle / targetHandle to edges based on relative node positions.
 *
 * @param {Node[]} nodesArr - current nodes with positions
 * @param {Edge[]} edgesArr - current edges
 * @param {Object} overrides - edgeId → { source_side, target_side, control_point }
 * @param {string|null} onlyNodeId - if set, only recompute edges connected to this node
 */
export function applyEdgeSides(nodesArr, edgesArr, overrides = {}, onlyNodeId = null) {
  const posMap = Object.fromEntries(nodesArr.map((n) => [n.id, n.position]));
  return edgesArr.map((e) => {
    const isConnected = e.source === onlyNodeId || e.target === onlyNodeId;
    if (onlyNodeId && !isConnected) return e;

    const override = overrides[e.id];
    const src = posMap[e.source] ?? { x: 0, y: 0 };
    const tgt = posMap[e.target] ?? { x: 0, y: 0 };
    const auto = computeSide(src, tgt);
    const sourceSide = override?.source_side ?? auto.sourceSide;
    const targetSide = override?.target_side ?? auto.targetSide;

    return {
      ...e,
      sourceHandle: `s-${sourceSide}`,
      targetHandle: `t-${targetSide}`,
      sourceHandleId: `s-${sourceSide}`,
      targetHandleId: `t-${targetSide}`,
      data: {
        ...e.data,
        controlPoint: override?.control_point ?? e.data?.controlPoint ?? null,
      },
    };
  });
}

/**
 * Apply overrides/sides for a single edge. Use for targeted updates so only one edge object changes.
 *
 * @param {Node[]} nodesArr - current nodes with positions
 * @param {Edge} edge - the edge to update
 * @param {Object} overrides - edgeId → { source_side, target_side, control_point }
 * @returns {Edge} - updated edge with sourceHandle, targetHandle, data.controlPoint
 */
export function applyEdgeSidesForEdge(nodesArr, edge, overrides = {}) {
  const posMap = Object.fromEntries(nodesArr.map((n) => [n.id, n.position]));
  const override = overrides[edge.id];
  const src = posMap[edge.source] ?? { x: 0, y: 0 };
  const tgt = posMap[edge.target] ?? { x: 0, y: 0 };
  const auto = computeSide(src, tgt);
  const sourceSide = override?.source_side ?? auto.sourceSide;
  const targetSide = override?.target_side ?? auto.targetSide;

  return {
    ...edge,
    sourceHandle: `s-${sourceSide}`,
    targetHandle: `t-${targetSide}`,
    sourceHandleId: `s-${sourceSide}`,
    targetHandleId: `t-${targetSide}`,
    data: {
      ...edge.data,
      controlPoint: override?.control_point ?? edge.data?.controlPoint ?? null,
    },
  };
}

/**
 * Parse the stored layout JSON — handles both the new format
 *   { nodes: {...}, edges: {...} }
 * and the legacy format
 *   { "hw-1": {x,y}, ... }  (flat node position map).
 */
export function parseLayoutData(raw) {
  const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
  if (parsed && typeof parsed.nodes === 'object' && !Array.isArray(parsed.nodes)) {
    return {
      nodes: parsed.nodes || {},
      edges: parsed.edges || {},
      boundaries: parsed.boundaries || [],
      labels: parsed.labels || [],
      visualLines: Array.isArray(parsed.visualLines) ? parsed.visualLines : [],
      nodeShapes:
        parsed.nodeShapes && typeof parsed.nodeShapes === 'object' ? parsed.nodeShapes : {},
      edgeMode: parsed.edgeMode || 'smoothstep',
      edgeLabelVisible: parsed.edgeLabelVisible ?? true,
      nodeSpacing: parsed.nodeSpacing || 1,
      groupBy: parsed.groupBy || 'none',
    };
  }
  return {
    nodes: parsed || {},
    edges: {},
    boundaries: [],
    labels: [],
    visualLines: [],
    nodeShapes: {},
    edgeMode: 'smoothstep',
    edgeLabelVisible: true,
    nodeSpacing: 1,
    groupBy: 'none',
  };
}

export function boundaryFlowRect(startFlow, endFlow) {
  return {
    minX: Math.min(startFlow.x, endFlow.x),
    maxX: Math.max(startFlow.x, endFlow.x),
    minY: Math.min(startFlow.y, endFlow.y),
    maxY: Math.max(startFlow.y, endFlow.y),
  };
}

export function nodeCenterInFlow(node) {
  const width = Number(node?.width || 140);
  const height = Number(node?.height || 140);
  const basePos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
  const x = Number(basePos.x || 0) + width / 2;
  const y = Number(basePos.y || 0) + height / 2;
  return { x, y };
}

export function nodeBoundsInFlow(node) {
  const width = Number(node?.width || 140);
  const height = Number(node?.height || 140);
  const basePos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
  const x = Number(basePos.x || 0);
  const y = Number(basePos.y || 0);
  return {
    minX: x,
    maxX: x + width,
    minY: y,
    maxY: y + height,
  };
}

export function rectIntersectsRect(a, b) {
  return a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY;
}

export function cross(o, a, b) {
  return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

export function convexHull(points) {
  if (points.length <= 1) return points;
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);

  const lower = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), point) <= 0) lower.pop();
    lower.push(point);
  }

  const upper = [];
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    /* eslint-disable-next-line security/detect-object-injection -- index in own array */
    const point = sorted[i];
    while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), point) <= 0) upper.pop();
    upper.push(point);
  }

  lower.pop();
  upper.pop();
  return [...lower, ...upper];
}

export function expandPolygon(points, padding = 46) {
  if (!points.length) return points;
  const centroid = points.reduce((acc, point) => ({ x: acc.x + point.x, y: acc.y + point.y }), {
    x: 0,
    y: 0,
  });
  centroid.x /= points.length;
  centroid.y /= points.length;

  return points.map((point) => {
    const dx = point.x - centroid.x;
    const dy = point.y - centroid.y;
    const dist = Math.hypot(dx, dy) || 1;
    return {
      x: Math.round((point.x + (dx / dist) * padding) * 10) / 10,
      y: Math.round((point.y + (dy / dist) * padding) * 10) / 10,
    };
  });
}

export function computeBoundaryPolygon(boundary, nodesArr) {
  const memberIds = Array.isArray(boundary.memberIds)
    ? new Set(boundary.memberIds.map(String))
    : null;
  const members = memberIds ? nodesArr.filter((node) => memberIds.has(String(node.id))) : [];

  if (members.length < 1) {
    const rect = boundary?.flowRect;
    if (
      !rect ||
      !Number.isFinite(rect.minX) ||
      !Number.isFinite(rect.maxX) ||
      !Number.isFinite(rect.minY) ||
      !Number.isFinite(rect.maxY)
    ) {
      return [];
    }
    return [
      { x: rect.minX, y: rect.minY },
      { x: rect.maxX, y: rect.minY },
      { x: rect.maxX, y: rect.maxY },
      { x: rect.minX, y: rect.maxY },
    ];
  }

  const cloud = [];
  members.forEach((node) => {
    const width = Number(node?.width || 140);
    const height = Number(node?.height || 140);
    const basePos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
    const x = Number(basePos.x || 0);
    const y = Number(basePos.y || 0);
    cloud.push(
      { x: x - 18, y: y - 20 },
      { x: x + width + 18, y: y - 20 },
      { x: x - 18, y: y + height + 20 },
      { x: x + width + 18, y: y + height + 20 }
    );
  });

  const hull = convexHull(cloud);
  return expandPolygon(hull, 28);
}

export function flowToScreenPoint(point, viewportValue) {
  return {
    x: point.x * viewportValue.zoom + viewportValue.x,
    y: point.y * viewportValue.zoom + viewportValue.y,
  };
}

export function boundaryPath(points, viewportValue) {
  if (!points.length) return '';
  const screenPoints = points.map((point) => flowToScreenPoint(point, viewportValue));
  return (
    screenPoints
      .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
      .join(' ') + ' Z'
  );
}

export function boundaryRoundedRectPath(bbox, viewportValue, radius) {
  const tl = flowToScreenPoint({ x: bbox.minX, y: bbox.minY }, viewportValue);
  const br = flowToScreenPoint({ x: bbox.maxX, y: bbox.maxY }, viewportValue);
  const w = br.x - tl.x;
  const h = br.y - tl.y;
  const r = Math.min(radius * viewportValue.zoom, w / 2, h / 2);
  return `M ${tl.x + r} ${tl.y} L ${br.x - r} ${tl.y} Q ${br.x} ${tl.y} ${br.x} ${tl.y + r} L ${br.x} ${br.y - r} Q ${br.x} ${br.y} ${br.x - r} ${br.y} L ${tl.x + r} ${br.y} Q ${tl.x} ${br.y} ${tl.x} ${br.y - r} L ${tl.x} ${tl.y + r} Q ${tl.x} ${tl.y} ${tl.x + r} ${tl.y} Z`;
}

export function boundaryEllipsePath(bbox, viewportValue) {
  const tl = flowToScreenPoint({ x: bbox.minX, y: bbox.minY }, viewportValue);
  const br = flowToScreenPoint({ x: bbox.maxX, y: bbox.maxY }, viewportValue);
  const cx = (tl.x + br.x) / 2;
  const cy = (tl.y + br.y) / 2;
  const rx = (br.x - tl.x) / 2;
  const ry = (br.y - tl.y) / 2;
  return `M ${cx - rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx + rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx - rx} ${cy} Z`;
}

export function distanceBetweenPositions(a, b) {
  const dx = (a?.x ?? 0) - (b?.x ?? 0);
  const dy = (a?.y ?? 0) - (b?.y ?? 0);
  return Math.hypot(dx, dy);
}

function hasNodeCollision(candidate, nodesArr, movingNodeId, threshold = 150) {
  return nodesArr.some((node) => {
    if (!node || node.id === movingNodeId) return false;
    if (
      !node.position ||
      typeof node.position.x !== 'number' ||
      typeof node.position.y !== 'number'
    )
      return false;
    return distanceBetweenPositions(candidate, node.position) < threshold;
  });
}

export function resolveNonOverlappingPosition(candidate, nodesArr, movingNodeId) {
  if (!hasNodeCollision(candidate, nodesArr, movingNodeId)) return candidate;

  const radiusStep = 70;
  const angleStep = 20;
  const maxRings = 4;

  for (let ring = 1; ring <= maxRings; ring += 1) {
    const radius = radiusStep * ring;
    for (let angle = 0; angle < 360; angle += angleStep) {
      const rad = (Math.PI / 180) * angle;
      const testPos = {
        x: Math.round((candidate.x + radius * Math.cos(rad)) * 10) / 10,
        y: Math.round((candidate.y + radius * Math.sin(rad)) * 10) / 10,
      };
      if (!hasNodeCollision(testPos, nodesArr, movingNodeId)) return testPos;
    }
  }

  return candidate;
}
