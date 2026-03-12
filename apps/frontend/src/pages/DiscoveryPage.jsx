/* eslint-disable security/detect-object-injection -- Map used for job-keyed state */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import '../styles/discovery.css';
import {
  getProfiles,
  getJobs,
  cancelJob,
  getPendingResults,
  getDiscoveryStatus,
  getJobLogs,
  startAdHocScan,
} from '../api/discovery.js';
import { X } from 'lucide-react';
import { systemApi } from '../api/client.jsx';
import { discoveryEmitter } from '../hooks/useDiscoveryStream.js';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger.js';

import DiscoverySidebar from '../components/discovery/DiscoverySidebar.jsx';
import DiscoveryHistoryPage from './DiscoveryHistoryPage.jsx';
import ScanTable from '../components/discovery/ScanTable.jsx';
import ScanDetailPanel from '../components/discovery/ScanDetailPanel.jsx';
import ScanProfilesPanel from '../components/discovery/ScanProfilesPanel.jsx';
import DiscoveryStatusBar from '../components/discovery/DiscoveryStatusBar.jsx';
import NewScanPage from '../components/discovery/NewScanPage.jsx';
import ReviewQueuePanel from '../components/discovery/ReviewQueuePanel.jsx';
import ProxmoxIntegrationSection from '../components/proxmox/ProxmoxIntegrationSection.jsx';

const STATUS_FILTERS = new Map([
  ['all', null],
  ['active', ['running']],
  ['completed', ['completed', 'done']],
  ['queued', ['queued']],
]);

function logApiWarning(scope, error) {
  logger.warn(`[DiscoveryPage] ${scope}`, error);
}

