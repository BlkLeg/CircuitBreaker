import React, { useState, useEffect, useCallback, useRef } from 'react';
import PropTypes from 'prop-types';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Eye, EyeOff } from 'lucide-react';
import { logsApi } from '../api/client';
import { IconImg } from '../components/common/IconPickerModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import TimestampCell from '../components/TimestampCell.jsx';
import { formatAbsolute } from '../lib/time.js';
import { useAuth } from '../context/AuthContext.jsx';

// ── Actor avatar ──────────────────────────────────────────────────────────────────────────────

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
  const initial = actor && actor !== 'anonymous' ? actor[0].toUpperCase() : '?';
  const hue = actor
    ? actor.split('').reduce((sum, c) => sum + (c.codePointAt(0) ?? 0), 0) % 360
    : 200;
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        flexShrink: 0,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: `hsl(${hue}, 50%, 35%)`,
        color: '#fff',
        fontSize: size * 0.5,
        fontWeight: 600,
        lineHeight: 1,
      }}
    >
      {initial}
    </span>
  );
}

ActorAvatar.propTypes = {
  actor: PropTypes.string,
  gravatarHash: PropTypes.string,
  size: PropTypes.number,
};

ActorAvatar.defaultProps = {
  actor: null,
  gravatarHash: null,
  size: 20,
};

// ── Helpers ──────────────────────────────────────────────────────────────────────────────

const ACTION_COLOR = {
  create: 'var(--color-online)',
  created: 'var(--color-online)',
  add: 'var(--color-online)',
  update: 'var(--color-primary)',
  updated: 'var(--color-primary)',
  attach: 'var(--color-primary)',
  placed: 'var(--color-primary)',
  moved: 'var(--color-primary)',
  login_success: 'var(--color-online)',
  delete: 'var(--color-danger)',
  deleted: 'var(--color-danger)',
  remove: 'var(--color-danger)',
  removed: 'var(--color-danger)',
  detach: '#f9a825',
  reset: '#f9a825',
  login_failed: '#f9a825',
};

function actionColor(action) {
  if (!action) return 'var(--color-text-muted)';
  if (ACTION_COLOR[action]) return ACTION_COLOR[action];
  const prefix = action.split('_')[0];
  return ACTION_COLOR[prefix] ?? 'var(--color-text-muted)';
}

const ENTITY_ROUTES = {
  hardware: '/hardware',
  compute: '/compute-units',
  service: '/services',
  storage: '/storage',
  network: '/networks',
  misc: '/misc',
  cluster: '/clusters',
  external_node: '/external-nodes',
  rack: '/hardware',
  category: '/services',
  environment: '/settings',
  settings: '/settings',
  auth: null,
  oobe: null,
  telemetry: '/hardware',
  topology: '/topology',
  scan_job: '/discovery',
  scan_result: '/discovery',
};

const LIMIT_OPTIONS = [25, 50, 100, 500];
const ENTITY_OPTIONS = [
  '',
  'hardware',
  'compute',
  'service',
  'storage',
  'network',
  'misc',
  'cluster',
  'external_node',
  'rack',
  'category',
  'environment',
  'settings',
  'auth',
  'telemetry',
  'topology',
  'scan_job',
  'scan_result',
];
const SEVERITY_OPTIONS = ['info', 'warn', 'error'];
const SEVERITY_COLORS = {
  info: 'var(--color-primary)',
  warn: '#f9a825',
  error: 'var(--color-danger)',
};

const TIME_PRESETS = [
  { label: 'Last 1h', minutes: 60 },
  { label: 'Last 24h', minutes: 1440 },
  { label: 'Last 7d', minutes: 10080 },
  { label: 'Last 30d', minutes: 43200 },
  { label: 'All time', minutes: null },
];

// ── Diff Viewer ────────────────────────────────────────────────────────────────

