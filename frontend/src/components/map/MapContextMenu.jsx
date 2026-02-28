import React, { useEffect, useRef, useState } from 'react';
import { Link2, ImageIcon, ChevronRight, Search, Loader, Unlink } from 'lucide-react';
import {
  hardwareApi,
  computeUnitsApi,
  servicesApi,
  storageApi,
  networksApi,
  miscApi,
  clustersApi,
  externalNodesApi,
} from '../../api/client';
import { useToast } from '../common/Toast';
import IconPickerModal from '../common/IconPickerModal';

// ── Menu config ──────────────────────────────────────────────────────────────

const LINK_ITEMS = {
  service:  ['hardware', 'compute', 'storage', 'misc', 'network', 'external'],
  compute:  ['hardware', 'service', 'network'],
  hardware: ['compute', 'storage', 'cluster'],
  network:  ['hardware', 'compute', 'service', 'external'],
  storage:  ['hardware', 'service'],
  misc:     ['service'],
  external: ['network'],
};

const LINK_LABEL = {
  hardware: 'Link to Hardware',
  compute:  'Link to Compute',
  service:  'Link to Services',
  storage:  'Link to Storage',
  network:  'Link to Network',
  misc:     'Link to Misc',
  cluster:  'Add to Cluster',
  external: 'Link to External',
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const LIST_API = {
  hardware: (p) => hardwareApi.list(p),
  compute:  (p) => computeUnitsApi.list(p),
  service:  (p) => servicesApi.list(p),
  storage:  (p) => storageApi.list(p),
  network:  (p) => networksApi.list(p),
  misc:     (p) => miscApi.list(p),
  cluster:  (p) => clustersApi.list(p),
  external: (p) => externalNodesApi.list(p),
};

// hardware uses vendor_icon_slug; storage/network/misc have no icon column yet
const UPDATE_ICON_API = {
  hardware: (id, slug) => hardwareApi.update(id, { vendor_icon_slug: slug }),
  compute:  (id, slug) => computeUnitsApi.update(id, { icon_slug: slug }),
  service:  (id, slug) => servicesApi.update(id, { icon_slug: slug }),
  storage:  (id, slug) => storageApi.update(id, { icon_slug: slug }),
  network:  (id, slug) => networksApi.update(id, { icon_slug: slug }),
  misc:     (id, slug) => miscApi.update(id, { icon_slug: slug }),
  external: (id, slug) => externalNodesApi.update(id, { icon_slug: slug }),
};

const ICON_SUPPORTED_TYPES = new Set(['hardware', 'compute', 'service', 'storage', 'network', 'misc', 'external']);

function getLabel(entity, type) {
  return entity.name || entity.hostname || entity.slug || entity.cidr || `#${entity.id}`;
}

function getSublabel(entity, type) {
  if (type === 'hardware') return entity.vendor || entity.ip_address || null;
  if (type === 'compute')  return entity.ip_address || entity.kind || null;
  if (type === 'service')  return entity.slug || entity.status || null;
  if (type === 'storage')  return entity.kind || (entity.capacity_gb ? `${entity.capacity_gb} GB` : null);
  if (type === 'network')  return entity.cidr || null;
  if (type === 'misc')     return entity.kind || null;
  if (type === 'cluster')  return entity.environment || (entity.member_count != null ? `${entity.member_count} members` : null);
  if (type === 'external') return entity.provider || entity.ip_address || null;
  return null;
}

async function performLink(srcNode, targetType, targetEntity) {
  const srcId  = srcNode._refId;
  const tgtId  = targetEntity.id;
  const srcType = srcNode.originalType;

  if (srcType === 'service') {
    if (targetType === 'hardware') return servicesApi.update(srcId, { hardware_id: tgtId });
    if (targetType === 'compute')  return servicesApi.update(srcId, { compute_id: tgtId });
    if (targetType === 'storage')  return servicesApi.addStorage(srcId, { storage_id: tgtId });
    if (targetType === 'misc')     return servicesApi.addMisc(srcId, { misc_id: tgtId });
    if (targetType === 'network') {
      if (srcNode._computeId) return networksApi.addMember(tgtId, { compute_id: srcNode._computeId });
      if (srcNode._hwId)      return networksApi.addHardwareMember(tgtId, { hardware_id: srcNode._hwId });
      throw new Error('Service has no hosting compute or hardware — cannot join network');
    }
  }
  if (srcType === 'compute') {
    if (targetType === 'hardware') return computeUnitsApi.update(srcId, { hardware_id: tgtId });
    if (targetType === 'service')  return servicesApi.update(tgtId, { compute_id: srcId });
    if (targetType === 'network')  return networksApi.addMember(tgtId, { compute_id: srcId });
  }
  if (srcType === 'hardware') {
    if (targetType === 'compute')  return computeUnitsApi.update(tgtId, { hardware_id: srcId });
    if (targetType === 'storage')  return storageApi.update(tgtId, { hardware_id: srcId });
    if (targetType === 'cluster')  return clustersApi.addMember(tgtId, { hardware_id: srcId });
  }
  if (srcType === 'network') {
    if (targetType === 'hardware') return networksApi.addHardwareMember(srcId, { hardware_id: tgtId });
    if (targetType === 'compute')  return networksApi.addMember(srcId, { compute_id: tgtId });
    if (targetType === 'service') {
      // Resolve the service's hosting compute or hardware, then join that to the network
      const svcRes = await servicesApi.get(tgtId);
      const svc = svcRes.data;
      if (svc.compute_id)  return networksApi.addMember(srcId, { compute_id: svc.compute_id });
      if (svc.hardware_id) return networksApi.addHardwareMember(srcId, { hardware_id: svc.hardware_id });
      throw new Error('Service has no hosting compute or hardware — cannot join network');
    }
  }
  if (srcType === 'storage') {
    if (targetType === 'service')  return servicesApi.addStorage(tgtId, { storage_id: srcId });
    if (targetType === 'hardware') return storageApi.update(srcId, { hardware_id: tgtId });
  }
  if (srcType === 'misc') {
    if (targetType === 'service')  return servicesApi.addMisc(tgtId, { misc_id: srcId });
  }
  if (srcType === 'service') {
    if (targetType === 'external') return servicesApi.addExternalDep(srcId, { external_node_id: tgtId });
  }
  if (srcType === 'network') {
    if (targetType === 'external') return externalNodesApi.addNetwork(tgtId, { network_id: srcId });
  }
  if (srcType === 'external') {
    if (targetType === 'network') return externalNodesApi.addNetwork(srcId, { network_id: tgtId });
  }
  throw new Error(`No API mapping for ${srcType} → ${targetType}`);
}

// ── Unlink helpers ────────────────────────────────────────────────────────────

function parseNodeId(nodeId) {
  const m = nodeId.match(/^([a-z]+)-(\d+)$/);
  return m ? { prefix: m[1], id: parseInt(m[2], 10) } : null;
}

async function performUnlink(edge) {
  const src = parseNodeId(edge.source);
  const tgt = parseNodeId(edge.target);
  const rel  = edge._relation;
  if (!src || !tgt) throw new Error('Cannot parse node IDs for unlink');

  // service_storage junction
  if (rel === 'uses' && src.prefix === 'svc' && tgt.prefix === 'st')
    return servicesApi.removeStorage(src.id, tgt.id);
  // service_misc junction
  if (rel === 'integrates_with' && src.prefix === 'svc' && tgt.prefix === 'misc')
    return servicesApi.removeMisc(src.id, tgt.id);
  // service.compute_id nullable FK
  if (rel === 'runs' && tgt.prefix === 'svc' && src.prefix === 'cu')
    return servicesApi.update(tgt.id, { compute_id: null });
  // service.hardware_id nullable FK
  if (rel === 'runs' && tgt.prefix === 'svc' && src.prefix === 'hw')
    return servicesApi.update(tgt.id, { hardware_id: null });
  // compute.hardware_id nullable FK
  if (rel === 'hosts' && src.prefix === 'hw' && tgt.prefix === 'cu')
    return computeUnitsApi.update(tgt.id, { hardware_id: null });
  // storage.hardware_id nullable FK
  if (rel === 'has_storage' && src.prefix === 'hw' && tgt.prefix === 'st')
    return storageApi.update(tgt.id, { hardware_id: null });
  // network hardware member
  if (rel === 'on_network' && src.prefix === 'hw' && tgt.prefix === 'net')
    return networksApi.removeHardwareMember(tgt.id, src.id);
  // network compute member
  if (rel === 'on_network' && src.prefix === 'cu' && tgt.prefix === 'net')
    return networksApi.removeMember(tgt.id, src.id);
  // service dependency
  if (rel === 'depends_on' && src.prefix === 'svc' && tgt.prefix === 'svc')
    return servicesApi.removeDependency(src.id, tgt.id);
  // external node ↔ network
  if (rel === 'connects_to' && src.prefix === 'ext' && tgt.prefix === 'net') {
    // Find the relation ID by listing external node networks
    const res = await externalNodesApi.getNetworks(src.id);
    const link = (res.data || []).find(l => l.network_id === tgt.id);
    if (link) return externalNodesApi.removeNetwork(link.id);
    throw new Error('External node ↔ network link not found');
  }
  // service → external node
  if (rel === 'depends_on' && src.prefix === 'svc' && tgt.prefix === 'ext') {
    const res = await servicesApi.getExternalDeps(src.id);
    const link = (res.data || []).find(l => l.external_node_id === tgt.id);
    if (link) return servicesApi.removeExternalDep(src.id, link.id);
    throw new Error('Service → external node link not found');
  }

  throw new Error(`No unlink mapping for ${rel} (${src.prefix} → ${tgt.prefix})`);
}

// ── Component ────────────────────────────────────────────────────────────────

export default function MapContextMenu({ node, position, onClose, onLinkSuccess, edges, nodes }) {
  const toast = useToast();
  const menuRef = useRef(null);

  const [activeSubmenu, setActiveSubmenu] = useState(null); // target entity type string
  const [options, setOptions]             = useState([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError]   = useState(null);
  const [search, setSearch]               = useState('');
  const [linking, setLinking]             = useState(false);
  const [showIconPicker, setShowIconPicker] = useState(false);
  const [unlinkingEdgeId, setUnlinkingEdgeId] = useState(null);

  // Constrain menu to viewport
  const menuW = 240;
  const menuH = 360;
  const x = Math.min(position.x, window.innerWidth  - menuW - 8);
  const y = Math.min(position.y, window.innerHeight - menuH - 8);

  // Close on outside click — suspended while icon picker is open (renders outside menuRef)
  useEffect(() => {
    if (showIconPicker) return;
    function handleMouseDown(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) onClose();
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [onClose, showIconPicker]);

  // Fetch entity list when submenu activates
  useEffect(() => {
    if (!activeSubmenu) { setOptions([]); setOptionsError(null); return; }
    setOptionsLoading(true);
    setOptionsError(null);
    setOptions([]);
    LIST_API[activeSubmenu]()
      .then(res => setOptions(res.data || []))
      .catch(err => setOptionsError(err.message || 'Failed to load'))
      .finally(() => setOptionsLoading(false));
  }, [activeSubmenu]);

  function openSubmenu(type) {
    setSearch('');
    setActiveSubmenu(prev => (prev === type ? null : type));
  }

  async function handleSelect(targetEntity) {
    setLinking(true);
    try {
      await performLink(node, activeSubmenu, targetEntity);
      toast.success(`Linked "${node.data.label}" → "${getLabel(targetEntity, activeSubmenu)}"`);
      onLinkSuccess();
    } catch (err) {
      toast.error(err.message || 'Link failed');
      setLinking(false);
    }
  }

  async function handleIconSelect(slug) {
    const api = UPDATE_ICON_API[node.originalType];
    if (!api) return;
    try {
      await api(node._refId, slug);
      toast.success('Icon updated');
      onLinkSuccess();
    } catch (err) {
      toast.error(err.message || 'Failed to update icon');
    }
  }

  async function handleUnlink(edge) {
    setUnlinkingEdgeId(edge.id);
    try {
      await performUnlink(edge);
      toast.success('Unlinked.');
      onLinkSuccess();
    } catch (err) {
      toast.error(err.message || 'Failed to unlink.');
      setUnlinkingEdgeId(null);
    }
  }

  const connectedEdges = (edges ?? []).filter(
    e => e.source === node.id || e.target === node.id
  );
  const linkedItems = connectedEdges.map(edge => {
    const otherId   = edge.source === node.id ? edge.target : edge.source;
    const otherNode = (nodes ?? []).find(n => n.id === otherId);
    return { edge, label: otherNode?.data?.label ?? otherId };
  });

  const linkItems  = LINK_ITEMS[node.originalType] || [];
  const filteredOptions = options.filter(e => {
    const label    = getLabel(e, activeSubmenu).toLowerCase();
    const sublabel = (getSublabel(e, activeSubmenu) || '').toLowerCase();
    const q        = search.toLowerCase();
    return !q || label.includes(q) || sublabel.includes(q);
  });

  return (
    <>
      <div
        ref={menuRef}
        style={{
          position: 'fixed',
          left: x,
          top: y,
          zIndex: 1000,
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 8,
          minWidth: menuW,
          maxWidth: menuW,
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          overflow: 'hidden',
          userSelect: 'none',
        }}
      >
        {/* Header */}
        <div style={{ padding: '8px 14px 6px', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.data.label}
          </div>
          <div style={{ fontSize: 10, color: 'var(--color-text-muted)', textTransform: 'capitalize', marginTop: 1 }}>
            {node.originalType}
          </div>
        </div>

        {/* Link items */}
        {linkItems.map(targetType => (
          <div key={targetType}>
            <button
              onClick={() => openSubmenu(targetType)}
              disabled={linking}
              style={{
                width: '100%',
                background: activeSubmenu === targetType ? 'rgba(0,212,255,0.08)' : 'transparent',
                border: 'none',
                color: '#cdd6f4',
                padding: '9px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                fontSize: 12,
                textAlign: 'left',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { if (activeSubmenu !== targetType) e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
              onMouseLeave={e => { if (activeSubmenu !== targetType) e.currentTarget.style.background = 'transparent'; }}
            >
              <Link2 size={13} style={{ color: 'rgba(255,255,255,0.4)', flexShrink: 0 }} />
              <span style={{ flex: 1 }}>{LINK_LABEL[targetType]}</span>
              <ChevronRight
                size={12}
                style={{
                  color: 'rgba(255,255,255,0.3)',
                  transform: activeSubmenu === targetType ? 'rotate(90deg)' : 'none',
                  transition: 'transform 0.15s',
                  flexShrink: 0,
                }}
              />
            </button>

            {/* Inline submenu */}
            {activeSubmenu === targetType && (
              <div style={{ background: 'var(--color-bg)', borderTop: '1px solid var(--color-border)' }}>
                {/* Search */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderBottom: '1px solid var(--color-border)' }}>
                  <Search size={11} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                  <input
                    autoFocus
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Search…"
                    style={{
                      flex: 1,
                      background: 'transparent',
                      border: 'none',
                      outline: 'none',
                      color: 'var(--color-text)',
                      fontSize: 11,
                      fontFamily: 'inherit',
                    }}
                  />
                  {optionsLoading && <Loader size={11} style={{ color: 'var(--color-text-muted)', animation: 'spin 1s linear infinite', flexShrink: 0 }} />}
                </div>

                {/* Entity list */}
                <div style={{ maxHeight: 180, overflowY: 'auto' }}>
                  {optionsError && (
                    <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--color-danger)' }}>{optionsError}</div>
                  )}
                  {!optionsLoading && !optionsError && filteredOptions.length === 0 && (
                    <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--color-text-muted)' }}>
                      {search ? 'No matches' : 'Nothing available'}
                    </div>
                  )}
                  {filteredOptions.map(entity => {
                    const label    = getLabel(entity, activeSubmenu);
                    const sublabel = getSublabel(entity, activeSubmenu);
                    return (
                      <button
                        key={entity.id}
                        onClick={() => handleSelect(entity)}
                        disabled={linking}
                        style={{
                          width: '100%',
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--color-text)',
                          padding: '7px 14px',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'flex-start',
                          gap: 2,
                          cursor: linking ? 'not-allowed' : 'pointer',
                          fontSize: 11,
                          textAlign: 'left',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-glow)'; }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                      >
                        <span style={{ fontWeight: 500 }}>{label}</span>
                        {sublabel && <span style={{ color: 'var(--color-text-muted)', fontSize: 10 }}>{sublabel}</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Unlink section */}
        {linkedItems.length > 0 && (
          <>
            <div style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }} />
            <div style={{ padding: '4px 14px 2px', fontSize: 10, color: 'var(--color-text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Unlink
            </div>
            {linkedItems.map(({ edge, label }) => (
              <button
                key={edge.id}
                onClick={() => handleUnlink(edge)}
                disabled={!!unlinkingEdgeId}
                style={{
                  width: '100%',
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--color-text)',
                  padding: '7px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  cursor: unlinkingEdgeId ? 'not-allowed' : 'pointer',
                  fontSize: 12,
                  textAlign: 'left',
                  opacity: unlinkingEdgeId === edge.id ? 0.5 : 1,
                }}
                onMouseEnter={e => { if (!unlinkingEdgeId) e.currentTarget.style.background = 'var(--color-glow)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                <Unlink size={13} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                {unlinkingEdgeId === edge.id ? 'Unlinking…' : label}
              </button>
            ))}
          </>
        )}

        {/* Divider — only when both link items and Edit Icon are present */}
        {(linkItems.length > 0 || linkedItems.length > 0) && ICON_SUPPORTED_TYPES.has(node.originalType) && (
          <div style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }} />
        )}

        {/* Edit Icon — only for types that have an icon column in the backend */}
        {ICON_SUPPORTED_TYPES.has(node.originalType) && (
          <button
            onClick={() => { setShowIconPicker(true); }}
            style={{
              width: '100%',
              background: 'transparent',
              border: 'none',
              color: 'var(--color-text)',
              padding: '9px 14px',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              cursor: 'pointer',
              fontSize: 12,
              textAlign: 'left',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-glow)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <ImageIcon size={13} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
            Edit Icon
          </button>
        )}
      </div>

      {/* Icon picker modal */}
      {showIconPicker && (
        <IconPickerModal
          currentSlug={null}
          onSelect={handleIconSelect}
          onClose={() => { setShowIconPicker(false); onClose(); }}
        />
      )}

    </>
  );
}
