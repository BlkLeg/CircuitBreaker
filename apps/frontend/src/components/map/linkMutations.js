/* eslint-disable security/detect-object-injection -- internal edge/node keys */
import {
  computeUnitsApi,
  hardwareApi,
  servicesApi,
  storageApi,
  networksApi,
  clustersApi,
  externalNodesApi,
} from '../../api/client';

const NODE_ID_PREFIX = {
  cluster: 'cluster',
  hardware: 'hw',
  compute: 'cu',
  service: 'svc',
  docker_container: 'svc',
  storage: 'st',
  network: 'net',
  docker_network: 'net',
  misc: 'misc',
  external: 'ext',
};

// Normalize docker sub-types to their base entity type for link resolution
function normaliseType(type) {
  if (type === 'docker_network') return 'network';
  if (type === 'docker_container') return 'service';
  return type;
}

const UPDATABLE_EDGE_PREFIXES = [
  'e-ext-net-',
  'e-svc-ext-',
  'e-dep-',
  'e-ss-',
  'e-sm-',
  'e-cn-',
  'e-hn-',
  'e-hh-',
  'e-np-',
];

export const LINK_ITEMS = {
  service: ['hardware', 'compute', 'storage', 'misc', 'network', 'external'],
  docker_container: ['hardware', 'compute', 'storage', 'misc', 'network', 'external'],
  compute: ['hardware', 'service', 'network'],
  hardware: ['hardware', 'compute', 'storage', 'cluster', 'network'],
  cluster: ['network'],
  network: ['hardware', 'compute', 'service', 'external', 'network'],
  docker_network: ['hardware', 'compute', 'service', 'external', 'network', 'docker_network'],
  storage: ['hardware', 'service'],
  misc: ['service'],
  external: ['network'],
};

function nodeIdFor(node) {
  const prefix = NODE_ID_PREFIX[node?.originalType];
  if (!prefix || node?._refId == null) return null;
  return `${prefix}-${node._refId}`;
}

function parseNodeId(nodeId) {
  const m = nodeId.match(/^([a-z]+)-(\d+)$/);
  return m ? { prefix: m[1], id: parseInt(m[2], 10) } : null;
}

function edgeMeta({ relation, edgePrefix, sourceNodeId, targetNodeId, updatable }) {
  return {
    relation,
    edgePrefix,
    sourceNodeId,
    targetNodeId,
    updatable: Boolean(updatable),
  };
}

