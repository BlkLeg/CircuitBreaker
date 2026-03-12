import { useState, useRef, useCallback } from 'react';

/**
 * Manages all context-menu open/close state for MapPage.
 *
 * Covers:
 *   - Node context menu  (contextMenu / contextMenuOpenRef)
 *   - Edge menu          (edgeMenu)
 *   - Boundary context menu (boundaryMenu)
 *   - Visual-line context menu (visualLineMenu)
 */
export function useContextMenuState() {
  // ── Node context menu ────────────────────────────────────────────────────────
  const [contextMenu, setContextMenu] = useState(null); // { x, y, node } | null
  const contextMenuOpenRef = useRef(false);

  const openNodeContextMenu = useCallback((event, node) => {
    event.preventDefault();
    contextMenuOpenRef.current = true;
    setContextMenu({ x: event.clientX, y: event.clientY, node });
  }, []);

  const closeNodeContextMenu = useCallback(() => {
    contextMenuOpenRef.current = false;
    setContextMenu(null);
  }, []);

  // ── Edge menu ────────────────────────────────────────────────────────────────
  const [edgeMenu, setEdgeMenu] = useState(null); // { edgeId, x, y, connectionType, isUpdatable } | null

  const openEdgeMenu = useCallback((edgeId, x, y, connectionType, isUpdatable) => {
    setEdgeMenu({ edgeId, x, y, connectionType, isUpdatable });
  }, []);

  const closeEdgeMenu = useCallback(() => setEdgeMenu(null), []);

  // ── Boundary context menu ────────────────────────────────────────────────────
  const [boundaryMenu, setBoundaryMenu] = useState(null); // { x, y, boundaryId } | null

  const openBoundaryContextMenu = useCallback((event, boundaryId) => {
    event.preventDefault();
    event.stopPropagation();
    setBoundaryMenu({ x: event.clientX, y: event.clientY, boundaryId });
  }, []);

  const closeBoundaryMenu = useCallback(() => setBoundaryMenu(null), []);

  // ── Visual-line context menu ─────────────────────────────────────────────────
  const [visualLineMenu, setVisualLineMenu] = useState(null); // { x, y, lineId } | null

  const openVisualLineContextMenu = useCallback((event, lineId) => {
    event.preventDefault();
    event.stopPropagation();
    setVisualLineMenu({ x: event.clientX, y: event.clientY, lineId });
  }, []);

  const closeVisualLineMenu = useCallback(() => setVisualLineMenu(null), []);

  // ── Dismiss all ─────────────────────────────────────────────────────────────
  const closeAllMenus = useCallback(() => {
    contextMenuOpenRef.current = false;
    setContextMenu(null);
    setEdgeMenu(null);
    setBoundaryMenu(null);
    setVisualLineMenu(null);
  }, []);

  return {
    // node context menu
    contextMenu,
    setContextMenu,
    contextMenuOpenRef,
    openNodeContextMenu,
    closeNodeContextMenu,
    // edge menu
    edgeMenu,
    setEdgeMenu,
    openEdgeMenu,
    closeEdgeMenu,
    // boundary context menu
    boundaryMenu,
    setBoundaryMenu,
    openBoundaryContextMenu,
    closeBoundaryMenu,
    // visual-line context menu
    visualLineMenu,
    setVisualLineMenu,
    openVisualLineContextMenu,
    closeVisualLineMenu,
    // convenience
    closeAllMenus,
  };
}
