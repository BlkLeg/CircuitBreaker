import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useSearchParams } from 'react-router-dom';
import { Plus, Play, Trash2, ChevronDown, ChevronRight, Layers } from 'lucide-react';
import { AnimatePresence } from 'framer-motion';
import '../styles/discovery.css';
import NmapArgsField from '../components/discovery/NmapArgsField.jsx';
import {
  getProfiles, deleteProfile, runProfile,
  startAdHocScan, cancelJob, getJobs, getJobResults,
  getPendingResults, bulkMerge, mergeResult,
} from '../api/discovery.js';
import { useSettings } from '../context/SettingsContext';
import { useToast } from '../components/common/Toast';
import { discoveryEmitter } from '../hooks/useDiscoveryStream.js';
import ScanProfileForm from '../components/discovery/ScanProfileForm.jsx';
import ReviewDrawer from '../components/discovery/ReviewDrawer.jsx';
import BulkActionsDrawer from '../components/discovery/BulkActionsDrawer.jsx';
import ServiceChecklistModal from '../components/discovery/ServiceChecklistModal.jsx';
import ScanAckModal from '../components/discovery/ScanAckModal.jsx';
import JobStatusBadge from '../components/discovery/JobStatusBadge.jsx';
import TimestampCell from '../components/TimestampCell.jsx';
import ConfirmDialog from '../components/common/ConfirmDialog.jsx';
import logger from '../utils/logger.js';

const TABS = ['profiles', 'adhoc', 'review', 'history'];
const TAB_LABELS = { profiles: 'Scan Profiles', adhoc: 'Ad-hoc Scan', review: 'Review Queue', history: 'Scan History' };

const PHASE_LABELS = {
  queued:    { label: 'Queued…',                       icon: '\u23F3' },
  arp:       { label: 'ARP scanning subnet',            icon: '\uD83D\uDCE1' },
  nmap:      { label: 'nmap port scanning',             icon: '\uD83D\uDD0D' },
  snmp:      { label: 'SNMP walking devices',           icon: '\uD83D\uDCCA' },
  http:      { label: 'HTTP probing open ports',        icon: '\uD83C\uDF10' },
  reconcile: { label: 'Matching to existing entities',  icon: '\uD83D\uDD17' },
  done:      { label: 'Scan complete',                  icon: '\u2705' },
  failed:    { label: 'Scan failed',                    icon: '\u274C' },
};

