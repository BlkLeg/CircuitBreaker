import { useCallback } from 'react';
import { graphApi } from '../api/client';
import {
  ENTITY_API_DELETE,
  normalizeBoundaryName,
  normalizeMapLabel,
  DEFAULT_BOUNDARY_COLOR,
  DEFAULT_BOUNDARY_FILL_OPACITY,
} from '../components/map/mapConstants';
import { unlinkByEdge } from '../components/map/linkMutations';

/**
 * Encapsulates layout-save and node-delete mutation logic extracted from
 * MapInternal.  Accepts a config object with the state / refs it needs and
 * returns stable callbacks.
 *
 * @returns {{ saveLayoutSnapshot, saveLayout, handleDeleteNodeAction, forceRemoveDeleteConflicts }}
 */
export function useMapMutations({
  mapId,
  // refs
  nodesRef,
  edgeOverridesRef,
  mapLabelsRef,
  visualLinesRef,
  dirtyRef,
  // state values (needed by saveLayoutSnapshot)
  boundaries,
  edgeMode,
  edgeLabelVisible,
  nodeSpacing,
  groupBy,
  // state setters
  setLastSaved,
  setError,
  setConfirmState,
  setDeleteConflictModal,
  setSelectedNode,
  // reactive state values (needed by delete handlers)
  edges,
  deleteConflictModal,
  selectedNodeId,
  // callbacks
  getLayoutName,
  fetchData,
  toast,
}) {
  const saveLayoutSnapshot = useCallback(
    async ({ labelsOverride } = {}) => {
      const nodePositions = {};
      const nodeShapes = {};
      nodesRef.current.forEach((n) => {
        nodePositions[n.id] = n.position;
        if (n.data?.nodeShape) nodeShapes[n.id] = n.data.nodeShape;
      });
      const payload = {
        nodes: nodePositions,
        nodeShapes,
        edges: edgeOverridesRef.current,
        boundaries: boundaries
          .filter((b) => !b.id?.startsWith('boundary-docker-auto-'))
          .map((boundary, index) => ({
            id: boundary.id,
            name: normalizeBoundaryName(boundary.name, index),
            memberIds: boundary.memberIds,
            flowRect: boundary.flowRect,
            color: boundary.color || DEFAULT_BOUNDARY_COLOR,
            fillOpacity: boundary.fillOpacity ?? DEFAULT_BOUNDARY_FILL_OPACITY,
            shape: boundary.shape || 'rectangle',
            behindNodes: boundary.behindNodes ?? false,
          })),
        labels: (labelsOverride ?? mapLabelsRef.current).map((label, index) =>
          normalizeMapLabel(label, index)
        ),
        visualLines: visualLinesRef.current.map((vl) => ({
          id: vl.id,
          startFlow: vl.startFlow,
          endFlow: vl.endFlow,
          lineType: vl.lineType,
        })),
        edgeMode,
        edgeLabelVisible,
        nodeSpacing,
        groupBy,
      };
      await graphApi.saveLayout(getLayoutName(), JSON.stringify(payload), mapId);
      setLastSaved(new Date().toISOString());
      dirtyRef.current = false;
    },
    [
      boundaries,
      getLayoutName,
      mapId,
      edgeMode,
      edgeLabelVisible,
      nodeSpacing,
      groupBy,
      nodesRef,
      edgeOverridesRef,
      mapLabelsRef,
      visualLinesRef,
      dirtyRef,
      setLastSaved,
    ]
  );

  const saveLayout = useCallback(async () => {
    try {
      await saveLayoutSnapshot();
    } catch (err) {
      setError('Failed to save layout: ' + err.message);
    }
  }, [saveLayoutSnapshot, setError]);

  const handleDeleteNodeAction = useCallback(
    (nodeId) => {
      const targetNode = nodesRef.current.find((n) => n.id === nodeId);
      if (!targetNode) {
        toast.error('Could not resolve node for deletion.');
        return;
      }

      const deleter = ENTITY_API_DELETE[targetNode.originalType];
      if (!deleter || !targetNode._refId) {
        toast.error('Delete is not supported for this node type.');
        return;
      }

      const label = targetNode.data?.label || targetNode.id;
      setConfirmState({
        open: true,
        message: `Delete node "${label}"? This uses the same delete behavior as the entity page.`,
        onConfirm: async () => {
          setConfirmState((s) => ({ ...s, open: false }));
          try {
            await deleter(targetNode._refId);
            if (selectedNodeId === targetNode.id) setSelectedNode(null);
            toast.success('Node deleted.');
            fetchData();
          } catch (err) {
            const reason = err?.message || 'Failed to delete node.';
            // Build blockers from current edges
            const connected = edges.filter(
              (edge) => edge.source === targetNode.id || edge.target === targetNode.id
            );
            const blockers = connected.map((edge) => {
              const otherNodeId = edge.source === targetNode.id ? edge.target : edge.source;
              const otherNode = nodesRef.current.find((n) => n.id === otherNodeId);
              return {
                edgeId: edge.id,
                relation: edge._relation || edge.data?.relation || edge.label || 'linked',
                otherLabel: otherNode?.data?.label || otherNodeId,
              };
            });
            setDeleteConflictModal({
              open: true,
              nodeId: targetNode.id,
              nodeRefId: targetNode._refId,
              nodeType: targetNode.originalType,
              nodeLabel: label,
              blockers,
              reason,
              forcing: false,
            });
          }
        },
      });
    },
    [
      nodesRef,
      edges,
      fetchData,
      selectedNodeId,
      setSelectedNode,
      setConfirmState,
      setDeleteConflictModal,
      toast,
    ]
  );

  const forceRemoveDeleteConflicts = useCallback(async () => {
    if (
      !deleteConflictModal.nodeId ||
      !deleteConflictModal.nodeRefId ||
      !deleteConflictModal.nodeType
    )
      return;
    const deleter = ENTITY_API_DELETE[deleteConflictModal.nodeType];
    if (!deleter) {
      toast.error('Delete is not supported for this node type.');
      return;
    }

    setDeleteConflictModal((m) => ({ ...m, forcing: true }));
    try {
      const connectedEdges = edges.filter(
        (edge) =>
          edge.source === deleteConflictModal.nodeId || edge.target === deleteConflictModal.nodeId
      );

      let edgeFailCount = 0;
      for (const edge of connectedEdges) {
        try {
          await unlinkByEdge({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            _relation: edge._relation,
            data: edge.data,
            label: edge.label,
          });
        } catch (err) {
          edgeFailCount++;
          console.error('Failed to remove edge:', edge.id, err);
        }
      }
      if (edgeFailCount > 0) {
        toast.warn(`${edgeFailCount} connection(s) could not be removed.`);
      }

      await deleter(deleteConflictModal.nodeRefId);
      if (selectedNodeId === deleteConflictModal.nodeId) setSelectedNode(null);
      setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }));
      toast.success('Node deleted after removing conflicts.');
      fetchData();
    } catch (err) {
      setDeleteConflictModal((m) => ({ ...m, forcing: false }));
      toast.error(err?.message || 'Force remove failed.');
    }
  }, [
    deleteConflictModal,
    edges,
    fetchData,
    selectedNodeId,
    setSelectedNode,
    setDeleteConflictModal,
    toast,
  ]);

  return { saveLayoutSnapshot, saveLayout, handleDeleteNodeAction, forceRemoveDeleteConflicts };
}
