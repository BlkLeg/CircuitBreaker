import { useCallback, useEffect } from 'react';

export function useMapVisualLines({
  lineDrawMode,
  setLineDrawMode,
  setLineDrawDraft,
  lineDrawDraftRef,
  linePointerMoveRef,
  linePointerUpRef,
  flowContainerRef,
  screenToFlow,
  setVisualLines,
  selectedVisualLineId,
  setSelectedVisualLineId,
  dirtyRef,
}) {
  const clearLinePointerListeners = useCallback(() => {
    if (linePointerMoveRef.current) {
      globalThis.removeEventListener('pointermove', linePointerMoveRef.current);
      linePointerMoveRef.current = null;
    }
    if (linePointerUpRef.current) {
      globalThis.removeEventListener('pointerup', linePointerUpRef.current);
      linePointerUpRef.current = null;
    }
  }, [linePointerMoveRef, linePointerUpRef]);

  const handleLinePointerDown = useCallback(
    (event) => {
      if (!lineDrawMode || event.button !== 0) return;
      if (event.target?.closest?.('[data-map-overlay-root="true"]')) return;
      // Prevent ReactFlow from interpreting this as a pan and calling
      // setPointerCapture() on the pane — which would redirect all subsequent
      // pointermove/pointerup events away from globalThis.
      event.stopPropagation();
      event.preventDefault();

      const paneEl = event.currentTarget;

      clearLinePointerListeners();
      const startFlow = screenToFlow(event.clientX, event.clientY);
      const startClient = { x: event.clientX, y: event.clientY };
      const draft = { startFlow, endFlow: startFlow, startClient, endClient: startClient };
      setLineDrawDraft(draft);
      lineDrawDraftRef.current = draft;

      const onMove = (moveEvt) => {
        const endFlow = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        const endClient = { x: moveEvt.clientX, y: moveEvt.clientY };
        setLineDrawDraft((prev) => {
          if (!prev) return prev;
          const next = { ...prev, endFlow, endClient };
          lineDrawDraftRef.current = next;
          return next;
        });
      };

      const onUp = () => {
        const latest = lineDrawDraftRef.current;
        paneEl.removeEventListener('pointermove', onMove);
        paneEl.removeEventListener('pointerup', onUp);
        linePointerMoveRef.current = null;
        linePointerUpRef.current = null;
        if (latest) {
          const dx = latest.endFlow.x - latest.startFlow.x;
          const dy = latest.endFlow.y - latest.startFlow.y;
          // Only commit if the user actually dragged (> 4px in flow space)
          if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
            setVisualLines((prev) => [
              ...prev,
              {
                id: `vline-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                startFlow: latest.startFlow,
                endFlow: latest.endFlow,
                lineType: lineDrawMode,
              },
            ]);
            dirtyRef.current = true;
          }
        }
        setLineDrawDraft(null);
        setLineDrawMode(null);
      };

      linePointerMoveRef.current = onMove;
      linePointerUpRef.current = onUp;
      paneEl.addEventListener('pointermove', onMove);
      paneEl.addEventListener('pointerup', onUp);
    },
    [
      clearLinePointerListeners,
      dirtyRef,
      lineDrawDraftRef,
      lineDrawMode,
      linePointerMoveRef,
      linePointerUpRef,
      screenToFlow,
      setLineDrawDraft,
      setLineDrawMode,
      setVisualLines,
    ]
  );

  useEffect(() => {
    if (!lineDrawMode) return;
    const paneEl = flowContainerRef.current?.querySelector('.react-flow__pane');
    if (!paneEl) return;
    paneEl.addEventListener('pointerdown', handleLinePointerDown);
    return () => paneEl.removeEventListener('pointerdown', handleLinePointerDown);
  }, [flowContainerRef, handleLinePointerDown, lineDrawMode]);

  const deleteVisualLine = useCallback(
    (lineId) => {
      setVisualLines((prev) => prev.filter((line) => line.id !== lineId));
      if (selectedVisualLineId === lineId) setSelectedVisualLineId(null);
      dirtyRef.current = true;
    },
    [dirtyRef, selectedVisualLineId, setSelectedVisualLineId, setVisualLines]
  );

  const updateVisualLineType = useCallback(
    (lineId, newType) => {
      setVisualLines((prev) =>
        prev.map((line) => (line.id === lineId ? { ...line, lineType: newType } : line))
      );
      dirtyRef.current = true;
    },
    [dirtyRef, setVisualLines]
  );

  const startVisualLineDrag = useCallback(
    (event, lineId, endpoint) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      event.preventDefault();

      const onMove = (moveEvt) => {
        const flowPoint = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        setVisualLines((prev) =>
          prev.map((line) =>
            line.id === lineId
              ? {
                  ...line,
                  ...(endpoint === 'start' ? { startFlow: flowPoint } : { endFlow: flowPoint }),
                }
              : line
          )
        );
      };

      const onUp = () => {
        globalThis.removeEventListener('pointermove', onMove);
        globalThis.removeEventListener('pointerup', onUp);
        dirtyRef.current = true;
      };

      globalThis.addEventListener('pointermove', onMove);
      globalThis.addEventListener('pointerup', onUp);
    },
    [dirtyRef, screenToFlow, setVisualLines]
  );

  useEffect(() => {
    if (!selectedVisualLineId) return;
    const onKey = (event) => {
      if (event.key === 'Escape') setSelectedVisualLineId(null);
      if (event.key === 'Delete' || event.key === 'Backspace')
        deleteVisualLine(selectedVisualLineId);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [deleteVisualLine, selectedVisualLineId, setSelectedVisualLineId]);

  return {
    deleteVisualLine,
    updateVisualLineType,
    startVisualLineDrag,
  };
}
