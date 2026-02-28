import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { logsApi } from '../api/client';
import { IconImg } from '../components/common/IconPickerModal';
import ConfirmDialog from '../components/common/ConfirmDialog';

// ── Actor avatar ──────────────────────────────────────────────────────────────

function ActorAvatar({ actor, gravatarHash, size = 20 }) {
  if (gravatarHash) {
    return (
      <img
        src={`https://www.gravatar.com/avatar/${gravatarHash}?s=${size * 2}&d=identicon`}
        alt={actor || 'user'}
        width={size}
        height={size}
        style={{ borderRadius: '50%', flexShrink: 0 }}
      />
    );
  }
  const initial = (actor && actor !== 'anonymous') ? actor[0].toUpperCase() : '?';
  const hue = actor ? actor.split('').reduce((sum, c) => sum + c.charCodeAt(0), 0) % 360 : 200;
  return (
    <span style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      background: `hsl(${hue}, 50%, 35%)`, color: '#fff',
      fontSize: size * 0.5, fontWeight: 600, lineHeight: 1,
    }}>{initial}</span>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatRelative(isoStr) {
  if (!isoStr) return '—';
  const diff = Date.now() - new Date(isoStr).getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function formatIso(isoStr) {
  if (!isoStr) return '';
  return new Date(isoStr).toLocaleString();
}

const ACTION_COLOR = {
  create: 'var(--color-online)',
  update: 'var(--color-primary)',
  delete: 'var(--color-danger)',
  add:    'var(--color-online)',
  remove: 'var(--color-danger)',
  attach: 'var(--color-primary)',
  detach: '#f9a825',
  reset:  '#f9a825',
};

function actionColor(action) {
  const prefix = action?.split('_')[0];
  return ACTION_COLOR[prefix] ?? 'var(--color-text-muted)';
}

const ENTITY_ROUTES = {
  hardware: '/hardware',
  compute:  '/compute-units',
  service:  '/services',
  storage:  '/storage',
  network:  '/networks',
  misc:     '/misc',
};

const LIMIT_OPTIONS = [25, 50, 100, 500];
const CATEGORY_OPTIONS = ['', 'crud', 'settings', 'relationships', 'docs'];
const ENTITY_OPTIONS = ['', 'hardware', 'compute', 'service', 'storage', 'network', 'misc'];

const TIME_PRESETS = [
  { label: 'Last 1h',  minutes: 60 },
  { label: 'Last 24h', minutes: 1440 },
  { label: 'Last 7d',  minutes: 10080 },
  { label: 'All time', minutes: null },
];

// ── Row expansion ─────────────────────────────────────────────────────────────

function JsonBlock({ value }) {
  if (!value) return null;
  let display = value;
  try {
    display = JSON.stringify(JSON.parse(value), null, 2);
  } catch { /* keep raw */ }
  return (
    <pre style={{
      background: 'var(--color-bg)',
      border: '1px solid var(--color-border)',
      borderRadius: 4,
      padding: '8px 10px',
      fontSize: 11,
      color: 'var(--color-text)',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-all',
      maxHeight: 200,
      overflowY: 'auto',
      margin: '4px 0',
    }}>{display}</pre>
  );
}

// ── Log row ───────────────────────────────────────────────────────────────────

function LogRow({ log, expanded, onToggle, navigate }) {
  const color = actionColor(log.action);

  const newValueObj = (() => {
    try { return log.new_value ? JSON.parse(log.new_value) : null; } catch { return null; }
  })();

  const vendor = newValueObj?.vendor ?? (log.entity_type === 'hardware' ? null : null);
  const iconSlug = newValueObj?.icon_slug ?? null;

  return (
    <>
      <tr
        onClick={onToggle}
        style={{ cursor: 'pointer', borderBottom: '1px solid rgba(30,42,58,0.6)', transition: 'background 0.1s' }}
        onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(0,212,255,0.03)'}
        onMouseLeave={(e) => e.currentTarget.style.background = ''}
      >
        {/* Time */}
        <td style={{ padding: '10px 12px', fontSize: 12, color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }} title={formatIso(log.timestamp)}>
          {formatRelative(log.timestamp)}
        </td>

        {/* Action */}
        <td style={{ padding: '10px 12px' }}>
          <span style={{
            display: 'inline-block',
            background: `${color}18`,
            color,
            border: `1px solid ${color}44`,
            borderRadius: 4,
            padding: '2px 7px',
            fontSize: 11,
            fontWeight: 600,
            fontFamily: 'monospace',
            letterSpacing: '0.02em',
          }}>
            {log.action}
          </span>
        </td>

        {/* Entity */}
        <td style={{ padding: '10px 12px', fontSize: 12 }}>
          {log.entity_type ? (
            <button
              onClick={(e) => { e.stopPropagation(); navigate(ENTITY_ROUTES[log.entity_type] ?? '/'); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, color: 'var(--color-primary)', fontSize: 12, padding: 0 }}
            >
              {iconSlug && <IconImg slug={iconSlug} size={14} />}
              <span style={{ textTransform: 'capitalize' }}>{log.entity_type}</span>
              {log.entity_id && <span style={{ color: 'var(--color-text-muted)' }}>#{log.entity_id}</span>}
            </button>
          ) : <span style={{ color: 'var(--color-text-muted)' }}>—</span>}
        </td>

        {/* Details preview */}
        <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--color-text-muted)', maxWidth: 260 }}>
          <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {newValueObj?.name ?? newValueObj?.title ?? log.details?.slice(0, 80) ?? '—'}
          </span>
        </td>

        {/* Actor / IP */}
        <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ActorAvatar actor={log.actor} gravatarHash={log.actor_gravatar_hash} size={20} />
            <span>{log.actor && log.actor !== 'anonymous' ? log.actor : (log.ip_address || 'anonymous')}</span>
          </div>
        </td>
      </tr>

      {/* Expanded detail row */}
      {expanded && (
        <tr style={{ background: 'var(--color-surface)' }}>
          <td colSpan={5} style={{ padding: '8px 16px 12px', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {log.old_value && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Before</div>
                  <JsonBlock value={log.old_value} />
                </div>
              )}
              {log.new_value && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>After</div>
                  <JsonBlock value={log.new_value} />
                </div>
              )}
              {!log.old_value && !log.new_value && log.details && (
                <div style={{ gridColumn: '1/-1' }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Details</div>
                  <JsonBlock value={log.details} />
                </div>
              )}
              <div style={{ gridColumn: '1/-1', fontSize: 11, color: 'var(--color-text-muted)' }}>
                <span style={{ marginRight: 16 }}>Full timestamp: {formatIso(log.timestamp)}</span>
                {log.user_agent && <span>UA: {log.user_agent.slice(0, 80)}</span>}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function LogsPage() {
  const navigate = useNavigate();
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const [logs, setLogs] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  // Filters
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [category, setCategory] = useState('');
  const [entityType, setEntityType] = useState('');
  const [search, setSearch] = useState('');
  const [timePreset, setTimePreset] = useState(null);   // minutes | null

  // Live mode (SSE)
  const [liveMode, setLiveMode] = useState(false);
  const sseRef = useRef(null);
  const lastTimestampRef = useRef(null);

  // ── Fetch ────────────────────────────────────────────────────────────────

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit, offset };
      if (category) params.category = category;
      if (entityType) params.entity_type = entityType;
      if (search.trim()) params.search = search.trim();
      if (timePreset) {
        const since = new Date(Date.now() - timePreset * 60_000);
        params.start_time = since.toISOString();
      }
      const res = await logsApi.list(params);
      setLogs(res.data.logs);
      setTotalCount(res.data.total_count);
      if (res.data.logs.length > 0) {
        lastTimestampRef.current = res.data.logs[0].timestamp;
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, category, entityType, search, timePreset]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  // Reset offset when filters change (but not when offset itself changes)
  useEffect(() => { setOffset(0); }, [limit, category, entityType, search, timePreset]);

  // ── SSE Live Mode ────────────────────────────────────────────────────────

  useEffect(() => {
    if (!liveMode) {
      sseRef.current?.close();
      sseRef.current = null;
      return;
    }

    const url = logsApi.stream(lastTimestampRef.current ?? new Date().toISOString());
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);
        setLogs(prev => [entry, ...prev]);
        setTotalCount(prev => prev + 1);
        lastTimestampRef.current = entry.timestamp;
      } catch { /* ignore malformed */ }
    };

    es.onerror = () => {
      // SSE reconnects automatically; no need to do anything
    };

    sseRef.current = es;
    return () => { es.close(); };
  }, [liveMode]);

  // ── Export ───────────────────────────────────────────────────────────────

  const handleExport = () => {
    const header = 'timestamp,level,category,action,entity_type,entity_id,actor,ip_address,details\n';
    const rows = logs.map(l => [
      l.timestamp, l.level, l.category, l.action,
      l.entity_type ?? '', l.entity_id ?? '',
      l.actor ?? '', l.ip_address ?? '',
      JSON.stringify(l.details ?? ''),
    ].join(',')).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `circuit-breaker-logs-${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  // ── Clear ────────────────────────────────────────────────────────────────

  const handleClear = () => {
    setConfirmState({
      open: true,
      message: 'Clear all logs? This cannot be undone.',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await logsApi.clear();
          setLogs([]);
          setTotalCount(0);
          lastTimestampRef.current = null;
        } catch (err) {
          setError(err.message);
        }
      }
    });
  };

  // ── Pagination ───────────────────────────────────────────────────────────

  const totalPages = Math.max(1, Math.ceil(totalCount / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const hasMore = (offset + limit) < totalCount;
  const hasPrev = offset > 0;

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px)' }}>
      {/* Header */}
      <div className="page-header" style={{ marginBottom: 0, paddingBottom: 10, borderBottom: '1px solid var(--color-border)', flexWrap: 'wrap', gap: 8 }}>
        <h2>System Logs</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flex: 1 }}>
          {/* Time presets */}
          <div style={{ display: 'flex', gap: 4 }}>
            {TIME_PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => setTimePreset(p.minutes)}
                style={{
                  padding: '4px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
                  border: '1px solid var(--color-border)',
                  background: timePreset === p.minutes ? 'rgba(0,212,255,0.12)' : 'transparent',
                  color: timePreset === p.minutes ? 'var(--color-primary)' : 'var(--color-text-muted)',
                }}
              >{p.label}</button>
            ))}
          </div>

          {/* Category */}
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            <option value="">All categories</option>
            {CATEGORY_OPTIONS.filter(Boolean).map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          {/* Entity type */}
          <select
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            <option value="">All entity types</option>
            {ENTITY_OPTIONS.filter(Boolean).map(e => <option key={e} value={e} style={{ textTransform: 'capitalize' }}>{e}</option>)}
          </select>

          {/* Search */}
          <input
            type="text"
            placeholder="Search logs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12, width: 160 }}
          />

          {/* Limit */}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            {LIMIT_OPTIONS.map(n => <option key={n} value={n}>{n} / page</option>)}
          </select>

          {/* Live toggle */}
          <button
            onClick={() => setLiveMode(v => !v)}
            style={{
              padding: '4px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
              border: `1px solid ${liveMode ? 'var(--color-online)' : 'var(--color-border)'}`,
              background: liveMode ? 'rgba(0,255,136,0.08)' : 'transparent',
              color: liveMode ? 'var(--color-online)' : 'var(--color-text-muted)',
              display: 'flex', alignItems: 'center', gap: 5,
            }}
          >
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: liveMode ? 'var(--color-online)' : 'var(--color-text-muted)', display: 'inline-block', boxShadow: liveMode ? '0 0 6px var(--color-online)' : 'none' }} />
            Live
          </button>

          {/* Refresh */}
          <button className="btn btn-sm" onClick={fetchLogs} disabled={loading} style={{ fontSize: 11 }}>
            {loading ? '…' : '↻ Refresh'}
          </button>

          {/* Export */}
          <button className="btn btn-sm" onClick={handleExport} disabled={logs.length === 0} style={{ fontSize: 11 }}>
            ↓ Export CSV
          </button>

          {/* Clear */}
          <button className="btn btn-sm btn-danger" onClick={handleClear} style={{ fontSize: 11 }}>
            🗑 Clear
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{ background: 'rgba(243,139,168,0.1)', border: '1px solid var(--color-danger)', color: 'var(--color-danger)', padding: '6px 12px', fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Table */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table className="entity-table" style={{ tableLayout: 'fixed' }}>
          <colgroup>
            <col style={{ width: 90 }} />
            <col style={{ width: 220 }} />
            <col style={{ width: 140 }} />
            <col />
            <col style={{ width: 150 }} />
          </colgroup>
          <thead>
            <tr>
              <th>Time</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Details</th>
              <th>Actor</th>
            </tr>
          </thead>
          <tbody>
            {loading && logs.length === 0 && (
              <tr>
                <td colSpan={5} className="empty-row">Loading…</td>
              </tr>
            )}
            {!loading && logs.length === 0 && (
              <tr>
                <td colSpan={5} className="empty-row">No activity recorded yet. Perform a CRUD action to see it here.</td>
              </tr>
            )}
            {logs.map(log => (
              <LogRow
                key={log.id}
                log={log}
                expanded={expandedId === log.id}
                onToggle={() => setExpandedId(prev => prev === log.id ? null : log.id)}
                navigate={navigate}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div style={{ borderTop: '1px solid var(--color-border)', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: 'var(--color-text-muted)', flexShrink: 0 }}>
        <span>
          {totalCount > 0
            ? `Showing ${offset + 1}–${Math.min(offset + limit, totalCount)} of ${totalCount.toLocaleString()} logs`
            : 'No logs'}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="btn btn-sm" disabled={!hasPrev} onClick={() => setOffset(0)} style={{ fontSize: 11 }}>⏮ First</button>
          <button className="btn btn-sm" disabled={!hasPrev} onClick={() => setOffset(o => Math.max(0, o - limit))} style={{ fontSize: 11 }}>← Prev</button>
          <span style={{ padding: '4px 8px', fontSize: 11 }}>{currentPage} / {totalPages}</span>
          <button className="btn btn-sm" disabled={!hasMore} onClick={() => setOffset(o => o + limit)} style={{ fontSize: 11 }}>Next →</button>
          <button className="btn btn-sm" disabled={!hasMore} onClick={() => setOffset((totalPages - 1) * limit)} style={{ fontSize: 11 }}>Last ⏭</button>
        </div>
      </div>
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default LogsPage;
