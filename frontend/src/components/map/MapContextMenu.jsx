import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Link2, ImageIcon, ChevronRight, Search, Loader, Unlink, CircleDot, Check } from 'lucide-react';
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
import { STATUS_COLORS } from '../../config/mapTheme';
import { buildPseudoNode, createLinkByNodes, LINK_ITEMS, unlinkByEdge } from './linkMutations';

// ── Menu config ──────────────────────────────────────────────────────────────

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
  cluster:  (id, slug) => clustersApi.update(id, { icon_slug: slug }),
  hardware: (id, slug) => hardwareApi.update(id, { vendor_icon_slug: slug }),
  compute:  (id, slug) => computeUnitsApi.update(id, { icon_slug: slug }),
  service:  (id, slug) => servicesApi.update(id, { icon_slug: slug }),
  storage:  (id, slug) => storageApi.update(id, { icon_slug: slug }),
  network:  (id, slug) => networksApi.update(id, { icon_slug: slug }),
  misc:     (id, slug) => miscApi.update(id, { icon_slug: slug }),
  external: (id, slug) => externalNodesApi.update(id, { icon_slug: slug }),
};

const ICON_SUPPORTED_TYPES = new Set(['cluster', 'hardware', 'compute', 'service', 'storage', 'network', 'misc', 'external']);

// ── Status update helpers ────────────────────────────────────────────────────

const UPDATE_STATUS_API = {
  hardware: (id, val) => hardwareApi.update(id, { status_override: val || null }),
  compute:  (id, val) => computeUnitsApi.update(id, { status_override: val || null }),
  service:  (id, val) => servicesApi.update(id, { status: val }),
};

const STATUS_OPTIONS_BY_TYPE = {
  hardware: [
    { value: '',            label: 'Auto (derived)' },
    { value: 'online',      label: 'Online' },
    { value: 'offline',     label: 'Offline' },
    { value: 'degraded',    label: 'Degraded' },
    { value: 'maintenance', label: 'Maintenance' },
  ],
  compute: [
    { value: '',            label: 'Auto (derived)' },
    { value: 'running',     label: 'Running' },
    { value: 'stopped',     label: 'Stopped' },
    { value: 'degraded',    label: 'Degraded' },
    { value: 'maintenance', label: 'Maintenance' },
  ],
  service: [
    { value: 'running',     label: 'Running' },
    { value: 'stopped',     label: 'Stopped' },
    { value: 'degraded',    label: 'Degraded' },
    { value: 'maintenance', label: 'Maintenance' },
  ],
};

const STATUS_SUPPORTED_TYPES = new Set(['hardware', 'compute', 'service']);

function getLabel(entity) {
  return entity.name || entity.hostname || entity.slug || entity.cidr || `#${entity.id}`;
}

