/**
 * BulkActionsDrawer — the primary UI for the Enhanced Bulk Review workflow.
 *
 * Presents 7 intelligent sections for multi-select discovery results:
 *  1. Group Info (cluster name, description)
 *  2. Network assignment (inferred CIDR, existing network, or new)
 *  3. Vendor catalog typeahead
 *  4. Role assignment
 *  5. Rack & U-slot placement
 *  6. Service detection summary
 *  7. Duplicate detection warnings
 *
 * Plus a mini topology preview via BulkPreviewMap.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { AnimatePresence, motion } from 'framer-motion';
import {
  X, ChevronDown, ChevronRight, Server, Network, Tag,
  Shield, HardDrive, Layers, AlertTriangle, MapPin, Zap,
  Search, Check, Info
} from 'lucide-react';
import { suggestBulkActions, enhancedBulkMerge, getVendorCatalog } from '../../api/discovery.js';
import { networksApi, clustersApi } from '../../api/client.jsx';
import { useToast } from '../common/Toast';
import BulkPreviewMap from './BulkPreviewMap.jsx';

// ── Role options matching ReviewDrawer ──────────────────────────────────────
const ROLE_OPTIONS = ['server', 'router', 'switch', 'firewall', 'ap', 'nas', 'workstation', 'other'];

// ── Collapsible section wrapper ────────────────────────────────────────────
function Section({ icon: Icon, title, badge, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ borderBottom: '1px solid var(--color-border)' }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '12px 0', background: 'none', border: 'none',
          cursor: 'pointer', color: 'var(--color-text)', fontSize: 13, fontWeight: 600,
        }}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Icon size={15} style={{ color: 'var(--color-primary)', flexShrink: 0 }} />
        <span style={{ flex: 1, textAlign: 'left' }}>{title}</span>
        {badge != null && (
          <span style={{
            fontSize: 10, padding: '1px 7px', borderRadius: 8,
            background: 'rgba(0,212,255,0.12)', color: 'var(--color-primary)',
            border: '1px solid rgba(0,212,255,0.25)', fontWeight: 600,
          }}>{badge}</span>
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ paddingBottom: 14 }}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

Section.propTypes = {
  icon: PropTypes.elementType.isRequired, title: PropTypes.string.isRequired,
  badge: PropTypes.node, defaultOpen: PropTypes.bool, children: PropTypes.node,
};

// ── Main Drawer ────────────────────────────────────────────────────────────
export default function BulkActionsDrawer({ results, onClose, onComplete }) {
  const toast = useToast();

  // Suggestions from backend intelligence layer
  const [suggestions, setSuggestions] = useState(null);
  const [loadingSuggestions, setLoadingSuggestions] = useState(true);

  // Vendor catalog
  const [vendorCatalog, setVendorCatalog] = useState({});
  const [catalogSearch, setCatalogSearch] = useState('');

  // Existing entities for linking
  const [existingNetworks, setExistingNetworks] = useState([]);
  const [existingClusters, setExistingClusters] = useState([]);

  // ── Form state ───────────────────────────────────────────────────────────
  // Cluster
  const [clusterEnabled, setClusterEnabled] = useState(false);
  const [clusterName, setClusterName] = useState('');
  const [clusterDesc, setClusterDesc] = useState('');

  // Network
  const [networkMode, setNetworkMode] = useState('none'); // 'none' | 'new' | 'existing'
  const [networkName, setNetworkName] = useState('');
  const [networkCidr, setNetworkCidr] = useState('');
  const [networkVlan, setNetworkVlan] = useState('');
  const [networkGateway, setNetworkGateway] = useState('');
  const [existingNetworkId, setExistingNetworkId] = useState(null);

  // Rack
  const [rackId, setRackId] = useState(null);

  // Per-node assignments
  const [assignments, setAssignments] = useState({});

  // Global role override
  const [globalRole, setGlobalRole] = useState('');

  // Service creation toggle
  const [createServices, setCreateServices] = useState(false);

  // Submit state
  const [submitting, setSubmitting] = useState(false);

  // Stable ref to toast so we don't re-trigger the effect when ToastProvider re-renders
  const toastRef = useRef(toast);
  useEffect(() => { toastRef.current = toast; }, [toast]);

  // ── Load suggestions, catalog, existing entities ─────────────────────────
  useEffect(() => {
    const abortController = new AbortController();
    const ids = results.map((r) => r.id);

    setLoadingSuggestions(true);
    suggestBulkActions({ result_ids: ids })
      .then((res) => {
        if (abortController.signal.aborted) return;
        const s = res.data;
        setSuggestions(s);

        // Pre-fill cluster suggestion
        if (s.clusters?.length) {
          setClusterEnabled(true);
          setClusterName(s.clusters[0].name || '');
          setClusterDesc(s.clusters[0].description || '');
        }

        // Pre-fill network suggestion
        if (s.networks?.length) {
          const net = s.networks[0];
          if (net.existing_id) {
            setNetworkMode('existing');
            setExistingNetworkId(net.existing_id);
          } else {
            setNetworkMode('new');
            setNetworkCidr(net.cidr || '');
            setNetworkName(net.name || '');
            setNetworkGateway(net.gateway_guess || '');
          }
        }

        // Pre-fill per-node vendor/role from catalog matches
        if (s.catalog_matches) {
          const initial = {};
          for (const [resultId, match] of Object.entries(s.catalog_matches)) {
            initial[resultId] = {
              vendor: match.vendor_key || '',
              vendor_catalog_key: match.vendor_key || '',
              model_catalog_key: match.device_key || '',
              vendor_icon_slug: match.icon || '',
              role: match.role || '',
            };
          }
          setAssignments(initial);
        }
      })
      .catch(() => { if (!abortController.signal.aborted) toastRef.current.error('Failed to load suggestions'); })
      .finally(() => { if (!abortController.signal.aborted) setLoadingSuggestions(false); });

    getVendorCatalog()
      .then((res) => { if (!abortController.signal.aborted) setVendorCatalog(res.data || {}); })
      .catch(() => {});

    networksApi.list({ limit: 200 })
      .then((res) => { if (!abortController.signal.aborted) setExistingNetworks(Array.isArray(res.data) ? res.data : (res.data?.items ?? [])); })
      .catch(() => {});

    clustersApi.list({ limit: 200 })
      .then((res) => { if (!abortController.signal.aborted) setExistingClusters(Array.isArray(res.data) ? res.data : (res.data?.items ?? [])); })
      .catch(() => {});

    return () => { abortController.abort(); };
  }, [results]);

  // ── Helper: update a single node assignment ──────────────────────────────
  const setNodeAssignment = useCallback((resultId, field, value) => {
    setAssignments((prev) => ({
      ...prev,
      [resultId]: { ...prev[resultId], [field]: value },
    }));
  }, []);

  // ── Apply global role to all nodes ───────────────────────────────────────
  const applyGlobalRole = useCallback(() => {
    if (!globalRole) return;
    setAssignments((prev) => {
      const next = { ...prev };
      for (const r of results) {
        next[r.id] = { ...next[r.id], role: globalRole };
      }
      return next;
    });
  }, [globalRole, results]);

  // ── Vendor catalog filtered list ─────────────────────────────────────────
  const filteredVendors = useMemo(() => {
    if (!vendorCatalog || typeof vendorCatalog !== 'object') return [];
    const entries = Object.entries(vendorCatalog);
    if (!catalogSearch.trim()) return entries.slice(0, 20);
    const q = catalogSearch.toLowerCase();
    return entries.filter(([key, v]) =>
      key.toLowerCase().includes(q) || (v.name || '').toLowerCase().includes(q)
    ).slice(0, 20);
  }, [vendorCatalog, catalogSearch]);

  // ── Submit ───────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = {
        result_ids: results.map((r) => r.id),
        create_services: createServices,
        assignments: results.map((r) => ({
          result_id: r.id,
          ...assignments[r.id],
          role: assignments[r.id]?.role || globalRole || undefined,
        })).filter((a) => Object.keys(a).length > 1), // only send if has overrides beyond result_id
      };

      if (clusterEnabled && clusterName.trim()) {
        payload.cluster = {
          name: clusterName.trim(),
          description: clusterDesc.trim() || undefined,
        };
      }

      if (networkMode === 'new' && networkName.trim()) {
        payload.network = {
          name: networkName.trim(),
          cidr: networkCidr.trim() || undefined,
          vlan_id: networkVlan ? Number.parseInt(networkVlan, 10) : undefined,
          gateway: networkGateway.trim() || undefined,
        };
      } else if (networkMode === 'existing' && existingNetworkId) {
        payload.network = { name: '', existing_id: existingNetworkId };
      }

      if (rackId) payload.rack_id = rackId;

      const res = await enhancedBulkMerge(payload);
      const { accepted = 0, skipped = 0 } = res.data;
      toast.success(`${accepted} host${accepted !== 1 ? 's' : ''} merged${skipped ? `, ${skipped} skipped` : ''}`);
      onComplete(res.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || 'Bulk merge failed');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Derived data ─────────────────────────────────────────────────────────
  const duplicates = suggestions?.duplicates || [];
  // Backend returns services as {result_id: [{port, name, category, ...}]}.
  // Flatten + deduplicate by port for the UI pills.
  const servicesByPort = useMemo(() => {
    const raw = suggestions?.services || {};
    const seen = new Map();
    for (const svcList of Object.values(raw)) {
      if (!Array.isArray(svcList)) continue;
      for (const svc of svcList) {
        if (!seen.has(svc.port)) seen.set(svc.port, svc);
      }
    }
    return Array.from(seen.values());
  }, [suggestions?.services]);
  const roleSummary = suggestions?.role_summary || {};
  const rackSuggestions = suggestions?.rack_suggestions || [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed', inset: 0, zIndex: 950,
        background: 'rgba(0,0,0,0.65)',
        display: 'flex', justifyContent: 'flex-end',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
    >
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: 'spring', damping: 28, stiffness: 300 }}
        style={{
          width: 640, maxWidth: '100vw',
          background: 'var(--color-surface)',
          borderLeft: '1px solid var(--color-border)',
          display: 'flex', flexDirection: 'column', height: '100%',
        }}
      >
        {/* ── Header ──────────────────────────────────────────────── */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid var(--color-border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
              Bulk Actions
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--color-text-muted)' }}>
              {results.length} host{results.length !== 1 ? 's' : ''} selected
            </p>
          </div>
          <button type="button" onClick={onClose} style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--color-text-muted)', padding: 4,
          }}>
            <X size={18} />
          </button>
        </div>

        {/* ── Body (scrollable) ───────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 24px' }}>
          {loadingSuggestions ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 0', color: 'var(--color-text-muted)', fontSize: 13 }}>
              Analyzing {results.length} hosts…
            </div>
          ) : (
            <>
              {/* ─── 1. Cluster ────────────────────────────────────── */}
              <Section icon={Layers} title="Cluster Grouping" badge={suggestions?.clusters?.length || null} defaultOpen={!!suggestions?.clusters?.length}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 10, cursor: 'pointer' }}>
                  <input type="checkbox" checked={clusterEnabled} onChange={(e) => setClusterEnabled(e.target.checked)} />
                  Create or assign a hardware cluster
                </label>
                {clusterEnabled && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <input className="form-input" placeholder="Cluster name" value={clusterName} onChange={(e) => setClusterName(e.target.value)} />
                    <input className="form-input" placeholder="Description (optional)" value={clusterDesc} onChange={(e) => setClusterDesc(e.target.value)} />
                    {existingClusters.length > 0 && (
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        <Info size={11} style={{ display: 'inline', marginRight: 4 }} />
                        If a cluster with this name exists, hosts will be added to it.
                      </div>
                    )}
                  </div>
                )}
              </Section>

              {/* ─── 2. Network ────────────────────────────────────── */}
              <Section icon={Network} title="Network Assignment"
                badge={suggestions?.networks?.length || null}
                defaultOpen={!!suggestions?.networks?.length}
              >
                <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
                  {['none', 'new', 'existing'].map((m) => (
                    <label key={m} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, cursor: 'pointer' }}>
                      <input type="radio" name="networkMode" value={m} checked={networkMode === m} onChange={() => setNetworkMode(m)} />
                      {m === 'none' ? 'Skip' : m === 'new' ? 'Create new' : 'Link existing'}
                    </label>
                  ))}
                </div>

                {networkMode === 'new' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <input className="form-input" placeholder="Network name" value={networkName} onChange={(e) => setNetworkName(e.target.value)} />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input className="form-input" placeholder="CIDR (e.g. 10.0.0.0/24)" value={networkCidr} onChange={(e) => setNetworkCidr(e.target.value)} style={{ flex: 1 }} />
                      <input className="form-input" placeholder="VLAN" value={networkVlan} onChange={(e) => setNetworkVlan(e.target.value)} style={{ width: 80 }} />
                    </div>
                    <input className="form-input" placeholder="Gateway (e.g. 10.0.0.1)" value={networkGateway} onChange={(e) => setNetworkGateway(e.target.value)} />
                  </div>
                )}

                {networkMode === 'existing' && (
                  <select className="form-input" value={existingNetworkId || ''} onChange={(e) => setExistingNetworkId(e.target.value ? Number.parseInt(e.target.value, 10) : null)}>
                    <option value="">Select a network…</option>
                    {existingNetworks.map((n) => (
                      <option key={n.id} value={n.id}>{n.name}{n.cidr ? ` (${n.cidr})` : ''}</option>
                    ))}
                  </select>
                )}

                {suggestions?.networks?.[0]?.cidr && networkMode !== 'none' && (
                  <div style={{ marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
                    <Zap size={11} style={{ display: 'inline', marginRight: 4, color: 'var(--color-primary)' }} />
                    Inferred: {suggestions.networks[0].cidr}
                    {suggestions.networks[0].name && ` → matches "${suggestions.networks[0].name}"`}
                  </div>
                )}
              </Section>

              {/* ─── 3. Vendor Catalog ─────────────────────────────── */}
              <Section icon={Tag} title="Vendor Matching" badge={Object.keys(suggestions?.catalog_matches || {}).length || null}>
                <div style={{ marginBottom: 8, position: 'relative' }}>
                  <Search size={14} style={{ position: 'absolute', left: 8, top: 9, color: 'var(--color-text-muted)' }} />
                  <input
                    className="form-input"
                    placeholder="Search vendor catalog…"
                    value={catalogSearch}
                    onChange={(e) => setCatalogSearch(e.target.value)}
                    style={{ paddingLeft: 28 }}
                  />
                </div>
                {filteredVendors.length > 0 && (
                  <div style={{ maxHeight: 160, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 4 }}>
                    {filteredVendors.map(([key, v]) => (
                      <div
                        key={key}
                        style={{
                          padding: '6px 10px', fontSize: 12, cursor: 'pointer',
                          borderBottom: '1px solid var(--color-border)',
                          background: 'var(--color-surface)',
                        }}
                        onClick={() => {
                          // Apply vendor to all un-assigned nodes
                          setAssignments((prev) => {
                            const next = { ...prev };
                            for (const r of results) {
                              if (!next[r.id]?.vendor_catalog_key) {
                                next[r.id] = {
                                  ...next[r.id],
                                  vendor: v.name || key,
                                  vendor_catalog_key: key,
                                  vendor_icon_slug: v.icon_slug || '',
                                };
                              }
                            }
                            return next;
                          });
                          toast.info(`Applied ${v.name || key} to unassigned hosts`);
                        }}
                        onMouseOver={(e) => { e.currentTarget.style.background = 'var(--color-bg)'; }}
                        onMouseOut={(e) => { e.currentTarget.style.background = 'var(--color-surface)'; }}
                      >
                        <strong>{v.name || key}</strong>
                        {v.device_count != null && <span style={{ color: 'var(--color-text-muted)', marginLeft: 8 }}>{v.device_count} devices</span>}
                      </div>
                    ))}
                  </div>
                )}
                {/* Show auto-detected vendor matches */}
                {suggestions?.catalog_matches && Object.keys(suggestions.catalog_matches).length > 0 && (
                  <div style={{ marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
                    <Check size={11} style={{ display: 'inline', marginRight: 4, color: '#22c55e' }} />
                    {Object.keys(suggestions.catalog_matches).length} host(s) auto-matched to vendor catalog
                  </div>
                )}
              </Section>

              {/* ─── 4. Role Assignment ────────────────────────────── */}
              <Section icon={Shield} title="Role Assignment" badge={Object.keys(roleSummary).length || null}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
                  <select className="form-input" value={globalRole} onChange={(e) => setGlobalRole(e.target.value)} style={{ flex: 1, fontSize: 12 }}>
                    <option value="">Apply role to all…</option>
                    {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <button type="button" className="btn btn-secondary" style={{ fontSize: 11 }} onClick={applyGlobalRole} disabled={!globalRole}>
                    Apply
                  </button>
                </div>
                {Object.keys(roleSummary).length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {Object.entries(roleSummary).map(([role, ids]) => (
                      <span key={role} style={{
                        padding: '2px 8px', borderRadius: 4,
                        background: 'rgba(107,114,128,0.15)', border: '1px solid rgba(107,114,128,0.3)',
                      }}>
                        {role}: {Array.isArray(ids) ? ids.length : ids}
                      </span>
                    ))}
                  </div>
                )}
              </Section>

              {/* ─── 5. Rack Assignment ────────────────────────────── */}
              <Section icon={HardDrive} title="Rack Placement" badge={rackSuggestions.length || null}>
                {rackSuggestions.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {rackSuggestions.map((rs) => (
                      <label key={rs.rack_id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, cursor: 'pointer' }}>
                        <input type="radio" name="rackId" value={rs.rack_id} checked={rackId === rs.rack_id} onChange={() => setRackId(rs.rack_id)} />
                        <span>
                          <strong>{rs.rack_name}</strong>
                          <span style={{ color: 'var(--color-text-muted)', marginLeft: 6 }}>
                            {rs.free_u} free U · {rs.height_u}U rack
                          </span>
                        </span>
                      </label>
                    ))}
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, cursor: 'pointer', color: 'var(--color-text-muted)' }}>
                      <input type="radio" name="rackId" value="" checked={rackId === null} onChange={() => setRackId(null)} />
                      No rack assignment
                    </label>
                  </div>
                ) : (
                  <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
                    No racks with available slots found.
                  </p>
                )}
              </Section>

              {/* ─── 6. Services ───────────────────────────────────── */}
              <Section icon={Zap} title="Detected Services" badge={servicesByPort.length || null}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, cursor: 'pointer', marginBottom: 10 }}>
                  <input type="checkbox" checked={createServices} onChange={(e) => setCreateServices(e.target.checked)} />
                  Auto-create service entities from detected ports
                </label>
                {servicesByPort.length > 0 ? (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {servicesByPort.map((svc) => (
                      <span key={svc.port} style={{
                        padding: '2px 8px', borderRadius: 4, fontSize: 11,
                        background: 'rgba(14,138,138,0.12)', color: '#0eb8b8',
                        border: '1px solid rgba(14,138,138,0.3)',
                      }}>
                        {typeof svc.name === 'string' ? svc.name : `Port ${svc.port}`} :{svc.port}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>No services detected on open ports.</p>
                )}
              </Section>

              {/* ─── 7. Duplicates ─────────────────────────────────── */}
              {duplicates.length > 0 && (
                <Section icon={AlertTriangle} title="Duplicate Warnings" badge={duplicates.length} defaultOpen>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {duplicates.map((d, i) => (
                      <div key={i} style={{
                        padding: '8px 10px', borderRadius: 4, fontSize: 12,
                        background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
                        color: '#f59e0b',
                      }}>
                        <AlertTriangle size={12} style={{ display: 'inline', marginRight: 6 }} />
                        {d.ip || d.mac}: {d.reason || 'Matches existing entity'}
                        {d.existing_name && <span style={{ color: 'var(--color-text-muted)', marginLeft: 4 }}>({d.existing_name})</span>}
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* ─── Per-node assignment table ─────────────────────── */}
              <Section icon={Server} title="Per-Host Overrides" defaultOpen={results.length <= 10}>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                    <thead>
                      <tr>
                        {['IP', 'Hostname', 'Role', 'Vendor', 'Name'].map((h) => (
                          <th key={h} style={{
                            textAlign: 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600,
                            textTransform: 'uppercase', letterSpacing: '0.05em',
                            color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)',
                          }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((r) => {
                        const a = assignments[r.id] || {};
                        return (
                          <tr key={r.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                            <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 11 }}>{r.ip_address}</td>
                            <td style={{ padding: '6px 8px' }}>{r.hostname || '—'}</td>
                            <td style={{ padding: '6px 8px' }}>
                              <select
                                className="form-input"
                                value={a.role || ''}
                                onChange={(e) => setNodeAssignment(r.id, 'role', e.target.value)}
                                style={{ fontSize: 11, padding: '2px 4px', width: 90 }}
                              >
                                <option value="">auto</option>
                                {ROLE_OPTIONS.map((ro) => <option key={ro} value={ro}>{ro}</option>)}
                              </select>
                            </td>
                            <td style={{ padding: '6px 8px', fontSize: 11 }}>{a.vendor || r.os_vendor || '—'}</td>
                            <td style={{ padding: '6px 8px' }}>
                              <input
                                className="form-input"
                                value={a.name || ''}
                                placeholder={r.hostname || r.ip_address}
                                onChange={(e) => setNodeAssignment(r.id, 'name', e.target.value)}
                                style={{ fontSize: 11, padding: '2px 6px', width: 110 }}
                              />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Section>

              {/* ─── Mini map preview ──────────────────────────────── */}
              <Section icon={MapPin} title="Topology Preview">
                <div style={{ height: 260, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--color-border)' }}>
                  <BulkPreviewMap
                    results={results}
                    clusterName={clusterEnabled ? clusterName : null}
                    networkName={networkMode !== 'none' ? (networkMode === 'existing'
                      ? existingNetworks.find((n) => n.id === existingNetworkId)?.name
                      : networkName) : null}
                    assignments={assignments}
                  />
                </div>
              </Section>
            </>
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────────── */}
        <div style={{
          padding: '14px 24px', borderTop: '1px solid var(--color-border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          background: 'var(--color-surface)',
        }}>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
              {results.length} host{results.length !== 1 ? 's' : ''}
            </span>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={submitting}
              style={{ fontWeight: 600 }}
            >
              {submitting ? 'Merging…' : `Accept & Merge ${results.length} Host${results.length !== 1 ? 's' : ''} →`}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

BulkActionsDrawer.propTypes = {
  results:    PropTypes.arrayOf(PropTypes.object).isRequired,
  onClose:    PropTypes.func.isRequired,
  onComplete: PropTypes.func.isRequired,
};
