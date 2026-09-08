import {
  NODE_STYLES,
  BASE_NODE_STYLE,
  resolveNodeIcon,
  getEdgeColor,
} from '../components/map/mapConstants';
import { getNodeRank } from './mapDataUtils';
import { normalizeConnectionType } from '../components/map/connectionTypes';
import { isUpdatableEdgeId } from '../components/map/linkMutations';
import {
  ADHOC_EDGE_COLOR,
  ADHOC_EDGE_DASH_ARRAY,
  ADHOC_EDGE_STROKE_WIDTH,
  AUTO_EDGE_STROKE_WIDTH,
} from '../lib/constants';

/**
 * Turns a `/graph/topology` response into the canonical node and edge arrays
 * the renderers draw.
 *
 * Pure: no fetching, no state, no React. It was inline in `useMapDataLoad`
 * between an await and a dozen setState calls, which is why none of it could
 * be exercised on its own.
 *
 * @param {{nodes: Array, edges: Array}} data - the topology response body
 * @param {object}  options
 * @param {boolean} options.showLabels   - render relation labels on edges
 * @param {Map<string, boolean>} options.includeTypes - active entity-type filter
 * @param {object}  options.uplinkOverrides - node id -> Mbps, from settings
 * @returns {{nodes: Array, edges: Array}} canonical map graph
 */
export function adaptTopology(data, { showLabels, includeTypes, uplinkOverrides = {} }) {
  const res = { data };

  const rawN = res.data.nodes.map((n) => {
    const nodeShell = {
      id: n.id,
      type: 'iconNode',
      className: n.role === 'switch' ? 'node-switch' : '',
      data: {},
      position: { x: 0, y: 0 },
      style: { ...BASE_NODE_STYLE },
      hidden: n.type === 'cluster' && !includeTypes.get('cluster'),
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
      type: n.type,
      role: n.role || null,
      iconSrc: resolveNodeIcon(n.type, n.icon_slug, n.vendor, n.kind, n.role, n.cluster_type),
      icon_slug: n.icon_slug ?? null,
      glowColor: NODE_STYLES.get(n.type)?.glowColor,
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
      ip_conflict: n.ip_conflict ?? false,
      download_speed_mbps: n.download_speed_mbps ?? null,
      upload_speed_mbps: n.upload_speed_mbps ?? null,
      proxmox_vmid: n.proxmox_vmid ?? null,
      proxmox_type: n.proxmox_type ?? null,
      proxmox_status: n.proxmox_status ?? null,
      proxmox_node_name: n.proxmox_node_name ?? null,
      integration_config_id: n.integration_config_id ?? null,
      device_type: n.device_type ?? null,
      docs: Array.isArray(n.docs) ? n.docs : [],
      // Monitor rollup — null across the board when the entity isn't monitored.
      monitor_id: n.monitor_id ?? null,
      monitor_enabled: n.monitor_enabled ?? null,
      monitor_status: n.monitor_status ?? null,
      monitor_latency_ms: n.monitor_latency_ms ?? null,
      monitor_last_checked_at: n.monitor_last_checked_at ?? null,
      monitor_uptime_pct_24h: n.monitor_uptime_pct_24h ?? null,
    };
    return nodeShell;
  });

  const rawE = res.data.edges.map((e) => {
    const color = getEdgeColor(e.relation);
    const relation = e.data?.relation || e.relation;
    const isAdHoc = isUpdatableEdgeId(e.id);
    const edgeStyle = isAdHoc
      ? {
          stroke: ADHOC_EDGE_COLOR,
          strokeWidth: ADHOC_EDGE_STROKE_WIDTH,
          strokeDasharray: ADHOC_EDGE_DASH_ARRAY,
          opacity: 0.95,
        }
      : { stroke: color, strokeWidth: AUTO_EDGE_STROKE_WIDTH, opacity: 0.75 };
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smart',
      label: showLabels ? relation : '',
      animated: e.relation === 'depends_on' || e.relation === 'runs',
      style: edgeStyle,
      _relation: e.relation,
      data: {
        label: showLabels ? relation : '',
        relation: relation,
        controlPoint: null,
        connection_type: normalizeConnectionType(e.data?.connection_type),
        bandwidth: e.data?.bandwidth || null,
        isAdHoc,
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

  const rawNodesWithOverrides = rawNodesWithClusterHints.map((node) => {
    const mbps = uplinkOverrides[node.id];
    if (mbps != null && Number.isFinite(Number(mbps))) {
      const val = Number(mbps);
      return {
        ...node,
        data: {
          ...node.data,
          uplinkSpeed: val,
          upload_speed_mbps: val,
          download_speed_mbps: val,
        },
      };
    }
    return node;
  });

  return { nodes: rawNodesWithOverrides, edges: rawE };
}
