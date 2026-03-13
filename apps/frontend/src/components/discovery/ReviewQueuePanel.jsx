/* eslint-disable security/detect-object-injection -- Map used for localEdits; merged keys from buildDefaultEdits */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Check, Layers, Map as MapIcon, RefreshCw, Server, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getPendingResults, mergeResult, enhancedBulkMerge } from '../../api/discovery.js';
import { createMonitor } from '../../api/monitor.js';
import { clustersApi } from '../../api/client.jsx';
import { useToast } from '../common/Toast';
import ReviewDrawer from './ReviewDrawer.jsx';
import { HARDWARE_ROLES } from '../../config/hardwareRoles.js';
import IconPickerModal, { IconImg } from '../common/IconPickerModal.jsx';
import NetworkSelectorDropdown from './NetworkSelectorDropdown.jsx';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Returns true when a scan result originated from the Docker source. */
function isDockerResult(r) {
  if (r.os_vendor === 'Docker') return true;
  try {
    const raw = r.raw_nmap_xml ? JSON.parse(r.raw_nmap_xml) : null;
    return raw?.source === 'docker';
  } catch {
    return false;
  }
}

/** Build initial per-row edit state. */
function buildDefaultEdits(r) {
  const docker = isDockerResult(r);
  return {
    monitor: r.state === 'new',
    ...(docker ? { iconSlug: 'docker', role: 'lxc' } : {}),
  };
}

// ── Tiny toggle switch ────────────────────────────────────────────────────────

function Toggle({ checked, onChange }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        width: 34,
        height: 18,
        borderRadius: 9,
        cursor: 'pointer',
        background: checked ? 'var(--color-primary)' : 'var(--color-border)',
        border: 'none',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: checked ? 18 : 2,
          width: 14,
          height: 14,
          borderRadius: 7,
          background: 'white',
          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          transition: 'left 0.15s',
        }}
      />
    </button>
  );
}

Toggle.propTypes = { checked: PropTypes.bool.isRequired, onChange: PropTypes.func.isRequired };

// ── State pill ────────────────────────────────────────────────────────────────

function StatePill({ state }) {
  const isConflict = state === 'conflict';
  return (
    <span
      style={{
        padding: '2px 7px',
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        background: isConflict ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
        color: isConflict ? '#f87171' : '#f59e0b',
        border: `1px solid ${isConflict ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`,
      }}
    >
      {isConflict ? 'Conflict' : 'New'}
    </span>
  );
}

StatePill.propTypes = { state: PropTypes.string.isRequired };

// ── Group-name prompt modal ───────────────────────────────────────────────────

