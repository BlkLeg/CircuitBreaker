import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

const mockApplyEdgeSides = vi.fn((draggedNodes, edges) => edges);
let latestReactFlowProps = null;

// Mock ReactFlow before importing MapPage
vi.mock('reactflow', () => {
  const ReactFlow = React.forwardRef((props, ref) => {
    latestReactFlowProps = props;
    return React.createElement('div', { 'data-testid': 'react-flow', ref }, props.children);
  });
  ReactFlow.displayName = 'ReactFlow';
  return {
    default: ReactFlow,
    Background: () => React.createElement('div', { 'data-testid': 'rf-background' }),
    Controls: () => React.createElement('div', { 'data-testid': 'rf-controls' }),
    Panel: ({ children }) => React.createElement('div', { 'data-testid': 'rf-panel' }, children),
    useNodesState: (initial) => [initial || [], vi.fn(), vi.fn()],
    useEdgesState: (initial) => {
      let current = initial || [];
      const setEdges = vi.fn((updater) => {
        current = typeof updater === 'function' ? updater(current) : updater;
        return current;
      });
      return [current, setEdges, vi.fn()];
    },
    ReactFlowProvider: ({ children }) => React.createElement('div', null, children),
    useReactFlow: () => ({
      fitView: vi.fn(),
      setViewport: vi.fn(),
      getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
      getNodes: () => [],
      getEdges: () => [],
      setNodes: vi.fn(),
      setEdges: vi.fn(),
      project: vi.fn((pos) => pos),
      screenToFlowPosition: vi.fn((pos) => pos),
    }),
    useViewport: () => ({ x: 0, y: 0, zoom: 1 }),
    MarkerType: { Arrow: 'arrow', ArrowClosed: 'arrowclosed' },
    Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
    addEdge: vi.fn(),
    applyNodeChanges: vi.fn((changes, nodes) => nodes),
    applyEdgeChanges: vi.fn((changes, edges) => edges),
  };
});

vi.mock('reactflow/dist/style.css', () => ({}));

// Mock api client
vi.mock('../api/client', () => {
  const mockClient = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return {
    default: mockClient,
    graphApi: {
      get: vi.fn().mockResolvedValue({ data: { nodes: [], edges: [] } }),
      updatePositions: vi.fn().mockResolvedValue({}),
    },
    environmentsApi: {
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
    settingsApi: {
      get: vi.fn().mockResolvedValue({ data: {} }),
      update: vi.fn(),
    },
    proxmoxApi: {
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
    hardwareApi: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
  };
});

vi.mock('../api/monitor.js', () => ({
  createMonitor: vi.fn(),
  updateMonitor: vi.fn(),
  runImmediateCheck: vi.fn(),
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useLocation: () => ({ pathname: '/map', search: '' }),
  Link: ({ children, ...props }) => React.createElement('a', props, children),
}));

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {
      graph_default_layout: 'dagre',
      map_title: 'Topology',
      show_external_nodes_on_map: true,
      vendor_icon_mode: 'custom_files',
      map_default_filters: '{}',
      show_experimental_features: false,
    },
    reloadSettings: vi.fn(),
  }),
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: { role: 'admin', is_admin: true },
  }),
}));

vi.mock('../context/TimezoneContext', () => ({
  useTimezone: () => ({
    timezone: 'UTC',
    setTimezone: vi.fn(),
  }),
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    info: vi.fn(),
  }),
}));

vi.mock('../hooks/useIsMobile', () => ({
  useIsMobile: () => false,
}));

vi.mock('../hooks/useCapabilities.js', () => ({
  useCapabilities: () => ({ caps: {} }),
}));

// Mock heavy sub-components
vi.mock('../components/common/IconPickerModal', () => ({
  default: () => null,
  IconImg: () => null,
}));
vi.mock('../components/common/ConfirmDialog', () => ({
  default: () => null,
}));
vi.mock('../components/common/FormModal', () => ({
  default: () => null,
}));
vi.mock('../components/map/ContextMenu', () => ({
  default: () => null,
}));
vi.mock('../components/map/TelemetrySidebar', () => ({
  default: () => null,
}));
vi.mock('../components/map/BoundaryContextMenu', () => ({
  default: () => null,
}));
vi.mock('../components/map/VisualLineContextMenu', () => ({
  default: () => null,
}));
vi.mock('../components/map/DrawToolsDropdown', () => ({
  default: () => null,
}));
vi.mock('../components/map/BulkQuickCreateModal', () => ({
  default: () => null,
}));
vi.mock('../components/map/CreateNodeModal', () => ({
  default: () => null,
}));
vi.mock('../components/map/CustomNode', () => ({
  default: () => React.createElement('div', null, 'CustomNode'),
}));
vi.mock('../components/map/CustomEdge', () => ({
  default: () => React.createElement('div', null, 'CustomEdge'),
}));
vi.mock('../components/map/ConnectionTypePicker', () => ({
  default: () => null,
}));
vi.mock('../components/map/DeleteConflictModal', () => ({
  default: () => null,
}));
vi.mock('../components/map/WifiOverlay', () => ({
  default: () => null,
}));
vi.mock('../components/Map/Sidebar', () => ({
  default: () => null,
}));

