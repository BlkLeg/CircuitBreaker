import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { ChevronDown, ChevronRight } from 'lucide-react';
import '../styles/discovery.css';
import { getJobs, getJobResults, cancelJob, enrichOpnsenseJob } from '../api/discovery.js';
import { useToast } from '../components/common/Toast';
import TimestampCell from '../components/TimestampCell.jsx';
import logger from '../utils/logger.js';
import AnimatedCounter from '../components/discovery/AnimatedCounter.jsx';
import {
  SCAN_ROW_ENTRY_ANIMATION_MS,
  SCAN_STATUS_RUNNING_PULSE_DURATION_MS,
  STATUS_BADGE_TRANSITION_MS,
} from '../lib/constants.js';

function logApiWarning(scope, error) {
  logger.warn(`[DiscoveryHistoryPage] ${scope}`, error);
}

function parseJsonArray(json) {
  if (!json) return [];
  try {
    const parsed = JSON.parse(json);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function HistoryStatusPill({ status }) {
  const normalized = status === 'completed' ? 'done' : status;
  const label =
    normalized === 'done' ? 'Done' : normalized.charAt(0).toUpperCase() + normalized.slice(1);
  const style = {
    '--history-status-transition-ms': `${STATUS_BADGE_TRANSITION_MS}ms`,
    ...(normalized === 'running'
      ? { '--history-status-running-pulse-ms': `${SCAN_STATUS_RUNNING_PULSE_DURATION_MS}ms` }
      : {}),
  };
  return (
    <span className={`history-status-pill status-${normalized}`} style={style}>
      {label}
    </span>
  );
}

HistoryStatusPill.propTypes = {
  status: PropTypes.string.isRequired,
};

const TYPE_COLORS = new Map([
  ['nmap', '#3b82f6'],
  ['snmp', '#8b5cf6'],
  ['arp', '#f59e0b'],
  ['http', '#10b981'],
  ['proxmox', '#a855f7'],
]);

function TypePill({ type }) {
  const color = TYPE_COLORS.get(type) || '#6b7280';
  return (
    <span
      style={{
        padding: '1px 7px',
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        background: `${color}22`,
        color,
        border: `1px solid ${color}44`,
      }}
    >
      {type}
    </span>
  );
}

TypePill.propTypes = {
  type: PropTypes.string.isRequired,
};

function PortPills({ ports }) {
  const shown = ports.slice(0, 4);
  const extra = ports.length - shown.length;
  return (
    <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', alignItems: 'center' }}>
      {shown.map((p) => (
        <span
          key={`${p.port}-${p.proto ?? p.protocol ?? 'unknown'}`}
          style={{
            padding: '1px 5px',
            borderRadius: 3,
            fontSize: 10,
            background: 'rgba(107,114,128,0.15)',
            color: 'var(--color-text-muted)',
            fontFamily: 'monospace',
          }}
        >
          {p.port}
        </span>
      ))}
      {extra > 0 && (
        <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>+{extra} more</span>
      )}
    </div>
  );
}

PortPills.propTypes = {
  ports: PropTypes.arrayOf(
    PropTypes.shape({
      port: PropTypes.number.isRequired,
    })
  ).isRequired,
};

function parsePorts(json) {
  if (!json) return [];
  try {
    return JSON.parse(json);
  } catch {
    return [];
  }
}

function computeElapsedMs(item, now) {
  const start = item.started_at ? new Date(item.started_at).getTime() : null;
  if (!start) return null;
  if (item.status === 'running') return now - start;
  const end = item.completed_at ? new Date(item.completed_at).getTime() : null;
  return end ? end - start : null;
}

function formatDuration(ms) {
  if (ms === null || ms < 0) return '--:--:--';
  const totalSecs = Math.floor(ms / 1000);
  const h = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
  const m = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
  const s = String(totalSecs % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function getProgressPercent(job) {
  if (typeof job?.progress_percent === 'number') {
    return Math.max(0, Math.min(100, Math.round(job.progress_percent)));
  }
  if (job?.status === 'completed' || job?.status === 'done') return 100;
  return 0;
}

function getLiveMessage(job) {
  if (!job) return '';
  const phase = job.current_phase || job.last_log_phase;
  const message = job.current_message || job.last_log_message;
  if (phase && message) return `${phase}: ${message}`;
  return phase || message || '';
}

const SOURCE_NETWORK = 'network';
const SOURCE_PROXMOX = 'proxmox';
const EMPTY_VALUE = '\u2014';

function ExpandedResults({ jobResults }) {
  if (!jobResults) {
    return (
      <div className="history-details-empty" style={{ margin: 0, padding: 16 }}>
        Loading results…
      </div>
    );
  }

  if (jobResults.length === 0) {
    return (
      <div className="history-details-empty" style={{ margin: 0, padding: 16 }}>
        No devices found
      </div>
    );
  }

  return (
    <div className="history-expanded-results" style={{ maxHeight: 300, overflowY: 'auto' }}>
      <table className="history-details-table">
        <thead>
          <tr>
            <th style={{ position: 'sticky', top: 0, zIndex: 1 }}>IP Address</th>
            <th style={{ position: 'sticky', top: 0, zIndex: 1 }}>MAC Address</th>
            <th style={{ position: 'sticky', top: 0, zIndex: 1 }}>OS / Vendor</th>
            <th style={{ position: 'sticky', top: 0, zIndex: 1 }}>Ports</th>
          </tr>
        </thead>
        <tbody>
          {jobResults.map((result) => {
            const ports = parsePorts(result.open_ports_json);
            return (
              <tr key={result.id ?? `${result.ip_address}-${result.mac_address ?? 'na'}`}>
                <td style={{ fontFamily: 'ui-monospace, monospace' }}>{result.ip_address}</td>
                <td
                  style={{
                    fontFamily: 'ui-monospace, monospace',
                    color: 'var(--color-text-muted)',
                  }}
                >
                  {result.mac_address || EMPTY_VALUE}
                </td>
                <td>
                  {[result.os_family, result.os_vendor].filter(Boolean).join(' ') || 'Unknown'}
                </td>
                <td>{ports.length > 0 ? <PortPills ports={ports} /> : EMPTY_VALUE}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

ExpandedResults.propTypes = {
  jobResults: PropTypes.array,
};

const ScanHistoryRow = React.memo(
  function ScanHistoryRow({
    item,
    isExpanded,
    jobResults,
    onToggleExpand,
    onCancelJob,
    onEnrichJob,
    onRefreshJobs,
  }) {
    const types = parseJsonArray(item.scan_types_json);
    const targetLabel = item.label || item.target_cidr || 'Ad-hoc scan';
    const progressPercent = getProgressPercent(item);
    const liveMessage = getLiveMessage(item);
    const showLiveMeta =
      item.status === 'running' ||
      item.status === 'queued' ||
      typeof item.progress_percent === 'number' ||
      typeof item.eta_seconds === 'number';
    const canCancel = item.status === 'running' || item.status === 'queued';
    const canEnrich =
      types.includes('opnsense') && (item.status === 'done' || item.status === 'completed');

    const [now, setNow] = useState(Date.now);
    useEffect(() => {
      if (item.status !== 'running') return;
      const id = setInterval(() => setNow(Date.now()), 1000);
      return () => clearInterval(id);
    }, [item.status]);

    useEffect(() => {
      if (item.status !== 'running' || (item.progress_percent ?? 0) < 100) return;
      const id = setInterval(() => {
        if (onRefreshJobs) onRefreshJobs();
      }, 3000);
      return () => clearInterval(id);
    }, [item.status, item.progress_percent, onRefreshJobs]);

    const timerStr = formatDuration(computeElapsedMs(item, now));

    return (
      <>
        <tr
          className="history-row history-row-enter"
          style={{ '--history-row-entry-ms': `${SCAN_ROW_ENTRY_ANIMATION_MS}ms` }}
          onClick={() => onToggleExpand(item)}
        >
          <td className="history-expand-cell">
            {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </td>
          <td>
            <TimestampCell isoString={item.started_at || item.created_at} />
          </td>
          <td className="history-target">{targetLabel}</td>
          <td>
            <div className="history-type-row">
              {item.source === SOURCE_PROXMOX ? (
                <TypePill type="proxmox" />
              ) : (
                types.map((t) => <TypePill key={t} type={t} />)
              )}
            </div>
          </td>
          <td>
            <div className="history-status-row">
              <HistoryStatusPill status={item.status} />
              <button
                type="button"
                className={`btn btn-secondary history-cancel-btn${canCancel ? '' : ' is-hidden'}`}
                onClick={(event) => onCancelJob(item.id, event)}
                disabled={!canCancel}
              >
                Cancel
              </button>
              {canEnrich && (
                <button
                  type="button"
                  className="btn btn-secondary history-cancel-btn"
                  onClick={(event) => {
                    event.stopPropagation();
                    onEnrichJob(item.id);
                  }}
                >
                  Enrich
                </button>
              )}
            </div>
            <div className="history-live-meta">
              <span className="history-live-meta-item">
                {showLiveMeta ? `${progressPercent}%` : EMPTY_VALUE}
              </span>
              <span className="history-live-meta-item">{timerStr}</span>
            </div>
            {item.started_at && (
              <div className="history-progress-track">
                <div
                  className={`history-progress-fill status-${item.status === 'completed' ? 'done' : item.status}`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            )}
            <div className={`history-live-message${liveMessage ? ' is-visible' : ''}`}>
              {liveMessage || EMPTY_VALUE}
            </div>
          </td>
          <td className="history-counter-cell">
            <AnimatedCounter value={item.hosts_found ?? 0} className="history-counter-value" />
          </td>
          <td className="history-counter-cell">
            <AnimatedCounter value={item.hosts_new ?? 0} className="history-counter-value" />
          </td>
          <td className="history-counter-cell">
            <AnimatedCounter value={item.hosts_conflict ?? 0} className="history-counter-value" />
          </td>
        </tr>
        {isExpanded && (
          <tr className="history-expanded-row">
            <td colSpan={8}>
              <div className="history-expanded-shell">
                <ExpandedResults jobResults={jobResults} />
              </div>
            </td>
          </tr>
        )}
      </>
    );
  },
  (previousProps, nextProps) =>
    previousProps.item === nextProps.item &&
    previousProps.isExpanded === nextProps.isExpanded &&
    previousProps.jobResults === nextProps.jobResults &&
    previousProps.onCancelJob === nextProps.onCancelJob &&
    previousProps.onEnrichJob === nextProps.onEnrichJob &&
    previousProps.onRefreshJobs === nextProps.onRefreshJobs
);

ScanHistoryRow.propTypes = {
  item: PropTypes.object.isRequired,
  isExpanded: PropTypes.bool.isRequired,
  jobResults: PropTypes.array,
  onToggleExpand: PropTypes.func.isRequired,
  onCancelJob: PropTypes.func.isRequired,
  onEnrichJob: PropTypes.func.isRequired,
  onRefreshJobs: PropTypes.func,
};

export default function DiscoveryHistoryPage({ embedded = false, jobsData = null, onRefreshJobs }) {
  const toast = useToast();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(new Set());
  const [results, setResults] = useState(() => new Map());
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');

  const load = useCallback(() => {
    setLoading(true);
    getJobs()
      .then((r) => setJobs(r.data || []))
      .catch((error) => {
        logApiWarning('Failed to load scan history', error);
        setJobs([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const hasExternalJobs = Array.isArray(jobsData);

  useEffect(() => {
    if (hasExternalJobs) {
      setLoading(false);
      return;
    }
    load();
  }, [load, hasExternalJobs]);

  const resultsRef = useRef(results);
  useEffect(() => {
    resultsRef.current = results;
  }, [results]);

  const handleCancelJob = useCallback(
    async (jobId, event) => {
      event?.stopPropagation();
      try {
        await cancelJob(jobId);
        toast.success('Scan cancelled');
        if (onRefreshJobs) {
          onRefreshJobs();
        } else {
          load();
        }
      } catch (err) {
        toast.error(err?.message || 'Failed to cancel scan');
      }
    },
    [load, onRefreshJobs, toast]
  );

  const handleEnrichJob = useCallback(
    async (jobId) => {
      try {
        await enrichOpnsenseJob(jobId);
        toast.success('Enrichment scan queued');
        if (onRefreshJobs) {
          onRefreshJobs();
        } else {
          load();
        }
      } catch (err) {
        toast.error(err?.response?.data?.detail || err?.message || 'Failed to start enrichment');
      }
    },
    [load, onRefreshJobs, toast]
  );

  const toggleExpand = useCallback((item) => {
    const key = item.id;
    let shouldFetchResults = false;

    setExpanded((currentExpanded) => {
      const nextExpanded = new Set(currentExpanded);
      if (nextExpanded.has(key)) {
        nextExpanded.delete(key);
      } else {
        nextExpanded.add(key);
        shouldFetchResults = !resultsRef.current.has(key);
      }
      return nextExpanded;
    });

    if (!shouldFetchResults) return;
    getJobResults(key)
      .then((response) => {
        const jobResults = Array.isArray(response.data) ? response.data : [];
        setResults((currentResults) => {
          if (currentResults.has(key)) return currentResults;
          const nextResults = new Map(currentResults);
          nextResults.set(key, jobResults);
          return nextResults;
        });
      })
      .catch((error) => logApiWarning('Failed to load job results', error));
  }, []);

  const activeJobs = hasExternalJobs ? jobsData : jobs;

  const merged = useMemo(
    () =>
      activeJobs
        .map((job) => ({
          source: job.source_type === 'proxmox' ? SOURCE_PROXMOX : SOURCE_NETWORK,
          ...job,
          sortAt: job.started_at || job.created_at,
        }))
        .sort((first, second) => {
          const firstTs = new Date(first.sortAt || 0).getTime();
          const secondTs = new Date(second.sortAt || 0).getTime();
          return secondTs - firstTs;
        }),
    [activeJobs]
  );

  const filtered = useMemo(
    () =>
      merged.filter((item) => {
        const matchesSource = sourceFilter === 'all' || sourceFilter === item.source;
        if (!matchesSource) return false;
        const targetText = `${item.label || ''} ${item.target_cidr || ''}`.toLowerCase();
        const matchesText = !filter || targetText.includes(filter.toLowerCase());
        const matchesStatus =
          statusFilter === 'all' ||
          item.status === statusFilter ||
          (statusFilter === 'completed' && item.status === 'done');
        return matchesText && matchesStatus;
      }),
    [filter, merged, sourceFilter, statusFilter]
  );

  return (
    <div
      style={
        embedded
          ? { padding: '20px 24px' }
          : { padding: '24px 28px', maxWidth: 1200, margin: '0 auto' }
      }
    >
      {!embedded && (
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 20 }}>Discovery Scans</h1>
      )}

      {/* Filters */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          marginBottom: 20,
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: 1, maxWidth: 300 }}>
          <input
            type="text"
            className="cb-input"
            placeholder="Filter by target or name…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <select
          className="cb-input"
          style={{ width: 'auto', minWidth: 100 }}
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
        >
          <option value="all">All Types</option>
          <option value="network">Network scans</option>
          <option value="proxmox">Proxmox</option>
        </select>
        <select
          className="cb-input"
          style={{ width: 'auto', minWidth: 120 }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">All Status</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {loading ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading scan history…</p>
      ) : filtered.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
          {merged.length === 0 ? 'No scan history yet.' : 'No scans match the current filters.'}
        </p>
      ) : (
        <div className="history-table-wrap">
          <table className="history-table">
            <thead>
              <tr>
                <th className="history-col-expand" />
                <th>Started</th>
                <th>Target</th>
                <th>Type</th>
                <th>Status</th>
                <th>Found</th>
                <th>New</th>
                <th>Conflicts</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <ScanHistoryRow
                  key={item.id}
                  item={item}
                  isExpanded={expanded.has(item.id)}
                  jobResults={results.get(item.id)}
                  onToggleExpand={toggleExpand}
                  onCancelJob={handleCancelJob}
                  onEnrichJob={handleEnrichJob}
                  onRefreshJobs={onRefreshJobs}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

DiscoveryHistoryPage.propTypes = {
  embedded: PropTypes.bool,
  jobsData: PropTypes.array,
  onRefreshJobs: PropTypes.func,
};
