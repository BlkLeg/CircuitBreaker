import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Activity, Network, Zap, Clock } from 'lucide-react';
import { discoveryEmitter } from '../../hooks/useDiscoveryStream.js';

export function LiveScanOverview({ activeJobId }) {
  const [scanStats, setScanStats] = useState({
    devicesFound: 0,
    hostsNew: 0,
    hostsConflict: 0,
    scanDuration: 0,
  });

  useEffect(() => {
    const handleJobUpdate = (jobData) => {
      if (jobData?.id === activeJobId) {
        const elapsed = jobData.started_at
          ? Math.floor((Date.now() - new Date(jobData.started_at).getTime()) / 1000)
          : 0;
        setScanStats({
          devicesFound: jobData.hosts_found || 0,
          hostsNew: jobData.hosts_new || 0,
          hostsConflict: jobData.hosts_conflict || 0,
          scanDuration: elapsed,
        });
      }
    };

    discoveryEmitter.on('job:update', handleJobUpdate);
    return () => discoveryEmitter.off('job:update', handleJobUpdate);
  }, [activeJobId]);

  const formatDuration = (seconds) => {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  return (
    <div className="live-scan-overview">
      <div className="live-scan-stat">
        <div className="live-scan-stat-icon">
          <Network size={16} />
        </div>
        <div className="live-scan-stat-content">
          <div className="live-scan-stat-label">Devices Found</div>
          <div className="live-scan-stat-value">{scanStats.devicesFound}</div>
        </div>
      </div>

      <div className="live-scan-stat">
        <div className="live-scan-stat-icon">
          <Activity size={16} />
        </div>
        <div className="live-scan-stat-content">
          <div className="live-scan-stat-label">New</div>
          <div className="live-scan-stat-value">{scanStats.hostsNew}</div>
        </div>
      </div>

      <div className="live-scan-stat">
        <div className="live-scan-stat-icon">
          <Zap size={16} />
        </div>
        <div className="live-scan-stat-content">
          <div className="live-scan-stat-label">Conflicts</div>
          <div className="live-scan-stat-value">{scanStats.hostsConflict}</div>
        </div>
      </div>

      <div className="live-scan-stat">
        <div className="live-scan-stat-icon">
          <Clock size={16} />
        </div>
        <div className="live-scan-stat-content">
          <div className="live-scan-stat-label">Duration</div>
          <div className="live-scan-stat-value">{formatDuration(scanStats.scanDuration)}</div>
        </div>
      </div>
    </div>
  );
}

LiveScanOverview.propTypes = {
  activeJobId: PropTypes.number,
};

export function ActiveTargetsList({ activeJob }) {
  const [targetProgress, setTargetProgress] = useState([]);

  useEffect(() => {
    const handleTargetUpdate = (data) => {
      if (data.job_id === activeJob?.id) {
        setTargetProgress(data.target_progress || []);
      }
    };

    discoveryEmitter.on('target:progress', handleTargetUpdate);
    return () => discoveryEmitter.off('target:progress', handleTargetUpdate);
  }, [activeJob?.id]);

  if (!activeJob || targetProgress.length === 0) {
    return (
      <div className="active-targets-list-empty">
        <p>No active scan targets</p>
      </div>
    );
  }

  return (
    <div className="active-targets-list">
      <h3 className="active-targets-title">Scan Progress</h3>
      {targetProgress.map((target, idx) => (
        <div key={`${target.network}-${idx}`} className="active-target-item">
          <div className="active-target-info">
            <span className="active-target-network">{target.network}</span>
            <span className="active-target-phase">{target.phase}</span>
          </div>
          <div className="active-target-progress">
            <div className="active-target-progress-bar">
              <div
                className="active-target-progress-fill"
                style={{ width: `${target.progress}%` }}
              />
            </div>
            <span className="active-target-progress-text">{target.progress}%</span>
          </div>
          <div className="active-target-stats">
            <span>{target.hosts_found || 0} found</span>
          </div>
        </div>
      ))}
    </div>
  );
}

ActiveTargetsList.propTypes = {
  activeJob: PropTypes.object,
};

export function RecentDevicesStream() {
  const [recentDevices, setRecentDevices] = useState([]);

  useEffect(() => {
    const handleDeviceFound = (data) => {
      setRecentDevices((prev) => [
        data,
        ...prev.slice(0, 9), // Keep only last 10 devices
      ]);
    };

    discoveryEmitter.on('result:added', handleDeviceFound);
    return () => discoveryEmitter.off('result:added', handleDeviceFound);
  }, []);

  if (recentDevices.length === 0) {
    return (
      <div className="recent-devices-empty">
        <p>No recent discoveries</p>
      </div>
    );
  }

  return (
    <div className="recent-devices-stream">
      <h3 className="recent-devices-title">Live Discoveries</h3>
      {recentDevices.map((device, idx) => (
        <div key={`${device.ip_address}-${idx}`} className="recent-device-item">
          <div className="recent-device-ip">{device.ip_address}</div>
          <div className="recent-device-info">
            {device.mac_address && <span className="recent-device-mac">{device.mac_address}</span>}
            {device.os_family && <span className="recent-device-os">{device.os_family}</span>}
          </div>
          <div className="recent-device-time">{new Date().toLocaleTimeString()}</div>
        </div>
      ))}
    </div>
  );
}

export function ScanPerformanceMetrics({ activeJob }) {
  const [metrics, setMetrics] = useState({
    estimatedCompletion: null,
    currentPhase: 'queued',
    totalProgress: 0,
  });

  useEffect(() => {
    const handleProgress = (data) => {
      if (data.job_id === activeJob?.id) {
        const eta =
          typeof data.eta_seconds === 'number'
            ? new Date(Date.now() + data.eta_seconds * 1000).toISOString()
            : null;
        setMetrics({
          estimatedCompletion: eta,
          currentPhase: data.phase || 'running',
          totalProgress: typeof data.percent === 'number' ? data.percent : 0,
        });
      }
    };

    discoveryEmitter.on('job:progress', handleProgress);
    return () => discoveryEmitter.off('job:progress', handleProgress);
  }, [activeJob?.id]);

  if (!activeJob) {
    return (
      <div className="scan-performance-empty">
        <p>No active scan</p>
      </div>
    );
  }

  return (
    <div className="scan-performance-metrics">
      <h3 className="scan-performance-title">Performance</h3>

      <div className="scan-performance-metric">
        <span className="scan-performance-label">Current Phase</span>
        <span className="scan-performance-value">{metrics.currentPhase}</span>
      </div>

      <div className="scan-performance-metric">
        <span className="scan-performance-label">Overall Progress</span>
        <span className="scan-performance-value">{metrics.totalProgress}%</span>
      </div>

      {metrics.estimatedCompletion && (
        <div className="scan-performance-metric">
          <span className="scan-performance-label">ETA</span>
          <span className="scan-performance-value">
            {new Date(metrics.estimatedCompletion).toLocaleTimeString()}
          </span>
        </div>
      )}
    </div>
  );
}

ScanPerformanceMetrics.propTypes = {
  activeJob: PropTypes.object,
};
