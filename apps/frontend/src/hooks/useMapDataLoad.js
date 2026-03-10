import { useCallback } from 'react';
import { graphApi } from '../api/client';
import {
  NODE_STYLES,
  BASE_NODE_STYLE,
  resolveNodeIcon,
  normalizeMapLabel,
  normalizeBoundaryName,
  getEdgeColor,
} from '../components/map/mapConstants';
import {
  applyEdgeSides,
  parseLayoutData,
  resolveNonOverlappingPosition,
} from '../utils/mapGeometryUtils';
import {
  getNodeRank,
  groupDockerIntoBoundaries,
  proxmoxClusterDetected,
} from '../utils/mapDataUtils';
import { normalizeConnectionType } from '../components/map/connectionTypes';
import { getDagreLayout, getDagreViewportOptions } from '../utils/layouts';
import { groupNodesIntoCloud } from '../utils/cloudView';
import { VIEWPORT_FIT_DEFAULTS } from '../utils/viewportFit';

/**
 * Encapsulates the graph data-loading logic (fetchData, autoPlaceNew, drain
 * effect) extracted from MapInternal.  Accepts a single config object with all
 * the state setters / refs / values it needs.
 *
 * @returns {{ fetchData, autoPlaceNew, updateNodePos }}
 */
export function useMapDataLoad({
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
  const getIncludeCSV = useCallback((types) => {
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
  }, []);

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
      try {
        const res = await graphApi.placeNode(newNodeId, envFilter || 'default');
        autoPlacedIdsRef.current.add(newNodeId);
        placingNodesRef.current.delete(newNodeId);
        updateNodePos(newNodeId, { x: res.data.x, y: res.data.y });
        batchPlacedCountRef.current += 1;
      } catch (e) {
        placingNodesRef.current.delete(newNodeId);
        console.error('Auto-place failed', e);
      } finally {
        pendingPlacementCountRef.current -= 1;
        if (pendingPlacementCountRef.current === 0 && batchPlacedCountRef.current > 0) {
          const count = batchPlacedCountRef.current;
          batchPlacedCountRef.current = 0;
          toast.success(count === 1 ? 'Node auto-placed' : `${count} nodes auto-placed`, {
            toastId: 'auto-place-batch',
            autoClose: 2000,
          });
          saveLayoutRef
            .current?.()
            .catch((err) => console.error('Auto-save after placement failed', err));
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
    ]
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const includeCSV = getIncludeCSV(includeTypes);
      const res = await graphApi.topology({
        environment_id: envFilter || undefined,
        include: includeCSV,
      });

      const rawN = res.data.nodes.map((n) => {
        const nodeShell = {
          id: n.id,
          type: 'iconNode',
          className: n.role === 'switch' ? 'node-switch' : '',
          data: {},
          position: { x: 0, y: 0 },
          style: { ...BASE_NODE_STYLE },
          hidden: n.type === 'cluster' && !includeTypes.cluster,
          originalType: n.type,
          _tags: n.tags || [],
          _refId: n.ref_id,
          _computeId: n.compute_id || null,
          _hwId: n.hardware_id || null,
          _hwRole: n.type === 'hardware' ? n.role || null : null,
        };
        const rank = getNodeRank(nodeShell);
        nodeShell.data = {
          label: n.label,
          role: n.role || null,
          iconSrc: resolveNodeIcon(n.type, n.icon_slug, n.vendor, n.kind, n.role, n.cluster_type),
          icon_slug: n.icon_slug ?? null,
          glowColor: NODE_STYLES[n.type]?.glowColor,
          rank,
          ip_address: n.ip_address || null,
          ports: Array.isArray(n.ports) ? n.ports : [],
          cidr: n.cidr || null,
          storage_summary: n.storage_summary || null,
          storage_allocated: n.storage_allocated || null,
          capacity_gb: n.capacity_gb || null,
          used_gb: n.used_gb || null,
          ...(n.type === 'cluster'
            ? {
                member_count: n.member_count,
                environment: n.environment,
                cluster_type: n.cluster_type ?? null,
              }
            : {}),
          status: n.status || null,
          status_override: n.status_override || null,
          docker_image: n.docker_image || null,
          docker_driver: n.docker_driver || null,
          docker_labels: n.docker_labels || null,
          compute_id: n.compute_id ?? null,
          hardware_id: n.hardware_id ?? null,
          is_docker: n.type === 'docker_network' || n.type === 'docker_container',
          telemetry_status: n.telemetry_status || 'unknown',
          telemetry_data: n.telemetry_data || null,
          telemetry_last_polled: n.telemetry_last_polled || null,
          u_height: n.u_height ?? 1,
          rack_unit: n.rack_unit ?? null,
          ip_conflict: n.ip_conflict ?? false,
          download_speed_mbps: n.download_speed_mbps ?? null,
          upload_speed_mbps: n.upload_speed_mbps ?? null,
          proxmox_vmid: n.proxmox_vmid ?? null,
          proxmox_type: n.proxmox_type ?? null,
          proxmox_status: n.proxmox_status ?? null,
          proxmox_node_name: n.proxmox_node_name ?? null,
          integration_config_id: n.integration_config_id ?? null,
          docs: Array.isArray(n.docs) ? n.docs : [],
        };
        return nodeShell;
      });

      const rawE = res.data.edges.map((e) => {
        const color = getEdgeColor(e.relation);
        const relation = e.data?.relation || e.relation;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: 'smart',
          label: showLabels ? relation : '',
          animated: e.relation === 'depends_on' || e.relation === 'runs',
          style: { stroke: color, strokeWidth: 1.5, opacity: 0.75 },
          _relation: e.relation,
          data: {
            label: showLabels ? relation : '',
            relation: showLabels ? relation : '',
            controlPoint: null,
            connection_type: normalizeConnectionType(e.data?.connection_type),
            bandwidth: e.data?.bandwidth || null,
          },
        };
      });

      const clusterMembers = new Set();
      rawE.forEach((e) => {
        if (e._relation === 'cluster_member' || e.data?.relation === 'cluster_member') {
          clusterMembers.add(e.source);
          clusterMembers.add(e.target);
        }
      });
      const rawNodesWithClusterHints = rawN.map((node) => ({
        ...node,
        data: { ...node.data, isClusterMember: clusterMembers.has(node.id) },
      }));

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
          const layoutRes = await graphApi.getLayout(layoutName);
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
      } catch {
        /* no saved layout */
      }

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
        rawNodesWithClusterHints,
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
        const mergedNodes = rawNodesWithClusterHints.map((n) => {
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
        if (cloudViewEnabled) {
          initialNodes = groupNodesIntoCloud(initialNodes);
        }

        setNodes(initialNodes);
        setEdges(applyEdgeSides(mergedNodes, rawE, savedEdgeOverrides));
        setLayoutEngine('manual');
      } else {
        const viewportWidth = containerRef?.current?.getBoundingClientRect?.()?.width;
        const dagreOptions = getDagreViewportOptions(viewportWidth);
        const layout = getDagreLayout(rawNodesWithClusterHints, rawE, 'TB', dagreOptions);
        let initialNodes = layout.nodes;
        if (cloudViewEnabled) {
          initialNodes = groupNodesIntoCloud(initialNodes);
        }
        setNodes(initialNodes);
        setEdges(applyEdgeSides(initialNodes, layout.edges, {}));
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
          } catch {
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
      setError(err.message || 'Failed to load topology');
    } finally {
      setLoading(false);
    }
  }, [
    containerRef,
    unmountedRef,
    envFilter,
    includeTypes,
    fitView,
    getLayoutName,
    isMobile,
    showLabels,
    cloudViewEnabled,
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
    getIncludeCSV,
    setLayoutEngine,
  ]);

  return { fetchData, autoPlaceNew, updateNodePos };
}