function RedactedPill() {
  return (
    <span
      style={{
        display: 'inline-block',
        background: 'rgba(120,120,120,0.18)',
        color: 'var(--color-text-muted)',
        borderRadius: 10,
        padding: '1px 8px',
        fontSize: 10,
        letterSpacing: '0.15em',
        fontFamily: 'monospace',
      }}
    >
      ●●●●●●
    </span>
  );
}

function renderDiffValue(val) {
  if (val === '***REDACTED***') return <RedactedPill />;
  if (val === null || val === undefined)
    return <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>—</span>;
  if (typeof val === 'object') return <code style={{ fontSize: 10 }}>{JSON.stringify(val)}</code>;
  return <span>{String(val)}</span>;
}

function parseBeforeAfter(diffStr, oldValueStr, newValueStr) {
  let before = null;
  let after = null;

  if (diffStr) {
    try {
      const parsed = JSON.parse(diffStr);
      before = parsed.before;
      after = parsed.after;
    } catch {
      /* ignore */
    }
  }

  if (before === undefined && after === undefined) {
    try {
      before = oldValueStr ? JSON.parse(oldValueStr) : null;
    } catch {
      before = null;
    }
    try {
      after = newValueStr ? JSON.parse(newValueStr) : null;
    } catch {
      after = null;
    }
  }

  return { before, after };
}

function getDisplayKeys(before, after) {
  const keys = new Set([
    ...(before && typeof before === 'object' ? Object.keys(before) : []),
    ...(after && typeof after === 'object' ? Object.keys(after) : []),
  ]);

  const isUpdate = before !== null && after !== null;
  return isUpdate
    ? [...keys].filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]))
    : [...keys];
}