function GroupNameModal({ kind, count, onConfirm, onCancel }) {
  const [name, setName] = useState('');
  const label = kind === 'stack' ? 'Stack' : 'Cluster';
  const placeholder = kind === 'stack' ? 'e.g. web-stack' : 'e.g. rack-01';
  const Icon = kind === 'stack' ? Layers : Server;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1200,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 10,
          padding: '28px 32px',
          width: 380,
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        }}
      >
        {/* Title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon size={18} style={{ color: 'var(--color-primary)' }} />
          <span style={{ fontSize: 15, fontWeight: 700 }}>
            Create {label}
            <span
              style={{
                marginLeft: 8,
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--color-text-muted)',
              }}
            >
              {count} device{count === 1 ? '' : 's'}
            </span>
          </span>
        </div>

        <p style={{ margin: 0, fontSize: 12, color: 'var(--color-text-muted)' }}>
          {kind === 'stack'
            ? 'Selected Docker containers will be accepted and grouped into a named Stack.'
            : 'Selected devices will be accepted and grouped into a named Hardware Cluster.'}
        </p>

        <input
          className="cb-input"
          autoFocus
          placeholder={placeholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && name.trim()) onConfirm(name.trim());
            if (e.key === 'Escape') onCancel();
          }}
          style={{ fontSize: 13, padding: '7px 10px' }}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: 12, padding: '6px 14px' }}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            style={{ fontSize: 12, padding: '6px 14px' }}
            disabled={!name.trim()}
            onClick={() => onConfirm(name.trim())}
          >
            Create {label}
          </button>
        </div>
      </div>
    </div>
  );
}

GroupNameModal.propTypes = {
  kind: PropTypes.oneOf(['cluster', 'stack']).isRequired,
  count: PropTypes.number.isRequired,
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

// ── Main component ────────────────────────────────────────────────────────────

export default function ReviewQueuePanel({ onCountChange }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [localEdits, setLocalEdits] = useState(() => new Map());
  const [drawerResult, setDrawerResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [iconPickerRowId, setIconPickerRowId] = useState(null);
  // null | 'cluster' | 'stack'
  const [groupPrompt, setGroupPrompt] = useState(null);
  // Synchronous lock — prevents double-click race before React re-renders the disabled state
  const opLock = useRef(false);
  const [sourceFilter, setSourceFilter] = useState('all'); // 'all' | 'docker' | 'network'
  const [selectedNetwork, setSelectedNetwork] = useState(null);
  const [pendingAccept, setPendingAccept] = useState(null); // { resultIds: number[] } | null

  const load = useCallback(() => {
    setLoading(true);
    getPendingResults({ limit: 200 })
      .then((res) => {
        const items = Array.isArray(res.data) ? res.data : (res.data?.results ?? []);
        const count = res.data?.total ?? items.length;
        setResults(items);
        setTotal(count);
        onCountChange?.(count);
        setLocalEdits((prev) => {
          const next = new Map(prev);
          for (const r of items) {
            const existing = next.get(r.id);
            if (existing) {
              // Back-fill any missing defaults without clobbering user edits
              const defaults = buildDefaultEdits(r);
              const merged = { ...existing };
              for (const [k, v] of Object.entries(defaults)) {
                if (merged[k] === undefined) merged[k] = v;
              }
              next.set(r.id, merged);
            } else {
              next.set(r.id, buildDefaultEdits(r));
            }
          }
          return next;
        });
      })
      .catch((err) => {
        console.error('Failed to fetch pending discovery results:', err);
      })
      .finally(() => setLoading(false));
  }, [onCountChange]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!pendingAccept) return;
    const handler = (e) => {
      if (e.key === 'Escape') setPendingAccept(null);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [pendingAccept]);

  const removeResult = useCallback(
    (id) => {
      setResults((prev) => {
        const next = prev.filter((r) => r.id !== id);
        setTotal(next.length);
        onCountChange?.(next.length);
        return next;
      });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    [onCountChange]
  );

  const removeResults = useCallback(
    (ids) => {
      setResults((prev) => {
        const next = prev.filter((r) => !ids.has(r.id));
        setTotal(next.length);
        onCountChange?.(next.length);
        return next;
      });
      setSelectedIds(new Set());
    },
    [onCountChange]
  );

  const setEdit = (id, field, value) => {
    setLocalEdits((prev) => {
      const next = new Map(prev);
      const cur = next.get(id) || {};
      next.set(id, { ...cur, [field]: value });
      return next;
    });
  };

  // ── Accept helpers ────────────────────────────────────────────────────────

  const _buildOverrides = (result, edits) => {
    const overrides = {
      name: edits.hostname ?? result.hostname ?? result.snmp_sys_name ?? result.ip_address,
      role: edits.role ?? (isDockerResult(result) ? 'lxc' : 'server'),
    };
    if (edits.iconSlug) overrides.vendor_icon_slug = edits.iconSlug;
    return overrides;
  };

  const _maybeCreateMonitor = async (entityId, edits) => {
    if (!entityId || !edits.monitor) return;
    try {
      await createMonitor({
        hardware_id: entityId,
        probe_methods: ['icmp', 'tcp', 'http'],
        interval_secs: 60,
        enabled: true,
      });
    } catch {
      // Monitor creation is best-effort
    }
  };

  // ── Shared helpers ────────────────────────────────────────────────────────

  /** Lock + unlock submitting state with the synchronous ref to stop double-clicks. */
  const _beginOp = () => {
    if (opLock.current) return false;
    opLock.current = true;
    setSubmitting(true);
    return true;
  };
  const _endOp = () => {
    opLock.current = false;
    setSubmitting(false);
  };

  /**
   * Run one mergeResult call and normalise the outcome:
   *   { id, result, edits, data, accepted: true }   — fresh accept
   *   { id, alreadyDone: true }                     — 409 (previously accepted/rejected)
   *   { id, error: Error }                           — genuine failure
   */
  const _mergeOne = async (id, result, edits, action, overrides) => {
    try {
      const res = await mergeResult(id, { action, overrides });
      return { id, result, edits, data: res.data, accepted: true };
    } catch (err) {
      if (err.statusCode === 409) {
        return { id, alreadyDone: true };
      }
      return { id, error: err };
    }
  };

  // ── Single-row actions ────────────────────────────────────────────────────

  const handleAccept = async (result) => {
    if (!_beginOp()) return;
    const edits = localEdits.get(result.id) || {};
    try {
      const outcome = await _mergeOne(
        result.id,
        result,
        edits,
        'accept',
        _buildOverrides(result, edits)
      );
      if (outcome.accepted) {
        const entityId = outcome.data?.entity_id ?? result.matched_entity_id ?? null;
        await _maybeCreateMonitor(entityId, edits);
        toast.success(`${result.ip_address} accepted`);
      } else if (outcome.alreadyDone) {
        toast.info(`${result.ip_address} was already processed`);
      } else {
        toast.error(outcome.error?.message || 'Failed to accept');
      }
      // Remove from queue regardless — if already done the item is stale
      if (outcome.accepted || outcome.alreadyDone) removeResult(result.id);
    } finally {
      _endOp();
    }
  };

  const handleReject = async (result) => {
    if (!_beginOp()) return;
    try {
      const outcome = await _mergeOne(result.id, result, {}, 'reject', {});
      if (outcome.accepted || outcome.alreadyDone) {
        toast.info(`${result.ip_address} rejected`);
        removeResult(result.id);
      } else {
        toast.error(outcome.error?.message || 'Failed to reject');
      }
    } finally {
      _endOp();
    }
  };

  // ── Bulk helpers (Promise.allSettled — never fail-fast) ───────────────────

  const _runBulkAccepts = async (ids) => {
    const snapshots = [...ids].map((id) => ({
      id,
      result: results.find((r) => r.id === id),
      edits: localEdits.get(id) || {},
    }));

    // Fire all merge requests concurrently; allSettled never rejects
    const settlements = await Promise.allSettled(
      snapshots.map(({ id, result: r, edits }) =>
        _mergeOne(id, r, edits, 'accept', _buildOverrides(r, edits))
      )
    );

    const fresh = [];
    const alreadyDoneIds = new Set();
    const errorCount = { n: 0 };

    settlements.forEach((s) => {
      const outcome = s.status === 'fulfilled' ? s.value : { id: null, error: s.reason };
      if (outcome.accepted) fresh.push(outcome);
      else if (outcome.alreadyDone) alreadyDoneIds.add(outcome.id);
      else errorCount.n += 1;
    });

    // Monitors for freshly merged items
    await Promise.all(
      fresh.map(({ result: r, edits, data }) => {
        const entityId = data?.entity_id ?? r?.matched_entity_id ?? null;
        return _maybeCreateMonitor(entityId, edits);
      })
    );

    const processedIds = new Set([...fresh.map((f) => f.id), ...alreadyDoneIds]);
    if (processedIds.size > 0) removeResults(processedIds);

    if (fresh.length > 0) toast.success(`${fresh.length} device(s) accepted`);
    if (alreadyDoneIds.size > 0)
      toast.info(`${alreadyDoneIds.size} already processed — removed from queue`);
    if (errorCount.n > 0) toast.error(`${errorCount.n} device(s) could not be accepted`);

    return fresh;
  };

  const handleBulkAccept = async (ids) => {
    if (ids.size === 0 || !_beginOp()) return;
    try {
      await _runBulkAccepts(ids);
    } finally {
      _endOp();
    }
  };

  const handleNetworkAccept = useCallback(async () => {
    if (!pendingAccept || !selectedNetwork) return;
    if (opLock.current) return;
    opLock.current = true;
    setSubmitting(true);
    try {
      const networkPayload = selectedNetwork.id
        ? { existing_id: selectedNetwork.id }
        : {
            name: selectedNetwork.name,
            ...(selectedNetwork.cidr ? { cidr: selectedNetwork.cidr } : {}),
          };

      await enhancedBulkMerge({
        result_ids: pendingAccept.resultIds,
        network: networkPayload,
      });

      setPendingAccept(null);
      setSelectedIds(new Set());
      toast.success(
        `Accepted ${pendingAccept.resultIds.length} result${pendingAccept.resultIds.length === 1 ? '' : 's'} → ${selectedNetwork.name}`
      );
      load();
    } catch {
      toast.error('Failed to accept results');
      setPendingAccept(null);
    } finally {
      opLock.current = false;
      setSubmitting(false);
    }
  }, [pendingAccept, selectedNetwork, toast, load]);

  const handleBulkReject = async (ids) => {
    if (ids.size === 0 || !_beginOp()) return;
    try {
      const settlements = await Promise.allSettled(
        [...ids].map((id) => _mergeOne(id, null, {}, 'reject', {}))
      );
      const done = new Set();
      let errorCount = 0;
      settlements.forEach((s) => {
        const o = s.status === 'fulfilled' ? s.value : { error: s.reason };
        if (o.accepted || o.alreadyDone) done.add(o.id);
        else errorCount += 1;
      });
      if (done.size > 0) {
        removeResults(done);
        toast.info(`${done.size} device(s) rejected`);
      }
      if (errorCount > 0) toast.error(`${errorCount} device(s) could not be rejected`);
    } finally {
      _endOp();
    }
  };

  /**
   * Accept all ids, create a hardware cluster/stack named `groupName`,
   * then link all resolved entity IDs as members.
   */
  const handleBulkGroup = async (ids, groupName, kind) => {
    if (ids.size === 0 || !_beginOp()) return;
    setGroupPrompt(null);
    const label = kind === 'stack' ? 'Stack' : 'Cluster';
    try {
      const fresh = await _runBulkAccepts(ids);

      const entityIds = fresh
        .map(({ result: r, data }) => data?.entity_id ?? r?.matched_entity_id ?? null)
        .filter(Boolean);

      if (entityIds.length > 0) {
        const clusterRes = await clustersApi.create({
          name: groupName,
          description:
            kind === 'stack'
              ? 'Docker Stack (auto-created from Review Queue)'
              : 'Hardware Cluster (auto-created from Review Queue)',
        });
        const clusterId = clusterRes.data?.id;
        if (clusterId) {
          await Promise.allSettled(
            entityIds.map((hwId) => clustersApi.addMember(clusterId, { hardware_id: hwId }))
          );
          toast.success(`${label} "${groupName}" created with ${entityIds.length} device(s)`);
        }
      }
    } catch (err) {
      toast.error(err?.message || `Failed to create ${label}`);
    } finally {
      _endOp();
    }
  };

  const displayResults =
    sourceFilter === 'docker'
      ? results.filter(isDockerResult)
      : sourceFilter === 'network'
        ? results.filter((r) => !isDockerResult(r))
        : results;

  const allSelected = displayResults.length > 0 && selectedIds.size === displayResults.length;
  const someSelected = selectedIds.size > 0;

  const toggleSelectAll = () => {
    setSelectedIds(allSelected ? new Set() : new Set(displayResults.map((r) => r.id)));
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (loading) {
    return (
      <div style={{ padding: '32px 24px', color: 'var(--color-text-muted)', fontSize: 13 }}>
        Loading…
      </div>
    );
  }

  const iconPickerResult =
    iconPickerRowId === null ? null : displayResults.find((r) => r.id === iconPickerRowId);

  return (
    <div
      style={{
        padding: '20px 24px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        height: '100%',
        minHeight: 0,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Review Queue</h2>
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          {sourceFilter !== 'all'
            ? `${displayResults.length} shown · ${total} pending`
            : `${total} pending`}
        </span>

        {/* Source filter chips */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          {[
            { key: 'all', label: 'All' },
            { key: 'docker', label: 'Docker', icon: '/icons/vendors/docker.svg' },
            { key: 'network', label: 'Network' },
          ].map(({ key, label, icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setSourceFilter(key)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 8px',
                fontSize: 11,
                fontWeight: 600,
                borderRadius: 4,
                border: `1px solid ${sourceFilter === key ? 'var(--color-primary)' : 'var(--color-border)'}`,
                background:
                  sourceFilter === key
                    ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)'
                    : 'transparent',
                color: sourceFilter === key ? 'var(--color-primary)' : 'var(--color-text-muted)',
                cursor: 'pointer',
              }}
            >
              {icon && <img src={icon} width={12} height={12} alt="" />}
              {label}
            </button>
          ))}
        </div>

        <NetworkSelectorDropdown
          value={selectedNetwork}
          onChange={setSelectedNetwork}
          disabled={submitting}
        />

        <div style={{ flex: 1 }} />
        <button type="button" className="scan-toolbar-btn" title="Refresh" onClick={load}>
          <RefreshCw size={14} />
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          style={{
            fontSize: 11,
            padding: '4px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
          onClick={() => navigate('/map')}
          title="Open topology map"
        >
          <MapIcon size={12} /> View Map
        </button>
      </div>

      {/* Bulk toolbar */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          flexWrap: 'wrap',
          padding: '8px 12px',
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 6,
        }}
      >
        {someSelected && (
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)', marginRight: 2 }}>
            {selectedIds.size} selected
          </span>
        )}

        {/* Primary selection actions */}
        <button
          type="button"
          className="btn btn-primary"
          style={{ fontSize: 11, padding: '4px 10px' }}
          disabled={submitting || !someSelected}
          onClick={() => {
            if (selectedNetwork) {
              setPendingAccept({ resultIds: Array.from(selectedIds), isAll: false });
            } else {
              handleBulkAccept(selectedIds);
            }
          }}
        >
          Accept
        </button>
        <button
          type="button"
          className="btn btn-danger"
          style={{ fontSize: 11, padding: '4px 10px' }}
          disabled={submitting || !someSelected}
          onClick={() => handleBulkReject(selectedIds)}
        >
          Reject
        </button>

        {/* Grouping actions — Cluster and Stack */}
        <div style={{ width: 1, height: 18, background: 'var(--color-border)', margin: '0 2px' }} />
        <button
          type="button"
          className="btn btn-secondary"
          title="Accept selected hardware and group into a named Cluster"
          style={{
            fontSize: 11,
            padding: '4px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
          disabled={submitting || !someSelected}
          onClick={() => setGroupPrompt('cluster')}
        >
          <Server size={11} /> Cluster
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          title="Accept selected Docker containers and group into a named Stack"
          style={{
            fontSize: 11,
            padding: '4px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
          disabled={submitting || !someSelected}
          onClick={() => setGroupPrompt('stack')}
        >
          <Layers size={11} /> Stack
        </button>

        <div style={{ flex: 1 }} />

        {/* All-results actions */}
        <button
          type="button"
          className="btn btn-secondary"
          style={{ fontSize: 11, padding: '4px 10px' }}
          disabled={submitting || displayResults.length === 0}
          onClick={() => {
            const allIds = displayResults.map((r) => r.id);
            if (selectedNetwork) {
              setPendingAccept({ resultIds: allIds, isAll: true });
            } else {
              handleBulkAccept(new Set(allIds));
            }
          }}
        >
          Accept All
        </button>
        <button
          type="button"
          className="btn btn-danger"
          style={{ fontSize: 11, padding: '4px 10px' }}
          disabled={submitting || displayResults.length === 0}
          onClick={() => handleBulkReject(new Set(displayResults.map((r) => r.id)))}
        >
          Reject All
        </button>
      </div>

      {/* Network accept confirmation banner */}
      {pendingAccept && selectedNetwork && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            background: 'var(--color-bg-alt, #0e1e2e)',
            border: '1px solid rgba(56,189,248,0.3)',
            borderRadius: 8,
            padding: '12px 16px',
            margin: '0 0 12px',
            fontSize: 13,
          }}
        >
          <span style={{ fontSize: 18 }}>🌐</span>
          <div style={{ flex: 1, color: 'var(--color-text, #c0c0e0)', lineHeight: 1.6 }}>
            {pendingAccept.isAll ? 'Accept all' : 'Accept'}{' '}
            <strong style={{ color: '#38bdf8' }}>
              {pendingAccept.resultIds.length} result
              {pendingAccept.resultIds.length === 1 ? '' : 's'}
            </strong>
            {!pendingAccept.isAll && (
              <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}> (selected)</span>
            )}{' '}
            and assign to{' '}
            <strong style={{ color: '#38bdf8' }}>
              {selectedNetwork.name}
              {selectedNetwork.cidr ? ` (${selectedNetwork.cidr})` : ''}
            </strong>
            ?
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: 12 }}
              onClick={() => setPendingAccept(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              style={{ fontSize: 12 }}
              onClick={handleNetworkAccept}
              disabled={submitting}
            >
              {submitting ? 'Accepting…' : 'Confirm'}
            </button>
          </div>
        </div>
      )}

      {/* Table — flex-scroll wrapper so it fills remaining height and scrolls independently */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {displayResults.length === 0 ? (
          <p
            style={{
              color: 'var(--color-text-muted)',
              fontSize: 13,
              textAlign: 'center',
              padding: '32px 0',
              margin: 0,
            }}
          >
            No pending results to review
          </p>
        ) : (
          <div className="scan-table-wrap">
            <table className="scan-table">
              <thead>
                <tr>
                  <th className="col-checkbox">
                    <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
                  </th>
                  <th>IP Address</th>
                  <th>Hostname</th>
                  <th>MAC</th>
                  <th title="Click icon to change">Icon</th>
                  <th>OS / Vendor</th>
                  <th>Role</th>
                  <th title="Enable uptime ping monitor after accept">Monitor</th>
                  <th>State</th>
                  <th>Source</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {displayResults.map((r) => {
                  const edits = localEdits.get(r.id) || {};
                  const docker = isDockerResult(r);
                  const hostname = edits.hostname ?? (r.hostname || r.snmp_sys_name || '');
                  const role = edits.role ?? (docker ? 'lxc' : 'server');
                  const iconSlug = edits.iconSlug ?? (docker ? 'docker' : null);
                  const monitorEnabled = edits.monitor ?? r.state === 'new';
                  const osVendor = [r.os_family, r.os_vendor].filter(Boolean).join(' / ') || '—';
                  return (
                    <tr
                      key={r.id}
                      className={selectedIds.has(r.id) ? 'selected' : ''}
                      onClick={() => setDrawerResult(r)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td
                        className="col-checkbox"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleSelect(r.id);
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.has(r.id)}
                          onChange={() => toggleSelect(r.id)}
                        />
                      </td>

                      <td className="col-target" style={{ fontFamily: 'monospace' }}>
                        {r.ip_address}
                      </td>

                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          className="cb-input"
                          style={{ fontSize: 12, padding: '3px 7px', width: '100%', minWidth: 110 }}
                          value={hostname}
                          placeholder={r.ip_address}
                          onChange={(e) => setEdit(r.id, 'hostname', e.target.value)}
                        />
                      </td>

                      <td style={{ fontFamily: 'monospace', fontSize: 11 }}>
                        {r.mac_address || '—'}
                      </td>

                      {/* Icon picker cell */}
                      <td
                        onClick={(e) => {
                          e.stopPropagation();
                          setIconPickerRowId(r.id);
                        }}
                        title={
                          iconSlug ? `Icon: ${iconSlug} — click to change` : 'Click to assign icon'
                        }
                        style={{ cursor: 'pointer', textAlign: 'center' }}
                      >
                        <div
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 28,
                            height: 28,
                            borderRadius: 6,
                            border: `1px ${iconSlug ? 'solid' : 'dashed'} var(--color-border)`,
                            background: iconSlug ? 'var(--color-surface)' : 'transparent',
                          }}
                        >
                          {iconSlug ? (
                            <IconImg slug={iconSlug} size={20} />
                          ) : (
                            <span style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
                              {'+'}
                            </span>
                          )}
                        </div>
                      </td>

                      <td style={{ fontSize: 12 }}>{osVendor}</td>

                      <td onClick={(e) => e.stopPropagation()}>
                        <select
                          className="cb-input"
                          style={{ fontSize: 12, padding: '3px 7px' }}
                          value={role}
                          onChange={(e) => setEdit(r.id, 'role', e.target.value)}
                        >
                          {HARDWARE_ROLES.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </td>

                      {/* Monitor toggle */}
                      <td onClick={(e) => e.stopPropagation()} style={{ textAlign: 'center' }}>
                        <Toggle
                          checked={monitorEnabled}
                          onChange={(v) => setEdit(r.id, 'monitor', v)}
                        />
                      </td>

                      <td>
                        <StatePill state={r.state} />
                      </td>

                      <td>
                        {docker ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontSize: 11,
                              color: 'var(--color-text-muted)',
                            }}
                          >
                            <img src="/icons/vendors/docker.svg" width={14} height={14} alt="" />
                            Docker
                          </span>
                        ) : (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontSize: 11,
                              color: 'var(--color-text-muted)',
                            }}
                          >
                            <Server size={14} />
                            Network
                          </span>
                        )}
                      </td>

                      <td onClick={(e) => e.stopPropagation()}>
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button
                            type="button"
                            className="scan-toolbar-btn"
                            title="Accept"
                            style={{ color: '#22c55e' }}
                            onClick={() => handleAccept(r)}
                          >
                            <Check size={14} />
                          </button>
                          <button
                            type="button"
                            className="scan-toolbar-btn"
                            title="Reject"
                            style={{ color: '#ef4444' }}
                            onClick={() => handleReject(r)}
                          >
                            <X size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Icon picker modal */}
      {iconPickerResult && (
        <IconPickerModal
          currentSlug={localEdits.get(iconPickerResult.id)?.iconSlug ?? null}
          onSelect={(slug) => {
            setEdit(iconPickerResult.id, 'iconSlug', slug);
          }}
          onClose={() => setIconPickerRowId(null)}
        />
      )}

      {/* Cluster / Stack name prompt */}
      {groupPrompt && (
        <GroupNameModal
          kind={groupPrompt}
          count={selectedIds.size}
          onConfirm={(name) => handleBulkGroup(selectedIds, name, groupPrompt)}
          onCancel={() => setGroupPrompt(null)}
        />
      )}

      {drawerResult && (
        <ReviewDrawer
          result={drawerResult}
          onClose={() => setDrawerResult(null)}
          onAccepted={() => {
            removeResult(drawerResult.id);
            setDrawerResult(null);
          }}
          onRejected={(id) => {
            removeResult(id);
            setDrawerResult(null);
          }}
        />
      )}
    </div>
  );
}

ReviewQueuePanel.propTypes = {
  onCountChange: PropTypes.func,
};
