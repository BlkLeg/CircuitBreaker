import React from 'react';
import PropTypes from 'prop-types';
import { motion } from 'framer-motion';
import { Play, Pause, Trash2, Settings } from 'lucide-react';
import JobStatusBadge from './JobStatusBadge.jsx';

function formatTime(iso) {
  if (!iso) return '--:--:--';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '--:--:--';
  }
}

function formatEtaSecs(secs) {
  if (secs <= 0) return '< 1s';
  const h = String(Math.floor(secs / 3600)).padStart(2, '0');
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(secs % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function parseJsonArray(json) {
  if (!json) return [];
  try {
    const arr = JSON.parse(json);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

const parseVlanIds = parseJsonArray;

function isDockerJob(job) {
  const types = parseJsonArray(job.scan_types_json);
  return types.includes('docker');
}

function computeEta(job, progressPct = 0, etaSeconds = undefined) {
  if (!job.started_at || job.status === 'completed' || job.status === 'done') return '--:--:--';
  if (job.status === 'queued') return 'Pending';
  if (typeof etaSeconds === 'number') return formatEtaSecs(etaSeconds);
  const pct = progressPct;
  if (pct <= 0) return '--:--:--';
  const elapsedMs = Date.now() - new Date(job.started_at).getTime();
  if (elapsedMs <= 0) return '--:--:--';
  const totalMs = (elapsedMs / pct) * 100;
  const remainMs = totalMs - elapsedMs;
  return formatEtaSecs(Math.floor(remainMs / 1000));
}

export default function ScanTable({
  jobs,
  profileMap,
  progressMap,
  etaMap,
  selectedJobId,
  onSelectJob,
  searchQuery,
  onSearchChange,
  onCancelJob,
}) {
  const filteredJobs = searchQuery
    ? jobs.filter((j) => {
        const q = searchQuery.toLowerCase();
        if (j.target_cidr?.toLowerCase().includes(q)) return true;
        if (isDockerJob(j) && 'docker'.includes(q)) return true;
        const scanTypes = parseJsonArray(j.scan_types_json);
        if (scanTypes.some((t) => t.toLowerCase().includes(q))) return true;
        return false;
      })
    : jobs;

  return (
    <>
      {/* Toolbar */}
      <div className="scan-toolbar">
        <div className="scan-toolbar-actions">
          <button type="button" className="scan-toolbar-btn" title="Resume" disabled>
            <Play size={14} />
          </button>
          <button type="button" className="scan-toolbar-btn" title="Pause" disabled>
            <Pause size={14} />
          </button>
          <button
            type="button"
            className="scan-toolbar-btn"
            title="Cancel selected scan"
            disabled={!selectedJobId}
            onClick={() => {
              if (selectedJobId) onCancelJob(selectedJobId);
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>

        <div className="scan-toolbar-divider" />

        <button type="button" className="scan-toolbar-btn" title="Settings" disabled>
          <Settings size={14} />
        </button>

        <span className="scan-toolbar-spacer" />

        <input
          type="text"
          className="cb-input scan-toolbar-filter"
          placeholder="Filter scans..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      {/* Table */}
      <div className="scan-table-wrap">
        <table className="scan-table">
          <thead>
            <tr>
              <th className="col-checkbox">
                <input type="checkbox" disabled />
              </th>
              <th>Target Network</th>
              <th>Profile</th>
              <th>Progress</th>
              <th>Status</th>
              <th className="col-found">Found</th>
              <th className="col-new">New</th>
              <th>Start Time</th>
              <th>ETA</th>
            </tr>
          </thead>
          <tbody>
            {filteredJobs.length === 0 ? (
              <tr>
                <td colSpan={9} className="scan-table-empty">
                  {searchQuery
                    ? 'No scans match your filter'
                    : 'No scans yet. Click "New Scan" to start.'}
                </td>
              </tr>
            ) : (
              filteredJobs.map((job) => {
                const pct =
                  progressMap.get(job.id) ??
                  (job.status === 'completed' || job.status === 'done' ? 100 : 0);
                const profileName =
                  (job.profile_id && profileMap.get(job.profile_id)) || job.label || 'Ad-hoc';
                const isSelected = selectedJobId === job.id;
                const isRunning = job.status === 'running';

                return (
                  <tr
                    key={job.id}
                    className={isSelected ? 'selected' : ''}
                    onClick={() => onSelectJob(job.id)}
                  >
                    <td className="col-checkbox">
                      <input type="checkbox" checked={isSelected} readOnly />
                    </td>
                    <td className="col-target">
                      <div
                        style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}
                      >
                        {parseVlanIds(job.vlan_ids).map((vid) => (
                          <span
                            key={vid}
                            style={{
                              background: 'rgba(56, 189, 248, 0.15)',
                              color: '#0284c7',
                              border: '1px solid rgba(56, 189, 248, 0.3)',
                              borderRadius: 4,
                              padding: '1px 6px',
                              fontSize: 10,
                              fontWeight: 600,
                              whiteSpace: 'nowrap',
                            }}
                            title={`VLAN ${vid}`}
                          >
                            VLAN {vid}
                          </span>
                        ))}
                        {isDockerJob(job) ? (
                          <span
                            title={job.label || 'Docker (all networks)'}
                            style={{
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              maxWidth: '150px',
                              display: 'inline-block',
                              verticalAlign: 'bottom',
                              color: 'var(--color-text-secondary)',
                            }}
                          >
                            Docker{job.target_cidr ? ` — ${job.target_cidr}` : ' (all networks)'}
                          </span>
                        ) : (
                          <span
                            title={job.target_cidr}
                            style={{
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              maxWidth: '150px',
                              display: 'inline-block',
                              verticalAlign: 'bottom',
                            }}
                          >
                            {job.target_cidr}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="col-profile">{profileName}</td>
                    <td className="col-progress">
                      <div className="scan-progress-cell">
                        <div className="scan-progress-meta">
                          <span className="scan-progress-pct">{pct}%</span>
                          {isRunning && <span className="scan-live-tag">LIVE</span>}
                        </div>
                        <div className="scan-progress-track">
                          <motion.div
                            className={`scan-progress-fill status-${job.status}`}
                            initial={{ width: 0 }}
                            animate={{ width: `${pct}%` }}
                            transition={{ duration: 0.4, ease: 'easeOut' }}
                          />
                        </div>
                      </div>
                    </td>
                    <td>
                      <JobStatusBadge status={job.status} pill />
                    </td>
                    <td className="col-found">
                      {(job.hosts_found ?? 0) > 0 ? (
                        <span style={{ color: 'var(--color-primary)' }}>{job.hosts_found}</span>
                      ) : (
                        0
                      )}
                    </td>
                    <td className="col-new">
                      {(job.hosts_new ?? 0) > 0 ? (
                        <span style={{ color: '#22c55e' }}>{job.hosts_new}</span>
                      ) : (
                        0
                      )}
                    </td>
                    <td className="col-time">
                      {job.status === 'queued' ? 'Pending' : formatTime(job.started_at)}
                    </td>
                    <td className="col-time">{computeEta(job, pct, etaMap?.[job.id])}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

ScanTable.propTypes = {
  jobs: PropTypes.array.isRequired,
  profileMap: PropTypes.object.isRequired,
  progressMap: PropTypes.object.isRequired,
  etaMap: PropTypes.object,
  selectedJobId: PropTypes.number,
  onSelectJob: PropTypes.func.isRequired,
  searchQuery: PropTypes.string.isRequired,
  onSearchChange: PropTypes.func.isRequired,
  onCancelJob: PropTypes.func.isRequired,
};
