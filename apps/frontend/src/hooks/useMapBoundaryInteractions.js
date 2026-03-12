import { useCallback, useEffect } from 'react';

export function useMapBoundaryInteractions({
  clearBoundaryPointerListeners,
  boundaryDrawMode,
  setBoundaryDrawMode,
  setBoundaryDraft,
  boundaryDraftRef,
  boundaryPointerMoveRef,
  boundaryPointerUpRef,
  finishBoundaryDrawRef,
  flowContainerRef,
  screenToFlowPosition,
  nodes,
  setBoundaries,
  pendingZonePresetRef,
  toast,
  dirtyRef,
  computeBoundaryPolygon,
  boundaryFlowRect,
  defaultBoundaryColor,
  defaultBoundaryFillOpacity,
  editingBoundaryId,
  editingBoundaryName,
  setEditingBoundaryId,
  setEditingBoundaryName,
  selectedBoundaryId,
  setSelectedBoundaryId,
  boundaryRenderData,
  resizingBoundaryRef,
  viewport,
  setSelectedNode,
}) {
  const finishBoundaryDraw = useCallback(
    (draft) => {
      const minX = Math.min(draft.startClient.x, draft.endClient.x);
      const maxX = Math.max(draft.startClient.x, draft.endClient.x);
      const minY = Math.min(draft.startClient.y, draft.endClient.y);
      const maxY = Math.max(draft.startClient.y, draft.endClient.y);
      if (maxX - minX < 16 || maxY - minY < 16) {
        setBoundaryDrawMode(false);
        setBoundaryDraft(null);
        return;
      }

      const startFlow = screenToFlowPosition({ x: minX, y: minY });
      const endFlow = screenToFlowPosition({ x: maxX, y: maxY });
      const rect = boundaryFlowRect(startFlow, endFlow);
      const memberIds = nodes
        .filter((node) => {
          const poly = computeBoundaryPolygon({ flowRect: rect }, [node]);
          return poly.some((point) => point);
        })
        .map((node) => String(node.id));

      if (memberIds.length === 0) {
        toast.info('Boundary requires at least one node inside the draw area.');
        setBoundaryDraft(null);
        return;
      }

      const boundaryId = `boundary-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const zonePreset = pendingZonePresetRef.current;
      pendingZonePresetRef.current = null;
      setBoundaries((prev) => [
        ...prev,
        {
          id: boundaryId,
          name: zonePreset
            ? `${zonePreset.defaultName} ${prev.filter((b) => b.zoneType === zonePreset.key).length + 1}`
            : `Boundary ${prev.length + 1}`,
          memberIds,
          flowRect: rect,
          color: zonePreset?.color || defaultBoundaryColor,
          fillOpacity: defaultBoundaryFillOpacity,
          shape: zonePreset?.shape || 'rectangle',
          zoneType: zonePreset?.key || null,
          behindNodes: false,
        },
      ]);
      dirtyRef.current = true;
      setBoundaryDrawMode(false);
      setBoundaryDraft(null);
      toast.success(zonePreset ? `${zonePreset.label} zone created.` : 'Boundary created.');
    },
    [
      boundaryFlowRect,
      computeBoundaryPolygon,
      defaultBoundaryColor,
      defaultBoundaryFillOpacity,
      dirtyRef,
      nodes,
      pendingZonePresetRef,
      screenToFlowPosition,
      setBoundaries,
      setBoundaryDraft,
      setBoundaryDrawMode,
      toast,
    ]
  );

  useEffect(() => {
    finishBoundaryDrawRef.current = finishBoundaryDraw;
  }, [finishBoundaryDraw, finishBoundaryDrawRef]);

  const handlePanePointerDown = useCallback(
    (event) => {
      if (!boundaryDrawMode || event.button !== 0) return;
      event.preventDefault();
      const initialDraft = {
        startClient: { x: event.clientX, y: event.clientY },
        endClient: { x: event.clientX, y: event.clientY },
      };
      clearBoundaryPointerListeners();
      setBoundaryDraft(initialDraft);
      boundaryDraftRef.current = initialDraft;

      const onPointerMove = (moveEvent) => {
        setBoundaryDraft((draft) => {
          if (!draft) return draft;
          const updated = {
            ...draft,
            endClient: { x: moveEvent.clientX, y: moveEvent.clientY },
          };
          boundaryDraftRef.current = updated;
          return updated;
        });
      };

      const onPointerUp = () => {
        const latestDraft = boundaryDraftRef.current;
        clearBoundaryPointerListeners();
        if (latestDraft) finishBoundaryDrawRef.current(latestDraft);
      };

      boundaryPointerMoveRef.current = onPointerMove;
      boundaryPointerUpRef.current = onPointerUp;
      globalThis.addEventListener('pointermove', onPointerMove);
      globalThis.addEventListener('pointerup', onPointerUp);
      if (typeof setSelectedNode === 'function') setSelectedNode(null);
    },
    [
      boundaryDrawMode,
      boundaryDraftRef,
      boundaryPointerMoveRef,
      boundaryPointerUpRef,
      clearBoundaryPointerListeners,
      finishBoundaryDrawRef,
      setSelectedNode,
      setBoundaryDraft,
    ]
  );

  useEffect(() => {
    if (!boundaryDrawMode) return;
    const paneEl = flowContainerRef.current?.querySelector('.react-flow__pane');
    if (!paneEl) return;
    paneEl.addEventListener('pointerdown', handlePanePointerDown);
    return () => paneEl.removeEventListener('pointerdown', handlePanePointerDown);
  }, [boundaryDrawMode, flowContainerRef, handlePanePointerDown]);

  const beginBoundaryRename = useCallback(
    (boundaryId, currentName) => {
      setEditingBoundaryId(boundaryId);
      setEditingBoundaryName(currentName);
    },
    [setEditingBoundaryId, setEditingBoundaryName]
  );

  const commitBoundaryRename = useCallback(() => {
    if (!editingBoundaryId) return;
    const nextName = editingBoundaryName.trim();
    if (!nextName) {
      setEditingBoundaryId(null);
      setEditingBoundaryName('');
      return;
    }
    setBoundaries((prev) =>
      prev.map((boundary) =>
        boundary.id === editingBoundaryId ? { ...boundary, name: nextName } : boundary
      )
    );
    dirtyRef.current = true;
    setEditingBoundaryId(null);
    setEditingBoundaryName('');
  }, [
    dirtyRef,
    editingBoundaryId,
    editingBoundaryName,
    setBoundaries,
    setEditingBoundaryId,
    setEditingBoundaryName,
  ]);

  const deleteBoundary = useCallback(
    (boundaryId) => {
      setBoundaries((prev) => prev.filter((b) => b.id !== boundaryId));
      if (selectedBoundaryId === boundaryId) setSelectedBoundaryId(null);
      dirtyRef.current = true;
    },
    [dirtyRef, selectedBoundaryId, setBoundaries, setSelectedBoundaryId]
  );

  const updateBoundaryColor = useCallback(
    (boundaryId, colorKey) => {
      setBoundaries((prev) =>
        prev.map((b) => (b.id === boundaryId ? { ...b, color: colorKey } : b))
      );
      dirtyRef.current = true;
    },
    [dirtyRef, setBoundaries]
  );

  const updateBoundaryShape = useCallback(
    (boundaryId, shapeKey) => {
      setBoundaries((prev) =>
        prev.map((b) => (b.id === boundaryId ? { ...b, shape: shapeKey } : b))
      );
      dirtyRef.current = true;
    },
    [dirtyRef, setBoundaries]
  );

  const sendBoundaryToBack = useCallback(
    (boundaryId) => {
      setBoundaries((prev) =>
        prev.map((b) => (b.id === boundaryId ? { ...b, behindNodes: true } : b))
      );
      dirtyRef.current = true;
    },
    [dirtyRef, setBoundaries]
  );

  const sendBoundaryToFront = useCallback(
    (boundaryId) => {
      setBoundaries((prev) =>
        prev.map((b) => (b.id === boundaryId ? { ...b, behindNodes: false } : b))
      );
      dirtyRef.current = true;
    },
    [dirtyRef, setBoundaries]
  );

  const screenToFlow = useCallback(
    (sx, sy) => ({ x: (sx - viewport.x) / viewport.zoom, y: (sy - viewport.y) / viewport.zoom }),
    [viewport]
  );

  const handleBoundaryClick = useCallback(
    (event, boundaryId) => {
      event.stopPropagation();
      setSelectedBoundaryId((prev) => (prev === boundaryId ? null : boundaryId));
    },
    [setSelectedBoundaryId]
  );

  const startBoundaryDrag = useCallback(
    (event, boundaryId) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      event.preventDefault();

      const renderItem = boundaryRenderData.find((b) => b.id === boundaryId);
      const bbox = renderItem?.flowBBox;
      if (!bbox) return;

      const startClient = { x: event.clientX, y: event.clientY };
      const startFlow = screenToFlow(event.clientX, event.clientY);

      const onMove = (moveEvt) => {
        const curFlow = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        const dx = curFlow.x - startFlow.x;
        const dy = curFlow.y - startFlow.y;
        setBoundaries((prev) =>
          prev.map((b) => {
            if (b.id !== boundaryId) return b;
            const base = b.flowRect || bbox;
            return {
              ...b,
              flowRect: {
                minX: base.minX + dx,
                maxX: base.maxX + dx,
                minY: base.minY + dy,
                maxY: base.maxY + dy,
              },
              memberIds: [],
            };
          })
        );
      };

      const onUp = (upEvt) => {
        globalThis.removeEventListener('pointermove', onMove);
        globalThis.removeEventListener('pointerup', onUp);
        const moved =
          Math.abs(upEvt.clientX - startClient.x) > 2 ||
          Math.abs(upEvt.clientY - startClient.y) > 2;
        if (!moved) {
          handleBoundaryClick(upEvt, boundaryId);
        } else {
          dirtyRef.current = true;
          setSelectedBoundaryId(boundaryId);
        }
      };

      globalThis.addEventListener('pointermove', onMove);
      globalThis.addEventListener('pointerup', onUp);
    },
    [
      boundaryRenderData,
      dirtyRef,
      handleBoundaryClick,
      screenToFlow,
      setBoundaries,
      setSelectedBoundaryId,
    ]
  );

  const startBoundaryResize = useCallback(
    (event, boundaryId, corner) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      event.preventDefault();

      const renderItem = boundaryRenderData.find((b) => b.id === boundaryId);
      const bbox = renderItem?.flowBBox;
      if (!bbox) return;
      const origRect = { minX: bbox.minX, maxX: bbox.maxX, minY: bbox.minY, maxY: bbox.maxY };

      resizingBoundaryRef.current = { boundaryId, corner, origRect };

      const onMove = (moveEvt) => {
        const flowPt = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        setBoundaries((prev) =>
          prev.map((b) => {
            if (b.id !== boundaryId) return b;
            const next = { ...origRect };
            if (corner === 'nw' || corner === 'sw')
              next.minX = Math.min(flowPt.x, origRect.maxX - 20);
            if (corner === 'ne' || corner === 'se')
              next.maxX = Math.max(flowPt.x, origRect.minX + 20);
            if (corner === 'nw' || corner === 'ne')
              next.minY = Math.min(flowPt.y, origRect.maxY - 20);
            if (corner === 'sw' || corner === 'se')
              next.maxY = Math.max(flowPt.y, origRect.minY + 20);
            return { ...b, flowRect: next, memberIds: [] };
          })
        );
      };

      const onUp = () => {
        globalThis.removeEventListener('pointermove', onMove);
        globalThis.removeEventListener('pointerup', onUp);
        resizingBoundaryRef.current = null;
        dirtyRef.current = true;
      };

      globalThis.addEventListener('pointermove', onMove);
      globalThis.addEventListener('pointerup', onUp);
    },
    [boundaryRenderData, dirtyRef, resizingBoundaryRef, screenToFlow, setBoundaries]
  );

  useEffect(() => {
    if (!selectedBoundaryId) return;
    const handleKey = (event) => {
      if (event.key === 'Escape') setSelectedBoundaryId(null);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [selectedBoundaryId, setSelectedBoundaryId]);

  return {
    beginBoundaryRename,
    commitBoundaryRename,
    deleteBoundary,
    updateBoundaryColor,
    updateBoundaryShape,
    sendBoundaryToBack,
    sendBoundaryToFront,
    screenToFlow,
    handleBoundaryClick,
    startBoundaryDrag,
    startBoundaryResize,
  };
}
