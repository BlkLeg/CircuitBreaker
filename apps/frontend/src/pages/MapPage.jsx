/* eslint-disable security/detect-object-injection -- internal/ReactFlow keys; Map used for id-keyed state */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ReactFlow, {
  Background,
  Controls,
  Panel,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { graphApi, environmentsApi, settingsApi, proxmoxApi, hardwareApi } from '../api/client';
import { createMonitor, updateMonitor, runImmediateCheck } from '../api/monitor.js';
import { useSettings } from '../context/SettingsContext';
import { useAuth } from '../context/AuthContext.jsx';
import IconPickerModal from '../components/common/IconPickerModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import FormModal from '../components/common/FormModal';
import { useTimezone } from '../context/TimezoneContext';
import ContextMenu from '../components/map/ContextMenu';
import TelemetrySidebar from '../components/map/TelemetrySidebar';
import BoundaryContextMenu from '../components/map/BoundaryContextMenu';
import VisualLineContextMenu from '../components/map/VisualLineContextMenu';
import DrawToolsDropdown from '../components/map/DrawToolsDropdown';
import BulkQuickCreateModal from '../components/map/BulkQuickCreateModal';
import CreateNodeModal from '../components/map/CreateNodeModal';
import CustomNode from '../components/map/CustomNode';
import CustomEdge from '../components/map/CustomEdge';
import ConnectionTypePicker from '../components/map/ConnectionTypePicker';
import DeleteConflictModal from '../components/map/DeleteConflictModal';
import { useIsMobile } from '../hooks/useIsMobile';
import { useCapabilities } from '../hooks/useCapabilities.js';
import WifiOverlay from '../components/map/WifiOverlay';
import Sidebar from '../components/Map/Sidebar';
import { useToast } from '../components/common/Toast';
import { X } from 'lucide-react';
import {
  CONNECTION_TYPE_OPTIONS,
  normalizeConnectionType,
} from '../components/map/connectionTypes';
import { CONNECTION_STYLES } from '../config/mapTheme';
import { HARDWARE_ROLES } from '../config/hardwareRoles';
import { recalculateAllEdges } from '../utils/bandwidthCalculator';
import {
  createLinkByNodeIds,
  inferEdgeNodeIdsFromMeta,
  unlinkByEdge,
  isUpdatableEdgeId,
} from '../components/map/linkMutations';

import { MapEdgeCallbacksContext, MapViewOptionsContext } from '../components/map/mapContexts';
export { MapEdgeCallbacksContext, MapViewOptionsContext };

import {
  getDagreLayout,
  getDagreViewportOptions,
  getForceLayout,
  getTreeLayout,
  getHierarchicalNetworkLayout,
  getRadialLayout,
  getElkLayeredLayout,
  getCircularClusterLayout,
  getGridRackLayout,
  getConcentricLayout,
  getCortexLayout,
  getMindmapLayout,
  scaleAndCenterToViewport,
} from '../utils/layouts';
import MapToolbar from '../components/MapToolbar';
// Sigma (WebGL renderer) is only used when useSigma=true; lazy-load to defer
// ~100 KB of sigma/graphology parsing until the user explicitly enables WebGL mode.
const SigmaMap = React.lazy(() => import('../components/map/SigmaMap'));
import { groupNodesIntoCloud, restoreFromCloudView } from '../utils/cloudView';
import { viewportFit } from '../utils/viewportFit';

// ── Extracted modules ────────────────────────────────────────────────────────
import {
  NODE_STYLES,
  NODE_TYPE_LABELS,
  FILTER_NODE_TYPES,
  CONNECTION_TYPE_LEGEND,
  STATUS_LEGEND,
  NODE_TYPE_ROUTES,
  ENTITY_API_UPDATE_ICON,
  ENTITY_API_UPDATE_STATUS,
  ENTITY_API_UPDATE_ALIAS,
  STATUS_OPTIONS_BY_TYPE,
  STATUS_OPTION_LABEL,
  BOUNDARY_PRESETS,
  BOUNDARY_SHAPES,
  resolveBoundaryPreset,
  boundaryFillString,
  normalizeBoundaryName,
  DEFAULT_BOUNDARY_COLOR,
  DEFAULT_BOUNDARY_FILL_OPACITY,
} from '../components/map/mapConstants';
import {
  applyEdgeSides,
  applyEdgeSidesForEdge,
  computeBoundaryPolygon,
  boundaryFlowRect,
  nodeCenterInFlow,
  nodeBoundsInFlow,
  rectIntersectsRect,
  flowToScreenPoint,
  boundaryPath,
  boundaryRoundedRectPath,
  boundaryEllipsePath,
} from '../utils/mapGeometryUtils';
import {
  buildRelatedNodes,
  buildNodeSysinfoRows,
  buildNodeStatusDetails,
  makeBulkRow,
  validateBulkRows,
  runBulkCreate,
  getDefaultQuickCreateValues,
} from '../utils/mapDataUtils';
import { useMapDataLoad } from '../hooks/useMapDataLoad';
import { useMapRealTimeUpdates } from '../hooks/useMapRealTimeUpdates';
import { useMapMutations } from '../hooks/useMapMutations';
import { useTopologyStream, topologyEmitter } from '../hooks/useTopologyStream';
import { canEdit } from '../utils/rbac';

// ── ReactFlow node/edge type registrations ───────────────────────────────────
// Both 'iconNode'/'custom' keys registered for backward compat with saved layouts.
const NODE_TYPES = { iconNode: CustomNode, custom: CustomNode };
const EDGE_TYPES = { smart: CustomEdge, custom: CustomEdge };

// ── Small module-level helpers ───────────────────────────────────────────────

function isLightTheme(settings) {
  return (
    settings.theme === 'light' ||
    (settings.theme === 'auto' && globalThis.matchMedia('(prefers-color-scheme: light)').matches)
  );
}

function omitKey(obj, key) {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key));
}

function isHiddenByTag(node, trimmedTag) {
  if (!trimmedTag) return false;
  return !(node._tags || []).some((t) => t.toLowerCase().includes(trimmedTag));
}

function getQuickCreateTitle(mode) {
  if (mode === 'service') return 'New Service';
  if (mode === 'compute') return 'New Compute Unit';
  return 'New Storage';
}

// ── Main Component ──────────────────────────────────────────────────────────

