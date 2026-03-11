import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { ChevronDown, ChevronRight } from 'lucide-react';
import '../styles/discovery.css';
import { getJobs, getJobResults, getProxmoxRuns, cancelJob } from '../api/discovery.js';
import { proxmoxApi } from '../api/client';
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

const SOURCE_NETWORK = 'network';
const SOURCE_PROXMOX = 'proxmox';

export default function DiscoveryHistoryPage({ embedded = false }) {
  const toast = useToast();
  const [jobs, setJobs] = useState([]);
  const [proxmoxRuns, setProxmoxRuns] = useState([]);
  const [integrationNames, setIntegrationNames] = useState(() => new Map());
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(new Set());
  const [results, setResults] = useState(() => new Map());
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      getJobs()
        .then((r) => r.data)
        .catch((error) => {
          logApiWarning('Failed to load scan history', error);
          return [];
        }),
      getProxmoxRuns()
        .then((r) => r.data)
        .catch((error) => {
          logApiWarning('Failed to load Proxmox runs', error);
          return [];
        }),
      proxmoxApi
        .list()
        .then((r) => r.data || [])
        .catch(() => []),
    ])
      .then(([jobList, runList, configs]) => {
        setJobs(jobList);
        setProxmoxRuns(runList);
        const names = new Map();
        (configs || []).forEach((c) => {
          names.set(c.id, c.name || `Integration ${c.id}`);
        });
        setIntegrationNames(names);
      })
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

  const toggleExpand = (item) => {
    const key = item.source === SOURCE_PROXMOX ? `proxmox-${item.id}` : item.id;
    const newExpanded = new Set(expanded);
    if (newExpanded.has(key)) {
      newExpanded.delete(key);
    } else {
      newExpanded.add(key);
      if (item.source === SOURCE_NETWORK && !results.has(item.id)) {
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

  const renderExpandedProxmoxRun = (run) => (
    <div className="history-expanded-results" style={{ padding: '8px 0' }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 12,
          marginBottom: 8,
        }}
      >
        <div
          style={{
            textAlign: 'center',
            padding: 8,
            background: 'var(--color-bg-elevated)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 18, fontWeight: 700, color: '#22c55e' }}>
            {run.nodes_imported ?? 0}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Nodes</div>
        </div>
        <div
          style={{
            textAlign: 'center',
            padding: 8,
            background: 'var(--color-bg-elevated)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 18, fontWeight: 700, color: '#3b82f6' }}>
            {run.vms_imported ?? 0}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>VMs</div>
        </div>
        <div
          style={{
            textAlign: 'center',
            padding: 8,
            background: 'var(--color-bg-elevated)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 18, fontWeight: 700, color: '#a855f7' }}>
            {run.cts_imported ?? 0}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Containers</div>
        </div>
        <div
          style={{
            textAlign: 'center',
            padding: 8,
            background: 'var(--color-bg-elevated)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 18, fontWeight: 700, color: '#f59e0b' }}>
            {run.storage_imported ?? 0}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Storage</div>
        </div>
      </div>
      {run.errors && run.errors.length > 0 && (
        <div
          style={{
            fontSize: 12,
            color: '#ef4444',
            background: 'rgba(239,68,68,0.08)',
            padding: 8,
            borderRadius: 6,
          }}
        >
          {run.errors.join('\n')}
        </div>
      )}
    </div>
  );

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

  // Merge network jobs and Proxmox runs, sort by date desc
  const merged = [
    ...jobs.map((j) => ({
      source: SOURCE_NETWORK,
      id: j.id,
      sortAt: j.created_at,
      ...j,
    })),
    ...proxmoxRuns.map((r) => ({
      source: SOURCE_PROXMOX,
      id: r.id,
      sortAt: r.started_at || r.created_at,
      ...r,
    })),
  ].sort((a, b) => {
    const ta = new Date(a.sortAt || 0).getTime();
    const tb = new Date(b.sortAt || 0).getTime();
    return tb - ta;
  });

  const filtered = merged.filter((item) => {
    const matchesSource =
      sourceFilter === 'all' ||
      (sourceFilter === 'network' && item.source === SOURCE_NETWORK) ||
      (sourceFilter === 'proxmox' && item.source === SOURCE_PROXMOX);
    if (!matchesSource) return false;
    if (item.source === SOURCE_NETWORK) {
      const matchesText = !filter || item.target_cidr?.toLowerCase().includes(filter.toLowerCase());
      const matchesStatus = statusFilter === 'all' || item.status === statusFilter;
      return matchesText && matchesStatus;
    }
    const targetName =
      integrationNames.get(item.integration_id) || `Proxmox ${item.integration_id}`;
    const matchesText = !filter || targetName.toLowerCase().includes(filter.toLowerCase());
    const matchesStatus = statusFilter === 'all' || item.status === statusFilter;
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
                const rowKey = item.source === SOURCE_PROXMOX ? `proxmox-${item.id}` : item.id;
                const isExpanded = expanded.has(rowKey);
                if (item.source === SOURCE_PROXMOX) {
                  const targetName =
                    integrationNames.get(item.integration_id) || `Proxmox ${item.integration_id}`;
                  return (
                    <React.Fragment key={rowKey}>
                      <tr className="history-row" onClick={() => toggleExpand(item)}>
                        <td className="history-expand-cell">
                          {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        </td>
                        <td>
                          <TimestampCell isoString={item.started_at || item.created_at} />
                        </td>
                        <td className="history-target">{targetName}</td>
                        <td>
                          <span
                            style={{
                              padding: '1px 7px',
                              borderRadius: 4,
                              fontSize: 10,
                              fontWeight: 600,
                              background: '#a855f722',
                              color: '#a855f7',
                              border: '1px solid #a855f744',
                            }}
                          >
                            Proxmox
                          </span>
                        </td>
                        <td>
                          <HistoryStatusPill
                            status={item.status === 'completed' ? 'done' : item.status}
                          />
                        </td>
                        <td>{item.nodes_imported ?? 0}</td>
                        <td>—</td>
                        <td>—</td>
                      </tr>
                      {isExpanded && (
                        <tr className="history-expanded-row">
                          <td colSpan={8}>
                            <div className="history-expanded-shell">
                              {renderExpandedProxmoxRun(item)}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                }
                const types = parseJsonArray(item.scan_types_json);
                return (
                  <React.Fragment key={rowKey}>
                    <tr className="history-row" onClick={() => toggleExpand(item)}>
                      <td className="history-expand-cell">
                        {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </td>
                      <td>
                        <TimestampCell isoString={item.created_at} />
                      </td>
                      <td className="history-target">{item.target_cidr}</td>
                      <td>
                        <div className="history-type-row">
                          {types.map((t) => (
                            <TypePill key={t} type={t} />
                          ))}
                        </div>
                      </td>
                      <td style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
};

DiscoveryHistoryPage.defaultProps = {
  embedded: false,
};