async function createLinkDirectional(sourceNode, targetNode) {
  const srcId = sourceNode._refId;
  const tgtId = targetNode._refId;
  const srcType = normaliseType(sourceNode.originalType);
  const targetType = normaliseType(targetNode.originalType);

  if (srcType === 'service') {
    if (targetType === 'hardware') {
      await servicesApi.update(srcId, { hardware_id: tgtId });
      return edgeMeta({
        relation: 'hosts',
        edgePrefix: 'e-hw-svc-',
        sourceNodeId: `hw-${tgtId}`,
        targetNodeId: `svc-${srcId}`,
        updatable: false,
      });
    }
    if (targetType === 'compute') {
      await servicesApi.update(srcId, { compute_id: tgtId });
      return edgeMeta({
        relation: 'runs',
        edgePrefix: 'e-cu-svc-',
        sourceNodeId: `cu-${tgtId}`,
        targetNodeId: `svc-${srcId}`,
        updatable: false,
      });
    }
    if (targetType === 'storage') {
      await servicesApi.addStorage(srcId, { storage_id: tgtId });
      return edgeMeta({
        relation: 'uses',
        edgePrefix: 'e-ss-',
        sourceNodeId: `svc-${srcId}`,
        targetNodeId: `st-${tgtId}`,
        updatable: true,
      });
    }
    if (targetType === 'misc') {
      await servicesApi.addMisc(srcId, { misc_id: tgtId });
      return edgeMeta({
        relation: 'integrates_with',
        edgePrefix: 'e-sm-',
        sourceNodeId: `svc-${srcId}`,
        targetNodeId: `misc-${tgtId}`,
        updatable: true,
      });
    }
    if (targetType === 'network') {
      if (sourceNode._computeId) {
        await networksApi.addMember(tgtId, { compute_id: sourceNode._computeId });
        return edgeMeta({
          relation: 'on_network',
          edgePrefix: 'e-svc-net-',
          sourceNodeId: `svc-${srcId}`,
          targetNodeId: `net-${tgtId}`,
          updatable: false,
        });
      }
      if (sourceNode._hwId) {
        await networksApi.addHardwareMember(tgtId, { hardware_id: sourceNode._hwId });
        return edgeMeta({
          relation: 'on_network',
          edgePrefix: 'e-svc-net-',
          sourceNodeId: `svc-${srcId}`,
          targetNodeId: `net-${tgtId}`,
          updatable: false,
        });
      }
      throw new Error('Service has no hosting compute or hardware and cannot join a network.');
    }
    if (targetType === 'external') {
      await servicesApi.addExternalDep(srcId, { external_node_id: tgtId });
      return edgeMeta({
        relation: 'depends_on',
        edgePrefix: 'e-svc-ext-',
        sourceNodeId: `svc-${srcId}`,
        targetNodeId: `ext-${tgtId}`,
        updatable: true,
      });
    }
  }

  if (srcType === 'compute') {
    if (targetType === 'hardware') {
      await computeUnitsApi.update(srcId, { hardware_id: tgtId });
      return edgeMeta({
        relation: 'hosts',
        edgePrefix: 'e-hw-cu-',
        sourceNodeId: `hw-${tgtId}`,
        targetNodeId: `cu-${srcId}`,
        updatable: false,
      });
    }
    if (targetType === 'service') {
      await servicesApi.update(tgtId, { compute_id: srcId });
      return edgeMeta({
        relation: 'runs',
        edgePrefix: 'e-cu-svc-',
        sourceNodeId: `cu-${srcId}`,
        targetNodeId: `svc-${tgtId}`,
        updatable: false,
      });
    }
    if (targetType === 'network') {
      await networksApi.addMember(tgtId, { compute_id: srcId });
      return edgeMeta({
        relation: 'connects_to',
        edgePrefix: 'e-cn-',
        sourceNodeId: `cu-${srcId}`,
        targetNodeId: `net-${tgtId}`,
        updatable: true,
      });
    }
  }

  if (srcType === 'hardware') {
    if (targetType === 'hardware') {
      await hardwareApi.createConnection(srcId, { target_hardware_id: tgtId });
      return edgeMeta({
        relation: 'connects_to',
        edgePrefix: 'e-hh-',
        sourceNodeId: `hw-${srcId}`,
        targetNodeId: `hw-${tgtId}`,
        updatable: true,
      });
    }
    if (targetType === 'compute') {
      await computeUnitsApi.update(tgtId, { hardware_id: srcId });
      return edgeMeta({
        relation: 'hosts',
        edgePrefix: 'e-hw-cu-',
        sourceNodeId: `hw-${srcId}`,
        targetNodeId: `cu-${tgtId}`,
        updatable: false,
      });
    }
    if (targetType === 'storage') {
      await storageApi.update(tgtId, { hardware_id: srcId });
      return edgeMeta({
        relation: 'has_storage',
        edgePrefix: 'e-hw-st-',
        sourceNodeId: `hw-${srcId}`,
        targetNodeId: `st-${tgtId}`,
        updatable: false,
      });
    }
    if (targetType === 'cluster') {
      await clustersApi.addMember(tgtId, { hardware_id: srcId });
      return edgeMeta({
        relation: 'cluster_member',
        edgePrefix: 'e-cluster-',
        sourceNodeId: `cluster-${tgtId}`,
        targetNodeId: `hw-${srcId}`,
        updatable: false,
      });
    }
    if (targetType === 'network') {
      await networksApi.addHardwareMember(tgtId, { hardware_id: srcId });
      return edgeMeta({
        relation: 'on_network',
        edgePrefix: 'e-hn-',
        sourceNodeId: `hw-${srcId}`,
        targetNodeId: `net-${tgtId}`,
        updatable: true,
      });
    }
  }

  if (srcType === 'network') {
    if (targetType === 'hardware') {
      await networksApi.addHardwareMember(srcId, { hardware_id: tgtId });
      return edgeMeta({
        relation: 'on_network',
        edgePrefix: 'e-hn-',
        sourceNodeId: `hw-${tgtId}`,
        targetNodeId: `net-${srcId}`,
        updatable: true,
      });
    }
    if (targetType === 'compute') {
      await networksApi.addMember(srcId, { compute_id: tgtId });
      return edgeMeta({
        relation: 'connects_to',
        edgePrefix: 'e-cn-',
        sourceNodeId: `cu-${tgtId}`,
        targetNodeId: `net-${srcId}`,
        updatable: true,
      });
    }
    if (targetType === 'service') {
      const svcRes = await servicesApi.get(tgtId);
      const svc = svcRes.data;
      if (svc.compute_id) {
        await networksApi.addMember(srcId, { compute_id: svc.compute_id });
      } else if (svc.hardware_id) {
        await networksApi.addHardwareMember(srcId, { hardware_id: svc.hardware_id });
      } else {
        throw new Error('Service has no hosting compute or hardware and cannot join a network.');
      }
      return edgeMeta({
        relation: 'on_network',
        edgePrefix: 'e-svc-net-',
        sourceNodeId: `svc-${tgtId}`,
        targetNodeId: `net-${srcId}`,
        updatable: false,
      });
    }
    if (targetType === 'external') {
      await externalNodesApi.addNetwork(tgtId, { network_id: srcId });
      return edgeMeta({
        relation: 'connects_to',
        edgePrefix: 'e-ext-net-',
        sourceNodeId: `ext-${tgtId}`,
        targetNodeId: `net-${srcId}`,
        updatable: true,
      });
    }
    if (targetType === 'network') {
      await networksApi.addPeer(srcId, tgtId);
      const aId = Math.min(srcId, tgtId);
      const bId = Math.max(srcId, tgtId);
      return edgeMeta({
        relation: 'peers_with',
        edgePrefix: 'e-np-',
        sourceNodeId: `net-${aId}`,
        targetNodeId: `net-${bId}`,
        updatable: true,
      });
    }
  }

  if (srcType === 'cluster') {
    if (targetType === 'network') {
      const membersRes = await clustersApi.getMembers(srcId);
      const members = membersRes.data || [];
      if (members.length === 0) {
        throw new Error('Cluster has no hardware members to connect to this network.');
      }
      await Promise.all(
        members.map((m) => networksApi.addHardwareMember(tgtId, { hardware_id: m.hardware_id }))
      );
      // The graph refresh will show per-hardware on_network edges; return a
      // non-updatable synthetic meta so the caller knows the action succeeded.
      return edgeMeta({
        relation: 'on_network',
        edgePrefix: 'e-hn-',
        sourceNodeId: `cluster-${srcId}`,
        targetNodeId: `net-${tgtId}`,
        updatable: false,
      });
    }
  }

  if (srcType === 'storage') {
    if (targetType === 'service') {
      await servicesApi.addStorage(tgtId, { storage_id: srcId });
      return edgeMeta({
        relation: 'uses',
        edgePrefix: 'e-ss-',
        sourceNodeId: `svc-${tgtId}`,
        targetNodeId: `st-${srcId}`,
        updatable: true,
      });
    }
    if (targetType === 'hardware') {
      await storageApi.update(srcId, { hardware_id: tgtId });
      return edgeMeta({
        relation: 'has_storage',
        edgePrefix: 'e-hw-st-',
        sourceNodeId: `hw-${tgtId}`,
        targetNodeId: `st-${srcId}`,
        updatable: false,
      });
    }
  }

  if (srcType === 'misc') {
    if (targetType === 'service') {
      await servicesApi.addMisc(tgtId, { misc_id: srcId });
      return edgeMeta({
        relation: 'integrates_with',
        edgePrefix: 'e-sm-',
        sourceNodeId: `svc-${tgtId}`,
        targetNodeId: `misc-${srcId}`,
        updatable: true,
      });
    }
  }

  if (srcType === 'external') {
    if (targetType === 'network') {
      await externalNodesApi.addNetwork(srcId, { network_id: tgtId });
      return edgeMeta({
        relation: 'connects_to',
        edgePrefix: 'e-ext-net-',
        sourceNodeId: `ext-${srcId}`,
        targetNodeId: `net-${tgtId}`,
        updatable: true,
      });
    }
  }

  throw new Error(`No link mapping for ${srcType} -> ${targetType}`);
}

