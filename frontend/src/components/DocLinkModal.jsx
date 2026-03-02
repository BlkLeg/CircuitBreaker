import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  hardwareApi,
  servicesApi,
  computeUnitsApi,
  storageApi,
  networksApi,
  environmentsApi,
  docsApi,
} from '../api/client';
import { useToast } from './common/Toast';
import logger from '../utils/logger';

// ── Entity type config ─────────────────────────────────────────────────────

const ENTITY_TYPES = [
  { key: 'hardware',     label: 'Hardware',     icon: '🖥',  api: (q) => hardwareApi.list(q ? { q } : undefined) },
  { key: 'service',      label: 'Services',     icon: '⚙️',  api: (q) => servicesApi.list(q ? { q } : undefined) },
  { key: 'compute',      label: 'Compute',      icon: '💻',  api: (q) => computeUnitsApi.list(q ? { q } : undefined) },
  { key: 'storage',      label: 'Storage',      icon: '💾',  api: (q) => storageApi.list(q ? { q } : undefined) },
  { key: 'network',      label: 'Networks',     icon: '🌐',  api: (q) => networksApi.list(q ? { q } : undefined) },
  { key: 'environment',  label: 'Environments', icon: '🏷',  api: (q) => environmentsApi.list(q ? { q } : undefined) },
];

function getEntityName(entity, type) {
  return entity.name || entity.title || `#${entity.id}`;
}

function getEntitySub(entity, type) {
  if (type === 'hardware')    return entity.role || entity.vendor || '';
  if (type === 'service')     return entity.status || entity.category || '';
  if (type === 'compute')     return entity.kind || entity.os || '';
  if (type === 'storage')     return entity.kind || '';
  if (type === 'network')     return entity.cidr || '';
  if (type === 'environment') return entity.color || '';
  return '';
}

// ── Modal ─────────────────────────────────────────────────────────────────

/**
 * DocLinkModal — lets the user link a doc to any entity type.
 *
 * Props:
 *   docId       — ID of the doc being linked
 *   docTitle    — display name of the doc
 *   existingLinks — array of {entity_type, entity_id} already linked
 *   onClose     — close without changes
 *   onLinked    — called after a successful attach/detach to trigger refresh
 */
export default function DocLinkModal({ docId, docTitle, existingLinks = [], onClose, onLinked }) {
  const toast = useToast();
  const [activeType, setActiveType] = useState(ENTITY_TYPES[0].key);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [pending, setPending] = useState(null); // entity id currently being toggled
  const searchRef = useRef(null);
  const searchDebounce = useRef(null);

  // Set of already-linked entity ids for the current type
  const linkedIds = new Set(
    existingLinks
      .filter((l) => l.entity_type === activeType)
      .map((l) => l.entity_id)
  );

  const fetchItems = useCallback(async (type, q) => {
    const cfg = ENTITY_TYPES.find((t) => t.key === type);
    if (!cfg) return;
    setLoading(true);
    setItems([]);
    try {
      const res = await cfg.api(q || '');
      const data = res?.data ?? res ?? [];
      setItems(Array.isArray(data) ? data : []);
    } catch (err) {
      logger.error('DocLinkModal fetch:', err);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when tab or debounced search changes
  useEffect(() => {
    clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(() => {
      fetchItems(activeType, search);
    }, 200);
  }, [activeType, search, fetchItems]);

  // Focus search on open
  useEffect(() => {
    setTimeout(() => searchRef.current?.focus(), 60);
  }, []);

  const handleTabChange = (key) => {
    setActiveType(key);
    setSearch('');
  };

  const handleToggle = useCallback(async (entity) => {
    const isLinked = linkedIds.has(entity.id);
    setPending(entity.id);
    try {
      if (isLinked) {
        await docsApi.detach({ doc_id: docId, entity_type: activeType, entity_id: entity.id });
        toast.success(`Unlinked from ${getEntityName(entity, activeType)}`);
      } else {
        await docsApi.attach({ doc_id: docId, entity_type: activeType, entity_id: entity.id });
        toast.success(`Linked to ${getEntityName(entity, activeType)}`);
      }
      onLinked?.();
    } catch (err) {
      logger.error('DocLinkModal toggle:', err);
      toast.error(err?.response?.data?.detail || 'Link operation failed.');
    } finally {
      setPending(null);
    }
  }, [docId, activeType, linkedIds, toast, onLinked]);

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal doc-link-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Link document to entity"
      >
        {/* Header */}
        <div className="doc-link-modal-header">
          <div>
            <div className="doc-link-modal-title">Link to Entity</div>
            <div className="doc-link-modal-subtitle">
              Attach <em>"{docTitle}"</em> to a record in your lab
            </div>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Type tabs */}
        <div className="doc-link-tabs">
          {ENTITY_TYPES.map((t) => {
            const count = existingLinks.filter((l) => l.entity_type === t.key).length;
            return (
              <button
                key={t.key}
                className={`doc-link-tab${activeType === t.key ? ' active' : ''}`}
                onClick={() => handleTabChange(t.key)}
              >
                <span className="doc-link-tab-icon">{t.icon}</span>
                {t.label}
                {count > 0 && <span className="doc-link-tab-badge">{count}</span>}
              </button>
            );
          })}
        </div>

        {/* Search */}
        <div className="doc-link-search-wrap">
          <input
            ref={searchRef}
            className="doc-link-search"
            type="search"
            placeholder={`Search ${ENTITY_TYPES.find((t) => t.key === activeType)?.label ?? ''}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* List */}
        <div className="doc-link-list">
          {loading ? (
            <div className="doc-link-empty">Loading…</div>
          ) : items.length === 0 ? (
            <div className="doc-link-empty">No results{search ? ` for "${search}"` : ''}.</div>
          ) : (
            items.map((entity) => {
              const linked = linkedIds.has(entity.id);
              const busy   = pending === entity.id;
              const sub    = getEntitySub(entity, activeType);
              return (
                <div
                  key={entity.id}
                  className={`doc-link-item${linked ? ' linked' : ''}`}
                  onClick={() => !busy && handleToggle(entity)}
                >
                  <div className="doc-link-item-info">
                    <span className="doc-link-item-name">{getEntityName(entity, activeType)}</span>
                    {sub && <span className="doc-link-item-sub">{sub}</span>}
                  </div>
                  <button
                    className={`doc-link-item-btn${linked ? ' unlink' : ' link'}`}
                    disabled={busy}
                    onClick={(e) => { e.stopPropagation(); if (!busy) handleToggle(entity); }}
                    title={linked ? 'Remove link' : 'Add link'}
                  >
                    {busy ? '…' : linked ? '✕ Unlink' : '+ Link'}
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="doc-link-footer">
          <span className="doc-link-footer-hint">
            {existingLinks.length} total link{existingLinks.length !== 1 ? 's' : ''} on this doc
          </span>
          <button className="btn btn-sm" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
