import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { graphApi, settingsApi, hardwareApi } from '../api/client';
import { getResultsWithInference } from '../api/discovery';
import ScanImportModal from '../components/ScanImportModal';
import { useSettings } from '../context/SettingsContext';
import { useAuth } from '../context/AuthContext.jsx';
import { useTimezone } from '../context/TimezoneContext';
import ContextMenu from '../components/map/ContextMenu';
import TelemetrySidebar from '../components/map/TelemetrySidebar';
import BoundaryContextMenu from '../components/map/BoundaryContextMenu';
import VisualLineContextMenu from '../components/map/VisualLineContextMenu';
import MapCanvasOverlays from '../components/map/MapCanvasOverlays';
import CustomNode from '../components/map/CustomNode';
import CustomEdge from '../components/map/CustomEdge';
import ConnectionTypePicker from '../components/map/ConnectionTypePicker';
import { useIsMobile } from '../hooks/useIsMobile';
import { useCapabilities } from '../hooks/useCapabilities.js';
import WifiOverlay from '../components/map/WifiOverlay';
import Sidebar from '../components/map/Sidebar';
import { useToast } from '../components/common/Toast';
import { normalizeConnectionType } from '../components/map/connectionTypes';
import { useHardwareRoles } from '../hooks/useHardwareRoles';
import { recalculateAllEdges } from '../utils/bandwidthCalculator';
import {
  createLinkByNodeIds,
  unlinkByEdge,
  isUpdatableEdgeId,
} from '../components/map/linkMutations';

import { MapEdgeCallbacksContext, MapViewOptionsContext } from '../components/map/mapContexts';
export { MapEdgeCallbacksContext, MapViewOptionsContext };

// Layout functions consumed by useMapLayout hook (../hooks/useMapLayout)
// Sigma (WebGL renderer) is only used when useSigma=true; lazy-load to defer
// ~100 KB of sigma/graphology parsing until the user explicitly enables WebGL mode.
const SigmaMap = lazyRoute('SigmaMap', () => import('../components/map/SigmaMap'));
import { groupNodesIntoCloud, restoreFromCloudView } from '../utils/cloudView';
import { viewportFit } from '../utils/viewportFit';
import { lazyRoute } from '../lib/lazyRoute';

// ── Extracted modules ────────────────────────────────────────────────────────
import {
  NODE_TYPE_ROUTES,
  BOUNDARY_PRESETS,
  resolveBoundaryPreset,
  boundaryFillString,
  normalizeBoundaryName,
  DEFAULT_BOUNDARY_COLOR,
  DEFAULT_BOUNDARY_FILL_OPACITY,
} from '../components/map/mapConstants';
import {
  applyEdgeSidesForEdge,
  computeBoundaryPolygon,
  boundaryFlowRect,
  nodeCenterInFlow,
  flowToScreenPoint,
  boundaryPath,
  boundaryRoundedRectPath,
  boundaryEllipsePath,
} from '../utils/mapGeometryUtils';
import {
  buildRelatedNodes,
  buildNodeSysinfoRows,
  buildNodeStatusDetails,
} from '../utils/mapDataUtils';
import { useMapDataLoad } from '../hooks/useMapDataLoad';
import { useMapAutoPlacement } from '../hooks/useMapAutoPlacement';
import { useMapTabs } from '../hooks/useMapTabs';
import { useMapRealTimeUpdates } from '../hooks/useMapRealTimeUpdates';
import { useMapMutations } from '../hooks/useMapMutations';
import { useMapEditorUi } from '../hooks/useMapEditorUi';
import { useMapFilters } from '../hooks/useMapFilters';
import { useMapNodeCommands } from '../hooks/useMapNodeCommands';
import MapHeader from '../components/map/MapHeader';
import BoundaryInspector from '../components/map/BoundaryInspector';
import MapDialogs from '../components/map/MapDialogs';
import EdgeInspector from '../components/map/EdgeInspector';
import MapCanvas from '../components/map/MapCanvas';
import { MapErrorBanner, ScanImportBanner } from '../components/map/MapStatusBanners';
import { useTelemetryStream } from '../hooks/useTelemetryStream';
import { useTopologyStream, topologyEmitter } from '../hooks/useTopologyStream';
import { canEdit } from '../utils/rbac';
import { useMapLayout } from '../hooks/useMapLayout';
import { useContextMenuState } from '../hooks/useContextMenuState';
import { useMapPolling } from '../hooks/useMapPolling';
import { useMapBoundaryInteractions } from '../hooks/useMapBoundaryInteractions';
import { useMapVisualLines } from '../hooks/useMapVisualLines';
import { useMapEdgeInteractions } from '../hooks/useMapEdgeInteractions';
import { useMapNodeDragSnap } from '../hooks/useMapNodeDragSnap';
import {
  ConnectionStateProvider,
  useConnectionStateContext,
} from '../providers/ConnectionStateProvider';

// ── ReactFlow node/edge type registrations ───────────────────────────────────
// Both 'iconNode'/'custom' keys registered for backward compat with saved layouts.
const NODE_TYPES = { iconNode: CustomNode, custom: CustomNode };
const EDGE_TYPES = { smart: CustomEdge, custom: CustomEdge };

// ── Small module-level helpers ───────────────────────────────────────────────
import { isLightTheme, omitKey } from '../utils/mapHelpers';

// ── Main Component ──────────────────────────────────────────────────────────

