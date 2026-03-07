import React, { useState, useEffect, useCallback, useRef } from 'react';
import PropTypes from 'prop-types';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, RefreshCw } from 'lucide-react';
import { getJobResults } from '../../api/discovery.js';
import JobStatusBadge from './JobStatusBadge.jsx';

const PROBE_COLORS = { nmap: '#3b82f6', snmp: '#8b5cf6', arp: '#f59e0b', http: '#10b981' };

function TypePill({ type }) {
  const color = PROBE_COLORS[type] || '#6b7280';
  return (
    <span
      className="type-pill"
      style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}
    >
      {type}
    </span>
  );
}

TypePill.propTypes = { type: PropTypes.string.isRequired };

function formatTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '—';
  }
}

function parseScanTypes(job) {
  if (!job?.scan_types_json) return [];
  try {
    return JSON.parse(job.scan_types_json);
  } catch {
    return [];
  }
}

function formatEtaSecs(secs) {
  if (secs <= 0) return '< 1s';
  const h = String(Math.floor(secs / 3600)).padStart(2, '0');
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(secs % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function computeEta(job, progressPct = 0, etaSeconds = undefined) {
  if (!job.started_at || job.status === 'completed' || job.status === 'done') return '--:--:--';
  if (job.status === 'queued') return 'Pending';
  if (typeof etaSeconds === 'number') return formatEtaSecs(etaSeconds);
  if (progressPct <= 0) return '--:--:--';
  const elapsedMs = Date.now() - new Date(job.started_at).getTime();
  if (elapsedMs <= 0) return '--:--:--';
  const totalMs = (elapsedMs / progressPct) * 100;
  const remainMs = totalMs - elapsedMs;
  return formatEtaSecs(Math.floor(remainMs / 1000));
}

function parsePorts(json) {
  if (!json) return [];
  try {
    return JSON.parse(json);
  } catch {
    return [];
  }
}

function phaseToLevel(phase, message) {
  const msg = (message || '').toLowerCase();
  if (msg.includes('warn') || msg.includes('blocking')) return 'warn';
  if (phase === 'done') return 'success';
  if (phase === 'failed' || phase === 'error') return 'error';
  return 'info';
}

function formatLogTimestamp(ts) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '';
  }
}

const TABS = ['General', 'Scan Log', 'Found Devices'];
const LOG_LEVELS = ['ALL', 'INFO', 'SUCCESS', 'WARN', 'ERROR'];

