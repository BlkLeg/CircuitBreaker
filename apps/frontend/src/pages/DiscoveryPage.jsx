/* eslint-disable security/detect-object-injection -- Map used for job-keyed state */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import '../styles/discovery.css';
import {
  getProfiles,
  getJobs,
  getPendingResults,
  getDiscoveryStatus,
  startAdHocScan,
} from '../api/discovery.js';
import { X } from 'lucide-react';
import { systemApi } from '../api/client.jsx';
import { discoveryEmitter } from '../hooks/useDiscoveryStream.js';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger.js';

import DiscoverySidebar from '../components/discovery/DiscoverySidebar.jsx';
import DiscoveryHistoryPage from './DiscoveryHistoryPage.jsx';
import ScanProfilesPanel from '../components/discovery/ScanProfilesPanel.jsx';
import NewScanPage from '../components/discovery/NewScanPage.jsx';
import ReviewQueuePanel from '../components/discovery/ReviewQueuePanel.jsx';
import ProxmoxIntegrationSection from '../components/proxmox/ProxmoxIntegrationSection.jsx';

function logApiWarning(scope, error) {
  logger.warn(`[DiscoveryPage] ${scope}`, error);
}

export default function DiscoveryPage() {
  const location = useLocation();
  const toast = useToast();

  const [jobs, setJobs] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [filter, setFilter] = useState('all');
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

  const locationFilterAppliedRef = useRef(false);

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

  useEffect(() => {
    if (locationFilterAppliedRef.current) return;
    const requestedFilter = location.state?.discoveryFilter;
    if (typeof requestedFilter === 'string' && requestedFilter.trim()) {
      setFilter(requestedFilter);
      locationFilterAppliedRef.current = true;
    }
  }, [location.state]);

  const loadPendingResults = useCallback(() => {
    getPendingResults({ limit: 1 })
      .then((res) => {
        const count = res.data?.total ?? (Array.isArray(res.data) ? res.data.length : 0);
        setPendingReviewCount(count);
      })
      .catch((err) => logApiWarning('Failed to fetch pending count', err));
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
      if (!data?.job_id) return;

      let progressPercent = null;
      if (typeof data.percent === 'number') {
        progressPercent = Math.round(data.percent);
      } else if (
        typeof data.processed === 'number' &&
        typeof data.total === 'number' &&
        data.total > 0
      ) {
        progressPercent = Math.round((data.processed / data.total) * 100);
      }

      setJobs((prev) => {
        const idx = prev.findIndex((job) => job.id === data.job_id);
        if (idx === -1) return prev;
        const existing = prev[idx];
        const nextJob = {
          ...existing,
          ...(progressPercent != null ? { progress_percent: progressPercent } : {}),
          ...(typeof data.eta_seconds === 'number' ? { eta_seconds: data.eta_seconds } : {}),
          ...(data.phase ? { current_phase: data.phase } : {}),
          ...(data.message ? { current_message: data.message } : {}),
        };
        const next = [...prev];
        next[idx] = nextJob;
        return next;
      });
    };

    const onScanLogEntry = (data) => {
      if (!data?.job_id) return;
      setJobs((prev) => {
        const idx = prev.findIndex((job) => job.id === data.job_id);
        if (idx === -1) return prev;
        const existing = prev[idx];
        const nextJob = {
          ...existing,
          ...(data.message ? { last_log_message: data.message } : {}),
          ...(data.phase ? { last_log_phase: data.phase } : {}),
          ...(data.level ? { last_log_level: data.level } : {}),
          ...(data.timestamp ? { last_log_ts: data.timestamp } : {}),
        };
        const next = [...prev];
        next[idx] = nextJob;
        return next;
      });
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
  }, [loadJobs]);

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

  let mainContent;
  if (filter === 'proxmox') {
    mainContent = (
      <div className="discovery-proxmox-section" style={{ padding: 24, maxWidth: 720 }}>
        <ProxmoxIntegrationSection />
      </div>
    );
  } else if (filter === 'profiles') {
    mainContent = <ScanProfilesPanel onSaved={loadProfiles} />;
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
    mainContent = <DiscoveryHistoryPage embedded jobsData={jobs} onRefreshJobs={loadJobs} />;
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