function MapInternal() {
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
  // Ignore 'remove' from React Flow so edges are only deleted via explicit Delete in CustomEdge
  const onEdgesChange = useCallback(
    (changes) => onEdgesChangeBase(changes.filter((c) => c.type !== 'remove')),
    [onEdgesChangeBase]
  );

  const outerMapRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [layoutEngine, setLayoutEngine] = useState(() => settings?.graph_default_layout || 'dagre');
  const [cloudViewEnabled, setCloudViewEnabled] = useState(false);
  const [useSigma, setUseSigma] = useState(false);
  // Phase 6: view options — edge rendering mode, label visibility, node spacing, group-by
  const [edgeMode, setEdgeMode] = useState('smoothstep'); // 'straight' | 'smoothstep' | 'bundled'
  const [edgeLabelVisible, setEdgeLabelVisible] = useState(true);
  const [nodeSpacing, setNodeSpacing] = useState(1); // multiplier: 0.5 / 1 / 1.5 / 2
  const [groupBy, setGroupBy] = useState('none'); // 'none' | 'type' | 'environment' | 'rack'
  const prevGroupByRef = React.useRef('none');
  const [lastSaved, setLastSaved] = useState(null);
  const dirtyRef = useRef(false);
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
  const [boundaries, setBoundaries] = useState([]);
  const [mapLabels, setMapLabels] = useState([]);
  const [mapLabelMenuOpenId, setMapLabelMenuOpenId] = useState(null);
  const [boundaryDrawMode, setBoundaryDrawMode] = useState(false);
  const [boundaryDraft, setBoundaryDraft] = useState(null);
  const [editingBoundaryId, setEditingBoundaryId] = useState(null);
  const pendingZonePresetRef = useRef(null); // holds ZONE_PRESETS entry when zone draw is started
  const [editingBoundaryName, setEditingBoundaryName] = useState('');
  const [boundaryMenu, setBoundaryMenu] = useState(null);
  const [selectedBoundaryId, setSelectedBoundaryId] = useState(null);
  const resizingBoundaryRef = useRef(null);
  const [visualLines, setVisualLines] = useState([]);
  const [lineDrawMode, setLineDrawMode] = useState(null);
  const [lineDrawDraft, setLineDrawDraft] = useState(null);
  const [selectedVisualLineId, setSelectedVisualLineId] = useState(null);
  const [visualLineMenu, setVisualLineMenu] = useState(null);
  // Edge anchor context menu — { edgeId, x, y } | null
  const [edgeMenu, setEdgeMenu] = useState(null);
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
  const layoutEngineRef = useRef(layoutEngine);
  const applyLayoutRef = useRef(() => {});

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
      if (telemetrySidebarTimerRef.current) {
        clearTimeout(telemetrySidebarTimerRef.current);
        telemetrySidebarTimerRef.current = null;
      }
    };
  }, []);

  // Pending discoveries badge + real-time telemetry/monitor polling
  const { pendingDiscoveries } = useMapRealTimeUpdates({
    setNodes,
    nodesRef,
    unmountedRef,
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
        return exists ? prev : [...prev, newEdge];
      });
    };

    const onCableRemoved = ({ source_id, target_id, connection_id }) => {
      setEdges((prev) =>
        prev.filter((e) => {
          if (connection_id != null && String(e.id) === String(connection_id)) return false;
          if (e.source === source_id && e.target === target_id) return false;
          return true;
        })
      );
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

  // Filters
  const [envFilter, setEnvFilter] = useState('');
  const [environmentsList, setEnvironmentsList] = useState([]);
  const [tagFilter, setTagFilter] = useState('');
  const [includeTypes, setIncludeTypes] = useState({
    cluster: true,
    hardware: true,
    compute: true,
    service: true,
    storage: true,
    network: true,
    misc: true,
    external: true,
    docker: false,
  });
  // Sub-role filter for hardware nodes (null = show all)
  const [hwRoleFilter, setHwRoleFilter] = useState(null);

  // Telemetry sidebar state (hover card)
  const [telemetrySidebarNode, setTelemetrySidebarNode] = useState(null);
  const [telemetrySidebarPos, setTelemetrySidebarPos] = useState({ x: 0, y: 0 });
  const telemetrySidebarTimerRef = useRef(null);

  // Context menu state (node)
  const [contextMenu, setContextMenu] = useState(null); // { x, y, node } | null
  const contextMenuOpenRef = useRef(false);

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
  const [createNodeModal, setCreateNodeModal] = useState({ isOpen: false, position: null });
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [iconPickerNode, setIconPickerNode] = useState(null);
  const [quickActionModal, setQuickActionModal] = useState(null);
  const [quickActionValue, setQuickActionValue] = useState('');
  const [quickActionSaving, setQuickActionSaving] = useState(false);
  const [roleModal, setRoleModal] = useState({
    open: false,
    nodeRefId: null,
    nodeLabel: '',
    currentRole: '',
    isEdit: false,
  });
  const [quickCreateModal, setQuickCreateModal] = useState({
    open: false,
    mode: null,
    title: '',
    sourceLabel: '',
    initialValues: {},
  });
  const [quickCreateRows, setQuickCreateRows] = useState([]);
  const [quickCreateRowErrors, setQuickCreateRowErrors] = useState({});
  const [quickCreateSaving, setQuickCreateSaving] = useState(false);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [deleteConflictModal, setDeleteConflictModal] = useState({
    open: false,
    nodeId: null,
    nodeRefId: null,
    nodeType: null,
    nodeLabel: '',
    blockers: [],
    reason: '',
    forcing: false,
  });

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

  // Esc key to dismiss context menus
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        clearBoundaryPointerListeners();
        clearLabelPointerListeners();
        contextMenuOpenRef.current = false;
        setContextMenu(null);
        setEdgeMenu(null);
        setPendingConnection(null);
        setBoundaryDrawMode(false);
        setBoundaryDraft(null);
        setLineDrawMode(null);
        setLineDrawDraft(null);
        setVisualLineMenu(null);
        setMapLabelMenuOpenId(null);
        setEditingBoundaryId(null);
        setEditingBoundaryName('');
        setCreateNodeModal({ isOpen: false, position: null });
        setIconPickerOpen(false);
        setIconPickerNode(null);
        setQuickActionModal(null);
        setQuickActionValue('');
        setQuickCreateModal({
          open: false,
          mode: null,
          title: '',
          sourceLabel: '',
          initialValues: {},
        });
        setQuickCreateRows([]);
        setQuickCreateRowErrors({});
        setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }));
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [clearBoundaryPointerListeners, clearLabelPointerListeners]);

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
  }, [mapLabelMenuOpenId]);

  // Selected node side panel
  const [selectedNode, setSelectedNode] = useState(null);
  const selectedNodeRef = useRef(null);
  useEffect(() => {
    selectedNodeRef.current = selectedNode;
  }, [selectedNode]);

  // Debounce tag filter
  const tagDebounceRef = useRef(null);
  const [debouncedTag, setDebouncedTag] = useState('');

  // Fetch environments list for filter dropdown
  useEffect(() => {
    environmentsApi
      .list()
      .then((r) => setEnvironmentsList(r.data))
      .catch((err) => {
        console.error('Environments list load failed:', err);
      });
  }, []);

  // Settings initialization (run once after settings load)
  const settingsApplied = useRef(false);
  useEffect(() => {
    if (settings && !settingsApplied.current) {
      settingsApplied.current = true;
      if (settings.default_environment) {
        // Match default_environment string to an environment id
        // (will be reconciled after environmentsList loads)
        setEnvFilter(settings.default_environment);
      }
      if (settings.map_default_filters && typeof settings.map_default_filters === 'object') {
        const f = settings.map_default_filters;
        if (f.include && typeof f.include === 'object') {
          setIncludeTypes((prev) => ({ ...prev, ...f.include }));
        }
      }
    }
  }, [settings]);

  useEffect(() => {
    clearTimeout(tagDebounceRef.current);
    tagDebounceRef.current = setTimeout(() => setDebouncedTag(tagFilter), 300);
    return () => clearTimeout(tagDebounceRef.current);
  }, [tagFilter]);

  // Re-apply tag filter client-side (preserves positions via hidden property)
  useEffect(() => {
    const trimmedTag = debouncedTag.trim().toLowerCase();
    setNodes((prev) => prev.map((n) => ({ ...n, hidden: isHiddenByTag(n, trimmedTag) })));
    setEdges((prev) =>
      prev.map((e) => {
        if (!trimmedTag) return { ...e, hidden: false };
        return e; // edge visibility handled by ReactFlow when both nodes are hidden
      })
    );
  }, [debouncedTag, setNodes, setEdges]);

  // Hardware sub-role filter — hide/show hardware nodes by role
  useEffect(() => {
    setNodes((prev) =>
      prev.map((n) => {
        if (n.originalType !== 'hardware') return n;
        return { ...n, hidden: hwRoleFilter ? n._hwRole !== hwRoleFilter : false };
      })
    );
  }, [hwRoleFilter, setNodes]);

  const getIncludeCSV = (types) => {
    const MAP = {
      hardware: 'hardware',
      compute: 'compute',
      service: 'services',
      storage: 'storage',
      network: 'networks',
      misc: 'misc',
      external: 'external',
    };
    return (
      Object.entries(types)
        .filter(([, v]) => v)
        .map(([k]) => MAP[k])
        .filter(Boolean)
        .join(',') || 'hardware'
    );
  };

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

  const getTopologyParams = useCallback(
    () => ({
      environment_id: envFilter || undefined,
      include: getIncludeCSV(includeTypes),
    }),
    [envFilter, includeTypes]
  );

  const getNewestEdgeId = useCallback((edgesArr, predicate) => {
    const candidates = edgesArr.filter(predicate);
    candidates.sort((a, b) => {
      const aNum = Number((a.id.match(/(\\d+)(?!.*\\d)/) || [])[1] || 0);
      const bNum = Number((b.id.match(/(\\d+)(?!.*\\d)/) || [])[1] || 0);
      return bNum - aNum;
    });
    return candidates[0]?.id || null;
  }, []);

  const { fetchData, autoPlaceNew, updateNodePos } = useMapDataLoad({
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
    placingNodesRef,
    pendingPlacementCountRef,
    batchPlacedCountRef,
    saveLayoutRef,
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
    toast,
  });

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Handle Cloud View Toggle independent of fetch
  useEffect(() => {
    let t;
    if (cloudViewEnabled) {
      setNodes((nds) => groupNodesIntoCloud(nds));
      t = setTimeout(() => {
        if (isMountedRef.current) viewportFit(fitView);
      }, 100);
    } else {
      setNodes((nds) => restoreFromCloudView(nds));
      t = setTimeout(() => {
        if (isMountedRef.current) viewportFit(fitView);
      }, 100);
    }
    return () => {
      if (t) clearTimeout(t);
    };
  }, [cloudViewEnabled, setNodes, fitView]);

  // Kiosk: debounced refit on resize so the graph stays readable after window/layout changes
  useEffect(() => {
    let debounceTimer;
    const onResize = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        if (isMountedRef.current && typeof fitView === 'function') {
          viewportFit(fitView, { duration: 400 });
        }
      }, 300);
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      clearTimeout(debounceTimer);
    };
  }, [fitView]);

  layoutEngineRef.current = layoutEngine;

  const applyLayout = useCallback(
    (engine) => {
      setLoading(true);

      if (engine === 'manual') {
        setLayoutEngine('manual');
        setLoading(false);
        return;
      }

      const baseNodes = cloudViewEnabled ? restoreFromCloudView(nodes) : [...nodes];

      const rect = flowContainerRef.current?.getBoundingClientRect?.();
      const viewport = rect ? { width: rect.width, height: rect.height } : null;

      // Viewport normalizer for bounded layouts only; Force/Radial/Concentric keep their own behavior.
      const skipNormalizer = ['force', 'radial', 'concentric'].includes(engine);
      const _applyResult = (layout) => {
        if (layout) {
          let finalNodes = layout.nodes;
          if (viewport && finalNodes.length > 0 && !skipNormalizer) {
            finalNodes = scaleAndCenterToViewport(finalNodes, viewport);
          }
          if (cloudViewEnabled) {
            finalNodes = groupNodesIntoCloud(finalNodes);
          }
          setNodes(finalNodes);
          setEdges(applyEdgeSides(finalNodes, layout.edges, edgeOverridesRef.current));
          setTimeout(() => {
            if (isMountedRef.current) viewportFit(fitView, { duration: 400 });
          }, 10);
        }
        setLayoutEngine(engine);
        dirtyRef.current = true;
        setLoading(false);
        settingsApi.update({ graph_default_layout: engine }).catch((err) => {
          console.warn('Failed to save default layout preference:', err);
        });
      };

      const layoutSpacing = nodeSpacing ?? 1;
      const dagreOptions = getDagreViewportOptions(
        viewport?.width ?? rect?.width,
        viewport,
        layoutSpacing
      );

      if (engine === 'elk_layered') {
        getElkLayeredLayout(baseNodes, edges)
          .then((layout) => {
            if (isMountedRef.current) _applyResult(layout);
          })
          .catch((err) => {
            console.error('Async layout computation failed:', err);
            if (isMountedRef.current)
              _applyResult(getDagreLayout(baseNodes, edges, 'LR', dagreOptions));
          });
        return;
      }

      setTimeout(() => {
        if (!isMountedRef.current) return;
        let layout;
        if (engine === 'dagre') layout = getDagreLayout(baseNodes, edges, 'TB', dagreOptions);
        else if (engine === 'dagre_lr')
          layout = getDagreLayout(baseNodes, edges, 'LR', dagreOptions);
        else if (engine === 'force') layout = getForceLayout(baseNodes, edges);
        else if (engine === 'tree')
          layout = getTreeLayout(baseNodes, edges, viewport, layoutSpacing);
        else if (engine === 'hierarchical_network')
          layout = getHierarchicalNetworkLayout(baseNodes, edges, layoutSpacing);
        else if (engine === 'radial') layout = getRadialLayout(baseNodes, edges);
        else if (engine === 'circular_cluster')
          layout = getCircularClusterLayout(baseNodes, edges, layoutSpacing);
        else if (engine === 'grid_rack')
          layout = getGridRackLayout(baseNodes, edges, layoutSpacing);
        else if (engine === 'concentric') layout = getConcentricLayout(baseNodes, edges);
        else if (engine === 'cortex')
          layout = getCortexLayout(baseNodes, edges, viewport, layoutSpacing);
        else if (engine === 'mindmap')
          layout = getMindmapLayout(baseNodes, edges, viewport, layoutSpacing);
        _applyResult(layout);
      }, 50);
    },
    [nodes, edges, setNodes, setEdges, fitView, cloudViewEnabled, nodeSpacing]
  );

  applyLayoutRef.current = applyLayout;

  // Re-apply current layout when map container is resized (e.g. sidebar toggled)
  useEffect(() => {
    const el = flowContainerRef.current;
    if (!el) return;
    let debounceTimer;
    const ro = new ResizeObserver(() => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        if (isMountedRef.current && layoutEngineRef.current !== 'manual') {
          applyLayoutRef.current(layoutEngineRef.current);
        }
      }, 200);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      clearTimeout(debounceTimer);
    };
  }, []);

  // Apply a layout preset when Group By changes (declared after applyLayout to avoid TDZ)
  useEffect(() => {
    if (groupBy === prevGroupByRef.current) return;
    prevGroupByRef.current = groupBy;
    if (groupBy === 'type') applyLayout('circular_cluster');
    else if (groupBy === 'rack') applyLayout('grid_rack');
    else if (groupBy === 'environment') applyLayout('hierarchical_network');
    // 'none' just keeps the current layout unchanged
  }, [groupBy, applyLayout]);

  const applyPreset = useCallback(
    (preset) => {
      applyLayout(preset.layout);
    },
    [applyLayout]
  );

  useEffect(() => {
    // Look for nodes marked _needsAutoPlace that aren't already in-flight.
    const nodesToPlace = nodes.filter(
      (n) => n._needsAutoPlace && !placingNodesRef.current.has(n.id)
    );
    if (nodesToPlace.length > 0) {
      // Mark all as in-flight before kicking off parallel placements so this
      // effect doesn't re-fire for the same nodes while API calls are pending.
      nodesToPlace.forEach((n) => placingNodesRef.current.add(n.id));
      nodesToPlace.forEach((n) => autoPlaceNew(n.id));
    }
  }, [nodes, autoPlaceNew]);

  const { saveLayoutSnapshot, saveLayout, handleDeleteNodeAction, forceRemoveDeleteConflicts } =
    useMapMutations({
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

  const handleNodeMouseEnter = useCallback((event, node) => {
    if (contextMenuOpenRef.current) return;
    // Don't show hover telemetry when the main (click) Sidebar is open — avoids overlap
    if (selectedNodeRef.current) return;
    if (telemetrySidebarTimerRef.current) clearTimeout(telemetrySidebarTimerRef.current);
    telemetrySidebarTimerRef.current = setTimeout(() => {
      if (!isMountedRef.current || contextMenuOpenRef.current || selectedNodeRef.current) return;
      setTelemetrySidebarPos({ x: event.clientX + 20, y: event.clientY - 30 });
      setTelemetrySidebarNode(node);
    }, 400);
  }, []);

  const handleNodeMouseLeave = useCallback(() => {
    if (telemetrySidebarTimerRef.current) {
      clearTimeout(telemetrySidebarTimerRef.current);
      telemetrySidebarTimerRef.current = null;
    }
  }, []);

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
    [canMapEdit, screenToFlowPosition]
  );

  const handleCreateNode = useCallback(
    async (nodeData) => {
      try {
        const payload = {
          name: nodeData.label,
          hostname: nodeData.label,
          ip_address: nodeData.subLabel || null,
          type: 'hardware',
          role: nodeData.iconType,
          vendor_icon_slug: nodeData.icon_slug || null,
          environment_id: envFilter || undefined,
        };
        const res = await hardwareApi.create(payload);

        if (res.data?.id) {
          updateNodePos(res.data.id, nodeData.position);
        }

        toast.success('Node created');
        setCreateNodeModal({ isOpen: false, position: null });
        fetchData();
      } catch (err) {
        toast.error('Failed to create node: ' + err.message);
      }
    },
    [envFilter, fetchData, updateNodePos, toast]
  );

  const handleUpdateStatusAction = useCallback(
    (nodeId) => {
      const targetNode = nodesRef.current.find((n) => n.id === nodeId);
      if (!targetNode) {
        toast.error('Could not resolve node for status update.');
        return;
      }

      const targetType = targetNode.originalType;
      const updater = ENTITY_API_UPDATE_STATUS[targetType];
      const allowed = STATUS_OPTIONS_BY_TYPE[targetType] || [];
      if (!updater || allowed.length === 0 || !targetNode._refId) {
        toast.error('Status updates are not supported for this node type.');
        return;
      }

      const currentRaw = targetNode.data?.status_override || targetNode.data?.status || '';
      const currentValue = currentRaw ? String(currentRaw).toLowerCase() : 'auto';
      setQuickActionModal({
        mode: 'status',
        nodeType: targetType,
        refId: targetNode._refId,
        label: targetNode.data?.label || 'node',
        allowed,
      });
      setQuickActionValue(currentValue);
    },
    [toast]
  );

  const handleAliasAction = useCallback(
    (nodeId) => {
      const targetNode = nodesRef.current.find((n) => n.id === nodeId);
      if (!targetNode) {
        toast.error('Could not resolve node for alias update.');
        return;
      }

      const updater = ENTITY_API_UPDATE_ALIAS[targetNode.originalType];
      if (!updater || !targetNode._refId) {
        toast.error('Alias updates are not supported for this node type.');
        return;
      }

      setQuickActionModal({
        mode: 'alias',
        nodeType: targetNode.originalType,
        refId: targetNode._refId,
        label: targetNode.data?.label || 'node',
      });
      setQuickActionValue(targetNode.data?.label || '');
    },
    [toast]
  );

  const submitAliasQuickAction = useCallback(
    async (modalData, value) => {
      const updater = ENTITY_API_UPDATE_ALIAS[modalData.nodeType];
      const nextName = value.trim();
      if (!updater) {
        toast.error('Alias updates are not supported for this node type.');
        return false;
      }
      if (!nextName) {
        toast.error('Alias cannot be empty.');
        return false;
      }
      await updater(modalData.refId, nextName);
      toast.success('Alias updated');
      return true;
    },
    [toast]
  );

  const submitStatusQuickAction = useCallback(
    async (modalData, value) => {
      const updater = ENTITY_API_UPDATE_STATUS[modalData.nodeType];
      const allowed = modalData.allowed || [];
      const normalized = value.trim().toLowerCase();
      if (!updater) {
        toast.error('Status updates are not supported for this node type.');
        return false;
      }
      if (!allowed.includes(normalized)) {
        toast.error(`Invalid status. Allowed values: ${allowed.join(', ')}`);
        return false;
      }
      await updater(modalData.refId, normalized === 'auto' ? '' : normalized);
      toast.success(
        normalized === 'auto' ? 'Status reset to auto' : `Status updated to ${normalized}`
      );
      return true;
    },
    [toast]
  );

  const handleSubmitQuickAction = useCallback(async () => {
    if (!quickActionModal) return;
    setQuickActionSaving(true);
    try {
      const ok =
        quickActionModal.mode === 'alias'
          ? await submitAliasQuickAction(quickActionModal, quickActionValue)
          : await submitStatusQuickAction(quickActionModal, quickActionValue);
      if (!ok) return;

      setQuickActionModal(null);
      setQuickActionValue('');
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Action failed');
    } finally {
      setQuickActionSaving(false);
    }
  }, [
    fetchData,
    quickActionModal,
    quickActionValue,
    submitAliasQuickAction,
    submitStatusQuickAction,
    toast,
  ]);

  const handleRoleAction = useCallback(
    (nodeId) => {
      const targetNode = nodesRef.current.find((n) => n.id === nodeId);
      if (!targetNode) {
        toast.error('Could not resolve node for role update.');
        return;
      }

      if (targetNode.originalType !== 'hardware' || !targetNode._refId) {
        toast.error('Role designation is supported for hardware nodes only.');
        return;
      }

      const currentRole = targetNode._hwRole || '';
      setRoleModal({
        open: true,
        nodeRefId: targetNode._refId,
        nodeLabel: targetNode.data?.label || 'node',
        currentRole,
        isEdit: Boolean(currentRole),
      });
    },
    [toast]
  );

  const handleSubmitRoleModal = useCallback(
    async (values) => {
      if (!roleModal.nodeRefId) return;

      try {
        await hardwareApi.update(roleModal.nodeRefId, { role: values.role });
        toast.success(roleModal.isEdit ? 'Role updated.' : 'Role designated.');
        setRoleModal({
          open: false,
          nodeRefId: null,
          nodeLabel: '',
          currentRole: '',
          isEdit: false,
        });
        fetchData();
      } catch (err) {
        toast.error(err?.message ?? 'Failed to update role.');
      }
    },
    [fetchData, roleModal.isEdit, roleModal.nodeRefId, toast]
  );

  const openQuickCreateModal = useCallback((mode, nodeId, kindHint = null) => {
    const targetNode = nodesRef.current.find((n) => n.id === nodeId) || null;
    const initialValues = getDefaultQuickCreateValues(mode, targetNode, kindHint);
    setQuickCreateModal({
      open: true,
      mode,
      title: getQuickCreateTitle(mode),
      sourceLabel: targetNode?.data?.label || 'selected node',
      initialValues,
    });
    setQuickCreateRows([makeBulkRow(mode, initialValues)]);
    setQuickCreateRowErrors({});
  }, []);

  const updateQuickCreateRow = useCallback((rowId, key, value) => {
    setQuickCreateRows((rows) =>
      rows.map((row) => (row.id === rowId ? { ...row, [key]: value } : row))
    );
    setQuickCreateRowErrors((prev) => {
      if (!prev[rowId]) return prev;
      return { ...prev, [rowId]: '' };
    });
  }, []);

  const addQuickCreateRow = useCallback(() => {
    setQuickCreateRows((rows) => [
      ...rows,
      makeBulkRow(quickCreateModal.mode, quickCreateModal.initialValues),
    ]);
  }, [quickCreateModal.initialValues, quickCreateModal.mode]);

  const removeQuickCreateRow = useCallback((rowId) => {
    setQuickCreateRows((rows) => rows.filter((row) => row.id !== rowId));
    setQuickCreateRowErrors((prev) => {
      if (!prev[rowId]) return prev;
      const next = { ...prev };
      delete next[rowId];
      return next;
    });
  }, []);

  const handleBulkQuickCreateSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      const rows = quickCreateRows.filter((row) =>
        Object.values(row).some((v) => String(v ?? '').trim() !== '')
      );
      if (rows.length === 0) {
        toast.error('Add at least one entry.');
        return;
      }

      const rowValidation = validateBulkRows(quickCreateModal.mode, rows);
      if (Object.keys(rowValidation).length > 0) {
        setQuickCreateRowErrors(rowValidation);
        return;
      }

      setQuickCreateSaving(true);
      const { successCount, failed } = await runBulkCreate(
        quickCreateModal.mode,
        rows,
        quickCreateModal.initialValues
      );

      if (failed.length > 0) {
        const failedErrors = Object.fromEntries(failed.map((f) => [f.rowId, f.message]));
        setQuickCreateRowErrors(failedErrors);
        if (successCount > 0) {
          toast.info(`Created ${successCount}, failed ${failed.length}.`);
          await fetchData();
        } else {
          toast.error('No entries were created.');
        }
        setQuickCreateSaving(false);
        return;
      }

      await fetchData();
      toast.success(
        `Created ${successCount} ${quickCreateModal.mode}${successCount === 1 ? '' : 's'}.`
      );
      setQuickCreateModal({
        open: false,
        mode: null,
        title: '',
        sourceLabel: '',
        initialValues: {},
      });
      setQuickCreateRows([]);
      setQuickCreateRowErrors({});
      setQuickCreateSaving(false);
    },
    [fetchData, quickCreateModal.initialValues, quickCreateModal.mode, quickCreateRows, toast]
  );

  const handleQuickCreateAction = useCallback(
    (action, nodeId) => {
      if (action === 'add_service') {
        openQuickCreateModal('service', nodeId);
        return true;
      }
      if (action === 'add_container') {
        openQuickCreateModal('compute', nodeId, 'container');
        return true;
      }
      if (action === 'add_vm') {
        openQuickCreateModal('compute', nodeId, 'vm');
        return true;
      }
      if (action === 'add_storage') {
        openQuickCreateModal('storage', nodeId);
        return true;
      }
      if (action === 'add_cluster') {
        navigate('/hardware');
        toast.info('Opened Hardware. Create or edit a cluster to add members.');
        return true;
      }
      return false;
    },
    [navigate, openQuickCreateModal, toast]
  );

  const handleContextAction = useCallback(
    async (action, data) => {
      const { nodeId, targetId } = data;
      try {
        if (action.startsWith('link_to_')) {
          await createLinkByNodeIds(nodeId, targetId, nodesRef.current);
          toast.success('Nodes linked successfully');
          fetchData();
        } else if (action === 'edit_icon') {
          const targetNode = nodesRef.current.find((n) => n.id === nodeId);
          if (!targetNode) {
            toast.error('Could not resolve node for icon editing.');
            return;
          }
          setIconPickerNode(targetNode);
          setIconPickerOpen(true);
        } else if (action === 'alias') {
          handleAliasAction(nodeId);
        } else if (action === 'edit_role') {
          handleRoleAction(nodeId);
        } else if (action === 'update_status') {
          handleUpdateStatusAction(nodeId);
        } else if (action === 'delete_node') {
          handleDeleteNodeAction(nodeId);
        } else if (action === 'pin_node') {
          setNodes((nds) =>
            nds.map((n) =>
              n.id === nodeId ? { ...n, draggable: false, data: { ...n.data, _pinned: true } } : n
            )
          );
          dirtyRef.current = true;
        } else if (action === 'unpin_node') {
          setNodes((nds) =>
            nds.map((n) =>
              n.id === nodeId ? { ...n, draggable: true, data: { ...n.data, _pinned: false } } : n
            )
          );
          dirtyRef.current = true;
        } else if (action === 'set_node_shape') {
          const { shape } = data;
          setNodes((nds) =>
            nds.map((n) =>
              n.id === nodeId ? { ...n, data: { ...n.data, nodeShape: shape || undefined } } : n
            )
          );
          dirtyRef.current = true;
        } else if (
          action === 'proxmox_vm_start' ||
          action === 'proxmox_vm_stop' ||
          action === 'proxmox_vm_reboot'
        ) {
          const nd = nodesRef.current.find((n) => n.id === nodeId);
          if (!nd?.data?.proxmox_vmid || !nd?.data?.integration_config_id) {
            toast.error('Missing Proxmox metadata on this node.');
            return;
          }
          const pveAction = action.replace('proxmox_vm_', '');
          const parentHw = nodesRef.current.find(
            (n) => n.originalType === 'hardware' && n._refId === nd.data.hardware_id
          );
          const nodeName = parentHw?.data?.proxmox_node_name || nd.data.proxmox_node_name;
          if (!nodeName) {
            toast.error('Could not resolve parent Proxmox node.');
            return;
          }
          const res = await proxmoxApi.vmAction(
            nd.data.integration_config_id,
            nodeName,
            nd.data.proxmox_type || 'qemu',
            nd.data.proxmox_vmid,
            pveAction
          );
          if (res.data?.ok) {
            toast.success(`VM ${nd.data.label || nd.data.proxmox_vmid}: ${pveAction} sent`);
          } else {
            toast.error(`VM action failed: ${res.data?.error || 'Unknown error'}`);
          }
        } else if (handleQuickCreateAction(action, nodeId)) {
          return;
        } else if (action === 'monitor_create') {
          const nd = nodesRef.current.find((n) => n.id === nodeId);
          if (!nd?._refId) return;
          await createMonitor({
            hardware_id: nd._refId,
            probe_methods: ['icmp', 'tcp', 'http'],
            interval_secs: 60,
            enabled: true,
          });
          toast.success('Monitoring enabled');
          fetchData();
        } else if (action === 'monitor_toggle') {
          const nd = nodesRef.current.find((n) => n.id === nodeId);
          if (!nd?._refId) return;
          const next = !nd.data?.monitor_enabled;
          await updateMonitor(nd._refId, { enabled: next });
          setNodes((nds) =>
            nds.map((n) =>
              n.id === nodeId ? { ...n, data: { ...n.data, monitor_enabled: next } } : n
            )
          );
          toast.success(next ? 'Monitoring resumed' : 'Monitoring paused');
        } else if (action === 'monitor_check_now') {
          const nd = nodesRef.current.find((n) => n.id === nodeId);
          if (!nd?._refId) return;
          await runImmediateCheck(nd._refId);
          toast.success('Probe triggered');
          fetchData();
        } else {
          toast.info(`Action ${action} triggered but specific handler not implemented yet`);
        }
      } catch (err) {
        toast.error(`Action failed: ${err.message}`);
      }
    },
    [
      fetchData,
      handleAliasAction,
      handleDeleteNodeAction,
      handleQuickCreateAction,
      handleRoleAction,
      handleUpdateStatusAction,
      setNodes,
      toast,
    ]
  );

  const handleIconPick = useCallback(
    async (slug) => {
      if (!iconPickerNode) return;
      const updater = ENTITY_API_UPDATE_ICON[iconPickerNode.originalType];
      if (!updater || !iconPickerNode._refId) {
        toast.error('Icon editing is not supported for this node type.');
        return;
      }

      try {
        await updater(iconPickerNode._refId, slug);
        toast.success('Icon updated');
        setIconPickerOpen(false);
        setIconPickerNode(null);
        fetchData();
      } catch (err) {
        toast.error(err?.message || 'Failed to update icon');
      }
    },
    [fetchData, iconPickerNode, toast]
  );

  const handleNodeContextMenu = useCallback(
    (event, node) => {
      event.preventDefault();
      if (!canMapEdit) return;
      if (telemetrySidebarTimerRef.current) {
        clearTimeout(telemetrySidebarTimerRef.current);
        telemetrySidebarTimerRef.current = null;
      }
      setTelemetrySidebarNode(null);
      contextMenuOpenRef.current = true;
      setContextMenu({ x: event.clientX, y: event.clientY, node });
    },
    [canMapEdit]
  );

  const handleContextMenuClose = useCallback(() => {
    contextMenuOpenRef.current = false;
    setContextMenu(null);
  }, []);

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
  }, [selectedNode]);

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
      setSelectedNode(null);
    },
    [boundaryDrawMode, clearBoundaryPointerListeners]
  );

  const finishBoundaryDraw = useCallback(
    (draft) => {
      if (!draft) return;

      const width = Math.abs((draft.endClient?.x || 0) - (draft.startClient?.x || 0));
      const height = Math.abs((draft.endClient?.y || 0) - (draft.startClient?.y || 0));
      if (width < 12 || height < 12) {
        setBoundaryDraft(null);
        toast.info('Drag a larger area to create a boundary.');
        return;
      }

      const containerRect = flowContainerRef.current?.getBoundingClientRect();
      if (!containerRect) {
        setBoundaryDraft(null);
        return;
      }

      const startFlow = screenToFlowPosition({
        x: draft.startClient.x,
        y: draft.startClient.y,
      });
      const endFlow = screenToFlowPosition({
        x: draft.endClient.x,
        y: draft.endClient.y,
      });
      const rect = boundaryFlowRect(startFlow, endFlow);

      const memberIds = nodesRef.current
        .filter((node) => {
          if (!node || node.hidden) return false;
          const bounds = nodeBoundsInFlow(node);
          return rectIntersectsRect(bounds, rect);
        })
        .map((node) => String(node.id));

      if (memberIds.length < 1) {
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
          color: zonePreset?.color || DEFAULT_BOUNDARY_COLOR,
          fillOpacity: DEFAULT_BOUNDARY_FILL_OPACITY,
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
    [screenToFlowPosition, toast]
  );

  useEffect(() => {
    finishBoundaryDrawRef.current = finishBoundaryDraw;
  }, [finishBoundaryDraw]);

  useEffect(() => {
    if (!boundaryDrawMode) return;
    const paneEl = flowContainerRef.current?.querySelector('.react-flow__pane');
    if (!paneEl) return;
    paneEl.addEventListener('pointerdown', handlePanePointerDown);
    return () => paneEl.removeEventListener('pointerdown', handlePanePointerDown);
  }, [boundaryDrawMode, handlePanePointerDown]);

  const beginBoundaryRename = useCallback((boundaryId, currentName) => {
    setEditingBoundaryId(boundaryId);
    setEditingBoundaryName(currentName);
  }, []);

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
  }, [editingBoundaryId, editingBoundaryName]);

  const deleteBoundary = useCallback(
    (boundaryId) => {
      setBoundaries((prev) => prev.filter((b) => b.id !== boundaryId));
      if (selectedBoundaryId === boundaryId) setSelectedBoundaryId(null);
      dirtyRef.current = true;
    },
    [selectedBoundaryId]
  );

  const updateBoundaryColor = useCallback((boundaryId, colorKey) => {
    setBoundaries((prev) => prev.map((b) => (b.id === boundaryId ? { ...b, color: colorKey } : b)));
    dirtyRef.current = true;
  }, []);

  const updateBoundaryShape = useCallback((boundaryId, shapeKey) => {
    setBoundaries((prev) => prev.map((b) => (b.id === boundaryId ? { ...b, shape: shapeKey } : b)));
    dirtyRef.current = true;
  }, []);

  const sendBoundaryToBack = useCallback((boundaryId) => {
    setBoundaries((prev) =>
      prev.map((b) => (b.id === boundaryId ? { ...b, behindNodes: true } : b))
    );
    dirtyRef.current = true;
  }, []);

  const sendBoundaryToFront = useCallback((boundaryId) => {
    setBoundaries((prev) =>
      prev.map((b) => (b.id === boundaryId ? { ...b, behindNodes: false } : b))
    );
    dirtyRef.current = true;
  }, []);

  const openBoundaryContextMenu = useCallback((event, boundaryId) => {
    event.preventDefault();
    event.stopPropagation();
    setBoundaryMenu({ x: event.clientX, y: event.clientY, boundaryId });
  }, []);

  const screenToFlow = useCallback(
    (sx, sy) => {
      return { x: (sx - viewport.x) / viewport.zoom, y: (sy - viewport.y) / viewport.zoom };
    },
    [viewport]
  );

  const handleBoundaryClick = useCallback((event, boundaryId) => {
    event.stopPropagation();
    setSelectedBoundaryId((prev) => (prev === boundaryId ? null : boundaryId));
  }, []);

  const startBoundaryDrag = useCallback(
    (event, boundaryId) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      event.preventDefault();

      const renderItem = boundaryRenderData.find((b) => b.id === boundaryId);
      const bbox = renderItem?.flowBBox;
      if (!bbox) return;

      const startFlow = screenToFlow(event.clientX, event.clientY);
      const origRect = { minX: bbox.minX, maxX: bbox.maxX, minY: bbox.minY, maxY: bbox.maxY };
      let moved = false;

      const onMove = (moveEvt) => {
        moved = true;
        const curFlow = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        const dx = curFlow.x - startFlow.x;
        const dy = curFlow.y - startFlow.y;
        setBoundaries((prev) =>
          prev.map((b) => {
            if (b.id !== boundaryId) return b;
            return {
              ...b,
              flowRect: {
                minX: origRect.minX + dx,
                maxX: origRect.maxX + dx,
                minY: origRect.minY + dy,
                maxY: origRect.maxY + dy,
              },
              memberIds: [],
            };
          })
        );
      };

      const onUp = (upEvt) => {
        globalThis.removeEventListener('pointermove', onMove);
        globalThis.removeEventListener('pointerup', onUp);
        if (moved) {
          dirtyRef.current = true;
        } else {
          handleBoundaryClick(upEvt, boundaryId);
        }
      };

      globalThis.addEventListener('pointermove', onMove);
      globalThis.addEventListener('pointerup', onUp);
    },
    [boundaryRenderData, screenToFlow, handleBoundaryClick]
  );

  const startBoundaryResize = useCallback(
    (event, boundaryId, corner) => {
      event.stopPropagation();
      event.preventDefault();
      const boundary = boundaries.find((b) => b.id === boundaryId);
      if (!boundary) return;

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
    [boundaries, boundaryRenderData, screenToFlow]
  );

  useEffect(() => {
    if (!selectedBoundaryId) return;
    const handleKey = (e) => {
      if (e.key === 'Escape') setSelectedBoundaryId(null);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [selectedBoundaryId]);

  // ── Visual Line draw mode ─────────────────────────────────────────────────
  const clearLinePointerListeners = useCallback(() => {
    if (linePointerMoveRef.current) {
      globalThis.removeEventListener('pointermove', linePointerMoveRef.current);
      linePointerMoveRef.current = null;
    }
    if (linePointerUpRef.current) {
      globalThis.removeEventListener('pointerup', linePointerUpRef.current);
      linePointerUpRef.current = null;
    }
  }, []);

  const handleLinePointerDown = useCallback(
    (event) => {
      if (!lineDrawMode || event.button !== 0) return;
      event.preventDefault();
      clearLinePointerListeners();

      const startClient = { x: event.clientX, y: event.clientY };
      const startFlow = screenToFlow(event.clientX, event.clientY);
      const draft = { startClient, endClient: startClient, startFlow, endFlow: startFlow };
      setLineDrawDraft(draft);
      lineDrawDraftRef.current = draft;

      const onMove = (moveEvt) => {
        const endFlow = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        setLineDrawDraft((prev) => {
          if (!prev) return prev;
          const updated = {
            ...prev,
            endClient: { x: moveEvt.clientX, y: moveEvt.clientY },
            endFlow,
          };
          lineDrawDraftRef.current = updated;
          return updated;
        });
      };

      const onUp = () => {
        clearLinePointerListeners();
        const latest = lineDrawDraftRef.current;
        if (!latest) return;
        const dx = Math.abs(latest.endClient.x - latest.startClient.x);
        const dy = Math.abs(latest.endClient.y - latest.startClient.y);
        if (dx < 8 && dy < 8) {
          setLineDrawDraft(null);
          return;
        }
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
        setLineDrawDraft(null);
        setLineDrawMode(null);
      };

      linePointerMoveRef.current = onMove;
      linePointerUpRef.current = onUp;
      globalThis.addEventListener('pointermove', onMove);
      globalThis.addEventListener('pointerup', onUp);
    },
    [lineDrawMode, clearLinePointerListeners, screenToFlow]
  );

  useEffect(() => {
    if (!lineDrawMode) return;
    const paneEl = flowContainerRef.current?.querySelector('.react-flow__pane');
    if (!paneEl) return;
    paneEl.addEventListener('pointerdown', handleLinePointerDown);
    return () => paneEl.removeEventListener('pointerdown', handleLinePointerDown);
  }, [lineDrawMode, handleLinePointerDown]);

  const deleteVisualLine = useCallback(
    (lineId) => {
      setVisualLines((prev) => prev.filter((vl) => vl.id !== lineId));
      if (selectedVisualLineId === lineId) setSelectedVisualLineId(null);
      dirtyRef.current = true;
    },
    [selectedVisualLineId]
  );

  const updateVisualLineType = useCallback((lineId, newType) => {
    setVisualLines((prev) =>
      prev.map((vl) => (vl.id === lineId ? { ...vl, lineType: newType } : vl))
    );
    dirtyRef.current = true;
  }, []);

  const openVisualLineContextMenu = useCallback((event, lineId) => {
    event.preventDefault();
    event.stopPropagation();
    setVisualLineMenu({ x: event.clientX, y: event.clientY, lineId });
  }, []);

  const startVisualLineDrag = useCallback(
    (event, lineId, endpoint) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      event.preventDefault();

      const vl = visualLinesRef.current.find((v) => v.id === lineId);
      if (!vl) return;

      const onMove = (moveEvt) => {
        const flowPt = screenToFlow(moveEvt.clientX, moveEvt.clientY);
        setVisualLines((prev) =>
          prev.map((v) => {
            if (v.id !== lineId) return v;
            return endpoint === 'start' ? { ...v, startFlow: flowPt } : { ...v, endFlow: flowPt };
          })
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
    [screenToFlow]
  );

  useEffect(() => {
    if (!selectedVisualLineId) return;
    const handleKey = (e) => {
      if (e.key === 'Escape') setSelectedVisualLineId(null);
      if (e.key === 'Delete' || e.key === 'Backspace') deleteVisualLine(selectedVisualLineId);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [selectedVisualLineId, deleteVisualLine]);

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
    [saveLayoutSnapshot]
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

  // ── Edge interaction handlers ───────────────────────────────────────────────

  const handleEdgeContextMenu = useCallback((event, _edge) => {
    event.preventDefault();
    setEdgeMenu({
      edgeId: _edge.id,
      x: event.clientX,
      y: event.clientY,
      connectionType: _edge.data?.connection_type || 'ethernet',
      isUpdatable: isUpdatableEdgeId(_edge.id),
    });
  }, []);

  const persistEdgeType = useCallback(async (edgeId, connectionType) => {
    if (!edgeId) return false;
    try {
      await graphApi.updateEdgeType(edgeId, connectionType);
      return true;
    } catch (err) {
      console.warn('Could not persist edge type:', err?.message);
      return false;
    }
  }, []);

  const handleEdgeConnectionTypeChange = useCallback(
    async (edgeId, newType) => {
      const normalized = normalizeConnectionType(newType) || 'ethernet';
      setEdges((prev) =>
        prev.map((e) =>
          e.id === edgeId ? { ...e, data: { ...e.data, connection_type: normalized } } : e
        )
      );
      setEdgeMenu((prev) => (prev ? { ...prev, connectionType: normalized } : prev));
      await persistEdgeType(edgeId, normalized);
    },
    [persistEdgeType, setEdges]
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
        prev.map((e) =>
          e.id === edgeId ? { ...e, data: { ...e.data, controlPoint: flowPos } } : e
        )
      );
      dirtyRef.current = true;
    },
    [screenToFlowPosition, setEdges]
  );

  const handleEdgeAnchorChange = useCallback(
    (edgeId, which, side) => {
      const key = which === 'source' ? 'source_side' : 'target_side';
      let updated;
      if (side === 'auto') {
        // Remove override for this side — auto-routing takes over
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
        prev.map((e) => (e.id === edgeId ? applyEdgeSidesForEdge(nodesRef.current, e, updated) : e))
      );
      dirtyRef.current = true;
      setEdgeMenu(null);
    },
    [setEdges]
  );

  const sideFromClientForNode = useCallback(
    (nodeId, clientPos) => {
      const node = nodesRef.current.find((candidate) => candidate.id === nodeId);
      if (!node || !clientPos) return null;
      const flowPos = screenToFlowPosition({
        x: clientPos.x,
        y: clientPos.y,
      });
      const center = nodeCenterInFlow(node);
      const dx = flowPos.x - center.x;
      const dy = flowPos.y - center.y;
      if (Math.abs(dx) > Math.abs(dy)) {
        return dx > 0 ? 'right' : 'left';
      }
      return dy > 0 ? 'bottom' : 'top';
    },
    [screenToFlowPosition]
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
        prev.map((e) => (e.id === edgeId ? applyEdgeSidesForEdge(nodesRef.current, e, updated) : e))
      );
      dirtyRef.current = true;
    },
    [setEdges, sideFromClientForNode]
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
        prev.map((e) => (e.id === edgeId ? applyEdgeSidesForEdge(nodesRef.current, e, updated) : e))
      );
      dirtyRef.current = true;
      setEdgeMenu(null);
    },
    [setEdges]
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
    [clampPickerPosition]
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
    [clampPickerPosition]
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
    [getNewestEdgeId, getTopologyParams]
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
    [findCreatedEdgeId, persistEdgeType, toast]
  );

  const reconnectEdge = useCallback(
    async (oldEdge, connection, connectionType) => {
      if (!oldEdge) return;
      if (oldEdge.source === connection.source && oldEdge.target === connection.target) {
        await persistEdgeType(oldEdge.id, connectionType);
        return;
      }

      // Unlink old edge first so the graph never shows duplicate logical edges.
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
    [findCreatedEdgeId, persistEdgeType, toast]
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
        if (current.mode === 'new') {
          await createConnection(current.connection, connectionType);
        } else {
          await reconnectEdge(current.oldEdge, current.connection, connectionType);
        }
        await fetchData();
      } catch (err) {
        toast.error(err.message || 'Connection update failed.');
        await fetchData();
      }
    },
    [createConnection, fetchData, pendingConnection, reconnectEdge, toast]
  );

  const handleNodeDragStop = useCallback(
    (_event, _node, draggedNodes) => {
      setEdges((prev) => applyEdgeSides(draggedNodes, prev, edgeOverridesRef.current, _node.id));
      dirtyRef.current = true;
    },
    [setEdges]
  );

  // Keep edgeCallbacksRef.current up-to-date so SmartEdge always calls the
  // latest version of handleControlPointChange without needing to re-render.
  edgeCallbacksRef.current = {
    onControlPointChange: handleControlPointChange,
    onEdgeEndpointDrop: handleEdgeEndpointDrop,
  };

  const viewOptions = React.useMemo(
    () => ({ edgeMode, edgeLabelVisible, nodeSpacing, groupBy }),
    [edgeMode, edgeLabelVisible, nodeSpacing, groupBy]
  );

  const handleToggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      outerMapRef.current?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }, []);

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

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
          {/* Header + Toolbar */}
          <div
            className="page-header"
            style={{
              marginBottom: 0,
              paddingBottom: 10,
              borderBottom: '1px solid var(--color-border)',
              flexWrap: 'wrap',
              gap: 8,
              position: 'sticky',
              top: 0,
              zIndex: 40,
              background: 'color-mix(in srgb, var(--color-bg) 88%, transparent)',
              backdropFilter: 'blur(6px)',
            }}
          >
            <h2 style={{ marginRight: 16 }}>{settings.map_title || 'Topology'}</h2>

            <div
              style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flex: 1 }}
            >
              {/* Environment */}
              <select
                value={envFilter}
                onChange={(e) => setEnvFilter(e.target.value ? Number(e.target.value) : '')}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-bg)',
                  color: 'var(--color-text)',
                  fontSize: 12,
                }}
              >
                <option value="">All Environments</option>
                {environmentsList.map((e) => (
                  <option key={e.id} value={e.id} style={e.color ? { color: e.color } : {}}>
                    {e.name}
                  </option>
                ))}
              </select>

              {/* Group By */}
              <select
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: groupBy !== 'none' ? 'var(--color-glow)' : 'var(--color-bg)',
                  color: groupBy !== 'none' ? 'var(--color-primary)' : 'var(--color-text)',
                  fontSize: 12,
                }}
                title="Group nodes by dimension"
              >
                <option value="none">Group by…</option>
                <option value="type">By Type</option>
                <option value="environment">By Environment</option>
                <option value="rack">By Rack</option>
              </select>

              {/* Tag filter */}
              <input
                type="text"
                placeholder="Filter by tag…"
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-bg)',
                  color: 'var(--color-text)',
                  fontSize: 12,
                  width: 130,
                }}
              />

              {/* Node type toggles */}
              <span
                style={{
                  color: 'var(--color-text-muted)',
                  fontSize: 11,
                  borderLeft: '1px solid var(--color-border)',
                  paddingLeft: 8,
                }}
              >
                Show:
              </span>
              {FILTER_NODE_TYPES.map((type) => {
                const style = NODE_STYLES[type];
                return (
                  <button
                    key={type}
                    onClick={() => setIncludeTypes((prev) => ({ ...prev, [type]: !prev[type] }))}
                    style={{
                      padding: '3px 8px',
                      borderRadius: 4,
                      border: `1px solid ${style.borderColor}`,
                      background: includeTypes[type] ? style.background : 'transparent',
                      color: includeTypes[type] ? '#fff' : style.background,
                      fontSize: 11,
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                  >
                    {NODE_TYPE_LABELS[type]}
                  </button>
                );
              })}
              {/* Docker toggle — single button controlling both docker_network + docker_container */}
              <button
                onClick={() => setIncludeTypes((prev) => ({ ...prev, docker: !prev.docker }))}
                style={{
                  padding: '3px 8px',
                  borderRadius: 4,
                  border: '1px solid #1cb8d8',
                  background: includeTypes.docker ? '#0b6e8e' : 'transparent',
                  color: includeTypes.docker ? '#fff' : '#1cb8d8',
                  fontSize: 11,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                Docker
              </button>

              {/* Hardware sub-role chips */}
              {includeTypes.hardware && (
                <>
                  <span
                    style={{
                      color: 'var(--color-text-muted)',
                      fontSize: 11,
                      borderLeft: '1px solid var(--color-border)',
                      paddingLeft: 8,
                    }}
                  >
                    Role:
                  </span>
                  {[
                    { value: 'ups', label: 'UPS' },
                    { value: 'pdu', label: 'PDU' },
                    { value: 'access_point', label: 'AP' },
                    { value: 'sbc', label: 'SBC' },
                  ].map(({ value, label }) => (
                    <button
                      key={value}
                      onClick={() => setHwRoleFilter((prev) => (prev === value ? null : value))}
                      style={{
                        padding: '3px 8px',
                        borderRadius: 4,
                        fontSize: 11,
                        cursor: 'pointer',
                        border: '1px solid #4a7fa5',
                        background: hwRoleFilter === value ? '#4a7fa5' : 'transparent',
                        color: hwRoleFilter === value ? '#fff' : '#4a7fa5',
                        transition: 'all 0.15s',
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </>
              )}

              <MapToolbar
                layout={layoutEngine}
                onChange={applyLayout}
                onPreset={applyPreset}
                viewOptions={viewOptions}
                onViewOptionsChange={(opts) => {
                  if (opts.edgeMode !== edgeMode) setEdgeMode(opts.edgeMode);
                  if (opts.edgeLabelVisible !== edgeLabelVisible)
                    setEdgeLabelVisible(opts.edgeLabelVisible);
                  if (opts.nodeSpacing !== nodeSpacing) setNodeSpacing(opts.nodeSpacing);
                }}
                onFullscreen={handleToggleFullscreen}
                isFullscreen={isFullscreen}
              />

              <button
                onClick={() => setUseSigma(!useSigma)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: `1px solid ${useSigma ? '#00d4aa' : 'var(--color-border)'}`,
                  background: useSigma ? 'rgba(0, 212, 170, 0.1)' : 'var(--color-bg)',
                  color: useSigma ? '#00d4aa' : 'var(--color-text)',
                  fontSize: 12,
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  marginRight: '8px',
                }}
              >
                {useSigma ? 'WebGL (Active)' : 'WebGL (>1k)'}
              </button>
              <button
                onClick={() => setCloudViewEnabled(!cloudViewEnabled)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: `1px solid ${cloudViewEnabled ? 'var(--color-primary)' : 'var(--color-border)'}`,
                  background: cloudViewEnabled ? 'rgba(254, 128, 25, 0.1)' : 'var(--color-bg)',
                  color: cloudViewEnabled ? 'var(--color-primary)' : 'var(--color-text)',
                  fontSize: 12,
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
              >
                {cloudViewEnabled ? '☁ Disable Cloud View' : '☁ Enable Cloud View'}
              </button>

              {caps && !caps.realtime?.available && (
                <span
                  style={{
                    fontSize: 11,
                    color: '#f59e0b',
                    background: 'rgba(245,158,11,0.08)',
                    border: '1px solid rgba(245,158,11,0.25)',
                    borderRadius: 6,
                    padding: '3px 8px',
                    whiteSpace: 'nowrap',
                  }}
                  title="Enable realtime in Settings → Integrations to receive live topology updates"
                >
                  ⚡ Realtime unavailable
                </span>
              )}

              <button
                className="btn btn-primary"
                onClick={saveLayout}
                disabled={loading}
                style={{ fontSize: 12, padding: '5px 12px' }}
              >
                {loading ? 'Loading…' : 'Save Positions'}
              </button>
              <button
                className="btn"
                onClick={fetchData}
                disabled={loading}
                style={{ fontSize: 12, padding: '5px 12px' }}
              >
                Refresh
              </button>
              <DrawToolsDropdown
                activeMode={(() => {
                  if (boundaryDrawMode) return 'Boundary';
                  if (lineDrawMode) return `${lineDrawMode} line`;
                  return null;
                })()}
                boundaryPresets={BOUNDARY_PRESETS}
                onStartBoundaryDraw={() => {
                  pendingZonePresetRef.current = null;
                  setLineDrawMode(null);
                  setLineDrawDraft(null);
                  setBoundaryDrawMode(true);
                  setBoundaryDraft(null);
                }}
                onStartZoneDraw={(zonePreset) => {
                  pendingZonePresetRef.current = zonePreset;
                  setLineDrawMode(null);
                  setLineDrawDraft(null);
                  setBoundaryDrawMode(true);
                  setBoundaryDraft(null);
                }}
                onStartLineDraw={(type) => {
                  setBoundaryDrawMode(false);
                  setBoundaryDraft(null);
                  setLineDrawMode(type);
                  setLineDrawDraft(null);
                }}
                onAddLabel={(colorKey) => addMapLabel(colorKey)}
                onCancel={() => {
                  setBoundaryDrawMode(false);
                  setBoundaryDraft(null);
                  setLineDrawMode(null);
                  setLineDrawDraft(null);
                }}
              />
              {pendingDiscoveries > 0 && (
                <button
                  type="button"
                  onClick={() => navigate('/discovery?tab=review')}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 5,
                    padding: '4px 10px',
                    borderRadius: 5,
                    border: 'none',
                    background: 'rgba(245,158,11,0.18)',
                    color: '#f59e0b',
                    cursor: 'pointer',
                    fontSize: 11,
                    fontWeight: 600,
                  }}
                >
                  🔍 {pendingDiscoveries} pending
                </button>
              )}
              {lastSaved && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  Saved: {new Date(lastSaved).toLocaleTimeString(undefined, { timeZone: timezone })}
                </span>
              )}
            </div>
          </div>

          {/* Error banner */}
          {error && (
            <div
              style={{
                background: 'rgba(243,139,168,0.15)',
                border: '1px solid #f38ba8',
                color: '#f38ba8',
                padding: '6px 12px',
                fontSize: 12,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span>{error}</span>
              <button
                onClick={() => setError(null)}
                style={{ background: 'none', border: 'none', color: '#f38ba8', cursor: 'pointer' }}
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Graph canvas */}
          <div
            ref={flowContainerRef}
            style={{ flex: 1, position: 'relative', background: 'var(--color-bg)' }}
          >
            {/* Boundaries sent "to back" — behind nodes so nodes can be clicked */}
            {boundaryRenderData.some((b) => b.behindNodes) && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 1, pointerEvents: 'none' }}>
                <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
                  {boundaryRenderData
                    .filter((b) => b.behindNodes)
                    .map((boundary) => (
                      <g key={boundary.id}>
                        <path
                          d={boundary.path}
                          fill={boundary.fill}
                          stroke={boundary.stroke}
                          strokeWidth={2}
                          strokeDasharray="8 6"
                          vectorEffect="non-scaling-stroke"
                          style={{ pointerEvents: 'none' }}
                        />
                      </g>
                    ))}
                </svg>
              </div>
            )}

            {boundaryRenderData.some((b) => !b.behindNodes) && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 9, pointerEvents: 'none' }}>
                <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
                  {boundaryRenderData
                    .filter((b) => !b.behindNodes)
                    .map((boundary) => (
                      <g key={boundary.id}>
                        <path
                          d={boundary.path}
                          fill={boundary.fill}
                          stroke={boundary.stroke}
                          strokeWidth={selectedBoundaryId === boundary.id ? 3 : 2}
                          strokeDasharray={selectedBoundaryId === boundary.id ? 'none' : '8 6'}
                          vectorEffect="non-scaling-stroke"
                          style={{
                            pointerEvents: 'visiblePainted',
                            cursor: selectedBoundaryId === boundary.id ? 'grab' : 'pointer',
                          }}
                          onPointerDown={(e) => startBoundaryDrag(e, boundary.id)}
                          onContextMenu={(e) => openBoundaryContextMenu(e, boundary.id)}
                        />
                        {selectedBoundaryId === boundary.id &&
                          (() => {
                            const { flowBBox } = boundary;
                            const corners = [
                              {
                                key: 'nw',
                                fx: flowBBox.minX,
                                fy: flowBBox.minY,
                                cursor: 'nwse-resize',
                              },
                              {
                                key: 'ne',
                                fx: flowBBox.maxX,
                                fy: flowBBox.minY,
                                cursor: 'nesw-resize',
                              },
                              {
                                key: 'sw',
                                fx: flowBBox.minX,
                                fy: flowBBox.maxY,
                                cursor: 'nesw-resize',
                              },
                              {
                                key: 'se',
                                fx: flowBBox.maxX,
                                fy: flowBBox.maxY,
                                cursor: 'nwse-resize',
                              },
                            ];
                            return corners.map((c) => {
                              const sp = flowToScreenPoint({ x: c.fx, y: c.fy }, viewport);
                              return (
                                <circle
                                  key={c.key}
                                  cx={sp.x}
                                  cy={sp.y}
                                  r={6}
                                  fill={boundary.stroke}
                                  stroke="var(--color-bg)"
                                  strokeWidth={2}
                                  style={{ pointerEvents: 'auto', cursor: c.cursor }}
                                  onPointerDown={(e) => startBoundaryResize(e, boundary.id, c.key)}
                                />
                              );
                            });
                          })()}
                      </g>
                    ))}
                </svg>
              </div>
            )}

            {visualLines.length > 0 && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 10, pointerEvents: 'none' }}>
                <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
                  {visualLines.map((vl) => {
                    const cs = CONNECTION_STYLES[vl.lineType] || CONNECTION_STYLES.ethernet;
                    const s = flowToScreenPoint(vl.startFlow, viewport);
                    const e = flowToScreenPoint(vl.endFlow, viewport);
                    const isSelected = selectedVisualLineId === vl.id;
                    return (
                      <g key={vl.id}>
                        <line
                          x1={s.x}
                          y1={s.y}
                          x2={e.x}
                          y2={e.y}
                          stroke="transparent"
                          strokeWidth={12}
                          style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            setSelectedVisualLineId((prev) => (prev === vl.id ? null : vl.id));
                          }}
                          onContextMenu={(ev) => openVisualLineContextMenu(ev, vl.id)}
                        />
                        <line
                          x1={s.x}
                          y1={s.y}
                          x2={e.x}
                          y2={e.y}
                          stroke={cs.stroke}
                          strokeWidth={isSelected ? cs.strokeWidth * 2 : cs.strokeWidth}
                          strokeDasharray={cs.strokeDasharray || 'none'}
                          strokeLinecap="round"
                          filter={cs.filter || 'none'}
                          style={{ pointerEvents: 'none' }}
                        />
                        {isSelected && (
                          <>
                            <circle
                              cx={s.x}
                              cy={s.y}
                              r={6}
                              fill={cs.stroke}
                              stroke="var(--color-bg)"
                              strokeWidth={2}
                              style={{ pointerEvents: 'auto', cursor: 'move' }}
                              onPointerDown={(ev) => startVisualLineDrag(ev, vl.id, 'start')}
                            />
                            <circle
                              cx={e.x}
                              cy={e.y}
                              r={6}
                              fill={cs.stroke}
                              stroke="var(--color-bg)"
                              strokeWidth={2}
                              style={{ pointerEvents: 'auto', cursor: 'move' }}
                              onPointerDown={(ev) => startVisualLineDrag(ev, vl.id, 'end')}
                            />
                          </>
                        )}
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}

            {boundaryRenderData.length > 0 && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 12, pointerEvents: 'none' }}>
                {boundaryRenderData.map((boundary) => (
                  <div
                    key={`label-${boundary.id}`}
                    style={{
                      position: 'absolute',
                      left: boundary.labelScreen.x,
                      top: boundary.labelScreen.y,
                      transform: 'translate(0, -100%)',
                      pointerEvents: 'auto',
                    }}
                  >
                    {editingBoundaryId === boundary.id ? (
                      <input
                        autoFocus
                        value={editingBoundaryName}
                        onChange={(event) => setEditingBoundaryName(event.target.value)}
                        onBlur={commitBoundaryRename}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') commitBoundaryRename();
                          if (event.key === 'Escape') {
                            setEditingBoundaryId(null);
                            setEditingBoundaryName('');
                          }
                        }}
                        style={{
                          minWidth: 140,
                          borderRadius: 999,
                          border: `1px solid ${boundary.stroke}`,
                          background: 'rgba(7, 18, 33, 0.92)',
                          color: 'var(--color-text)',
                          padding: '3px 10px',
                          fontSize: 12,
                          textAlign: 'center',
                        }}
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={(e) => handleBoundaryClick(e, boundary.id)}
                        onDoubleClick={() => beginBoundaryRename(boundary.id, boundary.name)}
                        onContextMenu={(e) => openBoundaryContextMenu(e, boundary.id)}
                        style={{
                          borderRadius: 999,
                          border: `1px solid ${boundary.stroke}`,
                          background: 'rgba(7, 18, 33, 0.72)',
                          color: 'var(--color-text)',
                          padding: '2px 10px',
                          fontSize: 12,
                          cursor: 'pointer',
                        }}
                        title="Click to select · Double-click to rename · Right-click for options"
                      >
                        {boundary.name}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {selectedBoundaryId &&
              (() => {
                const selBoundary = boundaries.find((b) => b.id === selectedBoundaryId);
                const selRender = boundaryRenderData.find((b) => b.id === selectedBoundaryId);
                if (!selBoundary || !selRender) return null;
                return (
                  <div
                    role="toolbar"
                    aria-label="Boundary options"
                    style={{
                      position: 'absolute',
                      top: 12,
                      right: 12,
                      zIndex: 40,
                      background: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 10,
                      padding: '10px 14px',
                      boxShadow: '0 4px 20px rgba(0,0,0,0.35)',
                      minWidth: 160,
                      userSelect: 'none',
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                  >
                    <div
                      style={{
                        fontSize: 10,
                        color: 'var(--color-text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        marginBottom: 8,
                      }}
                    >
                      Boundary Shape
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {BOUNDARY_SHAPES.map((s) => (
                        <button
                          key={s.key}
                          title={s.label}
                          onClick={() => updateBoundaryShape(selectedBoundaryId, s.key)}
                          style={{
                            width: 40,
                            height: 34,
                            borderRadius: 6,
                            border:
                              (selBoundary.shape || 'rectangle') === s.key
                                ? `2px solid ${selRender.stroke}`
                                : '1px solid var(--color-border)',
                            background:
                              (selBoundary.shape || 'rectangle') === s.key
                                ? 'var(--color-glow)'
                                : 'transparent',
                            color: 'var(--color-text)',
                            fontSize: 18,
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            transition: 'all 0.1s',
                          }}
                        >
                          {s.icon}
                        </button>
                      ))}
                    </div>
                    <div
                      style={{
                        fontSize: 10,
                        color: 'var(--color-text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        marginTop: 10,
                        marginBottom: 6,
                      }}
                    >
                      Color
                    </div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                      {BOUNDARY_PRESETS.map((preset) => (
                        <button
                          key={preset.key}
                          title={preset.label}
                          onClick={() => updateBoundaryColor(selectedBoundaryId, preset.key)}
                          style={{
                            width: 20,
                            height: 20,
                            borderRadius: '50%',
                            border:
                              (selBoundary.color || DEFAULT_BOUNDARY_COLOR) === preset.key
                                ? '2px solid var(--color-text)'
                                : '2px solid transparent',
                            background: preset.stroke,
                            cursor: 'pointer',
                            transition: 'transform 0.1s',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.transform = 'scale(1.15)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.transform = 'scale(1)';
                          }}
                        />
                      ))}
                    </div>
                  </div>
                );
              })()}

            {mapLabels.length > 0 && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 14, pointerEvents: 'none' }}>
                {mapLabels.map((label) => {
                  const preset = resolveBoundaryPreset(label.color);
                  const fillBg = boundaryFillString(preset, 0.15);
                  return (
                    <div
                      key={label.id}
                      className="map-pill-label"
                      style={{
                        position: 'absolute',
                        left: label.x,
                        top: label.y,
                        pointerEvents: 'auto',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        padding: '4px 10px',
                        borderRadius: 999,
                        border: `1.5px solid ${preset.stroke}`,
                        background: fillBg,
                        cursor: 'grab',
                        userSelect: 'none',
                      }}
                      onPointerDown={(event) => startMapLabelDrag(event, label.id)}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setMapLabelMenuOpenId((prev) => (prev === label.id ? null : label.id));
                      }}
                    >
                      <input
                        type="text"
                        value={label.text}
                        onChange={(event) => updateMapLabel(label.id, { text: event.target.value })}
                        onPointerDown={(event) => event.stopPropagation()}
                        placeholder="Label"
                        style={{
                          background: 'transparent',
                          border: 'none',
                          outline: 'none',
                          color: 'var(--color-text)',
                          fontSize: 12,
                          fontWeight: 600,
                          width: Math.max(40, label.text.length * 7 + 12),
                          minWidth: 40,
                          padding: 0,
                        }}
                      />
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          removeMapLabel(label.id);
                        }}
                        onPointerDown={(event) => event.stopPropagation()}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: preset.stroke,
                          cursor: 'pointer',
                          padding: '0 2px',
                          fontSize: 14,
                          lineHeight: 1,
                          fontWeight: 700,
                          opacity: 0.7,
                        }}
                        aria-label="Delete label"
                      >
                        &times;
                      </button>
                    </div>
                  );
                })}

                {mapLabelMenuOpenId && openMapLabelMenuPosition && (
                  <div
                    ref={labelMenuRef}
                    style={{
                      position: 'absolute',
                      left: openMapLabelMenuPosition.left,
                      top: openMapLabelMenuPosition.top,
                      pointerEvents: 'auto',
                      background: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 8,
                      padding: 8,
                      boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
                      zIndex: 50,
                    }}
                    onPointerDown={(event) => event.stopPropagation()}
                  >
                    <div
                      style={{
                        fontSize: 9,
                        color: 'var(--color-text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em',
                        marginBottom: 6,
                      }}
                    >
                      Label Color
                    </div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                      {BOUNDARY_PRESETS.map((preset) => {
                        const active =
                          mapLabels.find((entry) => entry.id === mapLabelMenuOpenId)?.color ===
                          preset.key;
                        return (
                          <button
                            key={preset.key}
                            title={preset.label}
                            onClick={() => {
                              updateMapLabel(mapLabelMenuOpenId, { color: preset.key });
                              setMapLabelMenuOpenId(null);
                            }}
                            style={{
                              width: 20,
                              height: 20,
                              borderRadius: '50%',
                              border: active
                                ? '2px solid var(--color-text)'
                                : '2px solid transparent',
                              background: preset.stroke,
                              cursor: 'pointer',
                              transition: 'transform 0.1s',
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.transform = 'scale(1.15)';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.transform = 'scale(1)';
                            }}
                          />
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {boundaryDrawMode && (
              <div
                style={{
                  position: 'absolute',
                  top: 10,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  zIndex: 20,
                  pointerEvents: 'none',
                }}
              >
                <div
                  style={{
                    padding: '5px 10px',
                    borderRadius: 999,
                    border: '1px solid var(--color-primary)',
                    background: 'rgba(0,0,0,0.45)',
                    color: 'var(--color-text)',
                    fontSize: 12,
                  }}
                >
                  Drag on the canvas to draw a boundary around nodes
                </div>
              </div>
            )}

            {boundaryDraft &&
              (() => {
                const left = Math.min(boundaryDraft.startClient.x, boundaryDraft.endClient.x);
                const top = Math.min(boundaryDraft.startClient.y, boundaryDraft.endClient.y);
                const width = Math.abs(boundaryDraft.endClient.x - boundaryDraft.startClient.x);
                const height = Math.abs(boundaryDraft.endClient.y - boundaryDraft.startClient.y);
                return (
                  <div
                    style={{
                      position: 'fixed',
                      left,
                      top,
                      width,
                      height,
                      border: '1px dashed rgba(95, 205, 255, 0.95)',
                      background: 'rgba(70, 170, 220, 0.12)',
                      zIndex: 25,
                      pointerEvents: 'none',
                    }}
                  />
                );
              })()}

            {lineDrawMode && !lineDrawDraft && (
              <div
                style={{
                  position: 'absolute',
                  top: 10,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  zIndex: 20,
                  pointerEvents: 'none',
                }}
              >
                <div
                  style={{
                    padding: '5px 10px',
                    borderRadius: 999,
                    border: `1px solid ${CONNECTION_STYLES[lineDrawMode]?.stroke || 'var(--color-primary)'}`,
                    background: 'rgba(0,0,0,0.45)',
                    color: 'var(--color-text)',
                    fontSize: 12,
                  }}
                >
                  Drag on the canvas to draw a {lineDrawMode} line
                </div>
              </div>
            )}

            {lineDrawDraft &&
              (() => {
                const cs = CONNECTION_STYLES[lineDrawMode] || CONNECTION_STYLES.ethernet;
                return (
                  <svg
                    style={{
                      position: 'fixed',
                      inset: 0,
                      width: '100vw',
                      height: '100vh',
                      zIndex: 25,
                      pointerEvents: 'none',
                    }}
                  >
                    <line
                      x1={lineDrawDraft.startClient.x}
                      y1={lineDrawDraft.startClient.y}
                      x2={lineDrawDraft.endClient.x}
                      y2={lineDrawDraft.endClient.y}
                      stroke={cs.stroke}
                      strokeWidth={cs.strokeWidth + 1}
                      strokeDasharray={cs.strokeDasharray || 'none'}
                      strokeLinecap="round"
                      opacity={0.85}
                    />
                  </svg>
                );
              })()}

            {useSigma ? (
              <React.Suspense fallback={null}>
                <SigmaMap envFilter={envFilter} includeTypes={includeTypes} />
              </React.Suspense>
            ) : (
              <ReactFlow
                onlyRenderVisibleElements={true}
                className={boundaryDrawMode || lineDrawMode ? 'map-draw-mode' : ''}
                style={{
                  zIndex: 5,
                  cursor: boundaryDrawMode || lineDrawMode ? 'crosshair' : 'default',
                }}
                nodeTypes={NODE_TYPES}
                edgeTypes={EDGE_TYPES}
                nodes={nodes}
                edges={edges}
                onNodesChange={(changes) => {
                  onNodesChange(changes);
                  if (changes.some((c) => c.type === 'position' && c.dragging))
                    dirtyRef.current = true;
                }}
                onEdgesChange={onEdgesChange}
                nodeExtent={[
                  [-4000, -4000],
                  [4000, 4000],
                ]}
                translateExtent={[
                  [-4000, -4000],
                  [4000, 4000],
                ]}
                onNodeDragStop={handleNodeDragStop}
                onNodeMouseEnter={handleNodeMouseEnter}
                onNodeMouseLeave={handleNodeMouseLeave}
                onNodeClick={handleNodeClick}
                onNodeContextMenu={handleNodeContextMenu}
                onPaneContextMenu={handlePaneContextMenu}
                onEdgeContextMenu={handleEdgeContextMenu}
                onConnect={handleConnect}
                onEdgeUpdate={handleEdgeUpdate}
                onMoveEnd={(_, vp) => localStorage.setItem('cb_map_viewport', JSON.stringify(vp))}
                onPaneMouseMove={handlePanePointerMove}
                connectionLineType="smoothstep"
                connectionRadius={14}
                defaultEdgeOptions={{ style: { strokeWidth: 3, stroke: '#888' } }}
                onPaneClick={() => {
                  setEdgeMenu(null);
                  setPendingConnection(null);
                  handlePaneClick();
                }}
                fitView
                minZoom={0.1}
                maxZoom={2.5}
                panOnDrag={!boundaryDrawMode && !lineDrawMode}
                panOnScroll={!boundaryDrawMode && !lineDrawMode}
                zoomOnScroll={!boundaryDrawMode && !lineDrawMode}
                zoomOnPinch={!boundaryDrawMode && !lineDrawMode}
                zoomOnDoubleClick={!boundaryDrawMode && !lineDrawMode}
                preventScrolling /* keep page from scrolling when pointer is over map */
                deleteKeyCode={null}
              >
                {/* Loading overlay */}
                {loading && nodes.length === 0 && (
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: 'var(--color-bg)',
                      zIndex: 100,
                    }}
                  >
                    <div
                      className="login-spin"
                      style={{
                        width: 48,
                        height: 48,
                        border: '4px solid var(--color-border)',
                        borderTopColor: 'var(--color-primary)',
                        borderRadius: '50%',
                      }}
                    />
                    <p style={{ marginTop: 16, color: 'var(--color-text-muted)', fontSize: 14 }}>
                      Loading topology…
                    </p>
                  </div>
                )}

                {/* Legend */}
                <Panel position="top-left" style={{ zIndex: 35 }}>
                  {legendOpen ? (
                    <div
                      style={{
                        background: 'var(--color-surface)',
                        padding: 12,
                        borderRadius: 8,
                        fontSize: 11,
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                        minWidth: 238,
                        boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                        position: 'relative',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          marginBottom: 8,
                        }}
                      >
                        <div
                          style={{
                            fontWeight: 600,
                            color: 'var(--color-text-muted)',
                            fontSize: 10,
                            textTransform: 'uppercase',
                            letterSpacing: '0.05em',
                          }}
                        >
                          Legend
                        </div>
                        <button
                          onClick={() => setLegendOpen(false)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--color-text-muted)',
                            cursor: 'pointer',
                            padding: 2,
                            display: 'flex',
                          }}
                        >
                          <X size={14} />
                        </button>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                        <div>
                          <div
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              letterSpacing: '0.05em',
                              textTransform: 'uppercase',
                              color: 'var(--color-text-muted)',
                              marginBottom: 6,
                            }}
                          >
                            Connection Types
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {CONNECTION_TYPE_LEGEND.map((entry) => (
                              <div
                                key={entry.key}
                                style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                              >
                                <span
                                  style={{
                                    width: 10,
                                    height: 10,
                                    borderRadius: '50%',
                                    background: entry.color,
                                    boxShadow: `0 0 8px ${entry.color}88`,
                                  }}
                                />
                                <span>{entry.label}</span>
                              </div>
                            ))}
                          </div>
                        </div>

                        <div>
                          <div
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              letterSpacing: '0.05em',
                              textTransform: 'uppercase',
                              color: 'var(--color-text-muted)',
                              marginBottom: 6,
                            }}
                          >
                            Node Types
                          </div>
                          <div
                            style={{
                              display: 'flex',
                              flexDirection: 'column',
                              gap: 6,
                              marginBottom: 10,
                            }}
                          >
                            {Object.entries(NODE_STYLES).map(([type, style]) => {
                              const isDockerType =
                                type === 'docker_network' || type === 'docker_container';
                              const isActive = isDockerType
                                ? includeTypes.docker
                                : includeTypes[type];
                              return (
                                <div
                                  key={type}
                                  style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                                >
                                  <div
                                    style={{
                                      width: 10,
                                      height: 10,
                                      background: style.background,
                                      borderRadius: 2,
                                      border: `1px solid ${style.borderColor}`,
                                    }}
                                  />
                                  <span
                                    style={{
                                      color: isActive
                                        ? 'var(--color-text)'
                                        : 'var(--color-text-muted)',
                                    }}
                                  >
                                    {NODE_TYPE_LABELS[type] || type}
                                  </span>
                                </div>
                              );
                            })}
                          </div>

                          <div
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              letterSpacing: '0.05em',
                              textTransform: 'uppercase',
                              color: 'var(--color-text-muted)',
                              marginBottom: 6,
                            }}
                          >
                            Status
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {STATUS_LEGEND.map((entry) => (
                              <div
                                key={entry.key}
                                style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                              >
                                <span
                                  style={{
                                    width: 9,
                                    height: 9,
                                    borderRadius: '50%',
                                    background: entry.color,
                                    boxShadow: `0 0 8px ${entry.color}88`,
                                  }}
                                />
                                <span>{entry.label}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setLegendOpen(true)}
                      style={{
                        background: 'var(--color-surface)',
                        padding: '6px 12px',
                        borderRadius: 20,
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
                      }}
                    >
                      <span>Legend</span>
                      <span style={{ fontSize: 10 }}>▼</span>
                    </button>
                  )}
                </Panel>
                <Controls style={{ zIndex: 35 }} />
                <Background color={bgGridColor} gap={24} size={1} />
              </ReactFlow>
            )}

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
                onClose={handleContextMenuClose}
                onAction={handleContextAction}
                avoidRectRef={sidebarBoundsRef}
                avoidRectRef2={telemetrySidebarBoundsRef}
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

            {/* Create Node Modal */}
            <CreateNodeModal
              isOpen={createNodeModal.isOpen}
              position={createNodeModal.position}
              onClose={() => setCreateNodeModal({ isOpen: false, position: null })}
              onConfirm={handleCreateNode}
            />

            {iconPickerOpen && iconPickerNode && (
              <IconPickerModal
                currentSlug={iconPickerNode.data?.icon_slug ?? null}
                onSelect={handleIconPick}
                onClose={() => {
                  setIconPickerOpen(false);
                  setIconPickerNode(null);
                }}
              />
            )}

            {quickActionModal &&
              globalThis.document?.body &&
              createPortal(
                <div
                  className="modal-overlay"
                  style={{
                    position: 'fixed',
                    inset: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 9999,
                  }}
                >
                  <dialog
                    open
                    className="modal"
                    aria-labelledby="quick-action-title"
                    style={{ width: 420, margin: 0 }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 8,
                      }}
                    >
                      <h3 id="quick-action-title">
                        {quickActionModal.mode === 'alias' ? 'Set Alias' : 'Update Status'}
                      </h3>
                      <button
                        type="button"
                        className="btn"
                        aria-label="Close quick action dialog"
                        onClick={() => {
                          setQuickActionModal(null);
                          setQuickActionValue('');
                        }}
                        style={{
                          width: 28,
                          height: 28,
                          padding: 0,
                          borderRadius: 999,
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <X size={14} />
                      </button>
                    </div>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        handleSubmitQuickAction();
                      }}
                    >
                      <div style={{ marginTop: 12 }}>
                        <div
                          style={{
                            marginBottom: 8,
                            fontSize: 12,
                            color: 'var(--color-text-muted)',
                          }}
                        >
                          {quickActionModal.label}
                        </div>
                        {quickActionModal.mode === 'alias' ? (
                          <input
                            className="input"
                            aria-label="Alias value"
                            style={{
                              width: '100%',
                              background: 'var(--color-surface)',
                              color: 'var(--color-text)',
                              border: '1px solid var(--color-border)',
                              borderRadius: 'var(--radius)',
                              padding: '6px 10px',
                            }}
                            autoFocus
                            value={quickActionValue}
                            onChange={(e) => setQuickActionValue(e.target.value)}
                            placeholder="Enter alias"
                          />
                        ) : (
                          <select
                            className="filter-select"
                            aria-label="Status value"
                            autoFocus
                            value={quickActionValue}
                            onChange={(e) => setQuickActionValue(e.target.value)}
                            style={{
                              width: '100%',
                              background: 'var(--color-surface)',
                              color: 'var(--color-text)',
                              border: '1px solid var(--color-border)',
                              borderRadius: 'var(--radius)',
                              padding: '6px 10px',
                            }}
                          >
                            {(quickActionModal.allowed || []).map((value) => (
                              <option key={value} value={value}>
                                {STATUS_OPTION_LABEL[value] || value}
                              </option>
                            ))}
                          </select>
                        )}
                      </div>

                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'flex-end',
                          gap: 8,
                          marginTop: 18,
                        }}
                      >
                        <button
                          type="button"
                          className="btn"
                          onClick={() => {
                            setQuickActionModal(null);
                            setQuickActionValue('');
                          }}
                          disabled={quickActionSaving}
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="btn btn-primary"
                          disabled={quickActionSaving}
                        >
                          {quickActionSaving ? 'Saving…' : 'Save'}
                        </button>
                      </div>
                    </form>
                  </dialog>
                </div>,
                globalThis.document.body
              )}

            <BulkQuickCreateModal
              open={quickCreateModal.open}
              modal={quickCreateModal}
              rows={quickCreateRows}
              rowErrors={quickCreateRowErrors}
              saving={quickCreateSaving}
              onSubmit={handleBulkQuickCreateSubmit}
              onUpdateRow={updateQuickCreateRow}
              onAddRow={addQuickCreateRow}
              onRemoveRow={removeQuickCreateRow}
              onClose={() => {
                setQuickCreateModal({
                  open: false,
                  mode: null,
                  title: '',
                  sourceLabel: '',
                  initialValues: {},
                });
                setQuickCreateRows([]);
                setQuickCreateRowErrors({});
              }}
            />

            <FormModal
              open={roleModal.open}
              title={roleModal.isEdit ? 'Edit Role' : 'Designate Role'}
              fields={[
                {
                  name: 'role',
                  label: `Role for ${roleModal.nodeLabel}`,
                  type: 'select',
                  required: true,
                  options: HARDWARE_ROLES,
                },
              ]}
              initialValues={{ role: roleModal.currentRole || '' }}
              onSubmit={handleSubmitRoleModal}
              onValidate={(values) => {
                const errors = {};
                if (!values.role) errors.role = 'Role is required.';
                return errors;
              }}
              onClose={() =>
                setRoleModal({
                  open: false,
                  nodeRefId: null,
                  nodeLabel: '',
                  currentRole: '',
                  isEdit: false,
                })
              }
              entityType="hardware"
              entityId={roleModal.nodeRefId}
            />

            <ConfirmDialog
              open={confirmState.open}
              message={confirmState.message}
              onConfirm={confirmState.onConfirm || (() => {})}
              onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
            />

            <DeleteConflictModal
              modal={deleteConflictModal}
              onCancel={() =>
                setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }))
              }
              onForceRemove={forceRemoveDeleteConflicts}
            />

            {/* Edge anchor context menu */}
            {edgeMenu &&
              (() => {
                const menuW = 220;
                const menuH = edgeMenu.isUpdatable ? 420 : 220;
                const ex = Math.min(edgeMenu.x, window.innerWidth - menuW - 8);
                const ey = Math.min(edgeMenu.y, window.innerHeight - menuH - 8);
                const currentOverride = edgeOverrides[edgeMenu.edgeId] || {};
                const SIDES = ['auto', 'top', 'right', 'bottom', 'left'];
                const stopAll = (e) => {
                  e.stopPropagation();
                  // Do not preventDefault so button clicks still work; we stop propagation so the pane never receives the event.
                };
                return (
                  <div
                    role="menu"
                    tabIndex={-1}
                    style={{
                      position: 'fixed',
                      left: ex,
                      top: ey,
                      zIndex: 1001,
                      background: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 8,
                      minWidth: menuW,
                      boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                      overflow: 'hidden',
                      userSelect: 'none',
                    }}
                    onMouseDown={stopAll}
                    onMouseUp={stopAll}
                    onClick={stopAll}
                    onPointerDown={stopAll}
                    onPointerUp={stopAll}
                  >
                    {/* ── Connection Type ────────────────────────────── */}
                    {edgeMenu.isUpdatable && (
                      <>
                        <div
                          style={{
                            padding: '7px 12px 5px',
                            borderBottom: '1px solid var(--color-border)',
                            fontSize: 10,
                            color: 'var(--color-text-muted)',
                            textTransform: 'uppercase',
                            letterSpacing: '0.08em',
                          }}
                        >
                          Connection Type
                        </div>
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(3, 1fr)',
                            gap: 4,
                            padding: '6px 10px 8px',
                          }}
                        >
                          {CONNECTION_TYPE_OPTIONS.map((t) => {
                            const style = CONNECTION_STYLES[t] || {};
                            const isActive =
                              (normalizeConnectionType(edgeMenu.connectionType) || 'ethernet') ===
                              t;
                            return (
                              <button
                                key={t}
                                type="button"
                                onPointerDown={(e) => e.stopPropagation()}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  e.preventDefault();
                                  handleEdgeConnectionTypeChange(edgeMenu.edgeId, t);
                                }}
                                title={t}
                                style={{
                                  padding: '3px 4px',
                                  borderRadius: 4,
                                  border: isActive
                                    ? `2px solid ${style.stroke || '#888'}`
                                    : '1px solid var(--color-border)',
                                  background: isActive ? `${style.stroke}22` : 'transparent',
                                  color: style.stroke || 'var(--color-text)',
                                  fontSize: 10,
                                  cursor: 'pointer',
                                  textAlign: 'center',
                                  fontWeight: isActive ? 700 : 400,
                                  whiteSpace: 'nowrap',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  transition: 'all 0.12s',
                                }}
                              >
                                {t}
                              </button>
                            );
                          })}
                        </div>
                        <div
                          style={{
                            height: 1,
                            background: 'var(--color-border)',
                            margin: '0 0 2px',
                          }}
                        />
                      </>
                    )}
                    <div
                      style={{
                        padding: '7px 12px 5px',
                        borderBottom: '1px solid var(--color-border)',
                        fontSize: 10,
                        color: 'var(--color-text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                      }}
                    >
                      Edge Anchors
                    </div>
                    <div
                      style={{
                        padding: '4px 12px 2px',
                        fontSize: 11,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      Source side
                    </div>
                    <div
                      style={{ display: 'flex', gap: 4, padding: '2px 12px 6px', flexWrap: 'wrap' }}
                    >
                      {SIDES.map((s) => (
                        <button
                          key={s}
                          type="button"
                          onPointerDown={(e) => e.stopPropagation()}
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            handleEdgeAnchorChange(edgeMenu.edgeId, 'source', s);
                          }}
                          style={{
                            padding: '2px 8px',
                            borderRadius: 4,
                            border: '1px solid var(--color-border)',
                            fontSize: 11,
                            cursor: 'pointer',
                            background:
                              currentOverride.source_side === s ||
                              (s === 'auto' && !currentOverride.source_side)
                                ? 'var(--color-primary)'
                                : 'transparent',
                            color:
                              currentOverride.source_side === s ||
                              (s === 'auto' && !currentOverride.source_side)
                                ? '#000'
                                : 'var(--color-text)',
                          }}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                    <div
                      style={{
                        padding: '4px 12px 2px',
                        fontSize: 11,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      Target side
                    </div>
                    <div
                      style={{ display: 'flex', gap: 4, padding: '2px 12px 6px', flexWrap: 'wrap' }}
                    >
                      {SIDES.map((s) => (
                        <button
                          key={s}
                          type="button"
                          onPointerDown={(e) => e.stopPropagation()}
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            handleEdgeAnchorChange(edgeMenu.edgeId, 'target', s);
                          }}
                          style={{
                            padding: '2px 8px',
                            borderRadius: 4,
                            border: '1px solid var(--color-border)',
                            fontSize: 11,
                            cursor: 'pointer',
                            background:
                              currentOverride.target_side === s ||
                              (s === 'auto' && !currentOverride.target_side)
                                ? 'var(--color-primary)'
                                : 'transparent',
                            color:
                              currentOverride.target_side === s ||
                              (s === 'auto' && !currentOverride.target_side)
                                ? '#000'
                                : 'var(--color-text)',
                          }}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                    <div
                      style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }}
                    />
                    <button
                      type="button"
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        handleClearBend(edgeMenu.edgeId);
                      }}
                      style={{
                        width: '100%',
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--color-text-muted)',
                        padding: '7px 12px',
                        fontSize: 11,
                        textAlign: 'left',
                        cursor: 'pointer',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--color-glow)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      Clear bend point
                    </button>
                    <button
                      onClick={() => setEdgeMenu(null)}
                      style={{
                        width: '100%',
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--color-text-muted)',
                        padding: '7px 12px',
                        fontSize: 11,
                        textAlign: 'left',
                        cursor: 'pointer',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--color-glow)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      Close
                    </button>
                  </div>
                );
              })()}

            <Sidebar
              node={selectedNode}
              anchor={selectedNodeAnchor}
              relationships={selectedNodeRelationships}
              sysinfo={selectedNodeSysinfo}
              status={selectedNodeStatus}
              onClose={() => setSelectedNode(null)}
              onUplinkChange={handleUplinkChange}
              onOpenInHud={(node) => {
                navigate(NODE_TYPE_ROUTES[node?.originalType] || '/');
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
  return (
    <ReactFlowProvider>
      <MapInternal />
    </ReactFlowProvider>
  );
}
