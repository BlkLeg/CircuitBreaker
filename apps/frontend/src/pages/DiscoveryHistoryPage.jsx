import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { ChevronDown, ChevronRight } from 'lucide-react';
import '../styles/discovery.css';
import { getJobs, getJobResults, cancelJob } from '../api/discovery.js';
import { useToast } from '../components/common/Toast';
import TimestampCell from '../components/TimestampCell.jsx';
import logger from '../utils/logger.js';

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
  return <span className={`history-status-pill status-${normalized}`}>{label}</span>;
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

function formatEtaSeconds(secs) {
  if (typeof secs !== 'number' || secs < 0) return null;
  if (secs < 1) return '< 1s';
  const h = String(Math.floor(secs / 3600)).padStart(2, '0');
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(Math.floor(secs % 60)).padStart(2, '0');
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

  const handleCancelJob = async (jobId, event) => {
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
  };

  const toggleExpand = (item) => {
    const key = item.id;
    const newExpanded = new Set(expanded);
    if (newExpanded.has(key)) {
      newExpanded.delete(key);
    } else {
      newExpanded.add(key);
      if (!results.has(item.id)) {
        getJobResults(item.id)
          .then((r) => {
            setResults((prev) => {
              const next = new Map(prev);
              next.set(item.id, r.data);
              return next;
            });
          })
          .catch((error) => logApiWarning('Failed to load job results', error));
      }
    }
    setExpanded(newExpanded);
  };

  const renderExpandedResults = (jobId) => {
    const jobResults = results.get(jobId);
    if (!jobResults)
      return (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
          Loading results…
        </p>
      );

    if (jobResults.length === 0) {
      return (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
          No devices found
        </p>
      );
    }

    return (
      <div className="history-expanded-results">
        {jobResults.slice(0, 10).map((result) => {
          const ports = parsePorts(result.open_ports_json);
          return (
            <div
              key={result.id ?? `${result.ip_address}-${result.mac_address ?? 'na'}`}
              className="history-result-row"
            >
              <div className="history-result-ip">{result.ip_address}</div>
              <div className="history-result-mac">{result.mac_address || '—'}</div>
              <div className="history-result-os">
                {[result.os_family, result.os_vendor].filter(Boolean).join(' ') || 'Unknown'}
              </div>
              {ports.length > 0 && (
                <div className="history-result-ports">
                  <PortPills ports={ports} />
                </div>
              )}
            </div>
          );
        })}
        {jobResults.length > 10 && (
          <p style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '8px 0 0' }}>
            …and {jobResults.length - 10} more results
          </p>
        )}
      </div>
    );
  };

  const activeJobs = hasExternalJobs ? jobsData : jobs;

  const merged = activeJobs
    .map((j) => ({
      source: j.source_type === 'proxmox' ? SOURCE_PROXMOX : SOURCE_NETWORK,
      ...j,
      sortAt: j.started_at || j.created_at,
    }))
    .sort((a, b) => {
      const ta = new Date(a.sortAt || 0).getTime();
      const tb = new Date(b.sortAt || 0).getTime();
      return tb - ta;
    });

  const filtered = merged.filter((item) => {
    const matchesSource = sourceFilter === 'all' || sourceFilter === item.source;
    if (!matchesSource) return false;
    const targetText = `${item.label || ''} ${item.target_cidr || ''}`.toLowerCase();
    const matchesText = !filter || targetText.includes(filter.toLowerCase());
    const matchesStatus =
      statusFilter === 'all' ||
      item.status === statusFilter ||
      (statusFilter === 'completed' && item.status === 'done');
    return matchesText && matchesStatus;
  });

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
              {filtered.map((item) => {
                const rowKey = item.id;
                const isExpanded = expanded.has(item.id);
                const types = parseJsonArray(item.scan_types_json);
                const targetLabel = item.label || item.target_cidr || 'Ad-hoc scan';
                const progressPercent = getProgressPercent(item);
                const liveEta = formatEtaSeconds(item.eta_seconds);
                const liveMessage = getLiveMessage(item);
                const showLiveMeta =
                  item.status === 'running' ||
                  item.status === 'queued' ||
                  typeof item.progress_percent === 'number' ||
                  typeof item.eta_seconds === 'number';
                return (
                  <React.Fragment key={rowKey}>
                    <tr className="history-row" onClick={() => toggleExpand(item)}>
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
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                            flexWrap: 'wrap',
                          }}
                        >
                          <HistoryStatusPill status={item.status} />
                          {(item.status === 'running' || item.status === 'queued') && (
                            <button
                              type="button"
                              className="btn btn-secondary"
                              style={{ fontSize: 10, padding: '2px 8px', lineHeight: 1.4 }}
                              onClick={(e) => handleCancelJob(item.id, e)}
                            >
                              Cancel
                            </button>
                          )}
                        </div>
                        {showLiveMeta && (
                          <div className="history-live-meta">
                            <span>{progressPercent}%</span>
                            {liveEta && <span>ETA {liveEta}</span>}
                          </div>
                        )}
                        {liveMessage && <div className="history-live-message">{liveMessage}</div>}
                      </td>
                      <td>{item.hosts_found ?? 0}</td>
                      <td>{item.hosts_new ?? 0}</td>
                      <td>{item.hosts_conflict ?? 0}</td>
                    </tr>
                    {isExpanded && (
                      <tr className="history-expanded-row">
                        <td colSpan={8}>
                          <div className="history-expanded-shell">
                            {renderExpandedResults(item.id)}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
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
