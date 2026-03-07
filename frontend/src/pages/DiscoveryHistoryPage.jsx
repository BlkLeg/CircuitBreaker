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

function TypePill({ type }) {
  const colors = { nmap: '#3b82f6', snmp: '#8b5cf6', arp: '#f59e0b', http: '#10b981' };
  const color = colors[type] || '#6b7280';
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

export default function DiscoveryHistoryPage({ embedded = false }) {
  const toast = useToast();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(new Set());
  const [results, setResults] = useState({});
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const load = useCallback(() => {
    setLoading(true);
    getJobs()
      .then((r) => setJobs(r.data))
      .catch((error) => logApiWarning('Failed to load scan history', error))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCancelJob = async (jobId, event) => {
    event?.stopPropagation();
    try {
      await cancelJob(jobId);
      toast.success('Scan cancelled');
      load();
    } catch (err) {
      toast.error(err?.message || 'Failed to cancel scan');
    }
  };

  const toggleExpand = (job) => {
    const jobId = job.id;
    const newExpanded = new Set(expanded);
    if (newExpanded.has(jobId)) {
      newExpanded.delete(jobId);
    } else {
      newExpanded.add(jobId);
      if (!results[jobId]) {
        // Load results for this job
        getJobResults(jobId)
          .then((r) => setResults((prev) => ({ ...prev, [jobId]: r.data })))
          .catch((error) => logApiWarning('Failed to load job results', error));
      }
    }
    setExpanded(newExpanded);
  };

  const renderExpandedResults = (jobId) => {
    const jobResults = results[jobId];
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
        {jobResults.slice(0, 10).map((result, idx) => {
          const ports = parsePorts(result.open_ports_json);
          return (
            <div key={idx} className="history-result-row">
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

  // Filter jobs
  const filtered = jobs.filter((j) => {
    const matchesText = !filter || j.target_cidr?.toLowerCase().includes(filter.toLowerCase());
    const matchesStatus = statusFilter === 'all' || j.status === statusFilter;
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
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 20 }}>Discovery Scan History</h1>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20, alignItems: 'center' }}>
        <div style={{ flex: 1, maxWidth: 300 }}>
          <input
            type="text"
            className="cb-input"
            placeholder="Filter by target CIDR…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
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
          {jobs.length === 0 ? 'No scan history yet.' : 'No scans match the current filters.'}
        </p>
      ) : (
        <div className="history-table-wrap">
          <table className="history-table">
            <thead>
              <tr>
                <th className="history-col-expand" />
                {['Started', 'Target', 'Types', 'Status', 'Found', 'New', 'Conflicts'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => {
                const types = parseJsonArray(j.scan_types_json);
                const isExpanded = expanded.has(j.id);
                return (
                  <React.Fragment key={j.id}>
                    <tr className="history-row" onClick={() => toggleExpand(j)}>
                      <td className="history-expand-cell">
                        {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </td>
                      <td>
                        <TimestampCell isoString={j.created_at} />
                      </td>
                      <td className="history-target">{j.target_cidr}</td>
                      <td>
                        <div className="history-type-row">
                          {types.map((t) => (
                            <TypePill key={t} type={t} />
                          ))}
                        </div>
                      </td>
                      <td style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <HistoryStatusPill status={j.status} />
                        {(j.status === 'running' || j.status === 'queued') && (
                          <button
                            type="button"
                            className="btn btn-secondary"
                            style={{ fontSize: 10, padding: '2px 8px', lineHeight: 1.4 }}
                            onClick={(e) => handleCancelJob(j.id, e)}
                          >
                            Cancel
                          </button>
                        )}
                      </td>
                      <td>{j.hosts_found ?? 0}</td>
                      <td>{j.hosts_new ?? 0}</td>
                      <td>{j.hosts_conflict ?? 0}</td>
                    </tr>
                    {isExpanded && (
                      <tr className="history-expanded-row">
                        <td colSpan={8}>
                          <div className="history-expanded-shell">
                            {renderExpandedResults(j.id)}
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
};

DiscoveryHistoryPage.defaultProps = {
  embedded: false,
};