function getSublabel(entity, type) {
  if (type === 'hardware') return entity.vendor || entity.ip_address || null;
  if (type === 'compute')  return entity.ip_address || entity.kind || null;
  if (type === 'service')  return entity.slug || entity.status || null;
  if (type === 'storage')  return entity.kind || (entity.capacity_gb ? `${entity.capacity_gb} GB` : null);
  if (type === 'network')  return entity.cidr || null;
  if (type === 'misc')     return entity.kind || null;
  if (type === 'cluster')  return entity.environment || (entity.member_count > -1 ? `${entity.member_count} members` : null);
  if (type === 'external') return entity.provider || entity.ip_address || null;
  return null;
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
  const [statusOpen, setStatusOpen] = useState(false);
  const [settingStatus, setSettingStatus] = useState(false);

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
      await createLinkByNodes(node, buildPseudoNode(activeSubmenu, targetEntity.id), true);
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
      await unlinkByEdge(edge);
      toast.success('Unlinked.');
      onLinkSuccess();
    } catch (err) {
      toast.error(err.message || 'Failed to unlink.');
      setUnlinkingEdgeId(null);
    }
  }

  async function handleSetStatus(value) {
    const api = UPDATE_STATUS_API[node.originalType];
    if (!api) return;
    setSettingStatus(true);
    try {
      await api(node._refId, value);
      toast.success(value ? `Status set to "${value}"` : 'Status reset to auto');
      onLinkSuccess();
    } catch (err) {
      toast.error(err.message || 'Failed to update status');
      setSettingStatus(false);
    }
  }

  const connectedEdges = (edges ?? []).filter(
    e => e.source === node.id || e.target === node.id
  );
  const linkedItems = connectedEdges.map(edge => {
    const otherId   = edge.source === node.id ? edge.target : edge.source;
    const otherNode = (nodes ?? []).find(n => n.id === otherId);
    return { edge, label: getLabel(otherNode?.data) ?? otherId };
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
          borderRadius: 12,
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
          <div style={{ fontSize: 10, color: 'var(--color-text)', textTransform: 'capitalize', marginTop: 1 }}>
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
                background: activeSubmenu === targetType ? 'var(--color-secondary)' : 'var(--color-surface)',
                border: 'none',
                color: 'var(--color-text)',
                padding: '9px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                fontSize: 12,
                textAlign: 'left',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { if (activeSubmenu !== targetType) e.currentTarget.style.background = 'var(--color-secondary)'; }}
              onMouseLeave={e => { if (activeSubmenu !== targetType) e.currentTarget.style.background = 'var(--color-surface)'; }}
            >
              <Link2 size={13} style={{ color: 'var(--color-text)', flexShrink: 0 }} />
              <span style={{ flex: 1 }}>{LINK_LABEL[targetType]}</span>
              <ChevronRight
                size={12}
                style={{
                  color: 'var(--color-text)',
                  transform: activeSubmenu === targetType ? 'rotate(90deg)' : 'none',
                  transition: 'transform 0.15s',
                  flexShrink: 0,
                }}
              />
            </button>

            {/* Inline submenu */}
            {activeSubmenu === targetType && (
              <div style={{ background: 'var(--color-surface)', borderTop: '1px solid var(--color-border)' }}>
                {/* Search */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-secondary)' }}>
                  <Search size={11} style={{ color: 'var(--color-text)', flexShrink: 0 }} />
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
                    <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--color-text)' }}>
                      {search ? 'No matches' : 'Nothing available'}
                    </div>
                  )}
                  {filteredOptions.map(entity => {
                    const label    = getLabel(entity);
                    const sublabel = getSublabel(entity, activeSubmenu);
                    return (
                      <button
                        key={entity.id}
                        onClick={() => handleSelect(entity)}
                        disabled={linking}
                        style={{
                          width: '100%',
                          background: 'var(--color-surface)',
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
                        onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-secondary)'; }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface)'; }}
                      >
                        <span style={{ fontWeight: 500 }}>{label}</span>
                        {sublabel && <span style={{ color: 'var(--color-text)', fontSize: 10 }}>{sublabel}</span>}
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
            <div style={{ padding: '4px 14px 2px', fontSize: 10, color: 'var(--color-text)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Unlink
            </div>
            {linkedItems.map(({ edge, label }) => (
              <button
                key={edge.id}
                onClick={() => handleUnlink(edge)}
                disabled={!!unlinkingEdgeId}
                style={{
                  width: '100%',
                  background: 'var(--color-surface)',
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
                onMouseEnter={e => { if (!unlinkingEdgeId) e.currentTarget.style.background = 'var(--color-secondary)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface)'; }}
              >
                <Unlink size={13} style={{ color: 'var(--color-text)', flexShrink: 0 }} />
                {unlinkingEdgeId === edge.id ? 'Unlinking…' : label}
              </button>
            ))}
          </>
        )}

        {/* Divider — only when both link items and Edit Icon are present */}
        {(linkItems.length > 0 || linkedItems.length > 0) && ICON_SUPPORTED_TYPES.has(node.originalType) && (
          <div style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }} />
        )}

        {/* Set Status — for hardware, compute, and service nodes */}
        {STATUS_SUPPORTED_TYPES.has(node.originalType) && (() => {
          const currentStatus = node.data?.status_override || node.data?.status || null;
          const statusOpts = STATUS_OPTIONS_BY_TYPE[node.originalType] || [];
          return (
            <>
              {(linkItems.length > 0 || linkedItems.length > 0) && !ICON_SUPPORTED_TYPES.has(node.originalType) && (
                <div style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }} />
              )}
              <button
                onClick={() => { setActiveSubmenu(null); setStatusOpen(prev => !prev); }}
                disabled={settingStatus}
                style={{
                  width: '100%',
                  background: statusOpen ? 'var(--color-secondary)' : 'var(--color-surface)',
                  border: 'none',
                  color: 'var(--color-text)',
                  padding: '9px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  cursor: 'pointer',
                  fontSize: 12,
                  textAlign: 'left',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => { if (!statusOpen) e.currentTarget.style.background = 'var(--color-secondary)'; }}
                onMouseLeave={e => { if (!statusOpen) e.currentTarget.style.background = 'var(--color-surface)'; }}
              >
                <CircleDot size={13} style={{ color: 'var(--color-text)', flexShrink: 0 }} />
                <span style={{ flex: 1 }}>Set Status</span>
                <ChevronRight
                  size={12}
                  style={{
                    color: 'var(--color-text)',
                    transform: statusOpen ? 'rotate(90deg)' : 'none',
                    transition: 'transform 0.15s',
                    flexShrink: 0,
                  }}
                />
              </button>
              {statusOpen && (
                <div style={{ background: 'var(--color-surface)', borderTop: '1px solid var(--color-border)' }}>
                  {statusOpts.map(opt => {
                    const isActive = opt.value
                      ? (currentStatus === opt.value)
                      : (!node.data?.status_override);
                    const dotColor = opt.value ? STATUS_COLORS[opt.value]?.border : 'var(--color-text-muted)';
                    return (
                      <button
                        key={opt.value}
                        onClick={() => handleSetStatus(opt.value)}
                        disabled={settingStatus}
                        style={{
                          width: '100%',
                          background: 'var(--color-surface)',
                          border: 'none',
                          color: 'var(--color-text)',
                          padding: '7px 14px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          cursor: settingStatus ? 'not-allowed' : 'pointer',
                          fontSize: 11,
                          textAlign: 'left',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-secondary)'; }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface)'; }}
                      >
                        <span style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: dotColor, flexShrink: 0,
                        }} />
                        <span style={{ flex: 1, fontWeight: isActive ? 600 : 400 }}>{opt.label}</span>
                        {isActive && <Check size={12} style={{ color: 'var(--color-primary)', flexShrink: 0 }} />}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          );
        })()}

        {/* Edit Icon — only for types that have an icon column in the backend */}
        {ICON_SUPPORTED_TYPES.has(node.originalType) && (
          <button
            onClick={() => { setActiveSubmenu(null); setShowIconPicker(true); }}
            style={{
              width: '100%',
              background: 'var(--color-surface)',
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
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-secondary)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface)'; }}
          >
            <ImageIcon size={13} style={{ color: 'var(--color-text)', flexShrink: 0 }} />
            Edit Icon
          </button>
        )}
      </div>

      {/* Icon picker modal */}
      {showIconPicker && (
        <IconPickerModal
          currentSlug={node.data?.icon_slug ?? null}
          onSelect={handleIconSelect}
          onClose={() => setShowIconPicker(false)}
        />
      )}

    </>
  );
}

MapContextMenu.propTypes = {
  node: PropTypes.object.isRequired,
  position: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  onLinkSuccess: PropTypes.func.isRequired,
  edges: PropTypes.array,
  nodes: PropTypes.array,
};