function MapInternal({ mapId, maps, onMapSwitch, onMapCreate, onMapRename, onMapDelete }) {
  const { options: HARDWARE_ROLES } = useHardwareRoles();
  const { onConnectStart, onConnectEnd } = useConnectionStateContext();
  const isMobile = useIsMobile();
  const { timezone } = useTimezone();
  const { fitView, screenToFlowPosition, setViewport } = useReactFlow();
  const viewport = useViewport();
  const hasRestoredViewport = useRef(false);
  const { settings, reloadSettings } = useSettings();
  const { user } = useAuth();
  const { caps } = useCapabilities();
  const toast = useToast();
  const navigate = useNavigate();
  const canMapEdit = canEdit(user);

  const isLight = isLightTheme(settings);
  const bgGridColor = isLight ? '#c8d4e0' : '#1a2035';

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState([]);

  // Every map filter in one unit — query inputs (environment, entity types)
  // and client-side visibility (tag, hardware role). Held as one object so
  // presentation components take `filters` as a single prop.
  const filters = useMapFilters({ settings, setNodes, setEdges });
  const { envFilter, tagFilter, setDebouncedTag, includeTypes } = filters;
  // Only allow edge selection state changes from React Flow.
  // Structural edge mutations must come from explicit user delete actions or
  // server-driven relationship updates (entity pages / topology events).
  const onEdgesChange = useCallback(
    (changes) => {
      const safeSelectionChanges = changes.filter((change) => change.type === 'select');
      if (safeSelectionChanges.length === 0) return;
      onEdgesChangeBase(safeSelectionChanges);
    },
    [onEdgesChangeBase]
  );

  const dirtyRef = useRef(false);

  const handleNodesChange = useCallback(
    (changes) => {
      onNodesChange(changes);
      if (changes.some((c) => c.type === 'position' && c.dragging)) dirtyRef.current = true;
    },
    [onNodesChange]
  );

  const outerMapRef = useRef(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [cloudViewEnabled, setCloudViewEnabled] = useState(false);
  const [useSigma, setUseSigma] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  // Track node IDs that have been auto-placed this session so fetchData re-runs
  // don't re-tag the same nodes as _needsAutoPlace before the layout is saved.
  const autoPlacedIdsRef = useRef(new Set());
  // Track nodes whose placement API call is currently in-flight so the drain
  // effect doesn't call autoPlaceNew for the same node multiple times.
  const placingNodesRef = useRef(new Set());
  // Stable ref to the latest saveLayoutSnapshot so autoPlaceNew can call it
  // without a forward-reference TDZ crash (saveLayoutSnapshot is declared later).
  const saveLayoutRef = useRef(null);
  // Count of in-flight auto-placements so we show a single batched toast.
  const pendingPlacementCountRef = useRef(0);
  const batchPlacedCountRef = useRef(0);
  const [showLabels] = useState(!isMobile);

  const [legendOpen, setLegendOpen] = useState(() => {
    const saved = localStorage.getItem('cb-legend-open');
    if (saved !== null) return saved === 'true';
    return !isMobile;
  });

  const [mapLabelDefaultColor] = useState(() => {
    const saved = localStorage.getItem('cb-map-label-default-color');
    return saved || 'blue';
  });
  useEffect(() => {
    localStorage.setItem('cb-legend-open', legendOpen);
  }, [legendOpen]);

  // Edge override state — { edgeId: { source_side, target_side, control_point? } }
  const [edgeOverrides, setEdgeOverrides] = useState({});
  // Transient editor UI — draw modes, drafts, menus and dialogs. Owned together
  // so cancelling is one action rather than a hand-maintained list of setters.
  //
  // Held as one object so presentation components can take `editorUi` as a
  // single prop; the destructure below is only for this body's convenience.
  const editorUi = useMapEditorUi({ fullscreenTargetRef: outerMapRef });
  const {
    mapLabelMenuOpenId,
    setMapLabelMenuOpenId,
    boundaryDrawMode,
    setBoundaryDrawMode,
    boundaryDraft,
    setBoundaryDraft,
    editingBoundaryId,
    setEditingBoundaryId,
    editingBoundaryName,
    setEditingBoundaryName,
    lineDrawMode,
    setLineDrawMode,
    lineDrawDraft,
    setLineDrawDraft,
    setCreateNodeModal,
    deleteConflictModal,
    setDeleteConflictModal,
    cancelActiveTool,
    isFullscreen,
    pendingZonePresetRef,
    setConfirmState,
  } = editorUi;

  const [boundaries, setBoundaries] = useState([]);
  const [mapLabels, setMapLabels] = useState([]);
  const [selectedBoundaryId, setSelectedBoundaryId] = useState(null);
  const resizingBoundaryRef = useRef(null);
  const [visualLines, setVisualLines] = useState([]);
  const [selectedVisualLineId, setSelectedVisualLineId] = useState(null);
  // Pending connection action (new connect or reconnect), resolved by type picker
  const [pendingConnection, setPendingConnection] = useState(null);

  // Stable refs so callbacks can always access the latest values
  const nodesRef = useRef([]);
  const edgeOverridesRef = useRef({});
  const flowContainerRef = useRef(null);
  const lastPointerRef = useRef({ x: 220, y: 120 });
  const boundaryDraftRef = useRef(null);
  const boundaryPointerMoveRef = useRef(null);
  const boundaryPointerUpRef = useRef(null);
  const finishBoundaryDrawRef = useRef(() => {});
  const mapLabelsRef = useRef([]);
  const visualLinesRef = useRef([]);
  const lineDrawDraftRef = useRef(null);
  const linePointerMoveRef = useRef(null);
  const linePointerUpRef = useRef(null);
  const labelPointerMoveRef = useRef(null);
  const labelPointerUpRef = useRef(null);
  const labelMenuRef = useRef(null);

  // Keep refs in sync with state
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);
  useEffect(() => {
    edgeOverridesRef.current = edgeOverrides;
  }, [edgeOverrides]);
  useEffect(() => {
    boundaryDraftRef.current = boundaryDraft;
  }, [boundaryDraft]);
  useEffect(() => {
    mapLabelsRef.current = mapLabels;
  }, [mapLabels]);
  useEffect(() => {
    visualLinesRef.current = visualLines;
  }, [visualLines]);
  useEffect(() => {
    lineDrawDraftRef.current = lineDrawDraft;
  }, [lineDrawDraft]);

  const telemetryEntityIds = useMemo(
    () =>
      nodes
        .filter((n) => n.originalType === 'hardware' && Number.isInteger(n._refId))
        .map((n) => n._refId),
    [nodes]
  );
  const { connected: telemetryConnected } = useTelemetryStream({
    entityIds: telemetryEntityIds,
  });

  // Stable ref that SmartEdge reads via MapEdgeCallbacksContext
  const edgeCallbacksRef = useRef(null);

  // Kiosk mode: guard timeouts/async so we never update state after unmount
  const isMountedRef = useRef(true);
  const unmountedRef = useRef(false);
  useEffect(() => {
    isMountedRef.current = true;
    unmountedRef.current = false;
    return () => {
      isMountedRef.current = false;
      unmountedRef.current = true;
    };
  }, []);

  // Pending discoveries badge + real-time telemetry/monitor polling
  const { pendingDiscoveries } = useMapRealTimeUpdates({
    setNodes,
    nodesRef,
    unmountedRef,
    telemetryConnected,
  });

  // Live topology sync: node moves, cable add/remove, status changes from other clients
  useTopologyStream();
  useEffect(() => {
    const onNodeMoved = ({ node_id, x, y }) => {
      setNodes((prev) => prev.map((n) => (n.id === node_id ? { ...n, position: { x, y } } : n)));
    };

    const onCableAdded = ({ source_id, target_id, connection_type, bandwidth_mbps }) => {
      const newEdge = {
        id: `cable-${source_id}-${target_id}`,
        source: source_id,
        target: target_id,
        type: 'smart',
        style: { strokeWidth: 1.5, opacity: 0.75 },
        data: {
          label: connection_type || 'ethernet',
          relation: connection_type || 'ethernet',
          controlPoint: null,
          connection_type: connection_type || 'ethernet',
          bandwidth: bandwidth_mbps ?? null,
        },
      };
      setEdges((prev) => {
        const exists = prev.some((e) => e.source === source_id && e.target === target_id);
        if (exists) return prev;
        const edgeWithAnchors = applyEdgeSidesForEdge(
          nodesRef.current || [],
          newEdge,
          edgeOverridesRef.current || {}
        );
        return [...prev, edgeWithAnchors];
      });
    };

    const onCableRemoved = ({ source_id, target_id, connection_id }) => {
      setEdges((prev) => {
        const filteredEdges = prev.filter((e) => {
          if (connection_id != null && String(e.id) === String(connection_id)) return false;
          if (e.source === source_id && e.target === target_id) return false;
          return true;
        });
        return filteredEdges;
      });
    };

    const onStatusChanged = ({ node_id, status }) => {
      setNodes((prev) =>
        prev.map((n) => (n.id === node_id ? { ...n, data: { ...n.data, status } } : n))
      );
    };

    topologyEmitter.on('topology:node_moved', onNodeMoved);
    topologyEmitter.on('topology:cable_added', onCableAdded);
    topologyEmitter.on('topology:cable_removed', onCableRemoved);
    topologyEmitter.on('topology:node_status_changed', onStatusChanged);
    return () => {
      topologyEmitter.off('topology:node_moved', onNodeMoved);
      topologyEmitter.off('topology:cable_added', onCableAdded);
      topologyEmitter.off('topology:cable_removed', onCableRemoved);
      topologyEmitter.off('topology:node_status_changed', onStatusChanged);
    };
  }, [setNodes, setEdges]);

  // Telemetry sidebar state (hover card)
  const [telemetrySidebarNode, setTelemetrySidebarNode] = useState(null);
  const [telemetrySidebarPos, setTelemetrySidebarPos] = useState({ x: 0, y: 0 });

  // Sidebar bounding rect — kept in a ref (not state) so updates don't trigger re-renders.
  // The ContextMenu reads this ref on each position recalculation to avoid overlapping the panel.
  const sidebarBoundsRef = useRef(null);
  const telemetrySidebarBoundsRef = useRef(null);
  const handleSidebarBoundsChange = useCallback((rect) => {
    sidebarBoundsRef.current = rect;
  }, []);
  const handleTelemetrySidebarBoundsChange = useCallback((rect) => {
    telemetrySidebarBoundsRef.current = rect;
  }, []);
  const lldpEnrichingRef = useRef(false);

  // Scan import banner + modal state
  const [scanImportPending, setScanImportPending] = useState(null);
  const [scanImportModalOpen, setScanImportModalOpen] = useState(false);

  useEffect(() => {
    const handler = async (e) => {
      const { scanId, newCount } = e.detail;
      try {
        const { data: results } = await getResultsWithInference(scanId);
        setScanImportPending({ scanId, newCount: results.filter((r) => r.is_new).length, results });
      } catch {
        setScanImportPending({ scanId, newCount, results: null });
      }
    };
    globalThis.addEventListener('scan:import-ready', handler);
    return () => globalThis.removeEventListener('scan:import-ready', handler);
  }, []);

  const clearBoundaryPointerListeners = useCallback(() => {
    if (boundaryPointerMoveRef.current) {
      globalThis.removeEventListener('pointermove', boundaryPointerMoveRef.current);
      boundaryPointerMoveRef.current = null;
    }
    if (boundaryPointerUpRef.current) {
      globalThis.removeEventListener('pointerup', boundaryPointerUpRef.current);
      boundaryPointerUpRef.current = null;
    }
  }, []);

  const clearLabelPointerListeners = useCallback(() => {
    if (labelPointerMoveRef.current) {
      globalThis.removeEventListener('pointermove', labelPointerMoveRef.current);
      labelPointerMoveRef.current = null;
    }
    if (labelPointerUpRef.current) {
      globalThis.removeEventListener('pointerup', labelPointerUpRef.current);
      labelPointerUpRef.current = null;
    }
  }, []);

  const {
    contextMenu,
    setContextMenu,
    contextMenuOpenRef,
    openNodeContextMenu,
    closeNodeContextMenu,
    edgeMenu,
    setEdgeMenu,
    boundaryMenu,
    setBoundaryMenu,
    openBoundaryContextMenu,
    visualLineMenu,
    setVisualLineMenu,
    openVisualLineContextMenu,
    closeAllMenus,
  } = useContextMenuState();

  // Esc key to dismiss context menus
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        clearBoundaryPointerListeners();
        clearLabelPointerListeners();
        closeAllMenus();
        setPendingConnection(null);
        cancelActiveTool();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [
    clearBoundaryPointerListeners,
    clearLabelPointerListeners,
    closeAllMenus,
    setPendingConnection,
    cancelActiveTool,
  ]);

  useEffect(() => {
    return () => {
      clearBoundaryPointerListeners();
      clearLabelPointerListeners();
    };
  }, [clearBoundaryPointerListeners, clearLabelPointerListeners]);

  useEffect(() => {
    if (!mapLabelMenuOpenId) return;
    const onPointerDown = (event) => {
      if (labelMenuRef.current && !labelMenuRef.current.contains(event.target)) {
        setMapLabelMenuOpenId(null);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [setMapLabelMenuOpenId, mapLabelMenuOpenId]);

  // Selected node side panel
  const [selectedNode, setSelectedNode] = useState(null);
  const selectedNodeRef = useRef(null);
  useEffect(() => {
    selectedNodeRef.current = selectedNode;
  }, [selectedNode]);

  const {
    layoutEngine,
    setLayoutEngine,
    applyLayout,
    applyLayoutRef,
    applyPreset,
    viewOptions,
    nodeSpacing,
    setNodeSpacing,
    edgeMode,
    setEdgeMode,
    edgeLabelVisible,
    setEdgeLabelVisible,
    groupBy,
    setGroupBy,
  } = useMapLayout({
    nodes,
    edges,
    setNodes,
    setEdges,
    setEdgeOverrides,
    edgeOverridesRef,
    flowContainerRef,
    isMountedRef,
    fitView,
    cloudViewEnabled,
    setLoading,
    dirtyRef,
    settings,
  });

  const layoutEngineRef = { current: layoutEngine };

  const {
    scheduleTelemetrySidebar,
    cancelTelemetrySidebar,
    scheduleTagDebounce,
    scheduleCloudViewFit,
    scheduleResizeFit,
  } = useMapPolling({
    onTelemetrySidebarShow: (node, pos) => {
      setTelemetrySidebarPos(pos);
      setTelemetrySidebarNode(node);
    },
    onTagDebounced: setDebouncedTag,
    onCloudViewFit: () => {
      if (isMountedRef.current) viewportFit(fitView);
    },
    onResizeFit: () => {
      if (isMountedRef.current && typeof fitView === 'function')
        viewportFit(fitView, { duration: 400 });
    },
    onResizeObserverLayout: () => {
      if (isMountedRef.current && layoutEngineRef?.current !== 'manual')
        applyLayoutRef.current(layoutEngineRef?.current);
    },
  });

  useEffect(() => {
    scheduleTagDebounce(tagFilter);
  }, [tagFilter, scheduleTagDebounce]);

  const getLayoutName = useCallback(() => {
    return envFilter ? `default::envid:${envFilter}` : 'default';
  }, [envFilter]);

  const clampPickerPosition = useCallback((x, y) => {
    const rect = flowContainerRef.current?.getBoundingClientRect();
    if (!rect) return { x: 24, y: 24 };
    const width = 240;
    const height = 180;
    const clampedX = Math.max(8, Math.min(x, rect.width - width - 8));
    const clampedY = Math.max(8, Math.min(y, rect.height - height - 8));
    return { x: clampedX, y: clampedY };
  }, []);

  const { updateNodePos, autoPlaceNew } = useMapAutoPlacement({
    envFilter,
    setNodes,
    autoPlacedIdsRef,
    placingNodesRef,
    pendingPlacementCountRef,
    batchPlacedCountRef,
    saveLayoutRef,
    fitView,
    toast,
  });

  const { fetchData } = useMapDataLoad({
    mapId,
    setLoading,
    setError,
    setEdgeMode,
    setEdgeLabelVisible,
    setNodeSpacing,
    setGroupBy,
    setLastSaved,
    setBoundaries,
    setMapLabels,
    setVisualLines,
    setEdgeOverrides,
    setNodes,
    setEdges,
    setLayoutEngine,
    edgeOverridesRef,
    autoPlacedIdsRef,
    hasRestoredViewport,
    unmountedRef,
    containerRef: flowContainerRef,
    fitView,
    setViewport,
    cloudViewEnabled,
    isMobile,
    showLabels,
    settings,
    envFilter,
    includeTypes,
    getLayoutName,
  });

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Cloud View is a transformation of the already-loaded document. The toggle
  // transforms the current nodes in place; useMapDataLoad reads the flag via a
  // ref so fetchData's identity is stable and toggling does not also re-issue a
  // topology request that would race this transform.
  useEffect(() => {
    if (cloudViewEnabled) {
      setNodes((nds) => groupNodesIntoCloud(nds));
    } else {
      setNodes((nds) => restoreFromCloudView(nds));
    }
    scheduleCloudViewFit();
  }, [cloudViewEnabled, setNodes, scheduleCloudViewFit]);

  // Kiosk: debounced refit on resize so the graph stays readable after window/layout changes
  useEffect(() => {
    const onResize = () => {
      scheduleResizeFit();
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
    };
  }, [scheduleResizeFit]);

  useEffect(() => {
    // Don't attempt placement when backend is unreachable
    if (error) return;
    // Look for nodes marked _needsAutoPlace that aren't already in-flight.
    const nodesToPlace = nodes.filter(
      (n) => n._needsAutoPlace && !placingNodesRef.current.has(n.id)
    );
    if (nodesToPlace.length > 0) {
      // Mark all as in-flight before starting so this effect doesn't re-fire
      // for the same nodes while API calls are pending.
      nodesToPlace.forEach((n) => placingNodesRef.current.add(n.id));
      // Serialize placements: each backend call sees the previous node's
      // committed position, preventing identical spiral coordinates.
      nodesToPlace.reduce((chain, n) => chain.then(() => autoPlaceNew(n.id)), Promise.resolve());
    }
  }, [nodes, autoPlaceNew, error]);

  const { saveLayoutSnapshot, saveLayout, handleDeleteNodeAction, forceRemoveDeleteConflicts } =
    useMapMutations({
      mapId,
      nodesRef,
      edgeOverridesRef,
      mapLabelsRef,
      visualLinesRef,
      dirtyRef,
      boundaries,
      edgeMode,
      edgeLabelVisible,
      nodeSpacing,
      groupBy,
      setLastSaved,
      setError,
      setConfirmState,
      setDeleteConflictModal,
      setSelectedNode,
      edges,
      deleteConflictModal,
      selectedNodeId: selectedNode?.id,
      getLayoutName,
      fetchData,
      toast,
    });

  // Keep the ref current so autoPlaceNew can call saveLayoutSnapshot without TDZ.
  saveLayoutRef.current = saveLayoutSnapshot;

  // ── Node interactions ──────────────────────────────────────────────────────

  const handleNodeMouseEnter = useCallback(
    (event, node) => {
      if (contextMenuOpenRef.current) return;
      // Don't show hover telemetry when the main (click) Sidebar is open — avoids overlap
      if (selectedNodeRef.current) return;
      scheduleTelemetrySidebar(node, { x: event.clientX + 20, y: event.clientY - 30 });
    },
    [contextMenuOpenRef, scheduleTelemetrySidebar]
  );

  const handleNodeMouseLeave = useCallback(() => {
    cancelTelemetrySidebar();
  }, [cancelTelemetrySidebar]);

  const handlePaneContextMenu = useCallback(
    (event) => {
      event.preventDefault();
      if (!canMapEdit) return;
      contextMenuOpenRef.current = false;
      setContextMenu(null);
      setCreateNodeModal({
        isOpen: true,
        position: screenToFlowPosition({
          x: event.clientX,
          y: event.clientY - 50,
        }),
      });
    },
    [setCreateNodeModal, canMapEdit, contextMenuOpenRef, screenToFlowPosition, setContextMenu]
  );

  const {
    handleCreateNode,
    handleSubmitQuickAction,
    handleSubmitRoleModal,
    updateQuickCreateRow,
    addQuickCreateRow,
    removeQuickCreateRow,
    handleBulkQuickCreateSubmit,
    handleContextAction,
    handleIconPick,
  } = useMapNodeCommands({
    editorUi,
    nodesRef,
    dirtyRef,
    lldpEnrichingRef,
    envFilter,
    mapId,
    fetchData,
    saveLayoutSnapshot,
    updateNodePos,
    handleDeleteNodeAction,
    setNodes,
    navigate,
    toast,
  });

  const handleNodeContextMenu = useCallback(
    (event, node) => {
      event.preventDefault();
      if (!canMapEdit) return;
      cancelTelemetrySidebar();
      setTelemetrySidebarNode(null);
      openNodeContextMenu(event, node);
    },
    [canMapEdit, cancelTelemetrySidebar, openNodeContextMenu]
  );

  const handleNodeClick = useCallback((event, node) => {
    setTelemetrySidebarNode(null);
    setSelectedNode(node);
  }, []);

  const handlePaneClick = useCallback(() => {
    contextMenuOpenRef.current = false;
    setContextMenu(null);
    setTelemetrySidebarNode(null);
    setBoundaryMenu(null);
    setSelectedBoundaryId(null);
    setSelectedVisualLineId(null);
    setVisualLineMenu(null);
    if (selectedNode) setSelectedNode(null);
  }, [contextMenuOpenRef, selectedNode, setBoundaryMenu, setContextMenu, setVisualLineMenu]);

  useEffect(() => {
    if (!selectedNode) return;
    const refreshed = nodes.find((node) => node.id === selectedNode.id);
    if (!refreshed) return;
    setSelectedNode(refreshed);
  }, [nodes, selectedNode]);

  const handleUplinkChange = useCallback(
    (nodeId, uplinkMbps) => {
      const value = Number(uplinkMbps);
      if (!Number.isFinite(value) || value <= 0) return;

      const updatedNodes = nodesRef.current.map((node) => {
        if (node.id !== nodeId) return node;
        return {
          ...node,
          data: {
            ...node.data,
            uplinkSpeed: value,
            upload_speed_mbps: value,
          },
        };
      });

      nodesRef.current = updatedNodes;
      setNodes(updatedNodes);
      setEdges((prev) => recalculateAllEdges(updatedNodes, prev));

      if (selectedNode?.id === nodeId) {
        const refreshed = updatedNodes.find((node) => node.id === nodeId);
        if (refreshed) setSelectedNode(refreshed);
      }

      const targetNode = updatedNodes.find((node) => node.id === nodeId);
      if (targetNode?.originalType === 'hardware' && targetNode._refId) {
        hardwareApi
          .update(targetNode._refId, { upload_speed_mbps: value, download_speed_mbps: value })
          .catch((err) => {
            console.warn('Failed to save hardware uplink speed:', err);
          });
      } else {
        const overrides = { ...(settings?.graph_uplink_overrides ?? {}), [nodeId]: value };
        settingsApi
          .update({ graph_uplink_overrides: overrides })
          .then(() => reloadSettings())
          .catch((err) => {
            console.warn('Failed to save uplink override preference:', err);
          });
      }
    },
    [selectedNode?.id, setEdges, setNodes, settings?.graph_uplink_overrides, reloadSettings]
  );

  const selectedNodeAnchor = useMemo(() => {
    if (!selectedNode) return null;

    const flowPos = selectedNode.positionAbsolute || selectedNode.position || { x: 0, y: 0 };
    const nodeWidth = selectedNode.width || 140;
    const nodeHeight = selectedNode.height || 140;

    return {
      x: viewport.x + (flowPos.x + nodeWidth) * viewport.zoom + 14,
      y: viewport.y + (flowPos.y + nodeHeight / 2) * viewport.zoom,
    };
  }, [selectedNode, viewport.x, viewport.y, viewport.zoom]);

  const selectedNodeRelationships = useMemo(() => {
    if (!selectedNode) return [];

    return buildRelatedNodes(selectedNode.id, nodes, edges).map((item) => ({
      direction: item.direction,
      relation: item.relation || 'linked_to',
      nodeId: item.node.id,
      nodeLabel: item.node.data?.alias || item.node.data?.label || item.node.id,
      nodeType: item.node.originalType || item.node.data?.type || 'node',
      nodeAddress: item.node.data?.ip_address || item.node.data?.cidr || null,
    }));
  }, [edges, nodes, selectedNode]);

  const selectedNodeSysinfo = useMemo(() => buildNodeSysinfoRows(selectedNode), [selectedNode]);
  const selectedNodeStatus = useMemo(() => buildNodeStatusDetails(selectedNode), [selectedNode]);

  const boundaryRenderData = useMemo(
    () =>
      boundaries
        .map((boundary, index) => {
          const shape = boundary.shape || 'rectangle';
          const polygon = computeBoundaryPolygon(boundary, nodes);
          if (polygon.length < 3) return null;
          const preset = resolveBoundaryPreset(boundary.color);
          const opacity = boundary.fillOpacity ?? DEFAULT_BOUNDARY_FILL_OPACITY;
          const bbox = polygon.reduce(
            (acc, p) => ({
              minX: Math.min(acc.minX, p.x),
              maxX: Math.max(acc.maxX, p.x),
              minY: Math.min(acc.minY, p.y),
              maxY: Math.max(acc.maxY, p.y),
            }),
            { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
          );
          const labelFlow = { x: bbox.minX + 4, y: bbox.minY - 2 };
          const labelScreen = flowToScreenPoint(labelFlow, viewport);
          let svgPath;
          if (shape === 'ellipse') svgPath = boundaryEllipsePath(bbox, viewport);
          else if (shape === 'rounded') svgPath = boundaryRoundedRectPath(bbox, viewport, 18);
          else svgPath = boundaryPath(polygon, viewport);
          return {
            id: boundary.id,
            name: normalizeBoundaryName(boundary.name, index),
            path: svgPath,
            labelScreen,
            stroke: preset.stroke,
            fill: boundaryFillString(preset, opacity),
            colorKey: preset.key,
            flowBBox: bbox,
            shape,
            behindNodes: boundary.behindNodes ?? false,
          };
        })
        .filter(Boolean),
    [boundaries, nodes, viewport]
  );

  const openMapLabelMenuPosition = useMemo(() => {
    if (!mapLabelMenuOpenId) return null;
    const label = mapLabels.find((entry) => entry.id === mapLabelMenuOpenId);
    if (!label) return null;

    const rect = flowContainerRef.current?.getBoundingClientRect();
    const menuWidth = 144;
    const menuHeight = 196;
    let left = label.x + label.width - 12;
    let top = label.y + 24;

    if (rect) {
      left = Math.max(8, Math.min(left, rect.width - menuWidth - 8));
      top = Math.max(8, Math.min(top, rect.height - menuHeight - 8));
    }

    return { left, top };
  }, [mapLabelMenuOpenId, mapLabels]);

  const {
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
  } = useMapBoundaryInteractions({
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
    defaultBoundaryColor: DEFAULT_BOUNDARY_COLOR,
    defaultBoundaryFillOpacity: DEFAULT_BOUNDARY_FILL_OPACITY,
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
  });

  const { deleteVisualLine, updateVisualLineType, startVisualLineDrag } = useMapVisualLines({
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
  });

  const addMapLabel = useCallback(
    (colorOverride) => {
      const rect = flowContainerRef.current?.getBoundingClientRect();
      const width = 220;
      const height = 96;
      const x = rect ? Math.max(12, rect.width / 2 - width / 2) : 180;
      const y = rect ? Math.max(12, rect.height / 2 - height / 2) : 180;

      setMapLabels((prev) => [
        ...prev,
        {
          id: `map-label-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          text: 'Label',
          x,
          y,
          width,
          height,
          color: colorOverride || mapLabelDefaultColor,
        },
      ]);
      dirtyRef.current = true;
    },
    [mapLabelDefaultColor]
  );

  const updateMapLabel = useCallback((labelId, patch) => {
    setMapLabels((prev) =>
      prev.map((label) => (label.id === labelId ? { ...label, ...patch } : label))
    );
    dirtyRef.current = true;
  }, []);

  const removeMapLabel = useCallback(
    (labelId) => {
      const nextLabels = mapLabelsRef.current.filter((label) => label.id !== labelId);
      mapLabelsRef.current = nextLabels;
      setMapLabels(nextLabels);
      setMapLabelMenuOpenId((prev) => (prev === labelId ? null : prev));
      dirtyRef.current = true;
      saveLayoutSnapshot({ labelsOverride: nextLabels }).catch((err) => {
        setError('Failed to persist label deletion: ' + err.message);
      });
    },
    [setMapLabelMenuOpenId, saveLayoutSnapshot]
  );

  const startMapLabelDrag = useCallback(
    (event, labelId) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();

      const rect = flowContainerRef.current?.getBoundingClientRect();
      const label = mapLabelsRef.current.find((entry) => entry.id === labelId);
      if (!rect || !label) return;

      clearLabelPointerListeners();

      const startClient = { x: event.clientX, y: event.clientY };
      const startPos = { x: label.x, y: label.y };

      const onPointerMove = (moveEvent) => {
        const dx = moveEvent.clientX - startClient.x;
        const dy = moveEvent.clientY - startClient.y;

        const maxX = Math.max(0, rect.width - label.width);
        const maxY = Math.max(0, rect.height - label.height);
        updateMapLabel(labelId, {
          x: Math.max(0, Math.min(maxX, startPos.x + dx)),
          y: Math.max(0, Math.min(maxY, startPos.y + dy)),
        });
      };

      const onPointerUp = () => {
        clearLabelPointerListeners();
      };

      labelPointerMoveRef.current = onPointerMove;
      labelPointerUpRef.current = onPointerUp;
      globalThis.addEventListener('pointermove', onPointerMove);
      globalThis.addEventListener('pointerup', onPointerUp);
    },
    [clearLabelPointerListeners, updateMapLabel]
  );

  // ── Drag-to-connect / drag-to-reconnect handlers ──────────────────────────

  const handlePanePointerMove = useCallback(
    (event) => {
      const rect = flowContainerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const next = clampPickerPosition(event.clientX - rect.left, event.clientY - rect.top);
      lastPointerRef.current = next;
      setBoundaryDraft((draft) => {
        if (!draft) return draft;
        return {
          ...draft,
          endClient: { x: event.clientX, y: event.clientY },
        };
      });
    },
    [setBoundaryDraft, clampPickerPosition]
  );

  const {
    handleEdgeContextMenu,
    handleEdgeConnectionTypeChange,
    handleControlPointChange,
    handleEdgeAnchorChange,
    handleEdgeEndpointDrop,
    handleClearBend,
    handleConnect,
    handleEdgeUpdate,
    handlePickConnectionType,
  } = useMapEdgeInteractions({
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
    unlinkByEdge,
    fetchData,
    toast,
    saveLayoutSnapshot,
  });

  const { handleNodeDragStart, handleNodeDragStop } = useMapNodeDragSnap({
    setEdges,
    dirtyRef,
    edgeOverridesRef,
    nodesRef,
  });

  // Keep edgeCallbacksRef.current up-to-date so SmartEdge always calls the
  // latest version of handleControlPointChange without needing to re-render.
  edgeCallbacksRef.current = {
    onControlPointChange: handleControlPointChange,
    onEdgeEndpointDrop: handleEdgeEndpointDrop,
  };

  const flow = {
    handleNodesChange,
    onEdgesChange,
    handleConnect,
    onConnectStart,
    onConnectEnd,
    handleNodeClick,
    handleNodeContextMenu,
    handleNodeDragStart,
    handleNodeDragStop,
    handleNodeMouseEnter,
    handleNodeMouseLeave,
    handlePaneClick,
    handlePaneContextMenu,
    handlePanePointerMove,
    handleEdgeContextMenu,
    handleEdgeUpdate,
    fitView,
  };

  const commands = {
    handleCreateNode,
    handleIconPick,
    handleSubmitQuickAction,
    handleSubmitRoleModal,
    handleBulkQuickCreateSubmit,
    forceRemoveDeleteConflicts,
    addQuickCreateRow,
    removeQuickCreateRow,
    updateQuickCreateRow,
    fetchData,
  };

  // One object per owner, so presentation components take six props instead of
  // the 54 individual values this markup reads.
  const view = {
    viewOptions,
    layoutEngine,
    applyLayout,
    applyPreset,
    edgeMode,
    setEdgeMode,
    edgeLabelVisible,
    setEdgeLabelVisible,
    nodeSpacing,
    setNodeSpacing,
    groupBy,
    setGroupBy,
    cloudViewEnabled,
    setCloudViewEnabled,
    useSigma,
    setUseSigma,
    bgGridColor,
  };
  const route = {
    mapId,
    maps,
    onMapSwitch,
    onMapCreate,
    onMapRename,
    onMapDelete,
    navigate,
    settings,
    user,
    caps,
    timezone,
    canMapEdit,
  };
  const persistence = {
    fetchData,
    saveLayout,
    lastSaved,
    loading,
    error,
    pendingDiscoveries,
  };
  const annotations = {
    addMapLabel,
    removeMapLabel,
    updateMapLabel,
  };

  return (
    <MapViewOptionsContext.Provider value={viewOptions}>
      <MapEdgeCallbacksContext.Provider value={edgeCallbacksRef}>
        <div
          ref={outerMapRef}
          className="page map-page"
          style={{
            height: isFullscreen ? '100vh' : 'calc(100vh - 60px)',
            display: 'flex',
            flexDirection: 'column',
            position: 'relative',
            background: 'var(--color-bg)',
          }}
        >
          <style>{`@keyframes tm-pulse { 0%,100% { opacity:1; } 50% { opacity:0.55; } }`}</style>
          {/* Scan import banner */}
          <ScanImportBanner
            pending={scanImportModalOpen ? null : scanImportPending}
            onReview={() => setScanImportModalOpen(true)}
            onDismiss={() => setScanImportPending(null)}
          />
          {/* Scan import modal */}
          {scanImportModalOpen && scanImportPending && (
            <ScanImportModal
              scanId={scanImportPending.scanId}
              results={scanImportPending.results || []}
              onClose={() => setScanImportModalOpen(false)}
              onImported={async () => {
                setScanImportModalOpen(false);
                setScanImportPending(null);
                await fetchData();
                fitView({ duration: 600 });
              }}
            />
          )}
          {/* Header + Toolbar */}
          <MapHeader
            view={view}
            filters={filters}
            editorUi={editorUi}
            route={route}
            persistence={persistence}
            annotations={annotations}
          />

          {/* Error banner */}
          <MapErrorBanner
            error={error}
            onRetry={() => {
              setError(null);
              fetchData();
            }}
          />

          {/* Graph canvas */}
          <div
            ref={flowContainerRef}
            style={{ flex: 1, position: 'relative', background: 'var(--color-bg)' }}
          >
            <MapCanvasOverlays
              boundaryRenderData={boundaryRenderData}
              selectedBoundaryId={selectedBoundaryId}
              startBoundaryDrag={startBoundaryDrag}
              startBoundaryResize={startBoundaryResize}
              openBoundaryContextMenu={openBoundaryContextMenu}
              viewport={viewport}
              visualLines={visualLines}
              selectedVisualLineId={selectedVisualLineId}
              setSelectedVisualLineId={setSelectedVisualLineId}
              openVisualLineContextMenu={openVisualLineContextMenu}
              startVisualLineDrag={startVisualLineDrag}
              editingBoundaryId={editingBoundaryId}
              editingBoundaryName={editingBoundaryName}
              setEditingBoundaryName={setEditingBoundaryName}
              setEditingBoundaryId={setEditingBoundaryId}
              commitBoundaryRename={commitBoundaryRename}
              handleBoundaryClick={handleBoundaryClick}
              beginBoundaryRename={beginBoundaryRename}
              mapLabels={mapLabels}
              resolveBoundaryPreset={resolveBoundaryPreset}
              boundaryFillString={boundaryFillString}
              startMapLabelDrag={startMapLabelDrag}
              setMapLabelMenuOpenId={setMapLabelMenuOpenId}
              updateMapLabel={updateMapLabel}
              removeMapLabel={removeMapLabel}
              mapLabelMenuOpenId={mapLabelMenuOpenId}
              openMapLabelMenuPosition={openMapLabelMenuPosition}
              labelMenuRef={labelMenuRef}
              boundaryDrawMode={boundaryDrawMode}
              boundaryDraft={boundaryDraft}
              lineDrawMode={lineDrawMode}
              lineDrawDraft={lineDrawDraft}
            />

            <BoundaryInspector
              boundaries={boundaries}
              boundaryRenderData={boundaryRenderData}
              selectedBoundaryId={selectedBoundaryId}
              onShapeChange={updateBoundaryShape}
              onColorChange={updateBoundaryColor}
            />
            <MapCanvas
              SigmaMap={SigmaMap}
              nodes={nodes}
              edges={edges}
              nodeTypes={NODE_TYPES}
              edgeTypes={EDGE_TYPES}
              flow={flow}
              editorUi={editorUi}
              view={view}
              filters={filters}
              route={route}
              persistence={persistence}
              legendOpen={legendOpen}
              onLegendToggle={setLegendOpen}
            />

            <WifiOverlay nodes={nodes} />

            {pendingConnection && (
              <ConnectionTypePicker
                x={pendingConnection.x}
                y={pendingConnection.y}
                defaultConnectionType={pendingConnection.defaultConnectionType}
                onSelect={handlePickConnectionType}
                onCancel={() => setPendingConnection(null)}
              />
            )}

            {/* Empty-canvas hint */}
            {!loading && nodes.length === 0 && !error && settings?.show_page_hints && (
              <div
                className="info-tip"
                style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  transform: 'translate(-50%, -50%)',
                  maxWidth: 400,
                  textAlign: 'center',
                  pointerEvents: 'none',
                  zIndex: 10,
                }}
              >
                💡 Your map is empty. Add <strong>Hardware</strong>, <strong>Compute Units</strong>,{' '}
                <strong>Services</strong>, or <strong>External Nodes</strong> from their pages to
                see them appear here.
              </div>
            )}

            {/* Hover telemetry floating sidebar — hide when main Sidebar is open so it never covers it */}
            {telemetrySidebarNode && !selectedNode && (
              <TelemetrySidebar
                node={telemetrySidebarNode}
                position={telemetrySidebarPos}
                onClose={() => setTelemetrySidebarNode(null)}
                onBoundsChange={handleTelemetrySidebarBoundsChange}
              />
            )}

            {/* Node context menu — avoid rects prevent collision with sidebar and hover box */}
            {contextMenu && canMapEdit && (
              <ContextMenu
                position={{ x: contextMenu.x, y: contextMenu.y }}
                node={contextMenu.node}
                nodes={nodes}
                onClose={closeNodeContextMenu}
                onAction={handleContextAction}
                avoidRectRef={sidebarBoundsRef}
                avoidRectRef2={telemetrySidebarBoundsRef}
                maps={maps}
                activeMapId={mapId}
                onRefresh={fetchData}
              />
            )}

            {boundaryMenu &&
              (() => {
                const brd = boundaryRenderData.find((b) => b.id === boundaryMenu.boundaryId);
                if (!brd) return null;
                return (
                  <BoundaryContextMenu
                    position={{ x: boundaryMenu.x, y: boundaryMenu.y }}
                    boundary={brd}
                    presets={BOUNDARY_PRESETS}
                    onRename={beginBoundaryRename}
                    onChangeColor={updateBoundaryColor}
                    onSendToBack={sendBoundaryToBack}
                    onSendToFront={sendBoundaryToFront}
                    onDelete={deleteBoundary}
                    onClose={() => setBoundaryMenu(null)}
                  />
                );
              })()}

            {visualLineMenu &&
              (() => {
                const vl = visualLines.find((v) => v.id === visualLineMenu.lineId);
                if (!vl) return null;
                return (
                  <VisualLineContextMenu
                    position={{ x: visualLineMenu.x, y: visualLineMenu.y }}
                    lineType={vl.lineType}
                    onChangeType={(newType) => updateVisualLineType(vl.id, newType)}
                    onDelete={() => deleteVisualLine(vl.id)}
                    onClose={() => setVisualLineMenu(null)}
                  />
                );
              })()}

            <MapDialogs editorUi={editorUi} commands={commands} hardwareRoles={HARDWARE_ROLES} />

            <EdgeInspector
              edgeMenu={edgeMenu}
              edgeOverrides={edgeOverrides}
              onClose={() => setEdgeMenu(null)}
              onAnchorChange={handleEdgeAnchorChange}
              onConnectionTypeChange={handleEdgeConnectionTypeChange}
              onClearBend={handleClearBend}
            />

            <Sidebar
              node={selectedNode}
              anchor={selectedNodeAnchor}
              relationships={selectedNodeRelationships}
              sysinfo={selectedNodeSysinfo}
              status={selectedNodeStatus}
              onClose={() => setSelectedNode(null)}
              onUplinkChange={handleUplinkChange}
              onOpenInHud={(node) => {
                navigate(NODE_TYPE_ROUTES.get(node?.originalType) || '/');
              }}
              onBoundsChange={handleSidebarBoundsChange}
              onMonitorAction={(action) =>
                handleContextAction(action, { nodeId: selectedNode?.id })
              }
            />
          </div>
        </div>
      </MapEdgeCallbacksContext.Provider>
    </MapViewOptionsContext.Provider>
  );
}

export default function MapPage() {
  const {
    maps,
    activeMapId,
    loading: mapsLoading,
    error: mapsError,
    retry: retryMaps,
    switchMap,
    createMap,
    renameMap,
    deleteMap,
  } = useMapTabs();

  if (mapsError) {
    return (
      <div style={{ padding: 32, color: 'var(--text-muted)' }}>
        <p>Could not load maps. Check your connection and try again.</p>
        <button onClick={retryMaps}>Retry</button>
      </div>
    );
  }

  if (mapsLoading || activeMapId == null) {
    return <div style={{ padding: 32, color: 'var(--text-muted)' }}>Loading maps…</div>;
  }

  return (
    <ReactFlowProvider key={activeMapId}>
      <ConnectionStateProvider>
        <MapInternal
          mapId={activeMapId}
          maps={maps}
          onMapSwitch={switchMap}
          onMapCreate={createMap}
          onMapRename={renameMap}
          onMapDelete={deleteMap}
        />
      </ConnectionStateProvider>
    </ReactFlowProvider>
  );
}
