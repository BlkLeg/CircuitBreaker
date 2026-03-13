import { NODE_DEFAULT_HEIGHT_PX, NODE_DEFAULT_WIDTH_PX } from '../lib/constants';

const HANDLE_IDS = new Set([
  'top',
  'top-right',
  'right',
  'bottom-right',
  'bottom',
  'bottom-left',
  'left',
  'top-left',
]);
const CARDINAL_HANDLES = new Set(['top', 'right', 'bottom', 'left']);

function asFiniteNumber(value, fallback = 0) {
  return Number.isFinite(value) ? Number(value) : fallback;
}

function stripHandlePrefix(handleId) {
  if (!handleId || typeof handleId !== 'string') return null;
  if (handleId.startsWith('s-') || handleId.startsWith('t-')) return handleId.slice(2);
  return handleId;
}

function normalizeHandleId(handleId) {
  const stripped = stripHandlePrefix(handleId);
  return HANDLE_IDS.has(stripped) ? stripped : null;
}

function edgeHandle(edge, kind) {
  if (!edge) return null;
  if (kind === 'source') return edge.sourceHandle ?? edge.sourceHandleId ?? null;
  return edge.targetHandle ?? edge.targetHandleId ?? null;
}

function getNodeBasePosition(node) {
  const basePos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
  return {
    x: asFiniteNumber(basePos.x),
    y: asFiniteNumber(basePos.y),
  };
}

function distance(a, b) {
  return Math.hypot((a?.x ?? 0) - (b?.x ?? 0), (a?.y ?? 0) - (b?.y ?? 0));
}

export function getConnectedHandleIds(nodeId, edges) {
  const ids = new Set();
  if (!nodeId || !Array.isArray(edges)) return ids;
  edges.forEach((edge) => {
    if (!edge) return;
    if (edge.source === nodeId) {
      const sourceId = normalizeHandleId(edgeHandle(edge, 'source'));
      if (sourceId) ids.add(sourceId);
    }
    if (edge.target === nodeId) {
      const targetId = normalizeHandleId(edgeHandle(edge, 'target'));
      if (targetId) ids.add(targetId);
    }
  });
  return ids;
}

export function getNodeHandlePositions(node) {
  const { x, y } = getNodeBasePosition(node);
  const width = asFiniteNumber(node?.width, NODE_DEFAULT_WIDTH_PX);
  const height = asFiniteNumber(node?.height, NODE_DEFAULT_HEIGHT_PX);

  return [
    { id: 'top', x: x + width * 0.5, y },
    { id: 'top-right', x: x + width, y: y + height * 0.25 },
    { id: 'right', x: x + width, y: y + height * 0.5 },
    { id: 'bottom-right', x: x + width, y: y + height * 0.75 },
    { id: 'bottom', x: x + width * 0.5, y: y + height },
    { id: 'bottom-left', x, y: y + height * 0.75 },
    { id: 'left', x, y: y + height * 0.5 },
    { id: 'top-left', x, y: y + height * 0.25 },
  ];
}

function getAllowedHandles(allHandles, overrideSide) {
  const normalized = normalizeHandleId(overrideSide);
  if (!normalized) return allHandles;
  return allHandles.filter((handle) => handle.id === normalized);
}

function getHandlePositionById(handles, handleId) {
  if (!handleId) return null;
  return handles.find((handle) => handle.id === handleId) || null;
}

function movedNodeSet(movedNodeIds) {
  if (Array.isArray(movedNodeIds)) return new Set(movedNodeIds.filter(Boolean).map(String));
  if (movedNodeIds) return new Set([String(movedNodeIds)]);
  return new Set();
}

function edgeTouchesMovedNode(edge, movedIds) {
  if (!edge) return false;
  return movedIds.has(String(edge.source)) || movedIds.has(String(edge.target));
}

