import { useCallback, useRef } from 'react';
import { snapEdgesToNearestHandles } from '../utils/mapHandleHelpers';
import { useEdgeIntegrityGuard } from './useEdgeIntegrityGuard';

const MOVEMENT_THRESHOLD_PX = 0.5;

function getNodePosition(node) {
  const pos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
  return {
    x: Number.isFinite(pos.x) ? pos.x : 0,
    y: Number.isFinite(pos.y) ? pos.y : 0,
  };
}

function withMovedNodePositions(nodes, movedNodes) {
  if (!Array.isArray(nodes) || !Array.isArray(movedNodes) || movedNodes.length === 0) return nodes;
  const movedMap = new Map(movedNodes.filter(Boolean).map((node) => [node.id, node]));
  return nodes.map((node) => {
    const moved = movedMap.get(node.id);
    if (!moved) return node;
    return { ...node, position: getNodePosition(moved), positionAbsolute: getNodePosition(moved) };
  });
}

export function useMapNodeDragSnap({ setEdges, dirtyRef, edgeOverridesRef, nodesRef }) {
  const dragStartPositionsRef = useRef(new Map());
  const { captureEdgeSnapshot, restoreIfCompromised, clearEdgeSnapshot } = useEdgeIntegrityGuard();

  const handleNodeDragStart = useCallback(
    (_event, node, draggedNodes) => {
      const trackedNodes =
        Array.isArray(draggedNodes) && draggedNodes.length > 0 ? draggedNodes : [node];
      const startPositions = new Map();
      trackedNodes.forEach((trackedNode) => {
        if (!trackedNode?.id) return;
        startPositions.set(trackedNode.id, getNodePosition(trackedNode));
      });
      dragStartPositionsRef.current = startPositions;
      setEdges((prevEdges) => {
        captureEdgeSnapshot(prevEdges);
        return prevEdges;
      });
    },
    [captureEdgeSnapshot, setEdges]
  );

  const handleNodeDragStop = useCallback(
    (_event, node, draggedNodes) => {
      const movedNodes =
        Array.isArray(draggedNodes) && draggedNodes.length > 0 ? draggedNodes : [node];
      const movedNodeIds = movedNodes.map((movedNode) => movedNode?.id).filter(Boolean);
      const hasActualMovement = movedNodes.some((movedNode) => {
        if (!movedNode?.id) return false;
        const startPos = dragStartPositionsRef.current.get(movedNode.id);
        if (!startPos) return true;
        const endPos = getNodePosition(movedNode);
        const dx = Math.abs(endPos.x - startPos.x);
        const dy = Math.abs(endPos.y - startPos.y);
        return dx > MOVEMENT_THRESHOLD_PX || dy > MOVEMENT_THRESHOLD_PX;
      });
      dragStartPositionsRef.current = new Map();
      if (!hasActualMovement || movedNodeIds.length === 0) {
        clearEdgeSnapshot();
        return;
      }

      const nodesWithMovedPositions = withMovedNodePositions(nodesRef.current || [], movedNodes);
      setEdges((prevEdges) => {
        const snappedEdges = snapEdgesToNearestHandles(
          movedNodeIds,
          nodesWithMovedPositions,
          prevEdges,
          edgeOverridesRef.current || {}
        );
        const guardedEdges = restoreIfCompromised(snappedEdges, prevEdges);
        clearEdgeSnapshot();
        return guardedEdges;
      });
      dirtyRef.current = true;
    },
    [clearEdgeSnapshot, dirtyRef, edgeOverridesRef, nodesRef, restoreIfCompromised, setEdges]
  );

  return { handleNodeDragStart, handleNodeDragStop };
}