export default function ScanDetailPanel({
  job,
  progressPct,
  etaSeconds,
  logEntries,
  detailedLogs,
  profileMap,
}) {
  const [activeTab, setActiveTab] = useState('General');
  const [logLevelFilter, setLogLevelFilter] = useState('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef(null);
  const [devices, setDevices] = useState([]);
  const [loadingDevices, setLoadingDevices] = useState(false);

  const loadDevices = useCallback(() => {
    if (!job) return;
    setLoadingDevices(true);
    getJobResults(job.id, { limit: 100 })
      .then((res) => {
        const results = Array.isArray(res.data) ? res.data : (res.data?.results ?? []);
        setDevices(results);
      })
      .catch(() => setDevices([]))
      .finally(() => setLoadingDevices(false));
  }, [job?.id]);

  useEffect(() => {
    if (activeTab === 'Found Devices' && job) loadDevices();
  }, [activeTab, job?.id, loadDevices]);

  useEffect(() => {
    setActiveTab('General');
  }, [job?.id]);

  // Auto-scroll log container when new entries arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  });

  const scanTypes = job ? parseScanTypes(job) : [];
  const pct = job
    ? (progressPct ?? (job.status === 'completed' || job.status === 'done' ? 100 : 0))
    : 0;
  const profileName = job
    ? (job.profile_id && profileMap[job.profile_id]) || job.label || 'Ad-hoc'
    : '—';

  // Prefer detailed DB-backed logs; fall back to lightweight progress-event logs
  const rawDetailedLogs = detailedLogs && detailedLogs.length > 0 ? detailedLogs : null;
  const rawProgressLogs = logEntries
    ? logEntries.map((e) => ({
        id: `p-${e.ts}`,
        timestamp: e.ts,
        level: phaseToLevel(e.phase, e.message).toUpperCase(),
        phase: e.phase,
        message: e.message,
        details: null,
      }))
    : [];
  const allLogs = rawDetailedLogs ?? rawProgressLogs;
  const combinedLogs =
    logLevelFilter === 'ALL' ? allLogs : allLogs.filter((e) => e.level === logLevelFilter);

  return (
    <div className="scan-detail-panel">
      <div className="scan-detail-header">
        <div className="scan-detail-tabs">
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              className={`scan-detail-tab ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        {job && (
          <div className="scan-detail-actions">
            <button
              type="button"
              className="scan-toolbar-btn"
              title="Export results"
              onClick={() => {
                const blob = new Blob([JSON.stringify(job, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `scan-${job.id}.json`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              <Download size={14} />
            </button>
            <button
              type="button"
              className="scan-toolbar-btn"
              title="Refresh"
              onClick={() => {
                if (activeTab === 'Found Devices') loadDevices();
              }}
            >
              <RefreshCw size={14} />
            </button>
          </div>
        )}
      </div>

      <div className="scan-detail-body">
        <AnimatePresence mode="wait">
          {activeTab === 'General' && (
            <motion.div
              key="general"
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              transition={{ duration: 0.15 }}
              className="detail-grid"
            >
              {job ? (
                <>
                  {/* Row 1: ID | Target | Profile */}
                  <div className="detail-item">
                    <span className="detail-item-label">ID</span>
                    <span className="detail-item-value mono">{job.id}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-item-label">Target</span>
                    <span className="detail-item-value mono">{job.target_cidr}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-item-label">Profile</span>
                    <span className="detail-item-value">{profileName}</span>
                  </div>
                  {/* Row 2: Status | Probes | Found */}
                  <div className="detail-item">
                    <span className="detail-item-label">Status</span>
                    <span className="detail-item-value">
                      <JobStatusBadge status={job.status} pill />
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-item-label">Probes</span>
                    <div className="detail-probes">
                      {scanTypes.map((t) => (
                        <TypePill key={t} type={t} />
                      ))}
                      {scanTypes.length === 0 && <span className="detail-item-value">—</span>}
                    </div>
                  </div>
                  <div className="detail-item">
                    <span className="detail-item-label">Found</span>
                    <span
                      className="detail-item-value"
                      style={
                        (job.hosts_found ?? 0) > 0 ? { color: 'var(--color-primary)' } : undefined
                      }
                    >
                      {job.hosts_found ?? 0}
                    </span>
                  </div>
                  {/* Row 3: New | Conflicts | Start Time */}
                  <div className="detail-item">
                    <span className="detail-item-label">New</span>
                    <span
                      className="detail-item-value"
                      style={(job.hosts_new ?? 0) > 0 ? { color: '#22c55e' } : undefined}
                    >
                      {job.hosts_new ?? 0}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-item-label">Conflicts</span>
                    <span className="detail-item-value">{job.hosts_conflict ?? 0}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-item-label">Start Time</span>
                    <span className="detail-item-value mono">{formatTime(job.started_at)}</span>
                  </div>
                  {/* Row 4: ETA */}
                  <div className="detail-item">
                    <span className="detail-item-label">ETA</span>
                    <span className="detail-item-value mono">
                      {computeEta(job, pct, etaSeconds)}
                    </span>
                  </div>
                </>
              ) : (
                <div className="scan-detail-empty" style={{ gridColumn: '1 / -1' }}>
                  Select a scan to view details
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'Scan Log' && (
            <motion.div
              key="log"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="scan-log-panel"
            >
              {/* Log controls */}
              <div className="scan-log-controls">
                <div className="log-filters">
                  <select
                    value={logLevelFilter}
                    onChange={(e) => setLogLevelFilter(e.target.value)}
                    className="log-level-filter"
                  >
                    {LOG_LEVELS.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="log-controls">
                  <label className="auto-scroll-toggle">
                    <input
                      type="checkbox"
                      checked={autoScroll}
                      onChange={(e) => setAutoScroll(e.target.checked)}
                    />
                    Auto-scroll
                  </label>
                </div>
              </div>

              {/* Log stream */}
              <div className="scan-log-stream" ref={logContainerRef}>
                {!job ? (
                  <div className="scan-log-empty">Select a scan to view log</div>
                ) : combinedLogs.length === 0 ? (
                  <div className="scan-log-empty">No log entries for this scan</div>
                ) : (
                  combinedLogs.map((entry) => (
                    <div key={entry.id} className="scan-log-entry">
                      <span className="log-ts">[{formatLogTimestamp(entry.timestamp)}]</span>
                      <span className={`log-level log-level-${entry.level.toLowerCase()}`}>
                        {entry.level}
                      </span>
                      {entry.phase && <span className="log-phase">{entry.phase}</span>}
                      <span className="log-msg">{entry.message}</span>
                      {entry.details && <div className="log-details">{entry.details}</div>}
                    </div>
                  ))
                )}
              </div>
            </motion.div>
          )}

          {activeTab === 'Found Devices' && (
            <motion.div
              key="results"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              {!job ? (
                <div className="scan-log-empty">Select a scan to view devices</div>
              ) : (
                <FoundDevicesTab loading={loadingDevices} devices={devices} />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function formatOsVendor(d) {
  if (d.os_vendor && d.os_family) return `${d.os_vendor} (${d.os_family})`;
  if (d.os_family) return d.os_family;
  if (d.os_vendor) return d.os_vendor;
  if (d.snmp_sys_name) return d.snmp_sys_name;
  return '—';
}

function FoundDevicesTab({ loading, devices }) {
  if (loading) return <div className="scan-log-empty">Loading devices…</div>;
  if (devices.length === 0)
    return <div className="scan-log-empty">No devices found in this scan</div>;

  return (
    <table className="found-devices-table">
      <thead>
        <tr>
          <th>IP Address</th>
          <th>Hostname</th>
          <th>OS / Vendor</th>
          <th>Services</th>
        </tr>
      </thead>
      <tbody>
        {devices.map((d) => {
          const ports = parsePorts(d.open_ports_json);
          const isNew = d.state === 'new';
          const serviceStr = ports.map((p) => p.port).join(', ');
          return (
            <tr key={d.id} className={isNew ? 'is-new' : ''}>
              <td className="col-ip">{d.ip_address}</td>
              <td>{d.hostname || '—'}</td>
              <td>{formatOsVendor(d)}</td>
              <td>
                {serviceStr || '—'}
                {isNew && <span className="found-new-badge">NEW</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

FoundDevicesTab.propTypes = {
  loading: PropTypes.bool,
  devices: PropTypes.array,
};

ScanDetailPanel.propTypes = {
  job: PropTypes.object,
  progressPct: PropTypes.number,
  etaSeconds: PropTypes.number,
  logEntries: PropTypes.array,
  detailedLogs: PropTypes.array,
  profileMap: PropTypes.object,
};