const STATE_BADGE = {
  new:      { label: 'New',      color: '#22c55e', bg: 'rgba(34,197,94,0.15)'  },
  matched:  { label: 'Matched',  color: '#6b7280', bg: 'rgba(107,114,128,0.15)' },
  conflict: { label: 'Conflict', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
};

function StateBadge({ state }) {
  const cfg = STATE_BADGE[state] ?? STATE_BADGE.new;
  return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}33` }}>
      {cfg.label}
    </span>
  );
}

StateBadge.propTypes = {
  state: PropTypes.string.isRequired,
};

function logApiWarning(scope, error) {
  logger.warn(`[DiscoveryPage] ${scope}`, error);
}

function pluralize(value, singular, plural = `${singular}s`) {
  return value === 1 ? singular : plural;
}

function getReviewTabLabel(pendingCount) {
  if (pendingCount > 0) {
    return `${TAB_LABELS.review} (${pendingCount})`;
  }
  return TAB_LABELS.review;
}

function getProgressFillClass(status) {
  if (status === 'running') return 'progress-fill indeterminate';
  if (status === 'completed' || status === 'done') return 'progress-fill full';
  return 'progress-fill';
}

export default function DiscoveryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { settings, reloadSettings } = useSettings();

  const activeTab = searchParams.get('tab') || 'profiles';
  const setTab = (t) => setSearchParams({ tab: t });

  // Pending count for Review Queue tab label — updated by WebSocket events
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    const onAdded = () => setPendingCount((c) => c + 1);
    discoveryEmitter.on('result:added', onAdded);
    return () => discoveryEmitter.off('result:added', onAdded);
  }, []);

  // Fetch initial pending count
  useEffect(() => {
    getPendingResults({ limit: 1 })
      .then((res) => setPendingCount(res.data?.total ?? res.data?.length ?? 0))
      .catch((error) => logApiWarning('Failed to fetch pending results count', error));
  }, []);

  // Scan ack gate
  const [ackPending, setAckPending]         = useState(false);
  const ackCallbackRef                       = useRef(null);

  const requireAck = useCallback((cb) => {
    if (settings?.scan_ack_accepted) { cb(); return; }
    ackCallbackRef.current = cb;
    setAckPending(true);
  }, [settings?.scan_ack_accepted]);

  const handleAckConfirm = () => {
    setAckPending(false);
    reloadSettings();
    ackCallbackRef.current?.();
    ackCallbackRef.current = null;
  };
  const handleAckCancel = () => { setAckPending(false); ackCallbackRef.current = null; };

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1200, margin: '0 auto' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 20 }}>Auto-Discovery</h1>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--color-border)', marginBottom: 24 }}>
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            style={{
              padding: '8px 16px', fontSize: 13, fontWeight: 500, cursor: 'pointer',
              background: 'none', border: 'none',
              borderBottom: activeTab === t ? '2px solid var(--color-primary)' : '2px solid transparent',
              color: activeTab === t ? 'var(--color-primary)' : 'var(--color-text-muted)',
              transition: 'all 0.15s',
            }}
          >
            {t === 'review' ? getReviewTabLabel(pendingCount) : TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {activeTab === 'profiles' && <ProfilesTab requireAck={requireAck} onJobStart={() => setTab('adhoc')} />}
      {activeTab === 'adhoc'    && <AdHocTab    requireAck={requireAck} onViewResults={() => setTab('review')} />}
      {activeTab === 'review'   && <ReviewTab   setPendingCount={setPendingCount} />}
      {activeTab === 'history'  && <HistoryTab />}

      {ackPending && <ScanAckModal onConfirm={handleAckConfirm} onCancel={handleAckCancel} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Tab 1 — Scan Profiles
// ─────────────────────────────────────────────────────────────────
function ProfilesTab({ requireAck, onJobStart }) {
  const toast = useToast();
  const [profiles, setProfiles] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editing,  setEditing]  = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    getProfiles()
      .then((r) => setProfiles(r.data))
      .catch((error) => logApiWarning('Failed to load profiles', error))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRunNow = (profile) => {
    requireAck(async () => {
      try {
        await runProfile(profile.id);
        toast.success(`Scan started for ${profile.cidr}`);
        onJobStart();
      } catch (err) {
        if (err?.response?.status === 429) toast.warn('Please wait before starting another scan');
        else toast.error(err?.message || 'Failed to start scan');
      }
    });
  };

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    try {
      await deleteProfile(deleteConfirm.id);
      toast.success(`Profile '${deleteConfirm.name}' deleted`);
      load();
    } catch (err) { toast.error(err?.message || 'Failed to delete'); }
    setDeleteConfirm(null);
  };

  if (loading) return <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading profiles…</p>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Scan Profiles</h2>
        <button type="button" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6 }} onClick={() => { setEditing(null); setFormOpen(true); }}>
          <Plus size={14} /> Add Profile
        </button>
      </div>

      {profiles.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center', padding: '40px 0' }}>
          No scan profiles yet. Add one to start discovering your network automatically.
        </p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              {['Name', 'CIDR', 'Scan Types', 'Schedule', 'Last Run', ''].map((h) => (
                <th key={h} style={thStyle}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {profiles.map((p) => (
              <tr key={p.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                <td style={tdStyle}>
                  <span style={{ marginRight: 6, fontSize: 10 }}>{p.enabled ? '●' : '○'}</span>
                  {p.name}
                </td>
                <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{p.cidr}</td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {p.scan_types.map((t) => <TypePill key={t} type={t} />)}
                  </div>
                </td>
                <td style={{ ...tdStyle, color: 'var(--color-text-muted)', fontSize: 12, fontFamily: 'monospace' }}>
                  {p.schedule_cron || '—'}
                </td>
                <td style={tdStyle}>
                  {p.last_run ? <TimestampCell isoString={p.last_run} /> : <span style={{ color: 'var(--color-text-muted)' }}>Never</span>}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button type="button" className="btn btn-secondary" style={{ padding: '3px 10px', fontSize: 11 }} onClick={() => handleRunNow(p)}>
                      <Play size={11} /> Run
                    </button>
                    <button type="button" className="btn btn-secondary" style={{ padding: '3px 10px', fontSize: 11 }} onClick={() => { setEditing(p); setFormOpen(true); }}>Edit</button>
                    <button type="button" className="btn btn-danger" style={{ padding: '3px 8px', fontSize: 11 }} onClick={() => setDeleteConfirm(p)}><Trash2 size={11} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={Boolean(deleteConfirm)}
        message={deleteConfirm ? `Delete profile "${deleteConfirm.name}"?` : ''}
        onConfirm={handleDelete}
        onCancel={() => setDeleteConfirm(null)}
      />

      {formOpen && (
        <ScanProfileForm
          profile={editing}
          onClose={() => setFormOpen(false)}
          onSaved={() => { setFormOpen(false); load(); }}
        />
      )}
    </div>
  );
}

ProfilesTab.propTypes = {
  requireAck: PropTypes.func.isRequired,
  onJobStart: PropTypes.func.isRequired,
};

// ─────────────────────────────────────────────────────────────────
// Tab 2 — Ad-hoc Scan
// ─────────────────────────────────────────────────────────────────
function AdHocTab({ requireAck, onViewResults }) {
  const toast = useToast();
  const { settings } = useSettings();

  const [cidr,        setCidr]        = useState(settings?.discovery_default_cidr || '');
  const [scanTypes,   setScanTypes]   = useState(['nmap', 'snmp', 'http']);
  const [nmapArgs,    setNmapArgs]    = useState(settings?.discovery_nmap_args || '-sV -O --open -T4');
  const [snmpCom,     setSnmpCom]     = useState('');
  const [advanced,    setAdvanced]    = useState(false);
  const [activeJob,   setActiveJob]   = useState(null);
  const [logLines,    setLogLines]    = useState([]);
  const [jobDone,     setJobDone]     = useState(false);
  const logIdRef = useRef(0);

  // Subscribe to WebSocket job events
  useEffect(() => {
    if (!activeJob) return;

    const onProgress = ({ job_id, phase, message }) => {
      if (job_id !== activeJob.id) return;
      if (message) {
        setLogLines((prev) => [
          ...prev.slice(-99),
          { id: `${activeJob.id}-${logIdRef.current++}`, text: message },
        ]);
      }
      if (phase) setActiveJob((j) => j ? { ...j, progress_phase: phase, progress_message: message } : j);
    };

    const onUpdate = (job) => {
      if (job.id !== activeJob.id) return;
      setActiveJob(job);
      if (job.status === 'completed' || job.status === 'done') {
        setJobDone(true);
        toast.success(`Scan complete — ${job.hosts_found} hosts found`);
        discoveryEmitter.emit('badge:refresh');
      } else if (job.status === 'failed') {
        toast.error(`Scan failed: ${job.error_text || 'unknown error'}`);
      } else if (job.status === 'cancelled') {
        toast.info('Scan cancelled');
      }
    };

    discoveryEmitter.on('job:progress', onProgress);
    discoveryEmitter.on('job:update',   onUpdate);
    return () => {
      discoveryEmitter.off('job:progress', onProgress);
      discoveryEmitter.off('job:update',   onUpdate);
    };
  }, [activeJob, toast]);

  const toggleScanType = (t) =>
    setScanTypes((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);

  const handleLaunch = () => {
    requireAck(async () => {
      setLogLines([]);
      setJobDone(false);
      try {
        const res = await startAdHocScan({
          cidr, scan_types: scanTypes,
          nmap_arguments: nmapArgs || undefined,
          snmp_community: snmpCom || undefined,
        });
        setActiveJob(res.data);
        toast.success(`Scan started for ${cidr}`);
      } catch (err) {
        if (err?.response?.status === 429) toast.warn('Please wait before starting another scan');
        else toast.error(err?.message || 'Failed to launch scan');
      }
    });
  };

  const handleCancel = async () => {
    if (!activeJob) return;
    try {
      await cancelJob(activeJob.id);
      toast.info('Scan cancelled');
      setActiveJob((j) => ({ ...j, status: 'cancelled' }));
    } catch (err) { toast.error(err?.message || 'Failed to cancel'); }
  };

  const isRunning = activeJob?.status === 'running';

  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Ad-hoc Scan</h2>

      {/* Form */}
      <div style={{ maxWidth: 520, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="cb-field">
          <label className="cb-label" htmlFor="adhoc-target-network">Target Network</label>
          <input id="adhoc-target-network" className="cb-input" value={cidr} onChange={(e) => setCidr(e.target.value)} placeholder="192.168.1.0/24" />
        </div>

        <div>
          <span style={labelStyle}>Scan Types</span>
          <div style={{ display: 'flex', gap: 12 }}>
            {['nmap', 'snmp', 'arp', 'http'].map((t) => (
              <label key={t} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', fontSize: 13 }}>
                <input type="checkbox" checked={scanTypes.includes(t)} onChange={() => toggleScanType(t)} />
                {t}
              </label>
            ))}
          </div>
        </div>

        {/* Advanced */}
        <button type="button" style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, padding: 0 }} onClick={() => setAdvanced((v) => !v)}>
          {advanced ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Advanced Options
        </button>
        {advanced && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingLeft: 16, borderLeft: '2px solid var(--color-border)' }}>
            <NmapArgsField value={nmapArgs} onChange={setNmapArgs} />
            <div className="cb-field">
              <label className="cb-label" htmlFor="adhoc-snmp-community">SNMP Community</label>
              <input id="adhoc-snmp-community" className="cb-input" type="password" value={snmpCom} onChange={(e) => setSnmpCom(e.target.value)} placeholder="public" autoComplete="off" />
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-primary" disabled={!cidr || isRunning} onClick={handleLaunch}>
            Launch Scan →
          </button>
        </div>
      </div>

      {/* Active job panel */}
      {activeJob && (
        <div style={{ marginTop: 28, padding: '20px 20px', borderRadius: 8, border: '1px solid var(--color-border)', background: 'var(--color-surface)', maxWidth: 620 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <JobStatusBadge status={activeJob.status} />
              <span style={{ fontSize: 13 }}>
                {isRunning ? `Scanning ${activeJob.target_cidr}…` : `${activeJob.target_cidr}`}
              </span>
            </div>
            {isRunning && (
              <button type="button" className="btn btn-secondary" style={{ fontSize: 11 }} onClick={handleCancel}>Cancel</button>
            )}
          </div>

          {/* Scan progress banner */}
          <div className="scan-progress-banner">
            {isRunning && (
              <div className="phase-row">
                <span className="phase-icon">
                  {(PHASE_LABELS[activeJob.progress_phase] ?? PHASE_LABELS.queued).icon}
                </span>
                <span className="phase-label">
                  {(PHASE_LABELS[activeJob.progress_phase] ?? PHASE_LABELS.queued).label}
                </span>
                <span className="spinner" aria-label="scanning" />
              </div>
            )}
            {activeJob.progress_message && (
              <div className="progress-message">{activeJob.progress_message}</div>
            )}
            <div className="progress-stats">
              <span>{activeJob.hosts_found} {pluralize(activeJob.hosts_found, 'host')} found</span>
              {activeJob.hosts_new > 0 && <span>{activeJob.hosts_new} new</span>}
              {activeJob.hosts_conflict > 0 && <span>{activeJob.hosts_conflict} conflicts</span>}
            </div>
            <div className="progress-track">
              <div className={getProgressFillClass(activeJob.status)} />
            </div>
          </div>

          {/* Live log */}
          {logLines.length > 0 && (
            <div style={{ maxHeight: 160, overflowY: 'auto', background: 'var(--color-bg)', borderRadius: 4, padding: '8px 10px', fontFamily: 'monospace', fontSize: 11, color: 'var(--color-text-muted)' }}>
              {logLines.map((line) => <div key={line.id}>✓ {line.text}</div>)}
            </div>
          )}

          {/* Done summary */}
          {jobDone && (
            <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12 }}>
                Scan complete. {activeJob.hosts_found} hosts found:{' '}
                <strong>{activeJob.hosts_new}</strong> new,{' '}
                <strong>{activeJob.hosts_conflict}</strong> conflict,{' '}
                <strong>{activeJob.hosts_updated}</strong> matched.
              </span>
              <button type="button" className="btn btn-primary" style={{ fontSize: 11 }} onClick={onViewResults}>
                Review Results →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

AdHocTab.propTypes = {
  requireAck: PropTypes.func.isRequired,
  onViewResults: PropTypes.func.isRequired,
};

// ─────────────────────────────────────────────────────────────────
// Tab 3 — Review Queue
// ─────────────────────────────────────────────────────────────────
function ReviewTab({ setPendingCount }) {
  const toast = useToast();
  const [results,   setResults]   = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [selected,  setSelected]  = useState(new Set());
  const [reviewing, setReviewing] = useState(null);
  const [bulkDrawerOpen, setBulkDrawerOpen] = useState(false);
  const [checklist, setChecklist] = useState(null);
  const [filterState, setFilterState] = useState('all');
  const [rejectConfirm, setRejectConfirm] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    getPendingResults({ limit: 100 })
      .then((r) => {
        const data = Array.isArray(r.data) ? r.data : (r.data?.results ?? []);
        setResults(data);
        const pending = data.filter((x) => x.merge_status === 'pending').length;
        setPendingCount(pending);
      })
      .catch((error) => logApiWarning('Failed to load review results', error))
      .finally(() => setLoading(false));
  }, [setPendingCount]);

  useEffect(() => { load(); }, [load]);

  // WebSocket: append new results at the top
  useEffect(() => {
    const onAdded = (result) => {
      setResults((prev) => [result, ...prev]);
      setPendingCount((c) => c + 1);
    };
    discoveryEmitter.on('result:added', onAdded);
    return () => discoveryEmitter.off('result:added', onAdded);
  }, [setPendingCount]);

  const filtered = filterState === 'all' ? results
    : results.filter((r) => r.state === filterState);

  const newRows = filtered.filter((r) => r.state === 'new' && r.merge_status === 'pending');
  const allNewSelected = newRows.length > 0 && newRows.every((r) => selected.has(r.id));

  const toggleAll = () => {
    if (allNewSelected) setSelected(new Set());
    else setSelected(new Set(newRows.map((r) => r.id)));
  };

  const toggleRow = (id, state) => {
    if (state !== 'new') return; // conflict rows can't be bulk-selected
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleBulkAccept = async () => {
    const ids = [...selected];
    try {
      const res = await bulkMerge({ result_ids: ids, action: 'accept' });
      const { accepted = 0, skipped = 0 } = res.data;
      const skippedSuffix = skipped ? `, ${skipped} skipped` : '';
      toast.success(`${accepted} ${pluralize(accepted, 'host')} accepted${skippedSuffix}`);
      setSelected(new Set());
      discoveryEmitter.emit('badge:refresh');
      load();
    } catch (err) { toast.error(err?.message || 'Bulk accept failed'); }
  };

  const handleBulkReject = async () => {
    const ids = [...selected];
    try {
      const res = await bulkMerge({ result_ids: ids, action: 'reject' });
      const rejected = res.data.rejected ?? ids.length;
      toast.success(`${rejected} ${pluralize(rejected, 'host')} rejected`);
      setSelected(new Set());
      discoveryEmitter.emit('badge:refresh');
      load();
    } catch (err) { toast.error(err?.message || 'Bulk reject failed'); }
  };

  const handleInlineReject = async (result) => {
    try {
      await mergeResult(result.id, { action: 'reject' });
      toast.info(`${result.ip_address} rejected`);
      discoveryEmitter.emit('badge:refresh');
      load();
    } catch (err) { toast.error(err?.message || 'Failed to reject'); }
    setRejectConfirm(null);
  };

  const handleAccepted = (data) => {
    setReviewing(null);
    if (data?.ports?.length) {
      setChecklist({ hardwareId: data.entity_id, hardwareName: data.name || data.entity_id, ports: data.ports });
    }
    discoveryEmitter.emit('badge:refresh');
    load();
  };

  if (loading) return <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading results…</p>;

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, flex: 1 }}>Review Queue</h2>
        <select className="form-input" style={{ width: 140, fontSize: 12 }} value={filterState} onChange={(e) => setFilterState(e.target.value)}>
          <option value="all">All States</option>
          <option value="new">New</option>
          <option value="conflict">Conflict</option>
          <option value="matched">Matched</option>
        </select>
        {selected.size > 0 && (
          <>
            <button type="button" className="btn btn-primary" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }} onClick={() => setBulkDrawerOpen(true)}>
              <Layers size={13} /> Bulk Actions ({selected.size})
            </button>
            <button type="button" className="btn btn-secondary" style={{ fontSize: 12 }} onClick={handleBulkAccept}>Quick Accept</button>
            <button type="button" className="btn btn-danger" style={{ fontSize: 12 }} onClick={handleBulkReject}>Reject Selected</button>
          </>
        )}
      </div>

      {filtered.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center', padding: '40px 0' }}>
          No pending results. Run a scan to discover devices on your network.
        </p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              <th style={thStyle}>
                <input type="checkbox" checked={allNewSelected} onChange={toggleAll} />
              </th>
              {['IP', 'Hostname', 'OS', 'Open Ports', 'State', ''].map((h) => <th key={h} style={thStyle}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => {
              const ports = parsePorts(r.open_ports_json);
              const muted = r.state === 'matched' || r.merge_status !== 'pending';
              return (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--color-border)', opacity: muted ? 0.5 : 1 }}>
                  <td style={tdStyle}>
                    {r.state === 'new' && r.merge_status === 'pending' && (
                      <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id, r.state)} />
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: 'monospace' }}>{r.ip_address}</td>
                  <td style={tdStyle}>{r.hostname || '—'}</td>
                  <td style={tdStyle}>{r.os_family || '—'}</td>
                  <td style={tdStyle}><PortPills ports={ports} /></td>
                  <td style={tdStyle}><StateBadge state={r.state} /></td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {r.merge_status === 'pending' && (
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button type="button" className="btn btn-primary" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => setReviewing(r)}>Accept</button>
                        {rejectConfirm === r.id ? (
                          <>
                            <button type="button" className="btn btn-danger" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => handleInlineReject(r)}>Yes, reject</button>
                            <button type="button" className="btn btn-secondary" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => setRejectConfirm(null)}>No</button>
                          </>
                        ) : (
                          <button type="button" className="btn btn-secondary" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => setRejectConfirm(r.id)}>Reject</button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {reviewing && (
        <ReviewDrawer
          result={reviewing}
          onClose={() => setReviewing(null)}
          onAccepted={handleAccepted}
          onRejected={() => { setReviewing(null); load(); }}
        />
      )}

      {checklist && (
        <ServiceChecklistModal
          hardwareId={checklist.hardwareId}
          hardwareName={checklist.hardwareName}
          ports={checklist.ports}
          onClose={() => { setChecklist(null); }}
        />
      )}

      <AnimatePresence>
        {bulkDrawerOpen && (
          <BulkActionsDrawer
            results={results.filter((r) => selected.has(r.id))}
            onClose={() => setBulkDrawerOpen(false)}
            onComplete={() => {
              setBulkDrawerOpen(false);
              setSelected(new Set());
              discoveryEmitter.emit('badge:refresh');
              load();
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

ReviewTab.propTypes = {
  setPendingCount: PropTypes.func.isRequired,
};

// ─────────────────────────────────────────────────────────────────
// Tab 4 — Scan History
// ─────────────────────────────────────────────────────────────────
function HistoryTab() {
  const [jobs,      setJobs]      = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [expanded,  setExpanded]  = useState(new Set());
  const [expandedResults, setExpandedResults] = useState({});
  const [filterStatus,   setFilterStatus]   = useState('all');

  useEffect(() => {
    setLoading(true);
    getJobs({ limit: 50 })
      .then((r) => setJobs(Array.isArray(r.data) ? r.data : (r.data?.jobs ?? [])))
      .catch((error) => logApiWarning('Failed to load job history', error))
      .finally(() => setLoading(false));
  }, []);

  const toggleExpand = async (job) => {
    const next = new Set(expanded);
    if (next.has(job.id)) { next.delete(job.id); setExpanded(next); return; }
    next.add(job.id);
    setExpanded(next);
    if (!expandedResults[job.id]) {
      const res = await getJobResults(job.id, { limit: 50 }).catch((error) => {
        logApiWarning(`Failed to load results for job ${job.id}`, error);
        return { data: [] };
      });
      const data = Array.isArray(res.data) ? res.data : (res.data?.results ?? []);
      setExpandedResults((prev) => ({ ...prev, [job.id]: data }));
    }
  };

  const filtered = filterStatus === 'all' ? jobs : jobs.filter((j) => j.status === filterStatus);

  const renderExpandedResults = (jobId) => {
    const jobResults = expandedResults[jobId];
    if (!jobResults) {
      return <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 4 }}>Loading…</p>;
    }
    if (jobResults.length === 0) {
      return <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 4 }}>No results for this job.</p>;
    }
    return (
      <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
        <thead>
          <tr>{['IP', 'Hostname', 'OS', 'State', 'Status'].map((h) => <th key={h} style={{ ...thStyle, fontSize: 10 }}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {jobResults.map((r) => (
            <tr key={r.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
              <td style={tdStyle}>{r.ip_address}</td>
              <td style={tdStyle}>{r.hostname || '—'}</td>
              <td style={tdStyle}>{r.os_family || '—'}</td>
              <td style={tdStyle}><StateBadge state={r.state} /></td>
              <td style={tdStyle}>{r.merge_status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  if (loading) return <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading history…</p>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Scan History</h2>
        <select className="form-input" style={{ width: 150, fontSize: 12 }} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
          <option value="all">All Statuses</option>
          <option value="done">Done</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
          <option value="running">Running</option>
        </select>
      </div>

      {filtered.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center', padding: '40px 0' }}>No scans have been run yet.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              {['Started', 'Target', 'Types', 'Status', 'Found', 'New', 'Conflicts'].map((h) => <th key={h} style={thStyle}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {filtered.map((j) => {
              const types = parseJsonArray(j.scan_types_json);
              const isExpanded = expanded.has(j.id);
              return (
                <React.Fragment key={j.id}>
                  <tr
                    style={{ borderBottom: '1px solid var(--color-border)', cursor: 'pointer' }}
                    onClick={() => toggleExpand(j)}
                  >
                    <td style={tdStyle}><TimestampCell isoString={j.created_at} /></td>
                    <td style={{ ...tdStyle, fontFamily: 'monospace' }}>{j.target_cidr}</td>
                    <td style={tdStyle}><div style={{ display: 'flex', gap: 4 }}>{types.map((t) => <TypePill key={t} type={t} />)}</div></td>
                    <td style={tdStyle}><JobStatusBadge status={j.status} /></td>
                    <td style={tdStyle}>{j.hosts_found ?? '—'}</td>
                    <td style={tdStyle}>{j.hosts_new ?? '—'}</td>
                    <td style={tdStyle}>{j.hosts_conflict ?? '—'}</td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={7} style={{ padding: '8px 16px', background: 'var(--color-bg)' }}>
                        {renderExpandedResults(j.id)}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────
function TypePill({ type }) {
  const colors = { nmap: '#3b82f6', snmp: '#8b5cf6', arp: '#f59e0b', http: '#10b981' };
  const color  = colors[type] || '#6b7280';
  return (
    <span style={{ padding: '1px 7px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: `${color}22`, color, border: `1px solid ${color}44` }}>
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
        <span key={`${p.port}-${p.proto ?? p.protocol ?? 'unknown'}`} style={{ padding: '1px 5px', borderRadius: 3, fontSize: 10, background: 'rgba(107,114,128,0.15)', color: 'var(--color-text-muted)', fontFamily: 'monospace' }}>
          {p.port}
        </span>
      ))}
      {extra > 0 && <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>+{extra} more</span>}
    </div>
  );
}

PortPills.propTypes = {
  ports: PropTypes.arrayOf(PropTypes.shape({
    port: PropTypes.number.isRequired,
  })).isRequired,
};

function parsePorts(json) {
  if (!json) return [];
  try { return JSON.parse(json); } catch { return []; }
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

const thStyle = { textAlign: 'left', padding: '8px 10px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)' };
const tdStyle = { padding: '9px 10px', verticalAlign: 'middle' };
const labelStyle = { display: 'block', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--color-text-muted)', marginBottom: 5 };