function findBestHandlePair(sourceHandles, targetHandles) {
  let best = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  let bestPenalty = Number.POSITIVE_INFINITY;
  sourceHandles.forEach((sourceHandle) => {
    targetHandles.forEach((targetHandle) => {
      const currentDistance = distance(sourceHandle, targetHandle);
      const currentPenalty =
        (CARDINAL_HANDLES.has(sourceHandle.id) ? 0 : 1) +
        (CARDINAL_HANDLES.has(targetHandle.id) ? 0 : 1);
      if (
        currentDistance < bestDistance ||
        (currentDistance === bestDistance && currentPenalty < bestPenalty)
      ) {
        bestDistance = currentDistance;
        bestPenalty = currentPenalty;
        best = { source: sourceHandle.id, target: targetHandle.id };
      }
    });
  });
  return best;
}

function preserveIdentityOrFallback(originalEdge, candidateEdge) {
  if (!candidateEdge || !originalEdge) return originalEdge;
  if (candidateEdge.id !== originalEdge.id) return originalEdge;
  if (candidateEdge.source !== originalEdge.source) return originalEdge;
  if (candidateEdge.target !== originalEdge.target) return originalEdge;
  return candidateEdge;
}

export function snapEdgesToNearestHandles(movedNodeIds, nodes, edges, overrides = {}) {
  const movedIds = movedNodeSet(movedNodeIds);
  if (!movedIds.size || !Array.isArray(nodes) || !Array.isArray(edges)) return edges;

  const nodeMap = new Map(nodes.map((node) => [String(node.id), node]));

  return edges.map((edge) => {
    if (!edgeTouchesMovedNode(edge, movedIds)) return edge;

    try {
      const sourceNode = nodeMap.get(String(edge.source));
      const targetNode = nodeMap.get(String(edge.target));
      if (!sourceNode || !targetNode) return edge;

      const sourceHandlePositions = getNodeHandlePositions(sourceNode);
      const targetHandlePositions = getNodeHandlePositions(targetNode);
      const edgeOverride = overrides?.[edge.id] || {};

      const sourceCandidates = getAllowedHandles(sourceHandlePositions, edgeOverride.source_side);
      const targetCandidates = getAllowedHandles(targetHandlePositions, edgeOverride.target_side);
      if (!sourceCandidates.length || !targetCandidates.length) return edge;

      const bestPair = findBestHandlePair(sourceCandidates, targetCandidates);
      if (!bestPair) return edge;

      const currentSourceHandle = normalizeHandleId(edgeHandle(edge, 'source'));
      const currentTargetHandle = normalizeHandleId(edgeHandle(edge, 'target'));
      const currentSourcePoint = getHandlePositionById(sourceHandlePositions, currentSourceHandle);
      const currentTargetPoint = getHandlePositionById(targetHandlePositions, currentTargetHandle);
      const bestSourcePoint = getHandlePositionById(sourceHandlePositions, bestPair.source);
      const bestTargetPoint = getHandlePositionById(targetHandlePositions, bestPair.target);

      const currentDistance =
        currentSourcePoint && currentTargetPoint
          ? distance(currentSourcePoint, currentTargetPoint)
          : Number.POSITIVE_INFINITY;
      const bestDistance =
        bestSourcePoint && bestTargetPoint
          ? distance(bestSourcePoint, bestTargetPoint)
          : Number.POSITIVE_INFINITY;

      const keepCurrentPair = currentDistance <= bestDistance;
      const nextSource =
        keepCurrentPair && currentSourceHandle ? currentSourceHandle : bestPair.source;
      const nextTarget =
        keepCurrentPair && currentTargetHandle ? currentTargetHandle : bestPair.target;
      const nextSourceHandle = `s-${nextSource}`;
      const nextTargetHandle = `t-${nextTarget}`;
      const currentSourceKey = edgeHandle(edge, 'source');
      const currentTargetKey = edgeHandle(edge, 'target');

      if (currentSourceKey === nextSourceHandle && currentTargetKey === nextTargetHandle)
        return edge;
      return preserveIdentityOrFallback(edge, {
        ...edge,
        sourceHandle: nextSourceHandle,
        targetHandle: nextTargetHandle,
        sourceHandleId: nextSourceHandle,
        targetHandleId: nextTargetHandle,
      });
    } catch (error) {
      console.warn('[map] snapEdgesToNearestHandles fallback', { edgeId: edge?.id, error });
      return edge;
    }
  });
}
