import { useCallback, useRef } from 'react';
import { graphApi } from '../../../api/client';
import { normalizeMapLabel, normalizeBoundaryName } from '../model/mapConstants';
import { applyEdgeSides, parseLayoutData } from '../../../utils/mapGeometryUtils';
import { groupDockerIntoBoundaries, proxmoxClusterDetected } from '../../../utils/mapDataUtils';
import { buildIncludeCSV } from '../../../utils/mapHelpers';
import { adaptTopology } from '../model/graphAdapter';
import { getDagreLayout, getDagreViewportOptions } from '../../../utils/layouts';
import { recalculateAllEdges } from '../../../utils/bandwidthCalculator';
import { groupNodesIntoCloud } from '../../../utils/cloudView';
import { VIEWPORT_FIT_DEFAULTS } from '../../../utils/viewportFit';
import {} from '../../../lib/constants';

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
}) {
  // Monotonic id for the newest in-flight topology request; see fetchData.
  const requestGenerationRef = useRef(0);

  // `fitView` and `setViewport` come from `useReactFlow()`, whose callbacks
  // change identity when the ReactFlow instance unmounts — which is exactly
  // what switching to the Sigma renderer does. As dependencies they made
  // fetchData's identity change on that toggle, and MapPage's
  // `useEffect(() => fetchData(), [fetchData])` then issued a second topology
  // request just for a renderer switch. Reading them through latest-value refs
  // keeps the current functions without the reactivity: they are how this hook
  // moves the viewport, never a reason to reload the graph.
  const fitViewRef = useRef(fitView);
  fitViewRef.current = fitView;
  const setViewportRef = useRef(setViewport);
  setViewportRef.current = setViewport;

  // Cloud View is a transformation of the loaded document, not an input to the
  // query. Reading it through a latest-value ref keeps fetchData's identity
  // stable across a toggle, so toggling no longer re-issues a topology request
  // that races the in-place transform MapPage already applies.
  const cloudViewEnabledRef = useRef(cloudViewEnabled);
  cloudViewEnabledRef.current = cloudViewEnabled;

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
            setViewportRef.current(JSON.parse(saved));
            hasRestoredViewport.current = true;
          } catch (err) {
            console.error('Failed to parse saved viewport:', err);
            fitViewRef.current({
              ...VIEWPORT_FIT_DEFAULTS,
              padding: isMobile ? 0.35 : VIEWPORT_FIT_DEFAULTS.padding,
            });
          }
        } else {
          fitViewRef.current({
            ...VIEWPORT_FIT_DEFAULTS,
            padding: isMobile ? 0.35 : VIEWPORT_FIT_DEFAULTS.padding,
          });
          if (nodesForProxmox && proxmoxClusterDetected(nodesForProxmox)) {
            const hypervisorNodes = nodesForProxmox.filter((n) => n.data?.role === 'hypervisor');
            if (hypervisorNodes.length > 0) {
              setTimeout(() => {
                if (unmountedRef?.current) return;
                fitViewRef.current({
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
    getLayoutName,
    isMobile,
    showLabels,
    settings?.graph_uplink_overrides,
    setEdges,
    setNodes,
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

  return { fetchData };
}