export default function DiscoveryPage() {
  const toast = useToast();

  const [jobs, setJobs] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [filter, setFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [pendingReviewCount, setPendingReviewCount] = useState(0);
  const [discoveryCapabilities, setDiscoveryCapabilities] = useState({
    effectiveMode: null,
    dockerAvailable: false,
    netRawCapable: false,
    dockerContainerCount: 0,
  });
  const [hostStats, setHostStats] = useState(null);
  const [dockerScanning, setDockerScanning] = useState(false);
  const [dockerScanError, setDockerScanError] = useState(null);

  const progressMapRef = useRef(new Map());
  const [progressMap, setProgressMap] = useState(() => new Map());
  const etaMapRef = useRef(new Map());
  const [etaMap, setEtaMap] = useState(() => new Map());
  const logMapRef = useRef(new Map());
  const [logMap, setLogMap] = useState(() => new Map());
  const [detailedLogMap, setDetailedLogMap] = useState(() => new Map());
  const detailedLogMapRef = useRef(new Map());

  // ── Data fetching ──────────────────────────────────────────────────────

  const loadJobs = useCallback(() => {
    getJobs()
      .then((res) => setJobs(res.data || []))
      .catch((err) => logApiWarning('Failed to load jobs', err));
  }, []);

  const loadProfiles = useCallback(() => {
    getProfiles()
      .then((res) => setProfiles(res.data || []))
      .catch((err) => logApiWarning('Failed to load profiles', err));
  }, []);

  useEffect(() => {
    loadJobs();
    loadProfiles();
  }, [loadJobs, loadProfiles]);

  const loadPendingResults = useCallback(() => {
    getPendingResults({ limit: 1 })
      .then((res) => {
        const count = res.data?.total ?? (Array.isArray(res.data) ? res.data.length : 0);
        setPendingReviewCount(count);
      })
      .catch((err) => logApiWarning('Failed to fetch pending count', err));
  }, []);

  const loadJobLogs = useCallback((jobId) => {
    getJobLogs(jobId)
      .then((res) => {
        const logs = Array.isArray(res.data) ? res.data : [];
        detailedLogMapRef.current.set(jobId, logs);
        setDetailedLogMap(new Map(detailedLogMapRef.current));
      })
      .catch((err) => {
        console.error('Failed to load job logs:', err);
      });
  }, []);

  useEffect(() => {
    loadPendingResults();
  }, [loadPendingResults]);

  useEffect(() => {
    getDiscoveryStatus()
      .then((res) =>
        setDiscoveryCapabilities({
          effectiveMode: res.data?.effective_mode ?? null,
          dockerAvailable: Boolean(res.data?.docker_available),
          netRawCapable: Boolean(res.data?.net_raw_capable),
          dockerContainerCount: res.data?.docker_container_count ?? 0,
        })
      )
      .catch((err) => {
        console.error('Discovery capabilities load failed:', err);
      });
  }, []);

  useEffect(() => {
    let mounted = true;
    const fetchHostStats = () => {
      systemApi
        .getStats()
        .then((res) => {
          if (!mounted || !res?.data) return;
          const mem = res.data.mem;
          const disk = res.data.disk;
          const memPercent =
            mem && typeof mem.total === 'number' && mem.total > 0
              ? Math.round((mem.used / mem.total) * 100)
              : null;
          const diskPercent =
            disk && typeof disk.percent === 'number' ? Math.round(disk.percent) : null;
          setHostStats(
            memPercent != null || diskPercent != null
              ? { memPercent: memPercent ?? null, diskPercent: diskPercent ?? null }
              : null
          );
        })
        .catch((err) => {
          console.error('Discovery host stats fetch failed:', err);
          if (mounted) setHostStats(null);
        });
    };
    fetchHostStats();
    const interval = setInterval(fetchHostStats, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  // ── WebSocket events ───────────────────────────────────────────────────

  useEffect(() => {
    const onJobUpdate = (jobData) => {
      if (!jobData?.id) {
        loadJobs();
        return;
      }
      setJobs((prev) => {
        const idx = prev.findIndex((j) => j.id === jobData.id);
        if (idx === -1) return [...prev, jobData];
        const next = [...prev];
        next[idx] = jobData;
        return next;
      });
    };

    const onJobProgress = (data) => {
      if (typeof data.percent === 'number') {
        progressMapRef.current.set(data.job_id, Math.round(data.percent));
        setProgressMap(new Map(progressMapRef.current));
      } else if (
        typeof data.processed === 'number' &&
        typeof data.total === 'number' &&
        data.total > 0
      ) {
        const pct = Math.round((data.processed / data.total) * 100);
        progressMapRef.current.set(data.job_id, pct);
        setProgressMap(new Map(progressMapRef.current));
      }

      if (typeof data.eta_seconds === 'number') {
        etaMapRef.current.set(data.job_id, data.eta_seconds);
        setEtaMap(new Map(etaMapRef.current));
      }

      if (data.message || data.phase) {
        const entry = { phase: data.phase, message: data.message, ts: Date.now() };
        const prev = logMapRef.current.get(data.job_id) || [];
        logMapRef.current.set(data.job_id, [...prev, entry].slice(-200));
        setLogMap(new Map(logMapRef.current));
      }
    };

    const onScanLogEntry = (data) => {
      if (data.job_id && data.message) {
        const entry = {
          id: data.log_id,
          timestamp: data.timestamp,
          level: data.level,
          phase: data.phase,
          message: data.message,
          details: data.details,
        };
        const prev = detailedLogMapRef.current.get(data.job_id) || [];
        detailedLogMapRef.current.set(data.job_id, [...prev, entry].slice(-500));
        setDetailedLogMap(new Map(detailedLogMapRef.current));
      }
    };

    const onResultAdded = () => {
      setPendingReviewCount((c) => c + 1);
    };

    const onWsReconnected = () => loadJobs();

    discoveryEmitter.on('job:update', onJobUpdate);
    discoveryEmitter.on('job:progress', onJobProgress);
    discoveryEmitter.on('scan:log_entry', onScanLogEntry);
    discoveryEmitter.on('result:added', onResultAdded);
    discoveryEmitter.on('ws:reconnected', onWsReconnected);

    return () => {
      discoveryEmitter.off('job:update', onJobUpdate);
      discoveryEmitter.off('job:progress', onJobProgress);
      discoveryEmitter.off('scan:log_entry', onScanLogEntry);
      discoveryEmitter.off('result:added', onResultAdded);
      discoveryEmitter.off('ws:reconnected', onWsReconnected);
    };
  }, [loadJobs, loadPendingResults]);

  // ── Derived state ──────────────────────────────────────────────────────

  const profileMap = useMemo(() => new Map(profiles.map((p) => [p.id, p.name])), [profiles]);

  // Load logs when a job is selected
  useEffect(() => {
    if (selectedJobId) {
      loadJobLogs(selectedJobId);
    }
  }, [selectedJobId, loadJobLogs]);

  const filteredJobs = useMemo(() => {
    const statusSet = STATUS_FILTERS.get(filter);
    if (!statusSet) return jobs;
    return jobs.filter((j) => statusSet.includes(j.status));
  }, [jobs, filter]);

  const jobCounts = useMemo(
    () =>
      new Map([
        ['all', jobs.length],
        ['active', jobs.filter((j) => j.status === 'running').length],
        ['completed', jobs.filter((j) => j.status === 'completed' || j.status === 'done').length],
        ['queued', jobs.filter((j) => j.status === 'queued').length],
      ]),
    [jobs]
  );

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedJobId) ?? null,
    [jobs, selectedJobId]
  );

  // ── Actions ────────────────────────────────────────────────────────────

  const handleDockerScan = async () => {
    if (dockerScanning) return;
    setDockerScanning(true);
    setDockerScanError(null);
    try {
      const res = await startAdHocScan({ scan_types: ['docker'] });
      toast.success('Docker scan started — results will appear in the Review Queue');
      const job = res?.data;
      if (job?.id) {
        setJobs((prev) => (prev.some((j) => j.id === job.id) ? prev : [job, ...prev]));
      } else {
        loadJobs();
      }
      setFilter('all');
    } catch (err) {
      const brief = err?.response?.data?.detail || err?.message || 'Docker scan failed';
      toast.error(brief);
      setDockerScanError(brief);
    } finally {
      setDockerScanning(false);
    }
  };

  const handleCancelJob = async (jobId) => {
    try {
      await cancelJob(jobId);
      toast.success('Scan cancelled');
      loadJobs();
    } catch (err) {
      toast.error(err?.message || 'Failed to cancel scan');
    }
  };

  const aggregateStats = useMemo(
    () => ({
      totalScans: jobs.length,
      activeCount: jobs.filter((j) => j.status === 'running').length,
      totalFound: jobs.reduce((s, j) => s + (j.hosts_found ?? 0), 0),
      conflictCount: jobs.reduce((s, j) => s + (j.hosts_conflict ?? 0), 0),
    }),
    [jobs]
  );

  let mainContent;
  if (filter === 'proxmox') {
    mainContent = (
      <div className="discovery-proxmox-section" style={{ padding: 24, maxWidth: 720 }}>
        <ProxmoxIntegrationSection />
      </div>
    );
  } else if (filter === 'profiles') {
    mainContent = <ScanProfilesPanel onSaved={loadProfiles} />;
  } else if (filter === 'history') {
    mainContent = <DiscoveryHistoryPage embedded />;
  } else if (filter === 'review') {
    mainContent = <ReviewQueuePanel onCountChange={setPendingReviewCount} />;
  } else if (filter === 'new-scan') {
    mainContent = (
      <NewScanPage
        discoveryCapabilities={discoveryCapabilities}
        profiles={profiles}
        onStarted={(job) => {
          if (job?.id) {
            setJobs((prev) => {
              if (prev.some((j) => j.id === job.id)) return prev;
              return [job, ...prev];
            });
          } else {
            loadJobs();
          }
          setFilter('all');
        }}
        onCancel={() => setFilter('all')}
      />
    );
  } else {
    mainContent = (
      <>
        <ScanTable
          jobs={filteredJobs}
          profileMap={profileMap}
          progressMap={progressMap}
          etaMap={etaMap}
          selectedJobId={selectedJobId}
          onSelectJob={setSelectedJobId}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onCancelJob={handleCancelJob}
        />
        <ScanDetailPanel
          job={selectedJob}
          progressPct={selectedJob ? progressMap.get(selectedJobId) : undefined}
          etaSeconds={selectedJob ? etaMap.get(selectedJobId) : undefined}
          logEntries={selectedJob ? logMap.get(selectedJobId) : undefined}
          detailedLogs={selectedJob ? detailedLogMap.get(selectedJobId) : undefined}
          profileMap={profileMap}
        />
        <DiscoveryStatusBar
          totalScans={aggregateStats.totalScans}
          activeCount={aggregateStats.activeCount}
          totalFound={aggregateStats.totalFound}
          conflictCount={aggregateStats.conflictCount}
          effectiveMode={discoveryCapabilities.effectiveMode}
          dockerAvailable={discoveryCapabilities.dockerAvailable}
        />
      </>
    );
  }

  return (
    <div className="discovery-layout">
      <DiscoverySidebar
        filter={filter}
        onFilterChange={setFilter}
        jobCounts={jobCounts}
        pendingReviewCount={pendingReviewCount}
        memoryUsed={hostStats?.memPercent ?? null}
        storageUsed={hostStats?.diskPercent ?? null}
        dockerAvailable={discoveryCapabilities.dockerAvailable}
        dockerScanning={dockerScanning}
        dockerContainerCount={discoveryCapabilities.dockerContainerCount}
        onDockerScan={handleDockerScan}
      />

      <div className="discovery-main">{mainContent}</div>

      {dockerScanError && (
        <div
          role="alertdialog"
          aria-labelledby="docker-error-title"
          aria-describedby="docker-error-message"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1200,
            background: 'rgba(0,0,0,0.55)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={() => setDockerScanError(null)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setDockerScanError(null);
            }
          }}
          tabIndex={-1}
        >
          <div
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 10,
              padding: '24px 28px',
              maxWidth: 420,
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
            }}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span id="docker-error-title" style={{ fontWeight: 700, fontSize: 14 }}>
                Docker Scan Error
              </span>
              <button
                type="button"
                className="scan-toolbar-btn"
                onClick={() => setDockerScanError(null)}
              >
                <X size={14} />
              </button>
            </div>
            <p
              id="docker-error-message"
              style={{ margin: 0, fontSize: 13, color: 'var(--color-text-muted)' }}
            >
              {dockerScanError}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
