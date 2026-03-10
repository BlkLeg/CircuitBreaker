import React from 'react';
import PropTypes from 'prop-types';
import { AlertCircle } from 'lucide-react';

const BADGE_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  padding: '1px 7px',
  borderRadius: 10,
  fontSize: 10,
  fontWeight: 600,
};

export default function DiscoveryStatusBar({
  totalScans,
  activeCount,
  totalFound,
  conflictCount,
  effectiveMode,
  dockerAvailable,
}) {
  return (
    <div className="discovery-status-bar">
      <div className="status-bar-left">
        <span className="status-bar-dot" />
        <span>Connected</span>
        <span className="status-bar-divider" />
        <span>Total Scans: {totalScans}</span>
        <span>Active: {activeCount}</span>
        <span>Found: {totalFound}</span>
        {effectiveMode && (
          <span
            style={{
              ...BADGE_STYLE,
              background:
                effectiveMode === 'full' ? 'rgba(22,163,74,0.15)' : 'rgba(217,119,6,0.15)',
              color: effectiveMode === 'full' ? '#16a34a' : '#d97706',
            }}
          >
            {effectiveMode === 'full' ? 'Full Mode' : 'Safe Mode'}
          </span>
        )}
        {dockerAvailable && (
          <span style={{ ...BADGE_STYLE, background: 'rgba(37,99,235,0.15)', color: '#3b82f6' }}>
            Docker
          </span>
        )}
      </div>
      <div className="status-bar-right">
        <span>Last Sync: Just now</span>
        {conflictCount > 0 && (
          <span className="status-bar-conflict">
            <AlertCircle size={10} />
            {conflictCount} Conflict{conflictCount === 1 ? '' : 's'} Detected
          </span>
        )}
      </div>
    </div>
  );
}

DiscoveryStatusBar.propTypes = {
  totalScans: PropTypes.number.isRequired,
  activeCount: PropTypes.number.isRequired,
  totalFound: PropTypes.number.isRequired,
  conflictCount: PropTypes.number.isRequired,
  effectiveMode: PropTypes.string,
  dockerAvailable: PropTypes.bool,
};

DiscoveryStatusBar.defaultProps = {
  effectiveMode: null,
  dockerAvailable: false,
};
