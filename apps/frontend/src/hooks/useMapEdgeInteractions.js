/* eslint-disable security/detect-object-injection -- edge override map keyed by edge IDs */
import { useCallback } from 'react';

export function useMapEdgeInteractions({
  setEdges,
  setEdgeMenu,
  setEdgeOverrides,
  edgeOverridesRef,
  nodesRef,
  dirtyRef,
  screenToFlowPosition,
  normalizeConnectionType,
  omitKey,
  applyEdgeSidesForEdge,
  nodeCenterInFlow,
  graphApi,
  isUpdatableEdgeId,
  clampPickerPosition,
  lastPointerRef,
  setPendingConnection,
  pendingConnection,
  createLinkByNodeIds,
  inferEdgeNodeIdsFromMeta,
  getTopologyParams,
  getNewestEdgeId,
  unlinkByEdge,
  fetchData,
  toast,
}) {
  const handleEdgeContextMenu = useCallback(
    (event, edge) => {
      event.preventDefault();
      setEdgeMenu({
        edgeId: edge.id,
        x: event.clientX,
        y: event.clientY,
        connectionType: edge.data?.connection_type || 'ethernet',
        isUpdatable: isUpdatableEdgeId(edge.id),
      });
    },
    [isUpdatableEdgeId, setEdgeMenu]
  );

  const persistEdgeType = useCallback(
    async (edgeId, connectionType) => {
      if (!edgeId) return false;
      try {
        await graphApi.updateEdgeType(edgeId, connectionType);
        return true;
      } catch (err) {
        console.warn('Could not persist edge type:', err?.message);
        return false;
      }
    },
    [graphApi]
  );

  const handleEdgeConnectionTypeChange = useCallback(
    async (edgeId, newType) => {
      const normalized = normalizeConnectionType(newType) || 'ethernet';
      setEdges((prev) =>
        prev.map((edge) =>
          edge.id === edgeId
            ? { ...edge, data: { ...edge.data, connection_type: normalized } }
            : edge
        )
      );
      setEdgeMenu((prev) => (prev ? { ...prev, connectionType: normalized } : prev));
      await persistEdgeType(edgeId, normalized);
    },
    [normalizeConnectionType, persistEdgeType, setEdgeMenu, setEdges]
  );

  const handleControlPointChange = useCallback(
    (edgeId, clientPos) => {
      const flowPos = screenToFlowPosition({ x: clientPos.x, y: clientPos.y });
      const updated = {
        ...edgeOverridesRef.current,
        [edgeId]: { ...edgeOverridesRef.current[edgeId], control_point: flowPos },
      };
      edgeOverridesRef.current = updated;
      setEdgeOverrides(updated);
      setEdges((prev) =>
        prev.map((edge) =>
          edge.id === edgeId ? { ...edge, data: { ...edge.data, controlPoint: flowPos } } : edge
        )
      );
      dirtyRef.current = true;
    },
    [dirtyRef, edgeOverridesRef, screenToFlowPosition, setEdgeOverrides, setEdges]
  );

  const handleEdgeAnchorChange = useCallback(
    (edgeId, which, side) => {
      const key = which === 'source' ? 'source_side' : 'target_side';
      let updated;
      if (side === 'auto') {
        const existing = { ...edgeOverridesRef.current[edgeId] };
        delete existing[key];
        if (Object.keys(existing).length === 0) {
          updated = omitKey(edgeOverridesRef.current, edgeId);
        } else {
          updated = { ...edgeOverridesRef.current, [edgeId]: existing };
        }
      } else {
        updated = {
          ...edgeOverridesRef.current,
          [edgeId]: { ...edgeOverridesRef.current[edgeId], [key]: side },
        };
      }
      edgeOverridesRef.current = updated;
      setEdgeOverrides(updated);
      setEdges((prev) =>
        prev.map((edge) =>
          edge.id === edgeId ? applyEdgeSidesForEdge(nodesRef.current, edge, updated) : edge
        )
      );
      dirtyRef.current = true;
    },
    [
      applyEdgeSidesForEdge,
      dirtyRef,
      edgeOverridesRef,
      nodesRef,
      omitKey,
      setEdgeOverrides,
      setEdges,
    ]
  );

  const sideFromClientForNode = useCallback(
    (nodeId, clientPos) => {
      const node = nodesRef.current.find((candidate) => candidate.id === nodeId);
      if (!node || !clientPos) return null;
      const flowPos = screenToFlowPosition({ x: clientPos.x, y: clientPos.y });
      const center = nodeCenterInFlow(node);
      const dx = flowPos.x - center.x;
      const dy = flowPos.y - center.y;
      if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? 'right' : 'left';
      return dy > 0 ? 'bottom' : 'top';
    },
    [nodeCenterInFlow, nodesRef, screenToFlowPosition]
  );

  const handleEdgeEndpointDrop = useCallback(
    (edgeId, which, nodeId, clientPos) => {
      const side = sideFromClientForNode(nodeId, clientPos);
      if (!side) return;
      const key = which === 'source' ? 'source_side' : 'target_side';
      const updated = {
        ...edgeOverridesRef.current,
        [edgeId]: { ...edgeOverridesRef.current[edgeId], [key]: side },
      };
      edgeOverridesRef.current = updated;
      setEdgeOverrides(updated);
      setEdges((prev) =>
        prev.map((edge) =>
          edge.id === edgeId ? applyEdgeSidesForEdge(nodesRef.current, edge, updated) : edge
        )
      );
      dirtyRef.current = true;
    },
    [
      applyEdgeSidesForEdge,
      dirtyRef,
      edgeOverridesRef,
      nodesRef,
      setEdgeOverrides,
      setEdges,
      sideFromClientForNode,
    ]
  );

  const handleClearBend = useCallback(
    (edgeId) => {
      const existing = { ...edgeOverridesRef.current[edgeId] };
      delete existing.control_point;
      const updated =
        Object.keys(existing).length === 0
          ? omitKey(edgeOverridesRef.current, edgeId)
          : { ...edgeOverridesRef.current, [edgeId]: existing };
      edgeOverridesRef.current = updated;
      setEdgeOverrides(updated);
      setEdges((prev) =>
        prev.map((edge) =>
          edge.id === edgeId ? applyEdgeSidesForEdge(nodesRef.current, edge, updated) : edge
        )
      );
      dirtyRef.current = true;
      setEdgeMenu(null);
    },
    [
      applyEdgeSidesForEdge,
      dirtyRef,
      edgeOverridesRef,
      nodesRef,
      omitKey,
      setEdgeMenu,
      setEdgeOverrides,
      setEdges,
    ]
  );

  const openConnectionPicker = useCallback(
    (mode, connection, oldEdge = null) => {
      const pos = clampPickerPosition(lastPointerRef.current.x, lastPointerRef.current.y);
      const defaultType =
        oldEdge?.data?.connection_type || oldEdge?.data?.connectionType || 'ethernet';
      setPendingConnection({
        mode,
        oldEdge,
        connection,
        defaultConnectionType: defaultType,
        x: pos.x,
        y: pos.y,
      });
    },
    [clampPickerPosition, lastPointerRef, setPendingConnection]
  );

  const findCreatedEdgeId = useCallback(
    async (linkMeta, fallbackConnection) => {
      const topoRes = await graphApi.topology(getTopologyParams());
      const edgeList = topoRes?.data?.edges || [];
      const nodeIds = inferEdgeNodeIdsFromMeta(
        linkMeta,
        fallbackConnection.source,
        fallbackConnection.target
      );
      return getNewestEdgeId(edgeList, (edge) => {
        const relation = edge?.data?.relation || edge?.relation;
        const relationMatch = !linkMeta?.relation || relation === linkMeta.relation;
        const prefixMatch = !linkMeta?.edgePrefix || edge.id.startsWith(linkMeta.edgePrefix);
        return (
          edge.source === nodeIds.sourceNodeId &&
          edge.target === nodeIds.targetNodeId &&
          relationMatch &&
          prefixMatch
        );
      });
    },
    [getNewestEdgeId, getTopologyParams, graphApi, inferEdgeNodeIdsFromMeta]
  );

  const createConnection = useCallback(
    async (connection, connectionType) => {
      const linkMeta = await createLinkByNodeIds(
        connection.source,
        connection.target,
        nodesRef.current
      );
      if (linkMeta.updatable) {
        const createdEdgeId = await findCreatedEdgeId(linkMeta, connection);
        if (!createdEdgeId) {
          toast.warn('Connection created, but edge ID lookup failed. Type may not persist.');
        } else if (connectionType !== 'ethernet') {
          await persistEdgeType(createdEdgeId, connectionType);
        }
      } else if (connectionType !== 'ethernet') {
        toast.info(
          'Connection created, but this structural link does not store a connection type.'
        );
      }
    },
    [createLinkByNodeIds, findCreatedEdgeId, nodesRef, persistEdgeType, toast]
  );

  const reconnectEdge = useCallback(
    async (oldEdge, connection, connectionType) => {
      if (!oldEdge) return;
      if (oldEdge.source === connection.source && oldEdge.target === connection.target) {
        await persistEdgeType(oldEdge.id, connectionType);
        return;
      }

      try {
        await unlinkByEdge(oldEdge);
      } catch (err) {
        toast.error(err?.message || 'Could not remove the previous connection.');
        return;
      }

      const linkMeta = await createLinkByNodeIds(
        connection.source,
        connection.target,
        nodesRef.current
      );
      if (linkMeta.updatable) {
        const createdEdgeId = await findCreatedEdgeId(linkMeta, connection);
        if (!createdEdgeId) {
          toast.warn('New connection created, but edge ID lookup failed. Type may not persist.');
        } else if (connectionType !== 'ethernet') {
          await persistEdgeType(createdEdgeId, connectionType);
        }
      } else if (connectionType !== 'ethernet') {
        toast.info('Reconnected link, but this structural link does not store a connection type.');
      }
    },
    [createLinkByNodeIds, findCreatedEdgeId, nodesRef, persistEdgeType, toast, unlinkByEdge]
  );

  const handleConnect = useCallback(
    (connection) => {
      if (!connection?.source || !connection?.target) return;
      openConnectionPicker('new', connection);
    },
    [openConnectionPicker]
  );

  const handleEdgeUpdate = useCallback(
    (oldEdge, newConnection) => {
      if (!oldEdge || !newConnection?.source || !newConnection?.target) return;
      openConnectionPicker('reconnect', newConnection, oldEdge);
    },
    [openConnectionPicker]
  );

  const handlePickConnectionType = useCallback(
    async (requestedType) => {
      if (!pendingConnection) return;
      const current = pendingConnection;
      setPendingConnection(null);

      const connectionType = normalizeConnectionType(requestedType) || 'ethernet';
      try {
        if (current.mode === 'new') await createConnection(current.connection, connectionType);
        else await reconnectEdge(current.oldEdge, current.connection, connectionType);
        await fetchData();
      } catch (err) {
        toast.error(err.message || 'Connection update failed.');
        await fetchData();
      }
    },
    [
      createConnection,
      fetchData,
      normalizeConnectionType,
      pendingConnection,
      reconnectEdge,
      setPendingConnection,
      toast,
    ]
  );

  return {
    handleEdgeContextMenu,
    handleEdgeConnectionTypeChange,
    handleControlPointChange,
    handleEdgeAnchorChange,
    handleEdgeEndpointDrop,
    handleClearBend,
    handleConnect,
    handleEdgeUpdate,
    handlePickConnectionType,
  };
}
