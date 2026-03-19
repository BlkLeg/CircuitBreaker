import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
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
import { groupNodesIntoCloud, restoreFromCloudView } from '../utils/cloudView';
import { viewportFit } from '../utils/viewportFit';
import { applyEdgeSides } from '../utils/mapGeometryUtils';
import { settingsApi } from '../api/client';

const RESIZE_LAYOUT_DEBOUNCE_MS = 200;
const RESIZE_LAYOUT_MIN_DELTA_PX = 2;

export function useMapLayout({
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
}) {
  const [layoutEngine, setLayoutEngine] = useState(() => settings?.graph_default_layout || 'dagre');
  const [edgeMode, setEdgeMode] = useState('smoothstep');
  const [edgeLabelVisible, setEdgeLabelVisible] = useState(true);
  const [nodeSpacing, setNodeSpacing] = useState(1);
  const [groupBy, setGroupBy] = useState('none');

  const layoutEngineRef = useRef(layoutEngine);
  const applyLayoutRef = useRef(() => {});
  const prevGroupByRef = useRef('none');
  const lastResizeRef = useRef({ width: 0, height: 0 });

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
      const skipNormalizer = ['force', 'radial', 'concentric'].includes(engine);

      const _applyResult = (layout) => {
        if (layout) {
          let finalNodes = layout.nodes;
          if (viewport && finalNodes.length > 0 && !skipNormalizer)
            finalNodes = scaleAndCenterToViewport(finalNodes, viewport);
          if (cloudViewEnabled) finalNodes = groupNodesIntoCloud(finalNodes);
          setNodes(finalNodes);
          edgeOverridesRef.current = {};
          setEdgeOverrides({});
          const cleanEdges = layout.edges.map((e) =>
            e.data?.controlPoint ? { ...e, data: { ...e.data, controlPoint: null } } : e
          );
          setEdges(applyEdgeSides(finalNodes, cleanEdges, {}));
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
    [
      nodes,
      edges,
      setNodes,
      setEdges,
      setEdgeOverrides,
      fitView,
      cloudViewEnabled,
      nodeSpacing,
      dirtyRef,
      edgeOverridesRef,
      flowContainerRef,
      isMountedRef,
      setLoading,
    ]
  );

  applyLayoutRef.current = applyLayout;

  // Re-apply current layout when map container is resized (e.g. sidebar toggled)
  useEffect(() => {
    const el = flowContainerRef.current;
    if (!el) return;
    const initialRect = el.getBoundingClientRect?.();
    if (initialRect) {
      lastResizeRef.current = { width: initialRect.width, height: initialRect.height };
    }
    let debounceTimer;
    const scheduleRelayoutIfMeaningful = (width, height) => {
      if (!Number.isFinite(width) || !Number.isFinite(height)) return;
      const prev = lastResizeRef.current;
      const deltaW = Math.abs(width - prev.width);
      const deltaH = Math.abs(height - prev.height);
      if (deltaW < RESIZE_LAYOUT_MIN_DELTA_PX && deltaH < RESIZE_LAYOUT_MIN_DELTA_PX) return;
      lastResizeRef.current = { width, height };
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        if (isMountedRef.current && layoutEngineRef.current !== 'manual')
          applyLayoutRef.current(layoutEngineRef.current);
      }, RESIZE_LAYOUT_DEBOUNCE_MS);
    };
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect?.();
      scheduleRelayoutIfMeaningful(rect?.width, rect?.height);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      clearTimeout(debounceTimer);
    };
  }, [flowContainerRef, isMountedRef]);

  // Apply a layout preset when groupBy changes
  useEffect(() => {
    if (groupBy === prevGroupByRef.current) return;
    prevGroupByRef.current = groupBy;
    if (groupBy === 'type') applyLayout('circular_cluster');
    else if (groupBy === 'rack') applyLayout('grid_rack');
    else if (groupBy === 'environment') applyLayout('hierarchical_network');
    // 'none' keeps the current layout unchanged
  }, [groupBy, applyLayout]);

  const applyPreset = useCallback((preset) => applyLayout(preset.layout), [applyLayout]);

  const viewOptions = useMemo(
    () => ({ edgeMode, edgeLabelVisible, nodeSpacing, groupBy }),
    [edgeMode, edgeLabelVisible, nodeSpacing, groupBy]
  );

  return {
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
  };
}
