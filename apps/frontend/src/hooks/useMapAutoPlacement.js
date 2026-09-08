import { useCallback } from 'react';
import { graphApi } from '../api/client';
import { resolveNonOverlappingPosition } from '../utils/mapGeometryUtils';
import { VIEWPORT_FIT_DEFAULTS } from '../utils/viewportFit';

/**
 * Auto-placement coordinator.
 *
 * New nodes arrive at (0,0) flagged `_needsAutoPlace`; the drain effect in
 * MapPage hands each one here and the server decides where it goes. What this
 * hook really owns is the bookkeeping around that call:
 *
 *   - an optimistic mark, so a `fetchData` landing mid-flight cannot re-tag the
 *     node and queue a second placement for it
 *   - a circuit breaker, so a failing backend does not leave the flag set and
 *     have the drain effect retry forever
 *   - batch accounting, so the layout is written and the toast raised once per
 *     completed batch rather than once per node
 *
 * @returns {{updateNodePos: Function, autoPlaceNew: Function}}
 */
export function useMapAutoPlacement({
  envFilter,
  setNodes,
  autoPlacedIdsRef,
  placingNodesRef,
  pendingPlacementCountRef,
  batchPlacedCountRef,
  saveLayoutRef,
  fitView,
  toast,
}) {
  const updateNodePos = useCallback(
    (id, pos) => {
      setNodes((nds) => {
        const safePos = resolveNonOverlappingPosition(pos, nds, id);
        return nds.map((n) =>
          n.id === id ? { ...n, position: safePos, _needsAutoPlace: false } : n
        );
      });
    },
    [setNodes]
  );

  const autoPlaceNew = useCallback(
    async (newNodeId) => {
      pendingPlacementCountRef.current += 1;
      // Optimistically mark as placed so fetchData re-runs during this API call
      // don't re-tag the node as _needsAutoPlace and queue a second placement.
      autoPlacedIdsRef.current.add(newNodeId);
      try {
        const res = await graphApi.placeNode(newNodeId, envFilter || 'default');
        placingNodesRef.current.delete(newNodeId);
        updateNodePos(newNodeId, { x: res.data.x, y: res.data.y });
        batchPlacedCountRef.current += 1;
      } catch (e) {
        // Placement failed: remove optimistic mark so the node can be retried.
        autoPlacedIdsRef.current.delete(newNodeId);
        placingNodesRef.current.delete(newNodeId);
        console.error('Auto-place failed', e);
        // Circuit breaker: clear flag with fallback position so the drain
        // effect doesn't re-trigger infinitely when backend is unreachable
        updateNodePos(newNodeId, { x: Math.random() * 800, y: Math.random() * 600 });
      } finally {
        pendingPlacementCountRef.current -= 1;
        if (pendingPlacementCountRef.current === 0 && batchPlacedCountRef.current > 0) {
          const count = batchPlacedCountRef.current;
          batchPlacedCountRef.current = 0;
          toast.success(count === 1 ? 'Node auto-placed' : `${count} nodes auto-placed`, {
            toastId: 'auto-place-batch',
            autoClose: 2000,
          });
          // Defer save until after React flushes setNodes so nodesRef.current
          // holds real positions (not zeros) when the layout is written to the DB.
          requestAnimationFrame(() => {
            saveLayoutRef
              .current?.()
              .catch((err) => console.error('Auto-save after placement failed', err));
          });
          // Fit view after all auto-placed nodes are positioned
          setTimeout(() => {
            fitView({ ...VIEWPORT_FIT_DEFAULTS, duration: 600 });
          }, 100);
        }
      }
    },
    [
      envFilter,
      updateNodePos,
      toast,
      pendingPlacementCountRef,
      autoPlacedIdsRef,
      placingNodesRef,
      batchPlacedCountRef,
      saveLayoutRef,
      fitView,
    ]
  );

  return { updateNodePos, autoPlaceNew };
}
