import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useSearchParams } from 'react-router-dom';
import { Plus, Play, Trash2, ChevronDown, ChevronRight, Layers, Copy, ClipboardList, CheckCircle2 } from 'lucide-react';
import { AnimatePresence } from 'framer-motion';
import '../styles/discovery.css';
import NmapArgsField from '../components/discovery/NmapArgsField.jsx';
import {
  getProfiles, deleteProfile, runProfile,
  startAdHocScan, cancelJob, getJobs, getJob, getJobResults,
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
import { hardwareApi } from '../api/client';

const TABS = ['profiles', 'adhoc', 'review', 'history'];
const TAB_LABELS = { profiles: 'Scan Profiles', adhoc: 'Ad-hoc Scan', review: 'Review Queue', history: 'Scan History' };
const ADHOC_ACTIVE_JOB_KEY = 'cb.discovery.activeAdhocJobId';

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

function getProgressPercentFromEvent(percent, processed, total) {
  if (typeof percent === 'number') {
    return Math.max(0, Math.min(100, Math.round(percent)));
  }
  if (typeof processed === 'number' && typeof total === 'number' && total > 0) {
    return Math.max(0, Math.min(100, Math.round((processed / total) * 100)));
  }
  return null;
}

function getReviewStateLabel(state) {
  if (state === 'conflict') return 'CHANGED';
  if (state === 'new') return 'NEW';
  if (state === 'matched') return 'MATCHED';
  return (state || 'UNKNOWN').toUpperCase();
}

async function fetchLabNamesById(ids) {
  const found = {};
  for (const id of ids) {
    try {
      const res = await hardwareApi.get(id);
      const name = res.data?.name || `Hardware ${id}`;
      found[id] = name;
    } catch {
      // no-op: leave unresolved IDs untouched
    }
  }
  return found;
}

function composeNmapArgs(baseArgs, timingTemplate, ports) {
  const base = (baseArgs || '-sV -O --open -T4').trim();
  const withoutTiming = base.replaceAll(/\s-T[0-5]\b/g, '').replaceAll(/\s+/g, ' ').trim();
  const timingPart = `-T${timingTemplate}`;
  const portsPart = ports.trim() ? ` -p ${ports.trim()}` : '';
  return `${withoutTiming} ${timingPart}${portsPart}`.trim();
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
    <div className="profiles-wrap">
      <div className="profiles-toolbar">
        <h2 className="profiles-title">Scan Profiles</h2>
        <button type="button" className="btn btn-primary profiles-add-btn" onClick={() => { setEditing(null); setFormOpen(true); }}>
          <Plus size={14} /> Add Profile
        </button>
      </div>

      {profiles.length === 0 ? (
        <p className="profiles-empty">
          No scan profiles yet. Add one to start discovering your network automatically.
        </p>
      ) : (
        <div className="profiles-grid">
          {profiles.map((p) => (
            <article
              key={p.id}
              className="profile-card"
            >
              <div className="profile-card-head">
                <h3 className="profile-card-name">{p.name}</h3>
                <span className={`profile-card-dot ${p.enabled ? 'enabled' : ''}`} />
              </div>

              <p className="profile-card-cidr">{p.cidr}</p>

              <div className="profile-card-types">
                {p.scan_types.map((t) => <TypePill key={t} type={t} />)}
              </div>

              <p className="profile-card-cron">◉ {p.schedule_cron || 'manual only'}</p>

              <div className="profile-card-actions">
                <button type="button" className="btn btn-secondary profile-action-btn" onClick={() => handleRunNow(p)}>
                  <Play size={11} /> Run
                </button>
                <button type="button" className="btn btn-secondary profile-action-btn" onClick={() => { setEditing(p); setFormOpen(true); }}>Edit</button>
                <button type="button" className="btn btn-danger profile-action-btn profile-delete-btn" onClick={() => setDeleteConfirm(p)}><Trash2 size={11} /></button>
              </div>
            </article>
          ))}
        </div>
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
  const [advanced,    setAdvanced]    = useState(true);
  const [timingTemplate, setTimingTemplate] = useState('3');
  const [ports,       setPorts]       = useState('');
  const [activeJob,   setActiveJob]   = useState(null);
  const [liveResults, setLiveResults] = useState([]);
  const [logLines,    setLogLines]    = useState([]);
  const [jobDone,     setJobDone]     = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [launching,   setLaunching]   = useState(false);
  const [launchPulse, setLaunchPulse] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const [livePercent, setLivePercent] = useState(null);
  const logIdRef = useRef(0);
  const liveResultsRef = useRef([]);
  const pulseTimerRef = useRef(null);

  useEffect(() => {
    liveResultsRef.current = liveResults;
  }, [liveResults]);

  const parseJobs = useCallback((payload) => (Array.isArray(payload) ? payload : (payload?.jobs ?? [])), []);

  const getElapsedSeconds = useCallback((job) => {
    const sourceTime = job?.started_at || job?.created_at;
    if (!sourceTime) return 0;
    const startMs = new Date(sourceTime).getTime();
    if (Number.isNaN(startMs)) return 0;
    return Math.max(0, Math.floor((Date.now() - startMs) / 1000));
  }, []);

  const formatElapsed = useCallback((seconds) => {
    const total = Math.max(0, Math.floor(seconds));
    const hrs = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hrs > 0) return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }, []);

  const getPhasePercent = useCallback((job) => {
    if (!job) return 0;
    if (job.status === 'completed' || job.status === 'done') return 100;
    if (job.status === 'failed' || job.status === 'cancelled') return 100;
    const phaseMap = {
      queued: 5,
      arp: 18,
      nmap: 45,
      snmp: 70,
      http: 78,
      reconcile: 90,
    };
    return phaseMap[job.progress_phase] ?? 10;
  }, []);

  useEffect(() => () => {
    if (pulseTimerRef.current) {
      globalThis.clearTimeout(pulseTimerRef.current);
      pulseTimerRef.current = null;
    }
  }, []);

  // Restore active ad-hoc scan after navigation/reload.
  useEffect(() => {
    let mounted = true;

    async function bootstrapActiveJob() {
      try {
        const res = await getJobs({ limit: 50 });
        const jobs = parseJobs(res.data);
        const persistedId = Number(localStorage.getItem(ADHOC_ACTIVE_JOB_KEY));

        let restored = null;
        if (Number.isFinite(persistedId)) {
          restored = jobs.find((j) => j.id === persistedId) ?? null;
        }
        if (!restored) {
          restored = jobs.find((j) => j.profile_id == null && (j.status === 'running' || j.status === 'queued')) ?? null;
        }
        if (!mounted || !restored) return;

        setActiveJob(restored);
        setLiveResults([]);
        setJobDone(restored.status === 'completed' || restored.status === 'done');
        setElapsedSeconds(getElapsedSeconds(restored));

        if (restored.status === 'running' || restored.status === 'queued') {
          localStorage.setItem(ADHOC_ACTIVE_JOB_KEY, String(restored.id));
        }
      } catch (error) {
        logApiWarning('Failed to restore active ad-hoc job', error);
      }
    }

    bootstrapActiveJob();
    return () => { mounted = false; };
  }, [getElapsedSeconds, parseJobs]);

  // Hydrate latest scan results for the active job (supports page navigation + refresh).
  useEffect(() => {
    if (!activeJob?.id) return;
    let cancelled = false;
    getJobResults(activeJob.id, { limit: 24 })
      .then((res) => {
        if (cancelled) return;
        const data = Array.isArray(res.data) ? res.data : (res.data?.results ?? []);
        setLiveResults(data);
      })
      .catch((error) => logApiWarning(`Failed to load live results for job ${activeJob.id}`, error));
    return () => { cancelled = true; };
  }, [activeJob?.id]);

  // Poll live results while scan is running so new hosts appear immediately even if WS delivery is delayed.
  useEffect(() => {
    if (!activeJob?.id) return;
    if (activeJob.status !== 'running' && activeJob.status !== 'queued') return;

    let cancelled = false;
    const poll = async () => {
      try {
        const res = await getJobResults(activeJob.id, { limit: 24 });
        if (cancelled) return;
        const data = Array.isArray(res.data) ? res.data : (res.data?.results ?? []);
        liveResultsRef.current = data;
        setLiveResults(data);
      } catch (error) {
        logApiWarning(`Failed to poll live results for job ${activeJob.id}`, error);
      }
    };

    const id = globalThis.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      globalThis.clearInterval(id);
    };
  }, [activeJob?.id, activeJob?.status]);

  // Tick elapsed timer while scan is active.
  useEffect(() => {
    if (!activeJob) return;
    setElapsedSeconds(getElapsedSeconds(activeJob));
    if (activeJob.status !== 'running' && activeJob.status !== 'queued') return;
    const id = globalThis.setInterval(() => {
      setElapsedSeconds(getElapsedSeconds(activeJob));
    }, 1000);
    return () => globalThis.clearInterval(id);
  }, [activeJob, getElapsedSeconds]);

  // Append host cards in real time as results arrive.
  useEffect(() => {
    if (!activeJob?.id) return;

    const onResultAdded = (result) => {
      if (Number(result.scan_job_id) !== Number(activeJob.id)) return;
      if (liveResultsRef.current.some((entry) => entry.id === result.id)) return;
      const next = [result, ...liveResultsRef.current].slice(0, 24);
      liveResultsRef.current = next;
      setLiveResults(next);
    };

    discoveryEmitter.on('result:added', onResultAdded);
    return () => discoveryEmitter.off('result:added', onResultAdded);
  }, [activeJob?.id]);

  // Poll fallback so UI still updates if websocket stream is unavailable.
  useEffect(() => {
    if (!activeJob) return;
    if (activeJob.status !== 'running' && activeJob.status !== 'queued') return;

    let cancelled = false;
    const tick = async () => {
      try {
        const res = await getJob(activeJob.id);
        if (cancelled) return;
        setActiveJob(res.data);
      } catch (error) {
        logApiWarning(`Failed to poll job ${activeJob.id}`, error);
      }
    };

    const id = globalThis.setInterval(tick, 3000);
    return () => {
      cancelled = true;
      globalThis.clearInterval(id);
    };
  }, [activeJob]);

  // Subscribe to WebSocket job events
  useEffect(() => {
    if (!activeJob) return;

    const onProgress = ({ job_id, phase, message, percent, processed, total }) => {
      if (job_id !== activeJob.id) return;
      if (message) {
        setLogLines((prev) => [
          ...prev.slice(-99),
          { id: `${activeJob.id}-${logIdRef.current++}`, text: message },
        ]);
      }
      const nextPercent = getProgressPercentFromEvent(percent, processed, total);
      if (nextPercent !== null) setLivePercent(nextPercent);
      if (phase) setActiveJob((j) => j ? { ...j, progress_phase: phase, progress_message: message } : j);
    };

    const onUpdate = (job) => {
      if (job.id !== activeJob.id) return;
      setActiveJob(job);
      if (job.status === 'completed' || job.status === 'done') {
        setLivePercent(100);
        setJobDone(true);
        localStorage.removeItem(ADHOC_ACTIVE_JOB_KEY);
        toast.success(`Scan complete — ${job.hosts_found} hosts found`);
        discoveryEmitter.emit('badge:refresh');
      } else if (job.status === 'failed') {
        setLivePercent(100);
        localStorage.removeItem(ADHOC_ACTIVE_JOB_KEY);
        toast.error(`Scan failed: ${job.error_text || 'unknown error'}`);
      } else if (job.status === 'cancelled') {
        setLivePercent(100);
        localStorage.removeItem(ADHOC_ACTIVE_JOB_KEY);
        toast.info('Scan cancelled');
      } else if (job.status === 'running' || job.status === 'queued') {
        localStorage.setItem(ADHOC_ACTIVE_JOB_KEY, String(job.id));
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
      setLiveResults([]);
      setJobDone(false);
      setLivePercent(0);
      setLaunchError('');
      setLaunching(true);
      setLaunchPulse(true);
      if (pulseTimerRef.current) {
        globalThis.clearTimeout(pulseTimerRef.current);
      }
      pulseTimerRef.current = globalThis.setTimeout(() => {
        setLaunchPulse(false);
        pulseTimerRef.current = null;
      }, 1400);
      try {
        const res = await startAdHocScan({
          cidr, scan_types: scanTypes,
          nmap_arguments: composeNmapArgs(nmapArgs, timingTemplate, ports) || undefined,
          snmp_community: snmpCom || undefined,
        });
        setActiveJob(res.data);
        setElapsedSeconds(getElapsedSeconds(res.data));
        localStorage.setItem(ADHOC_ACTIVE_JOB_KEY, String(res.data.id));
        toast.success(`Scan started for ${cidr}`);
      } catch (err) {
        setLaunchError(err?.message || 'Failed to launch scan');
        if (err?.response?.status === 429) toast.warn('Please wait before starting another scan');
        else toast.error(err?.message || 'Failed to launch scan');
      } finally {
        setLaunching(false);
      }
    });
  };

  const handleCancel = async () => {
    if (!activeJob) return;
    try {
      await cancelJob(activeJob.id);
      toast.info('Scan cancelled');
      setActiveJob((j) => ({ ...j, status: 'cancelled' }));
      localStorage.removeItem(ADHOC_ACTIVE_JOB_KEY);
    } catch (err) { toast.error(err?.message || 'Failed to cancel'); }
  };

  const isRunning = activeJob?.status === 'running';
  const isActive = activeJob?.status === 'running' || activeJob?.status === 'queued';
  const progressPercent = typeof livePercent === 'number' ? livePercent : getPhasePercent(activeJob);

  return (
    <div>
      <div className="adhoc-scan-card">
        <div className="adhoc-card-head">
          <h2 className="adhoc-scan-title"><span className="adhoc-title-dot" /> Ad-hoc Scan</h2>
          {(isActive || launching) && <span className="adhoc-running-chip">Scanning in progress...</span>}
        </div>

        <div className="adhoc-grid-two">
          <div className="cb-field">
            <label className="cb-label" htmlFor="adhoc-target-network">Target Network</label>
            <input id="adhoc-target-network" className="cb-input" value={cidr} onChange={(e) => setCidr(e.target.value)} placeholder="192.168.1.0/24" />
          </div>

          <NmapArgsField value={nmapArgs} onChange={setNmapArgs} />
        </div>

        <div className="cb-field">
          <span className="cb-label">Additional Probes</span>
          <div className="adhoc-probe-row">
            {['nmap', 'snmp', 'arp', 'http'].map((t) => (
              <label key={t} className={`adhoc-probe-chip ${scanTypes.includes(t) ? 'active' : ''}`}>
                <input type="checkbox" checked={scanTypes.includes(t)} onChange={() => toggleScanType(t)} />
                {t}
              </label>
            ))}
          </div>
        </div>

        <button type="button" className="adhoc-advanced-toggle" onClick={() => setAdvanced((v) => !v)}>
          {advanced ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Advanced Options
        </button>
        {advanced && (
          <div className="adhoc-advanced-body">
            <div className="cb-field">
              <label className="cb-label" htmlFor="adhoc-timing-template">Timing Template</label>
              <select id="adhoc-timing-template" className="cb-input" value={timingTemplate} onChange={(e) => setTimingTemplate(e.target.value)}>
                <option value="2">T2 (Polite)</option>
                <option value="3">T3 (Normal)</option>
                <option value="4">T4 (Aggressive)</option>
              </select>
            </div>

            <div className="cb-field">
              <label className="cb-label" htmlFor="adhoc-ports">Ports</label>
              <input
                id="adhoc-ports"
                className="cb-input"
                value={ports}
                onChange={(e) => setPorts(e.target.value)}
                placeholder="e.g. 80,443,22 or 1-1000"
              />
            </div>

            <div className="cb-field">
              <label className="cb-label" htmlFor="adhoc-snmp-community">SNMP Community</label>
              <input id="adhoc-snmp-community" className="cb-input" type="password" value={snmpCom} onChange={(e) => setSnmpCom(e.target.value)} placeholder="public" autoComplete="off" />
            </div>
          </div>
        )}

        <div className="adhoc-launch-row">
          <button type="button" className={`btn btn-primary adhoc-launch-btn ${launchPulse ? 'pulse' : ''}`} disabled={!cidr || isRunning || launching} onClick={handleLaunch}>
            <Play size={14} /> {launching ? 'Launching…' : 'Launch Scan'}
          </button>
        </div>

        {launchError && (
          <p className="adhoc-launch-error">{launchError}</p>
        )}
      </div>

      {/* Active job panel */}
      {(activeJob || launching) && (
        <div className="adhoc-runtime-wrap">
          <div className="adhoc-metrics-grid">
            <div className="adhoc-metric-card adhoc-metric-progress">
              <div className="adhoc-metric-head">
                <span className="adhoc-metric-label">Progress</span>
                {activeJob ? <JobStatusBadge status={activeJob.status} /> : <JobStatusBadge status="queued" />}
              </div>
              <div className="adhoc-metric-main">{activeJob ? progressPercent : 0}%</div>
              <div className="adhoc-metric-sub">{activeJob ? (PHASE_LABELS[activeJob.progress_phase] ?? PHASE_LABELS.queued).label : 'Starting scan…'}</div>
              <div className="adhoc-progress-track">
                <div className={`adhoc-progress-fill ${isActive || launching ? 'active' : ''}`} style={{ width: `${activeJob ? progressPercent : 0}%` }} />
              </div>
            </div>

            <div className="adhoc-metric-card">
              <div className="adhoc-metric-label">Elapsed Time</div>
              <div className="adhoc-metric-main adhoc-elapsed">{formatElapsed(elapsedSeconds)}</div>
              <div className="adhoc-metric-sub">
                {isActive || launching ? 'Running in background' : 'Scan finished'}
              </div>
            </div>

            <div className="adhoc-metric-card">
              <div className="adhoc-metric-label">Hosts Found</div>
              <div className="adhoc-metric-main">{activeJob?.hosts_found ?? 0}</div>
              <div className="adhoc-metric-sub">
                {activeJob?.started_at ? `Started ${new Date(activeJob.started_at).toLocaleTimeString()}` : 'Waiting for start'}
              </div>
            </div>
          </div>

          <div className="adhoc-live-section">
            <div className="adhoc-live-header">
              <span>Live Results</span>
              <span className="adhoc-live-pill">● Real-time updates</span>
            </div>

            {activeJob?.progress_message && (
              <p className="adhoc-live-message">{activeJob.progress_message}</p>
            )}

            {liveResults.length > 0 ? (
              <div className="adhoc-live-grid">
                {liveResults.map((result) => (
                  <LiveResultCard key={result.id} result={result} />
                ))}
              </div>
            ) : (
              <div className="adhoc-live-log">
                {logLines.length > 0
                  ? logLines.map((line) => <div key={line.id}>✓ {line.text}</div>)
                  : <div>Scanning network for devices…</div>}
              </div>
            )}

            <div className="adhoc-runtime-actions">
              {isRunning && (
                <button type="button" className="btn btn-secondary" style={{ fontSize: 11 }} onClick={handleCancel}>Cancel</button>
              )}
              {jobDone && (
                <button type="button" className="btn btn-primary" style={{ fontSize: 11 }} onClick={onViewResults}>
                  Review Results →
                </button>
              )}
            </div>
          </div>
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
  const [labNamesById, setLabNamesById] = useState({});
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

  useEffect(() => {
    const matchedIds = [...new Set(
      results
        .filter((r) => r.state === 'matched' && r.matched_entity_type === 'hardware' && r.matched_entity_id)
        .map((r) => r.matched_entity_id),
    )];
    const missingIds = matchedIds.filter((id) => !labNamesById[id]);
    if (missingIds.length === 0) return;

    let cancelled = false;
    async function hydrateMatchedNames() {
      const found = await fetchLabNamesById(missingIds);
      if (cancelled || Object.keys(found).length === 0) return;
      setLabNamesById((prev) => ({ ...prev, ...found }));
    }

    hydrateMatchedNames();

    return () => { cancelled = true; };
  }, [results, labNamesById]);

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
      <div className="review-queue-toolbar">
        <h2 className="review-queue-title">Review Queue ({filtered.length})</h2>
        <select className="cb-input review-queue-filter" value={filterState} onChange={(e) => setFilterState(e.target.value)}>
          <option value="all">All States</option>
          <option value="new">New</option>
          <option value="conflict">Conflict</option>
          <option value="matched">Matched</option>
        </select>
        {selected.size > 0 && (
          <>
            <button type="button" className="btn btn-primary review-queue-btn" style={{ display: 'flex', alignItems: 'center', gap: 5 }} onClick={() => setBulkDrawerOpen(true)}>
              <Layers size={13} /> Bulk Actions ({selected.size})
            </button>
            <button type="button" className="btn btn-secondary review-queue-btn" onClick={handleBulkAccept}>Quick Accept</button>
            <button type="button" className="btn btn-danger review-queue-btn" onClick={handleBulkReject}>Reject Selected</button>
          </>
        )}
      </div>

      {filtered.length === 0 ? (
        <p className="review-queue-empty">
          No pending results. Run a scan to discover devices on your network.
        </p>
      ) : (
        <div className="review-queue-table-wrap">
          <table className="review-queue-table">
            <thead>
              <tr>
                <th className="review-col-checkbox">
                  <input type="checkbox" checked={allNewSelected} onChange={toggleAll} />
                </th>
                {['IP', 'Hostname', 'OS', 'Open Ports', 'State', 'Actions'].map((h) => <th key={h}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const ports = parsePorts(r.open_ports_json);
                const muted = r.state === 'matched' || r.merge_status !== 'pending';
                const isInLab = r.state === 'matched' && r.matched_entity_type === 'hardware' && r.matched_entity_id;
                const hostnameLabel = isInLab
                  ? `${labNamesById[r.matched_entity_id] || r.hostname || 'Lab Device'} (${r.ip_address})`
                  : (r.hostname || '—');
                return (
                  <tr key={r.id} className={muted ? 'review-row-muted' : ''}>
                    <td>
                    {r.state === 'new' && r.merge_status === 'pending' && (
                      <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id, r.state)} />
                    )}
                    </td>
                    <td className="review-cell-ip">{r.ip_address}</td>
                    <td>{hostnameLabel}</td>
                    <td>{r.os_family || '—'}</td>
                    <td>
                      <div className="review-port-pills">
                        {ports.slice(0, 4).map((p) => (
                          <span key={`${r.id}-${p.port}-${p.protocol ?? 'tcp'}`} className="review-port-pill">{p.port}</span>
                        ))}
                      </div>
                    </td>
                    <td>
                      {isInLab ? (
                        <span className="review-state-inlab">
                          <CheckCircle2 size={12} /> In Lab
                        </span>
                      ) : (
                        <span className={`review-state-pill state-${r.state || 'unknown'}`}>
                          {getReviewStateLabel(r.state)}
                        </span>
                      )}
                    </td>
                    <td className="review-cell-actions">
                    {r.merge_status === 'pending' && (
                      <div className="review-action-group">
                        <button type="button" className="btn btn-primary review-action-btn" onClick={() => setReviewing(r)}>Accept</button>
                        {rejectConfirm === r.id ? (
                          <>
                            <button type="button" className="btn btn-danger review-action-btn" onClick={() => handleInlineReject(r)}>Yes, reject</button>
                            <button type="button" className="btn btn-secondary review-action-btn" onClick={() => setRejectConfirm(null)}>No</button>
                          </>
                        ) : (
                          <button type="button" className="btn btn-secondary review-action-btn" onClick={() => setRejectConfirm(r.id)}>Reject</button>
                        )}
                      </div>
                    )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
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
  const [labNamesById, setLabNamesById] = useState({});
  const [filterStatus,   setFilterStatus]   = useState('all');

  const loadJobs = useCallback(() => {
    setLoading(true);
    getJobs({ limit: 50 })
      .then((r) => setJobs(Array.isArray(r.data) ? r.data : (r.data?.jobs ?? [])))
      .catch((error) => logApiWarning('Failed to load job history', error))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  useEffect(() => {
    const hasLiveJob = jobs.some((j) => j.status === 'running' || j.status === 'queued');
    if (!hasLiveJob) return;

    const id = globalThis.setInterval(() => {
      getJobs({ limit: 50 })
        .then((r) => setJobs(Array.isArray(r.data) ? r.data : (r.data?.jobs ?? [])))
        .catch((error) => logApiWarning('Failed to refresh job history', error));
    }, 2500);

    return () => globalThis.clearInterval(id);
  }, [jobs]);

  useEffect(() => {
    const allResults = Object.values(expandedResults).flat();
    const matchedIds = [...new Set(
      allResults
        .filter((r) => r.state === 'matched' && r.matched_entity_type === 'hardware' && r.matched_entity_id)
        .map((r) => r.matched_entity_id),
    )];

    const missingIds = matchedIds.filter((id) => !labNamesById[id]);
    if (missingIds.length === 0) return;

    let cancelled = false;
    fetchLabNamesById(missingIds).then((found) => {
      if (cancelled || Object.keys(found).length === 0) return;
      setLabNamesById((prev) => ({ ...prev, ...found }));
    });

    return () => { cancelled = true; };
  }, [expandedResults, labNamesById]);

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
      return <p className="history-details-empty">Loading…</p>;
    }
    if (jobResults.length === 0) {
      return <p className="history-details-empty">No details available for this scan.</p>;
    }
    return (
      <table className="history-details-table">
        <thead>
          <tr>{['IP', 'Hostname', 'OS', 'State', 'Status'].map((h) => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {jobResults.map((r) => {
            const isInLab = r.state === 'matched' && r.matched_entity_type === 'hardware' && r.matched_entity_id;
            const hostnameLabel = isInLab
              ? `${labNamesById[r.matched_entity_id] || r.hostname || 'Lab Device'} (${r.ip_address})`
              : (r.hostname || '-');
            return (
              <tr key={r.id}>
                <td>{r.ip_address}</td>
                <td>{hostnameLabel}</td>
                <td>{r.os_family || '-'}</td>
                <td>
                  {isInLab ? (
                    <span className="history-state-inlab">
                      <CheckCircle2 size={12} /> In Lab
                    </span>
                  ) : (
                    <span className={`history-state-pill state-${r.state || 'new'}`}>
                      {getReviewStateLabel(r.state)}
                    </span>
                  )}
                </td>
                <td>{String(r.merge_status || '-').toUpperCase()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  };

  if (loading) return <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading history…</p>;

  return (
    <div className="history-wrap">
      <div className="history-toolbar">
        <h2 className="history-title">Scan History</h2>
        <div className="history-controls">
          <button type="button" className="history-icon-btn" onClick={loadJobs} aria-label="Refresh history">
            <ClipboardList size={14} />
          </button>
          <button
            type="button"
            className="history-icon-btn"
            onClick={() => navigator.clipboard?.writeText(JSON.stringify(filtered, null, 2))}
            aria-label="Copy history as JSON"
          >
            <Copy size={14} />
          </button>
          <select className="cb-input history-filter" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
          <option value="all">All Statuses</option>
          <option value="done">Done</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
          <option value="running">Running</option>
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="history-empty">No scans have been run yet.</p>
      ) : (
        <div className="history-table-wrap">
          <table className="history-table">
            <thead>
              <tr>
                <th className="history-col-expand" />
                {['Started', 'Target', 'Types', 'Status', 'Found', 'New', 'Conflicts'].map((h) => <th key={h}>{h}</th>)}
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
                      <td><TimestampCell isoString={j.created_at} /></td>
                      <td className="history-target">{j.target_cidr}</td>
                      <td>
                        <div className="history-type-row">
                          {types.map((t) => <TypePill key={t} type={t} />)}
                        </div>
                      </td>
                      <td><HistoryStatusPill status={j.status} /></td>
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

function HistoryStatusPill({ status }) {
  const normalized = status === 'completed' ? 'done' : status;
  const label = normalized === 'done' ? 'Done' : normalized.charAt(0).toUpperCase() + normalized.slice(1);
  return (
    <span className={`history-status-pill status-${normalized}`}>
      {label}
    </span>
  );
}

HistoryStatusPill.propTypes = {
  status: PropTypes.string.isRequired,
};

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

function LiveResultCard({ result }) {
  const ports = parsePorts(result.open_ports_json);
  const shownPorts = ports.slice(0, 3);
  const osLabel = [result.os_family, result.os_vendor].filter(Boolean).join(' ') || 'Unknown';

  return (
    <article className="adhoc-result-card">
      <div className="adhoc-result-top">
        <div>
          <div className="adhoc-result-ip">{result.ip_address}</div>
          <div className="adhoc-result-mac">{result.mac_address || '—'}</div>
        </div>
        <span className="adhoc-result-state">{result.state || 'new'}</span>
      </div>

      <div className="adhoc-result-os">OS Detection</div>
      <div className="adhoc-result-os-value">{osLabel}</div>

      {shownPorts.length > 0 && (
        <div className="adhoc-result-ports">
          {shownPorts.map((p) => (
            <span key={`${result.id}-${p.port}-${p.protocol ?? 'tcp'}`} className="adhoc-result-port-pill">
              {p.port}/{p.protocol ?? 'tcp'}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}

PortPills.propTypes = {
  ports: PropTypes.arrayOf(PropTypes.shape({
    port: PropTypes.number.isRequired,
  })).isRequired,
};

LiveResultCard.propTypes = {
  result: PropTypes.shape({
    id: PropTypes.number.isRequired,
    ip_address: PropTypes.string.isRequired,
    mac_address: PropTypes.string,
    open_ports_json: PropTypes.string,
    os_family: PropTypes.string,
    os_vendor: PropTypes.string,
    state: PropTypes.string,
  }).isRequired,
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

