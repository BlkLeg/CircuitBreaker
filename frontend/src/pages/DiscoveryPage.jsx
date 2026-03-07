import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import '../styles/discovery.css';
import {
  getProfiles,
  getJobs,
  cancelJob,
  getPendingResults,
  getDiscoveryStatus,
  getJobLogs,
} from '../api/discovery.js';
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

const STATUS_FILTERS = {
  all: null,
  active: ['running'],
  completed: ['completed', 'done'],
  queued: ['queued'],
};

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

  const progressMapRef = useRef({});
  const [progressMap, setProgressMap] = useState({});
  const etaMapRef = useRef({});
  const [etaMap, setEtaMap] = useState({});
  const logMapRef = useRef({});
  const [logMap, setLogMap] = useState({});
  const [detailedLogMap, setDetailedLogMap] = useState({});
  const detailedLogMapRef = useRef({});

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
        detailedLogMapRef.current = { ...detailedLogMapRef.current, [jobId]: logs };
        setDetailedLogMap({ ...detailedLogMapRef.current });
      })
      .catch(() => {});
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
      .catch(() => {});
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
        progressMapRef.current = {
          ...progressMapRef.current,
          [data.job_id]: Math.round(data.percent),
        };
        setProgressMap({ ...progressMapRef.current });
      } else if (
        typeof data.processed === 'number' &&
        typeof data.total === 'number' &&
        data.total > 0
      ) {
        const pct = Math.round((data.processed / data.total) * 100);
        progressMapRef.current = { ...progressMapRef.current, [data.job_id]: pct };
        setProgressMap({ ...progressMapRef.current });
      }

      if (typeof data.eta_seconds === 'number') {
        etaMapRef.current = { ...etaMapRef.current, [data.job_id]: data.eta_seconds };
        setEtaMap({ ...etaMapRef.current });
      }

      if (data.message || data.phase) {
        const entry = { phase: data.phase, message: data.message, ts: Date.now() };
        const prev = logMapRef.current[data.job_id] || [];
        logMapRef.current = { ...logMapRef.current, [data.job_id]: [...prev, entry].slice(-200) };
        setLogMap({ ...logMapRef.current });
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
        const prev = detailedLogMapRef.current[data.job_id] || [];
        detailedLogMapRef.current = {
          ...detailedLogMapRef.current,
          [data.job_id]: [...prev, entry].slice(-500),
        };
        setDetailedLogMap({ ...detailedLogMapRef.current });
      }
    };

    const onResultAdded = () => {
      setPendingReviewCount((c) => c + 1);
    };

    discoveryEmitter.on('job:update', onJobUpdate);
    discoveryEmitter.on('job:progress', onJobProgress);
    discoveryEmitter.on('scan:log_entry', onScanLogEntry);
    discoveryEmitter.on('result:added', onResultAdded);

    return () => {
      discoveryEmitter.off('job:update', onJobUpdate);
      discoveryEmitter.off('job:progress', onJobProgress);
      discoveryEmitter.off('scan:log_entry', onScanLogEntry);
      discoveryEmitter.off('result:added', onResultAdded);
    };
  }, [loadJobs, loadPendingResults]);

  // ── Derived state ──────────────────────────────────────────────────────

  const profileMap = useMemo(() => {
    const map = {};
    for (const p of profiles) map[p.id] = p.name;
    return map;
  }, [profiles]);

  // Load logs when a job is selected
  useEffect(() => {
    if (selectedJobId) {
      loadJobLogs(selectedJobId);
    }
  }, [selectedJobId, loadJobLogs]);

  const filteredJobs = useMemo(() => {
    const statusSet = STATUS_FILTERS[filter];
    if (!statusSet) return jobs;
    return jobs.filter((j) => statusSet.includes(j.status));
  }, [jobs, filter]);

  const jobCounts = useMemo(
    () => ({
      all: jobs.length,
      active: jobs.filter((j) => j.status === 'running').length,
      completed: jobs.filter((j) => j.status === 'completed' || j.status === 'done').length,
      queued: jobs.filter((j) => j.status === 'queued').length,
    }),
    [jobs]
  );

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedJobId) ?? null,
    [jobs, selectedJobId]
  );

  // ── Actions ────────────────────────────────────────────────────────────

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
  if (filter === 'profiles') {
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
        onStarted={() => {
          loadJobs();
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
          progressPct={selectedJob ? progressMap[selectedJobId] : undefined}
          etaSeconds={selectedJob ? etaMap[selectedJobId] : undefined}
          logEntries={selectedJob ? logMap[selectedJobId] : undefined}
          detailedLogs={selectedJob ? detailedLogMap[selectedJobId] : undefined}
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
      />

      <div className="discovery-main">{mainContent}</div>
    </div>
  );
}
