import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { useServerLifecycle } from '../hooks/useServerLifecycle.js';
import { MAX_OFFLINE_BEFORE_NOTIFY_MS } from '../lib/constants.js';

const STATE_CONFIG = {
  starting: {
    label: 'Server is starting up\u2026',
    subtext: 'Migrations and health checks are running.',
    color: 'var(--color-warning, #f59e0b)',
    spinner: true,
  },
  stopping: {
    label: 'Server is shutting down',
    subtext: 'Active connections are draining.',
    color: 'var(--color-warning, #f97316)',
    spinner: true,
  },
  offline: {
    label: 'Server is offline',
    subtext: 'Waiting for the server to come back online\u2026',
    color: 'var(--color-danger, #ef4444)',
    spinner: false,
  },
};

function getStateConfig(state) {
  if (state === 'starting') return STATE_CONFIG.starting;
  if (state === 'stopping') return STATE_CONFIG.stopping;
  if (state === 'offline') return STATE_CONFIG.offline;
  return null;
}

/**
 * Wraps the app. Blocks children from rendering until the server is ready.
 * Shows a status banner during starting / stopping / offline states.
 */
export default function ServerLifecycleBanner({ children }) {
  const { state, isReady, offlineSince } = useServerLifecycle();
  const [showOffline, setShowOffline] = useState(false);

  // Delay the offline banner slightly to avoid flicker on fast restarts.
  useEffect(() => {
    if (state !== 'offline') {
      setShowOffline(false);
      return;
    }
    const timer = setTimeout(() => setShowOffline(true), MAX_OFFLINE_BEFORE_NOTIFY_MS);
    return () => clearTimeout(timer);
  }, [state, offlineSince]);

  if (state === 'checking' || isReady) return <>{children}</>;

  const config = getStateConfig(state);
  const visible =
    state === 'starting' || state === 'stopping' || (state === 'offline' && showOffline);

  if (!visible || !config) return <>{children}</>;

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--color-bg, #0a0f1a)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {visible && config && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 12,
            padding: '32px 40px',
            borderRadius: 12,
            border: `1px solid ${config.color}44`,
            background: `${config.color}12`,
            maxWidth: 360,
            textAlign: 'center',
          }}
        >
          {config.spinner && (
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                border: `3px solid ${config.color}33`,
                borderTopColor: config.color,
                animation: 'cb-spin 0.9s linear infinite',
              }}
            />
          )}
          <p style={{ margin: 0, fontWeight: 600, color: config.color, fontSize: 15 }}>
            {config.label}
          </p>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--color-text-muted, #8892a4)' }}>
            {config.subtext}
          </p>
        </div>
      )}
      <style>{`@keyframes cb-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

ServerLifecycleBanner.propTypes = {
  children: PropTypes.node.isRequired,
};