function DiffTable({ diffStr, oldValueStr, newValueStr }) {
  const { before, after } = parseBeforeAfter(diffStr, oldValueStr, newValueStr);

  if (before === null && after === null) return null;

  const displayKeys = getDisplayKeys(before, after);
  const isUpdate = before !== null && after !== null;

  if (displayKeys.length === 0 && isUpdate) {
    return (
      <p
        style={{
          fontSize: 11,
          color: 'var(--color-text-muted)',
          fontStyle: 'italic',
          margin: '4px 0',
        }}
      >
        No field changes detected.
      </p>
    );
  }

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
      <thead>
        <tr>
          <th
            style={{
              textAlign: 'left',
              padding: '3px 8px',
              color: 'var(--color-text-muted)',
              fontWeight: 600,
              width: '28%',
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            Field
          </th>
          <th
            style={{
              textAlign: 'left',
              padding: '3px 8px',
              color: '#f9a825',
              fontWeight: 600,
              width: '36%',
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            Before
          </th>
          <th
            style={{
              textAlign: 'left',
              padding: '3px 8px',
              color: 'var(--color-online)',
              fontWeight: 600,
              width: '36%',
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            After
          </th>
        </tr>
      </thead>
      <tbody>
        {displayKeys.map((k) => (
          <tr key={k} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
            <td
              style={{
                padding: '3px 8px',
                color: 'var(--color-text-muted)',
                fontFamily: 'monospace',
              }}
            >
              {k}
            </td>
            <td style={{ padding: '3px 8px' }}>{renderDiffValue(before?.[k] ?? null)}</td>
            <td style={{ padding: '3px 8px' }}>{renderDiffValue(after?.[k] ?? null)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

DiffTable.propTypes = {
  diffStr: PropTypes.string,
  oldValueStr: PropTypes.string,
  newValueStr: PropTypes.string,
};

DiffTable.defaultProps = {
  diffStr: null,
  oldValueStr: null,
  newValueStr: null,
};

function JsonBlock({ value }) {
  if (!value) return null;
  let display = value;
  try {
    display = JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    /* keep raw */
  }
  return (
    <pre
      style={{
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
      }}
    >
      {display}
    </pre>
  );
}

JsonBlock.propTypes = {
  value: PropTypes.string,
};

JsonBlock.defaultProps = {
  value: null,
};

function getEntityName(log) {
  if (log.entity_name) return log.entity_name;
  try {
    return log.new_value ? JSON.parse(log.new_value)?.name : null;
  } catch {
    return null;
  }
}

function getIconSlug(log) {
  try {
    return log.new_value ? JSON.parse(log.new_value)?.icon_slug : null;
  } catch {
    return null;
  }
}

function EntityCell({ log, navigate }) {
  const entityName = getEntityName(log);
  const isDeleted = log.action === 'deleted' || log.action?.endsWith('_deleted');
  const entityRoute = log.entity_type ? ENTITY_ROUTES[log.entity_type] : null;
  const iconSlug = getIconSlug(log);

  const handleEntityClick = (e) => {
    e.stopPropagation();
    if (!entityRoute) return;
    const dest = log.entity_id ? `${entityRoute}?highlight=${log.entity_id}` : entityRoute;
    navigate(dest);
  };

  const label = entityName || (log.entity_id ? `#${log.entity_id}` : '—');

  if (!log.entity_type) return <span style={{ color: 'var(--color-text-muted)' }}>—</span>;

  const renderEntityContent = () => {
    if (isDeleted) {
      return (
        <span
          style={{
            textDecoration: 'line-through',
            color: 'var(--color-text-muted)',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          {iconSlug && <IconImg slug={iconSlug} size={13} />}
          {label}
          <span style={{ fontSize: 10, color: 'var(--color-danger)', textDecoration: 'none' }}>
            (deleted)
          </span>
        </span>
      );
    }

    if (entityRoute) {
      return (
        <button
          onClick={handleEntityClick}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            color: 'var(--color-primary)',
            fontSize: 12,
            padding: 0,
            textAlign: 'left',
          }}
        >
          {iconSlug && <IconImg slug={iconSlug} size={13} />}
          {label}
        </button>
      );
    }

    return <span style={{ color: 'var(--color-text)' }}>{label}</span>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span
        style={{
          fontSize: 10,
          color: 'var(--color-text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}
      >
        {log.entity_type}
      </span>
      {renderEntityContent()}
    </div>
  );
}

EntityCell.propTypes = {
  log: PropTypes.object.isRequired,
  navigate: PropTypes.func.isRequired,
};

function ExpandedContent({ log }) {
  const hasDiff = !!(log.diff || log.old_value || log.new_value);

  if (hasDiff) {
    return (
      <div>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: 'var(--color-text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginBottom: 6,
          }}
        >
          ▼ Changes
        </div>
        <DiffTable diffStr={log.diff} oldValueStr={log.old_value} newValueStr={log.new_value} />
      </div>
    );
  }

  if (log.details) {
    return (
      <div>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: 'var(--color-text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginBottom: 4,
          }}
        >
          Details
        </div>
        <JsonBlock value={log.details} />
      </div>
    );
  }

  return null;
}

ExpandedContent.propTypes = {
  log: PropTypes.object.isRequired,
};

function LogRow({ log, expanded, onToggle, navigate, isAdmin, revealed, onToggleReveal }) {
  const color = actionColor(log.action);
  const isLoginFailed = log.action === 'login_failed';
  const hasDiff = !!(log.diff || log.old_value || log.new_value);

  return (
    <>
      <tr
        onClick={onToggle}
        style={{
          cursor: hasDiff ? 'pointer' : 'default',
          borderBottom: '1px solid rgba(30,42,58,0.6)',
          transition: 'background 0.1s',
          borderLeft: isLoginFailed ? '3px solid #f9a825' : '3px solid transparent',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(0,212,255,0.03)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = '')}
      >
        {/* Time */}
        <td
          style={{
            padding: '10px 12px',
            fontSize: 12,
            color: 'var(--color-text-muted)',
            whiteSpace: 'nowrap',
          }}
        >
          <TimestampCell
            isoString={log.created_at_utc ?? log.timestamp}
            elapsedSeconds={log.elapsed_seconds ?? null}
          />
        </td>

        {/* Action badge */}
        <td style={{ padding: '10px 12px' }}>
          <span
            style={{
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
            }}
          >
            {log.action}
          </span>
        </td>

        {/* Entity */}
        <td style={{ padding: '10px 12px', fontSize: 12 }}>
          <EntityCell log={log} navigate={navigate} />
        </td>

        {/* Actor */}
        <td
          style={{
            padding: '10px 12px',
            fontSize: 11,
            color: 'var(--color-text-muted)',
            whiteSpace: 'nowrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ActorAvatar actor={log.actor} gravatarHash={log.actor_gravatar_hash} size={18} />
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span>{log.actor_name || log.actor || 'anonymous'}</span>
              {log.role_at_time && (
                <span style={{ fontSize: 9, opacity: 0.7, textTransform: 'uppercase' }}>
                  {log.role_at_time}
                </span>
              )}
            </div>
            {log.log_hash && (
              <span
                title={`Hash: ${log.log_hash}`}
                style={{ cursor: 'help', opacity: 0.5, marginLeft: 4 }}
              >
                🔒
              </span>
            )}
          </div>
        </td>

        {/* IP — blurred by default; admin can reveal per-row */}
        <td
          style={{
            padding: '10px 12px',
            fontSize: 11,
            color: 'var(--color-text-muted)',
            whiteSpace: 'nowrap',
          }}
        >
          {log.ip_address ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span
                style={{
                  fontWeight: isLoginFailed ? 700 : 400,
                  color: isLoginFailed ? '#f9a825' : undefined,
                  filter: revealed ? 'none' : 'blur(4px)',
                  userSelect: revealed ? 'text' : 'none',
                  transition: 'filter 0.2s',
                }}
              >
                {log.ip_address}
              </span>
              {isAdmin && (
                <button
                  type="button"
                  title={revealed ? 'Hide IP' : 'Reveal IP'}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleReveal(log.id);
                  }}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 2,
                    color: 'var(--color-text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                  aria-label={revealed ? 'Hide IP address' : 'Reveal IP address'}
                >
                  {revealed ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
              )}
            </div>
          ) : (
            <span style={{ opacity: 0.4 }}>—</span>
          )}
        </td>
      </tr>

      {/* Expanded diff panel */}
      {expanded && (
        <tr style={{ background: 'var(--color-surface)' }}>
          <td
            colSpan={5}
            style={{ padding: '8px 16px 12px', borderBottom: '1px solid var(--color-border)' }}
          >
            <ExpandedContent log={log} />
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--color-text-muted)' }}>
              <span style={{ marginRight: 16 }}>
                Full timestamp: {formatAbsolute(log.created_at_utc ?? log.timestamp)}
              </span>
              {log.user_agent && (
                <span style={{ marginRight: 16 }}>UA: {log.user_agent.slice(0, 80)}</span>
              )}
              {log.status_code && <span>HTTP {log.status_code}</span>}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

LogRow.propTypes = {
  log: PropTypes.object.isRequired,
  expanded: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
  navigate: PropTypes.func.isRequired,
  isAdmin: PropTypes.bool,
  revealed: PropTypes.bool,
  onToggleReveal: PropTypes.func,
};

LogRow.defaultProps = {
  isAdmin: false,
  revealed: false,
  onToggleReveal: () => {},
};

// ── Virtualized table (used when > 50 rows to avoid DOM bloat) ────────────────────────────────

const LOG_ROW_ESTIMATE_PX = 44;

function LogsVirtualTable({
  logs,
  loading,
  expandedId,
  setExpandedId,
  timestampSort,
  setTimestampSort,
  navigate,
  tableContainerRef,
  isAdmin,
  revealedIps,
  onToggleRevealIp,
  onRevealAll,
}) {
  const useVirtual = logs.length > 50;

  const virtualizer = useVirtualizer({
    count: logs.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => LOG_ROW_ESTIMATE_PX,
    overscan: 10,
    enabled: useVirtual,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const totalVirtualHeight = virtualizer.getTotalSize();
  const paddingTop = virtualItems.length > 0 ? (virtualItems[0]?.start ?? 0) : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? totalVirtualHeight - (virtualItems[virtualItems.length - 1]?.end ?? 0)
      : 0;

  const visibleItems = useVirtual ? virtualItems : logs.map((_, i) => ({ index: i }));

  return (
    <div ref={tableContainerRef} style={{ flex: 1, overflowY: 'auto' }}>
      <table className="entity-table" style={{ tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: 90 }} />
          <col style={{ width: 200 }} />
          <col style={{ width: 160 }} />
          <col style={{ width: 130 }} />
          <col style={{ width: 110 }} />
        </colgroup>
        <thead>
          <tr>
            <th
              onClick={() => setTimestampSort((s) => (s === 'desc' ? 'asc' : 'desc'))}
              style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
              title="Click to toggle sort order"
            >
              Time {timestampSort === 'desc' ? '↓' : '↑'}
            </th>
            <th>Action</th>
            <th>Entity</th>
            <th>Actor</th>
            <th style={{ position: 'relative' }}>
              IP
              {isAdmin && (
                <button
                  type="button"
                  onClick={onRevealAll}
                  title="Reveal all IPs in this view"
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    marginLeft: 6,
                    color: 'var(--color-text-muted)',
                    verticalAlign: 'middle',
                  }}
                  aria-label="Reveal all IP addresses"
                >
                  <Eye size={11} />
                </button>
              )}
            </th>
          </tr>
        </thead>
        <tbody>
          {loading && logs.length === 0 && (
            <tr>
              <td colSpan={5} className="empty-row">
                Loading…
              </td>
            </tr>
          )}
          {!loading && logs.length === 0 && (
            <tr>
              <td colSpan={5} className="empty-row">
                No activity recorded yet.
              </td>
            </tr>
          )}
          {useVirtual && paddingTop > 0 && (
            <tr>
              <td colSpan={5} style={{ height: paddingTop, padding: 0 }} />
            </tr>
          )}
          {visibleItems.map((virtualRow) => {
            const log = logs[virtualRow.index];
            if (!log) return null;
            return (
              <LogRow
                key={log.id}
                log={log}
                expanded={expandedId === log.id}
                onToggle={() => setExpandedId((prev) => (prev === log.id ? null : log.id))}
                navigate={navigate}
                isAdmin={isAdmin}
                revealed={revealedIps.has(log.id)}
                onToggleReveal={onToggleRevealIp}
              />
            );
          })}
          {useVirtual && paddingBottom > 0 && (
            <tr>
              <td colSpan={5} style={{ height: paddingBottom, padding: 0 }} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

LogsVirtualTable.propTypes = {
  logs: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  expandedId: PropTypes.any,
  setExpandedId: PropTypes.func.isRequired,
  timestampSort: PropTypes.string.isRequired,
  setTimestampSort: PropTypes.func.isRequired,
  navigate: PropTypes.func.isRequired,
  tableContainerRef: PropTypes.object.isRequired,
  isAdmin: PropTypes.bool,
  revealedIps: PropTypes.instanceOf(Set),
  onToggleRevealIp: PropTypes.func,
  onRevealAll: PropTypes.func,
};

LogsVirtualTable.defaultProps = {
  expandedId: null,
  isAdmin: false,
  revealedIps: new Set(),
  onToggleRevealIp: () => {},
  onRevealAll: () => {},
};
// ── Main Page ───────────────────────────────────────────────────────────────────────────────

function LogsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [logs, setLogs] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [availableActions, setAvailableActions] = useState([]);
  const [availableActors, setAvailableActors] = useState([]);
  const [revealedIps, setRevealedIps] = useState(() => new Set());

  const handleToggleRevealIp = useCallback((id) => {
    setRevealedIps((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleRevealAll = useCallback(() => {
    setRevealedIps(new Set(logs.map((l) => l.id)));
  }, [logs]);

  const [timestampSort, setTimestampSort] = useState(() => searchParams.get('sort') || 'desc');
  const [limit, setLimit] = useState(() => Number(searchParams.get('limit')) || 100);
  const [offset, setOffset] = useState(() => Number(searchParams.get('offset')) || 0);
  const [entityType, setEntityType] = useState(() => searchParams.get('entity_type') || '');
  const [actionFilter, setActionFilter] = useState(() => searchParams.get('action') || '');
  const [actorFilter, setActorFilter] = useState(() => searchParams.get('actor') || '');
  const [severity, setSeverity] = useState(() => searchParams.get('severity') || '');
  const [search, setSearch] = useState(() => searchParams.get('search') || '');
  const [timePreset, setTimePreset] = useState(null);

  const [liveMode, setLiveMode] = useState(false);
  const sseRef = useRef(null);
  const tableContainerRef = useRef(null);
  const lastTimestampRef = useRef(null);
  const searchDebounceRef = useRef(null);
  const [debouncedSearch, setDebouncedSearch] = useState(search);

  // ── Load distinct actions ─────────────────────────────────────────────────────────

  useEffect(() => {
    logsApi
      .actions()
      .then((r) => setAvailableActions(r.data.actions || []))
      .catch(() => {});
    logsApi
      .list({ limit: 500 })
      .then((r) => {
        const actors = [
          ...new Set((r.data.logs || []).map((l) => l.actor_name || l.actor).filter(Boolean)),
        ].sort();
        setAvailableActors(actors);
      })
      .catch(() => {});
  }, []);

  // ── Debounce search ────────────────────────────────────────────────────────────

  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(searchDebounceRef.current);
  }, [search]);

  // ── Sync filters → URL ───────────────────────────────────────────────────────────

  useEffect(() => {
    const p = {};
    if (entityType) p.entity_type = entityType;
    if (actionFilter) p.action = actionFilter;
    if (actorFilter) p.actor = actorFilter;
    if (severity) p.severity = severity;
    if (debouncedSearch) p.search = debouncedSearch;
    if (timestampSort !== 'desc') p.sort = timestampSort;
    if (limit !== 100) p.limit = String(limit);
    if (offset) p.offset = String(offset);
    setSearchParams(p, { replace: true });
  }, [
    entityType,
    actionFilter,
    actorFilter,
    severity,
    debouncedSearch,
    timestampSort,
    limit,
    offset,
    setSearchParams,
  ]);

  // ── Fetch ───────────────────────────────────────────────────────────────────────────

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit, offset, sort: timestampSort };
      if (entityType) params.entity_type = entityType;
      if (actionFilter) params.action = actionFilter;
      if (actorFilter) params.actor = actorFilter;
      if (severity) params.severity = severity;
      if (debouncedSearch.trim()) params.search = debouncedSearch.trim();
      if (timePreset) {
        params.start_time = new Date(Date.now() - timePreset * 60_000).toISOString();
      }
      const res = await logsApi.list(params);
      setLogs(res.data.logs);
      setTotalCount(res.data.total_count);
      if (res.data.logs.length > 0) lastTimestampRef.current = res.data.logs[0].timestamp;
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [
    limit,
    offset,
    entityType,
    actionFilter,
    actorFilter,
    severity,
    debouncedSearch,
    timePreset,
    timestampSort,
  ]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);
  useEffect(() => {
    setOffset(0);
  }, [
    limit,
    entityType,
    actionFilter,
    actorFilter,
    severity,
    debouncedSearch,
    timePreset,
    timestampSort,
  ]);

  // ── SSE Live Mode ─────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!liveMode) {
      sseRef.current?.close();
      sseRef.current = null;
      return;
    }
    const es = new EventSource(
      logsApi.stream(lastTimestampRef.current ?? new Date().toISOString())
    );
    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);
        setLogs((prev) => [entry, ...prev]);
        setTotalCount((prev) => prev + 1);
        lastTimestampRef.current = entry.timestamp;
      } catch {
        /* ignore */
      }
    };
    sseRef.current = es;
    return () => {
      es.close();
    };
  }, [liveMode]);

  // ── Export / Clear ────────────────────────────────────────────────────────────

  const handleExport = () => {
    const header =
      'timestamp,severity,action,entity_type,entity_id,entity_name,actor,role_at_time,ip_address,log_hash\n';
    const rows = logs
      .map((l) =>
        [
          l.created_at_utc ?? l.timestamp,
          l.severity ?? l.level ?? '',
          l.action ?? '',
          l.entity_type ?? '',
          l.entity_id ?? '',
          JSON.stringify(l.entity_name ?? ''),
          l.actor_name ?? l.actor ?? '',
          l.role_at_time ?? '',
          l.ip_address ?? '',
          l.log_hash ?? '',
        ].join(',')
      )
      .join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `circuit-breaker-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

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
      },
    });
  };

  // ── Clear filters ───────────────────────────────────────────────────────────

  const hasActiveFilters = !!(
    entityType ||
    actionFilter ||
    actorFilter ||
    severity ||
    debouncedSearch ||
    timePreset
  );
  const clearFilters = () => {
    setEntityType('');
    setActionFilter('');
    setActorFilter('');
    setSeverity('');
    setSearch('');
    setTimePreset(null);
    setOffset(0);
  };

  // ── Pagination ───────────────────────────────────────────────────────────────────

  const totalPages = Math.max(1, Math.ceil(totalCount / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const hasMore = offset + limit < totalCount;
  const hasPrev = offset > 0;

  return (
    <div
      className="page"
      style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px)' }}
    >
      {/* Header */}
      <div
        className="page-header"
        style={{
          marginBottom: 0,
          paddingBottom: 10,
          borderBottom: '1px solid var(--color-border)',
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <h2>Audit Log</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flex: 1 }}>
          {/* Time presets */}
          <div style={{ display: 'flex', gap: 4 }}>
            {TIME_PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => setTimePreset(p.minutes)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 4,
                  fontSize: 11,
                  cursor: 'pointer',
                  border: '1px solid var(--color-border)',
                  background: timePreset === p.minutes ? 'rgba(0,212,255,0.12)' : 'transparent',
                  color:
                    timePreset === p.minutes ? 'var(--color-primary)' : 'var(--color-text-muted)',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Entity type */}
          <select
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            style={{
              padding: '5px 8px',
              borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg)',
              color: 'var(--color-text)',
              fontSize: 12,
            }}
          >
            <option value="">All entity types</option>
            {ENTITY_OPTIONS.filter(Boolean).map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>

          {/* Action dropdown */}
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={{
              padding: '5px 8px',
              borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg)',
              color: 'var(--color-text)',
              fontSize: 12,
            }}
          >
            <option value="">All actions</option>
            {availableActions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>

          {/* Actor dropdown */}
          <select
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            style={{
              padding: '5px 8px',
              borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg)',
              color: 'var(--color-text)',
              fontSize: 12,
            }}
          >
            <option value="">All users</option>
            {availableActors.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>

          {/* Severity chips */}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            {SEVERITY_OPTIONS.map((s) => {
              const active = severity === s;
              const col = SEVERITY_COLORS[s];
              return (
                <button
                  key={s}
                  onClick={() => setSeverity(active ? '' : s)}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 10,
                    fontSize: 11,
                    cursor: 'pointer',
                    border: `1px solid ${active ? col : 'var(--color-border)'}`,
                    background: active ? `${col}22` : 'transparent',
                    color: active ? col : 'var(--color-text-muted)',
                    fontWeight: active ? 700 : 400,
                    textTransform: 'capitalize',
                  }}
                >
                  {s}
                </button>
              );
            })}
          </div>

          {/* Search */}
          <input
            type="text"
            placeholder="🔍 Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              padding: '5px 10px',
              borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg)',
              color: 'var(--color-text)',
              fontSize: 12,
              width: 160,
            }}
          />

          {/* Clear filters */}
          {hasActiveFilters && (
            <button
              onClick={clearFilters}
              style={{
                padding: '4px 10px',
                borderRadius: 4,
                fontSize: 11,
                cursor: 'pointer',
                border: '1px solid var(--color-danger)',
                background: 'rgba(243,139,168,0.08)',
                color: 'var(--color-danger)',
              }}
            >
              ✕ Clear filters
            </button>
          )}

          {/* Limit */}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{
              padding: '5px 8px',
              borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg)',
              color: 'var(--color-text)',
              fontSize: 12,
            }}
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} / page
              </option>
            ))}
          </select>

          {/* Live toggle */}
          <button
            onClick={() => setLiveMode((v) => !v)}
            style={{
              padding: '4px 10px',
              borderRadius: 4,
              fontSize: 11,
              cursor: 'pointer',
              border: `1px solid ${liveMode ? 'var(--color-online)' : 'var(--color-border)'}`,
              background: liveMode ? 'rgba(0,255,136,0.08)' : 'transparent',
              color: liveMode ? 'var(--color-online)' : 'var(--color-text-muted)',
              display: 'flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: liveMode ? 'var(--color-online)' : 'var(--color-text-muted)',
                display: 'inline-block',
                boxShadow: liveMode ? '0 0 6px var(--color-online)' : 'none',
              }}
            />
            {' Live'}
          </button>

          <button
            className="btn btn-sm"
            onClick={fetchLogs}
            disabled={loading}
            style={{ fontSize: 11 }}
          >
            {loading ? '…' : '↻ Refresh'}
          </button>
          <button
            className="btn btn-sm"
            onClick={handleExport}
            disabled={logs.length === 0}
            style={{ fontSize: 11 }}
          >
            ↓ Export CSV
          </button>
          <button className="btn btn-sm btn-danger" onClick={handleClear} style={{ fontSize: 11 }}>
            🗑 Clear
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            background: 'rgba(243,139,168,0.1)',
            border: '1px solid var(--color-danger)',
            color: 'var(--color-danger)',
            padding: '6px 12px',
            fontSize: 12,
          }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      <LogsVirtualTable
        logs={logs}
        loading={loading}
        expandedId={expandedId}
        setExpandedId={setExpandedId}
        timestampSort={timestampSort}
        setTimestampSort={setTimestampSort}
        navigate={navigate}
        tableContainerRef={tableContainerRef}
        isAdmin={isAdmin}
        revealedIps={revealedIps}
        onToggleRevealIp={handleToggleRevealIp}
        onRevealAll={handleRevealAll}
      />

      {/* Pagination */}
      <div
        style={{
          borderTop: '1px solid var(--color-border)',
          padding: '8px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: 12,
          color: 'var(--color-text-muted)',
          flexShrink: 0,
        }}
      >
        <span>
          {totalCount > 0
            ? `Showing ${offset + 1}–${Math.min(offset + limit, totalCount)} of ${totalCount.toLocaleString()} entries`
            : 'No logs'}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            className="btn btn-sm"
            disabled={!hasPrev}
            onClick={() => setOffset(0)}
            style={{ fontSize: 11 }}
          >
            ⏮ First
          </button>
          <button
            className="btn btn-sm"
            disabled={!hasPrev}
            onClick={() => setOffset((o) => Math.max(0, o - limit))}
            style={{ fontSize: 11 }}
          >
            ← Prev
          </button>
          <span style={{ padding: '4px 8px', fontSize: 11 }}>
            {currentPage} / {totalPages}
          </span>
          <button
            className="btn btn-sm"
            disabled={!hasMore}
            onClick={() => setOffset((o) => o + limit)}
            style={{ fontSize: 11 }}
          >
            Next →
          </button>
          <button
            className="btn btn-sm"
            disabled={!hasMore}
            onClick={() => setOffset((totalPages - 1) * limit)}
            style={{ fontSize: 11 }}
          >
            Last ⏭
          </button>
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