vi.mock('../components/MapToolbar', () => ({
  default: () => React.createElement('div', { 'data-testid': 'map-toolbar' }, 'MapToolbar'),
}));

vi.mock('../components/map/connectionTypes', () => ({
  CONNECTION_TYPE_OPTIONS: [],
  normalizeConnectionType: vi.fn((t) => t),
}));

vi.mock('../config/mapTheme', () => ({
  CONNECTION_STYLES: {},
}));

vi.mock('../config/hardwareRoles', () => ({
  HARDWARE_ROLES: [],
}));

vi.mock('../utils/bandwidthCalculator', () => ({
  recalculateAllEdges: vi.fn((edges) => edges),
}));

vi.mock('../components/map/linkMutations', () => ({
  createLinkByNodeIds: vi.fn(),
  inferEdgeNodeIdsFromMeta: vi.fn(),
  unlinkByEdge: vi.fn(),
  isUpdatableEdgeId: vi.fn(),
}));

vi.mock('../components/map/mapContexts', () => ({
  MapEdgeCallbacksContext: React.createContext({}),
  MapViewOptionsContext: React.createContext({}),
}));

vi.mock('../utils/layouts', () => ({
  getDagreLayout: vi.fn(() => []),
  getDagreViewportOptions: vi.fn(() => ({})),
  getForceLayout: vi.fn(() => []),
  getTreeLayout: vi.fn(() => []),
  getHierarchicalNetworkLayout: vi.fn(() => []),
  getRadialLayout: vi.fn(() => []),
  getElkLayeredLayout: vi.fn(async () => []),
  getCircularClusterLayout: vi.fn(() => []),
  getGridRackLayout: vi.fn(() => []),
  getConcentricLayout: vi.fn(() => []),
  getCortexLayout: vi.fn(() => []),
  getMindmapLayout: vi.fn(() => []),
  scaleAndCenterToViewport: vi.fn((nodes) => nodes),
}));

vi.mock('../utils/cloudView', () => ({
  groupNodesIntoCloud: vi.fn(),
  restoreFromCloudView: vi.fn(),
}));

vi.mock('../utils/mapGeometryUtils', async () => {
  const actual = await vi.importActual('../utils/mapGeometryUtils');
  return {
    ...actual,
    applyEdgeSides: (...args) => mockApplyEdgeSides(...args),
  };
});

vi.mock('../utils/viewportFit', () => ({
  viewportFit: vi.fn(),
}));

vi.mock('lucide-react', () => ({
  X: () => React.createElement('span', null, 'X'),
}));

// Need to mock the hooks that MapPage uses
vi.mock('../hooks/useMapDataLoad', () => ({
  useMapDataLoad: () => ({
    fetchData: vi.fn(),
    autoPlaceNew: vi.fn(),
    updateNodePos: vi.fn(),
  }),
}));

vi.mock('../hooks/useMapMutations', () => ({
  useMapMutations: () => ({
    saveLayoutSnapshot: vi.fn(),
    saveLayout: vi.fn(),
    handleDeleteNodeAction: vi.fn(),
    forceRemoveDeleteConflicts: vi.fn(),
  }),
}));

vi.mock('../hooks/useMapRealTimeUpdates', () => ({
  useMapRealTimeUpdates: () => ({
    pendingDiscoveries: 0,
  }),
}));

vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => ({
    data: new Map(),
    connected: false,
  }),
}));

// Polyfill ResizeObserver for jsdom
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    constructor(cb) {
      this._cb = cb;
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Import MapPage after all mocks
import MapPage from '../pages/MapPage.jsx';

describe('MapPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApplyEdgeSides.mockClear();
    latestReactFlowProps = null;
  });

  it('renders map page container', async () => {
    render(<MapPage />);

    await waitFor(() => {
      // MapPage wraps in ReactFlowProvider which renders our mock
      expect(screen.getByTestId('react-flow')).toBeInTheDocument();
    });
  });

  it('renders toolbar', async () => {
    render(<MapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('map-toolbar')).toBeInTheDocument();
    });
  });

  it('does not recompute edge sides on click or zero-delta drag stop', async () => {
    render(<MapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('react-flow')).toBeInTheDocument();
      expect(latestReactFlowProps).toBeTruthy();
    });

    const stationaryNode = {
      id: 'hw-1',
      position: { x: 100, y: 200 },
      positionAbsolute: { x: 100, y: 200 },
    };

    act(() => {
      latestReactFlowProps.onNodeClick?.({}, stationaryNode);
      latestReactFlowProps.onNodeDragStart?.({}, stationaryNode, [stationaryNode]);
      latestReactFlowProps.onNodeDragStop?.({}, stationaryNode, [stationaryNode]);
    });

    expect(mockApplyEdgeSides).not.toHaveBeenCalled();
  });
});
