import React from 'react';
import PropTypes from 'prop-types';
import { Plus, Layers, Settings2, ClipboardList, History } from 'lucide-react';

const FILTERS = [{ key: 'all', label: 'All Scans', Icon: Layers }];

export default function DiscoverySidebar({
  filter,
  onFilterChange,
  jobCounts,
  pendingReviewCount,
  networkLoad = 0,
  storageUsed = 0,
}) {
  return (
    <aside className="discovery-sidebar">
      <button
        type="button"
        className="sidebar-new-scan-btn"
        onClick={() => onFilterChange('new-scan')}
      >
        <Plus size={16} /> New Scan
      </button>

      <nav className="sidebar-nav">
        {FILTERS.map(({ key, label, Icon }) => {
          const count = jobCounts[key] ?? 0;
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

      <div className="sidebar-footer">
        <div className="sidebar-stat">
          <span className="sidebar-stat-label">Network Load</span>
          <span className="sidebar-stat-value">{networkLoad}%</span>
        </div>
        <div className="sidebar-stat-bar">
          <div
            className="sidebar-stat-bar-fill sidebar-stat-bar-blue"
            style={{ width: `${networkLoad}%` }}
          />
        </div>
        <div className="sidebar-stat">
          <span className="sidebar-stat-label">Storage</span>
          <span className="sidebar-stat-value">{storageUsed}%</span>
        </div>
        <div className="sidebar-stat-bar">
          <div
            className={`sidebar-stat-bar-fill ${storageUsed > 80 ? 'sidebar-stat-bar-amber' : 'sidebar-stat-bar-blue'}`}
            style={{ width: `${storageUsed}%` }}
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
  networkLoad: PropTypes.number,
  storageUsed: PropTypes.number,
};
