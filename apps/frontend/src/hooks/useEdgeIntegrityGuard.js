import { useCallback, useRef } from 'react';

function getEdgeIdSet(edges) {
  const ids = new Set();
  if (!Array.isArray(edges)) return ids;
  edges.forEach((edge) => {
    if (edge?.id != null) ids.add(String(edge.id));
  });
  return ids;
}

export function useEdgeIntegrityGuard() {
  const edgeSnapshotRef = useRef([]);

  const captureEdgeSnapshot = useCallback((edges) => {
    edgeSnapshotRef.current = Array.isArray(edges) ? edges : [];
  }, []);

  const restoreIfCompromised = useCallback((nextEdges, currentEdges) => {
    const snapshot = Array.isArray(edgeSnapshotRef.current) ? edgeSnapshotRef.current : [];
    const candidate = Array.isArray(nextEdges) ? nextEdges : currentEdges;
    if (!Array.isArray(candidate) || snapshot.length === 0) return candidate;

    const beforeIds = getEdgeIdSet(snapshot);
    const afterIds = getEdgeIdSet(candidate);
    const lostIds = [];
    beforeIds.forEach((id) => {
      if (!afterIds.has(id)) lostIds.push(id);
    });

    if (candidate.length < snapshot.length || lostIds.length > 0) {
      console.warn('[map] edge integrity restore triggered', {
        beforeCount: snapshot.length,
        afterCount: candidate.length,
        lostIds,
      });
      return snapshot;
    }

    return candidate;
  }, []);

  const clearEdgeSnapshot = useCallback(() => {
    edgeSnapshotRef.current = [];
  }, []);

  return {
    captureEdgeSnapshot,
    restoreIfCompromised,
    clearEdgeSnapshot,
  };
}
