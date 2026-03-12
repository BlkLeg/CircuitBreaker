import React from 'react';
import PropTypes from 'prop-types';
import { Plus, Layers, Settings2, ClipboardList, History } from 'lucide-react';
import LiveListenersPanel from './LiveListenersPanel.jsx';

const FILTERS = [{ key: 'all', label: 'All Scans', Icon: Layers }];

export default function DiscoverySidebar({
  filter,
  onFilterChange,
  jobCounts,
  pendingReviewCount,
  memoryUsed = null,
  storageUsed = null,
  listenerEnabled = false,
  dockerAvailable = false,
  dockerScanning = false,
  dockerContainerCount = 0,
  onDockerScan = () => {},
}) {
  const memPct = memoryUsed == null ? null : Math.min(100, Math.max(0, memoryUsed));
  const diskPct = storageUsed == null ? null : Math.min(100, Math.max(0, storageUsed));
  return (
    <aside className="discovery-sidebar">
      <button
        type="button"
        className="sidebar-new-scan-btn"
        onClick={() => onFilterChange('new-scan')}
      >
        <Plus size={16} /> New Scan
      </button>

      <button
        type="button"
        className="sidebar-docker-scan-btn"
        onClick={onDockerScan}
        disabled={!dockerAvailable || dockerScanning}
        title={
          dockerAvailable
            ? 'Scan your Docker environment and add containers to the Review Queue'
            : 'Docker daemon not reachable'
        }
      >
        <img src="/icons/vendors/docker.svg" width={16} height={16} alt="" />
        {dockerScanning ? 'Scanning…' : 'Discover Docker'}
      </button>
      {dockerContainerCount > 0 && (
        <p className="sidebar-docker-status">
          {dockerContainerCount} container{dockerContainerCount === 1 ? '' : 's'} visible
        </p>
      )}

      <nav className="sidebar-nav">
        {FILTERS.map(({ key, label, Icon }) => {
          const count = jobCounts.get(key) ?? 0;
          return (
            <button
              key={key}
              type="button"
              className={`sidebar-nav-item ${filter === key ? 'active' : ''}`}
              onClick={() => onFilterChange(key)}
            >
              <span className="sidebar-nav-icon">
                <Icon size={16} />
              </span>
              <span className="sidebar-nav-label">{label}</span>
              {count > 0 && <span className="sidebar-nav-count">{count}</span>}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-divider" />
      <p className="sidebar-section-label">Configuration</p>
      <nav className="sidebar-nav">
        <button
          type="button"
          className={`sidebar-nav-item ${filter === 'proxmox' ? 'active' : ''}`}
          onClick={() => onFilterChange('proxmox')}
        >
          <span className="sidebar-nav-icon">
            <img src="/icons/vendors/proxmox-dark.svg" width={16} height={16} alt="" />
          </span>
          <span className="sidebar-nav-label">Proxmox VE</span>
        </button>
        <button
          type="button"
          className={`sidebar-nav-item ${filter === 'profiles' ? 'active' : ''}`}
          onClick={() => onFilterChange('profiles')}
        >
          <span className="sidebar-nav-icon">
            <Settings2 size={16} />
          </span>
          <span className="sidebar-nav-label">Scan Profiles</span>
        </button>
        <button
          type="button"
          className={`sidebar-nav-item ${filter === 'review' ? 'active' : ''}`}
          onClick={() => onFilterChange('review')}
        >
          <span className="sidebar-nav-icon">
            <ClipboardList size={16} />
          </span>
          <span className="sidebar-nav-label">Review Queue</span>
          {pendingReviewCount > 0 && (
            <span className="sidebar-nav-count">{pendingReviewCount}</span>
          )}
        </button>
        <button
          type="button"
          className={`sidebar-nav-item ${filter === 'history' ? 'active' : ''}`}
          onClick={() => onFilterChange('history')}
        >
          <span className="sidebar-nav-icon">
            <History size={16} />
          </span>
          <span className="sidebar-nav-label">History</span>
        </button>
      </nav>

      <LiveListenersPanel listenerEnabled={listenerEnabled} />

      <div className="sidebar-footer">
        <div className="sidebar-stat">
          <span className="sidebar-stat-label">Memory</span>
          <span className="sidebar-stat-value">{memPct == null ? '—' : `${memPct}%`}</span>
        </div>
        <div className="sidebar-stat-bar">
          <div
            className="sidebar-stat-bar-fill sidebar-stat-bar-blue"
            style={{ width: `${memPct == null ? 0 : memPct}%` }}
          />
        </div>
        <div className="sidebar-stat">
          <span className="sidebar-stat-label">Disk</span>
          <span className="sidebar-stat-value">{diskPct == null ? '—' : `${diskPct}%`}</span>
        </div>
        <div className="sidebar-stat-bar">
          <div
            className={`sidebar-stat-bar-fill ${diskPct == null || diskPct <= 80 ? 'sidebar-stat-bar-blue' : 'sidebar-stat-bar-amber'}`}
            style={{ width: `${diskPct == null ? 0 : diskPct}%` }}
          />
        </div>
      </div>
    </aside>
  );
}

DiscoverySidebar.propTypes = {
  filter: PropTypes.string.isRequired,
  onFilterChange: PropTypes.func.isRequired,
  jobCounts: PropTypes.object.isRequired,
  pendingReviewCount: PropTypes.number,
  memoryUsed: PropTypes.number,
  storageUsed: PropTypes.number,
  listenerEnabled: PropTypes.bool,
  dockerAvailable: PropTypes.bool,
  dockerScanning: PropTypes.bool,
  dockerContainerCount: PropTypes.number,
  onDockerScan: PropTypes.func,
};