export async function createLinkByNodes(sourceNode, targetNode, allowReverse = true) {
  if (!sourceNode || !targetNode) throw new Error('Missing source/target nodes for link creation.');
  try {
    return await createLinkDirectional(sourceNode, targetNode);
  } catch (err) {
    const noMapping = typeof err?.message === 'string' && err.message.startsWith('No link mapping');
    if (!allowReverse || !noMapping) throw err;
    return createLinkDirectional(targetNode, sourceNode);
  }
}

export async function createLinkByNodeIds(sourceNodeId, targetNodeId, nodes) {
  const nodeMap = Array.isArray(nodes) ? new Map(nodes.map((n) => [n.id, n])) : nodes;
  const sourceNode = nodeMap?.get(sourceNodeId);
  const targetNode = nodeMap?.get(targetNodeId);
  if (!sourceNode || !targetNode) {
    throw new Error('Unable to resolve source/target entities for link creation.');
  }
  return createLinkByNodes(sourceNode, targetNode, true);
}

export function isUpdatableEdgeId(edgeId) {
  return UPDATABLE_EDGE_PREFIXES.some((prefix) => edgeId.startsWith(prefix));
}

export async function unlinkByEdge(edge) {
  const src = parseNodeId(edge.source);
  const tgt = parseNodeId(edge.target);
  const rel = edge._relation || edge.data?.relation || edge.label;
  if (!src || !tgt) throw new Error('Cannot parse node IDs for unlink.');

  if (rel === 'uses' && src.prefix === 'svc' && tgt.prefix === 'st') {
    return servicesApi.removeStorage(src.id, tgt.id);
  }
  if (rel === 'integrates_with' && src.prefix === 'svc' && tgt.prefix === 'misc') {
    return servicesApi.removeMisc(src.id, tgt.id);
  }
  if (rel === 'runs' && tgt.prefix === 'svc' && src.prefix === 'cu') {
    return servicesApi.update(tgt.id, { compute_id: null });
  }
  if (rel === 'runs' && tgt.prefix === 'svc' && src.prefix === 'hw') {
    return servicesApi.update(tgt.id, { hardware_id: null });
  }
  if (rel === 'hosts' && src.prefix === 'hw' && tgt.prefix === 'cu') {
    return computeUnitsApi.update(tgt.id, { hardware_id: null });
  }
  if (rel === 'hosts' && src.prefix === 'hw' && tgt.prefix === 'svc') {
    return servicesApi.update(tgt.id, { hardware_id: null });
  }
  if (rel === 'has_storage' && src.prefix === 'hw' && tgt.prefix === 'st') {
    return storageApi.update(tgt.id, { hardware_id: null });
  }
  if (rel === 'on_network' && src.prefix === 'svc' && tgt.prefix === 'net') {
    const serviceRes = await servicesApi.get(src.id);
    const service = serviceRes?.data || {};
    if (service.compute_id) {
      return networksApi.removeMember(tgt.id, service.compute_id);
    }
    if (service.hardware_id) {
      return networksApi.removeHardwareMember(tgt.id, service.hardware_id);
    }
    throw new Error(
      'Service has no hosting compute or hardware and cannot be removed from a network.'
    );
  }
  if (rel === 'on_network' && src.prefix === 'hw' && tgt.prefix === 'net') {
    return networksApi.removeHardwareMember(tgt.id, src.id);
  }
  if (
    (rel === 'on_network' || rel === 'connects_to') &&
    src.prefix === 'cu' &&
    tgt.prefix === 'net'
  ) {
    return networksApi.removeMember(tgt.id, src.id);
  }
  if (rel === 'cluster_member') {
    const clusterId = src.prefix === 'cluster' ? src.id : tgt.prefix === 'cluster' ? tgt.id : null;
    const hardwareId = src.prefix === 'hw' ? src.id : tgt.prefix === 'hw' ? tgt.id : null;
    if (!clusterId || !hardwareId) {
      throw new Error('Cannot resolve cluster membership unlink target.');
    }
    const membersRes = await clustersApi.getMembers(clusterId);
    const members = membersRes.data || [];
    const membership = members.find((m) => m.hardware_id === hardwareId);
    if (!membership) {
      throw new Error('Cluster membership not found.');
    }
    return clustersApi.removeMember(clusterId, membership.id);
  }
  if (rel === 'depends_on' && src.prefix === 'svc' && tgt.prefix === 'svc') {
    return servicesApi.removeDependency(src.id, tgt.id);
  }
  if (rel === 'connects_to' && src.prefix === 'ext' && tgt.prefix === 'net') {
    const res = await externalNodesApi.getNetworks(src.id);
    const link = (res.data || []).find((l) => l.network_id === tgt.id);
    if (!link) throw new Error('External node to network link not found.');
    return externalNodesApi.removeNetwork(link.id);
  }
  if (rel === 'depends_on' && src.prefix === 'svc' && tgt.prefix === 'ext') {
    const res = await servicesApi.getExternalDeps(src.id);
    const link = (res.data || []).find((l) => l.external_node_id === tgt.id);
    if (!link) throw new Error('Service to external node link not found.');
    return servicesApi.removeExternalDep(src.id, link.id);
  }
  if (rel === 'connects_to' && src.prefix === 'hw' && tgt.prefix === 'hw') {
    return hardwareApi.deleteConnection(parseInt(edge.id.replace('e-hh-', ''), 10));
  }
  if (rel === 'peers_with' && src.prefix === 'net' && tgt.prefix === 'net') {
    return networksApi.removePeer(src.id, tgt.id);
  }

  throw new Error(`No unlink mapping for ${rel} (${src.prefix} -> ${tgt.prefix}).`);
}

export function inferEdgeNodeIdsFromMeta(meta, fallbackSourceId, fallbackTargetId) {
  return {
    sourceNodeId: meta?.sourceNodeId || fallbackSourceId,
    targetNodeId: meta?.targetNodeId || fallbackTargetId,
  };
}

export function buildPseudoNode(originalType, refId) {
  return {
    originalType,
    _refId: refId,
    id: `${NODE_ID_PREFIX[originalType]}-${refId}`,
  };
}

export function nodeIdFromEntityNode(node) {
  return nodeIdFor(node);
}
