import { useCallback, useRef } from 'react';
import { graphApi } from '../api/client';
import { normalizeMapLabel, normalizeBoundaryName } from '../components/map/mapConstants';
import {
  applyEdgeSides,
  parseLayoutData,
  resolveNonOverlappingPosition,
} from '../utils/mapGeometryUtils';
import { groupDockerIntoBoundaries, proxmoxClusterDetected } from '../utils/mapDataUtils';
import { buildIncludeCSV } from '../utils/mapHelpers';
import { adaptTopology } from '../utils/graphAdapter';
import { getDagreLayout, getDagreViewportOptions } from '../utils/layouts';
import { recalculateAllEdges } from '../utils/bandwidthCalculator';
import { groupNodesIntoCloud } from '../utils/cloudView';
import { VIEWPORT_FIT_DEFAULTS } from '../utils/viewportFit';
import {} from '../lib/constants';

/**
 * Encapsulates the graph data-loading logic (fetchData, autoPlaceNew, drain
 * effect) extracted from MapInternal.  Accepts a single config object with all
 * the state setters / refs / values it needs.
 *
 * @returns {{ fetchData, autoPlaceNew, updateNodePos }}
 */
export function useMapDataLoad({
  mapId,
  // state setters
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
  // refs
  edgeOverridesRef,
  autoPlacedIdsRef,
  placingNodesRef,
  pendingPlacementCountRef,
  batchPlacedCountRef,
  saveLayoutRef,
  hasRestoredViewport,
  unmountedRef,
  containerRef,
  // ReactFlow callbacks
  fitView,
  setViewport,
  // values / callbacks
  cloudViewEnabled,
  isMobile,
  showLabels,
  settings,
  envFilter,
  includeTypes,
  getLayoutName,
  toast,
}) {
  // Monotonic id for the newest in-flight topology request; see fetchData.
  const requestGenerationRef = useRef(0);

  // Cloud View is a transformation of the loaded document, not an input to the
  // query. Reading it through a latest-value ref keeps fetchData's identity
  // stable across a toggle, so toggling no longer re-issues a topology request
  // that races the in-place transform MapPage already applies.
  const cloudViewEnabledRef = useRef(cloudViewEnabled);
  cloudViewEnabledRef.current = cloudViewEnabled;

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

  const fetchData = useCallback(async () => {
    // Request-generation guard. Changing map, environment, included types or
    // Cloud View re-issues this fetch, and the responses are not ordered: a
    // slower earlier request could otherwise resolve last and overwrite the
    // canvas with stale topology. Every await below is followed by a staleness
    // check, so only the newest in-flight request may touch state.
    const generation = requestGenerationRef.current + 1;
    requestGenerationRef.current = generation;
    const isStale = () => requestGenerationRef.current !== generation;

    setLoading(true);
    setError(null);
    try {
      const includeCSV = buildIncludeCSV(includeTypes);
      const res = await graphApi.topology({
        environment_id: envFilter || undefined,
        include: includeCSV,
        ...(mapId != null && { map_id: mapId }),
      });
      if (isStale()) return;

      const { nodes: rawNodesWithOverrides, edges: rawE } = adaptTopology(res.data, {
        showLabels,
        includeTypes,
        uplinkOverrides: settings?.graph_uplink_overrides ?? {},
      });

      let savedNodePositions = null;
      let savedEdgeOverrides = {};
      let savedBoundaries = [];
      let savedLabels = [];
      let savedVisualLines = [];
      let savedNodeShapes = {};
      let savedEdgeMode = null;
      let savedEdgeLabelVisible = null;
      let savedNodeSpacing = null;
      let savedGroupBy = null;
      try {
        const scopedLayoutName = getLayoutName();
        const layoutNames =
          scopedLayoutName === 'default' ? ['default'] : [scopedLayoutName, 'default'];

        for (const layoutName of layoutNames) {
          const layoutRes = await graphApi.getLayout(layoutName, mapId);
          if (!layoutRes.data.layout_data) continue;
          const parsed = parseLayoutData(layoutRes.data.layout_data);
          savedNodePositions = parsed.nodes;
          savedEdgeOverrides = parsed.edges || {};
          savedBoundaries = Array.isArray(parsed.boundaries) ? parsed.boundaries : [];
          savedLabels = Array.isArray(parsed.labels) ? parsed.labels : [];
          savedVisualLines = Array.isArray(parsed.visualLines) ? parsed.visualLines : [];
          savedNodeShapes = parsed.nodeShapes || {};
          savedEdgeMode = parsed.edgeMode;
          savedEdgeLabelVisible = parsed.edgeLabelVisible;
          savedNodeSpacing = parsed.nodeSpacing;
          savedGroupBy = parsed.groupBy;
          setLastSaved(layoutRes.data.updated_at);
          break;
        }
      } catch (err) {
        console.error('Layout parse/fetch failed:', err);
      }
      if (isStale()) return;

      setEdgeMode(savedEdgeMode || 'smoothstep');
      setEdgeLabelVisible(savedEdgeLabelVisible ?? true);
      setNodeSpacing(savedNodeSpacing || 1);
      setGroupBy(savedGroupBy || 'none');

      const normalizedSavedBoundaries = savedBoundaries
        .filter(
          (boundary) =>
            (Array.isArray(boundary?.memberIds) && boundary.memberIds.length >= 1) ||
            boundary?.flowRect
        )
        .map((boundary, index) => ({
          id: boundary.id || `boundary-${Date.now()}-${index}`,
          name: normalizeBoundaryName(boundary.name, index),
          memberIds: boundary.memberIds,
          flowRect: boundary.flowRect,
          color: boundary.color || null,
          fillOpacity: boundary.fillOpacity ?? null,
          shape: boundary.shape || 'rectangle',
          behindNodes: boundary.behindNodes ?? false,
        }));

      const dockerAutoBoundaries = groupDockerIntoBoundaries(
        rawNodesWithOverrides,
        rawE,
        normalizedSavedBoundaries
      );

      setBoundaries([...normalizedSavedBoundaries, ...dockerAutoBoundaries]);
      setMapLabels(savedLabels.map((label, index) => normalizeMapLabel(label, index)));
      setVisualLines(
        savedVisualLines
          .filter((vl) => vl?.startFlow && vl?.endFlow && vl?.lineType)
          .map((vl, index) => ({
            id: vl.id || `vline-${Date.now()}-${index}`,
            startFlow: { x: Number(vl.startFlow.x) || 0, y: Number(vl.startFlow.y) || 0 },
            endFlow: { x: Number(vl.endFlow.x) || 0, y: Number(vl.endFlow.y) || 0 },
            lineType: vl.lineType,
          }))
      );

      let nodesForProxmox = null;
      if (savedNodePositions) {
        const mergedNodes = rawNodesWithOverrides.map((n) => {
          const shapeData = savedNodeShapes[n.id]
            ? { ...n.data, nodeShape: savedNodeShapes[n.id] }
            : n.data;
          const nodeWithShape = { ...n, data: shapeData };
          if (savedNodePositions[n.id])
            return { ...nodeWithShape, position: savedNodePositions[n.id] };
          if (autoPlacedIdsRef.current.has(n.id)) return nodeWithShape;
          return { ...nodeWithShape, position: { x: 0, y: 0 }, _needsAutoPlace: true };
        });
        setEdgeOverrides(savedEdgeOverrides);
        edgeOverridesRef.current = savedEdgeOverrides;

        let initialNodes = mergedNodes;
        if (cloudViewEnabledRef.current) {
          initialNodes = groupNodesIntoCloud(initialNodes);
        }

        setNodes(initialNodes);
        const nextEdgesManual = applyEdgeSides(mergedNodes, rawE, savedEdgeOverrides);
        setEdges(recalculateAllEdges(initialNodes, nextEdgesManual));
        setLayoutEngine('manual');
      } else {
        const viewportWidth = containerRef?.current?.getBoundingClientRect?.()?.width;
        const layout = getDagreLayout(
          rawNodesWithOverrides,
          rawE,
          'TB',
          getDagreViewportOptions(viewportWidth)
        );
        let initialNodes = layout.nodes;
        if (cloudViewEnabledRef.current) {
          initialNodes = groupNodesIntoCloud(initialNodes);
        }
        setNodes(initialNodes);
        const nextEdgesAuto = applyEdgeSides(initialNodes, layout.edges, {});
        setEdges(recalculateAllEdges(initialNodes, nextEdgesAuto));
        setLayoutEngine(settings?.graph_default_layout || 'dagre');
        nodesForProxmox = initialNodes;
      }

      setTimeout(() => {
        if (unmountedRef?.current) return;
        const saved = localStorage.getItem('cb_map_viewport');
        if (saved && !hasRestoredViewport.current) {
          try {
            setViewport(JSON.parse(saved));
            hasRestoredViewport.current = true;
          } catch (err) {
            console.error('Failed to parse saved viewport:', err);
            fitView({
              ...VIEWPORT_FIT_DEFAULTS,
              padding: isMobile ? 0.35 : VIEWPORT_FIT_DEFAULTS.padding,
            });
          }
        } else {
          fitView({
            ...VIEWPORT_FIT_DEFAULTS,
            padding: isMobile ? 0.35 : VIEWPORT_FIT_DEFAULTS.padding,
          });
          if (nodesForProxmox && proxmoxClusterDetected(nodesForProxmox)) {
            const hypervisorNodes = nodesForProxmox.filter((n) => n.data?.role === 'hypervisor');
            if (hypervisorNodes.length > 0) {
              setTimeout(() => {
                if (unmountedRef?.current) return;
                fitView({
                  nodes: hypervisorNodes,
                  padding: 0.15,
                  duration: 1200,
                  minZoom: VIEWPORT_FIT_DEFAULTS.minZoom,
                  maxZoom: VIEWPORT_FIT_DEFAULTS.maxZoom,
                });
              }, 900);
            }
          }
        }
      }, 50);
    } catch (err) {
      if (!isStale()) setError(err.message || 'Failed to load topology');
    } finally {
      if (!isStale()) setLoading(false);
    }
  }, [
    mapId,
    containerRef,
    unmountedRef,
    envFilter,
    includeTypes,
    fitView,
    getLayoutName,
    isMobile,
    showLabels,
    settings?.graph_uplink_overrides,
    setEdges,
    setNodes,
    setViewport,
    settings?.graph_default_layout,
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
    edgeOverridesRef,
    autoPlacedIdsRef,
    hasRestoredViewport,
    setLayoutEngine,
  ]);

  return { fetchData, autoPlaceNew, updateNodePos };
}
