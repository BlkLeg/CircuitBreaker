const DEFAULT_UPLINK_MBPS = 1000;

function toPositiveNumber(value, fallback = DEFAULT_UPLINK_MBPS) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
}

function resolveNodeUplinkMbps(node) {
  if (!node?.data) return DEFAULT_UPLINK_MBPS;

  if (node.data.uplinkSpeed != null) {
    return toPositiveNumber(node.data.uplinkSpeed);
  }

  if (node.data.upload_speed_mbps != null) {
    return toPositiveNumber(node.data.upload_speed_mbps);
  }

  if (node.data.download_speed_mbps != null) {
    return toPositiveNumber(node.data.download_speed_mbps);
  }

  return DEFAULT_UPLINK_MBPS;
}

function applyTypeBandwidthCap(edgeType, speedMbps) {
  const normalized = String(edgeType || '').trim().toLowerCase();
  if (normalized === 'wireless') return Math.min(speedMbps, 300);
  if (normalized === 'tunnel' || normalized === 'vpn') return Math.min(speedMbps, 100);
  return speedMbps;
}

export function calculateEdgeBandwidth(sourceNode, targetNode, edgeType) {
  const sourceSpeed = resolveNodeUplinkMbps(sourceNode);
  const targetSpeed = resolveNodeUplinkMbps(targetNode);
  const limitedBySlowest = Math.min(sourceSpeed, targetSpeed);
  return applyTypeBandwidthCap(edgeType, limitedBySlowest);
}

export function recalculateAllEdges(nodes, edges) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  return edges.map((edge) => {
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (!sourceNode || !targetNode) return edge;

    const edgeType = edge?.data?.connection_type || edge?.data?.type || null;
    const bandwidth = calculateEdgeBandwidth(sourceNode, targetNode, edgeType);

    return {
      ...edge,
      data: {
        ...edge.data,
        bandwidth,
      },
    };
  });
}
