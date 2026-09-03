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
 * Wraps the app. Shows a status overlay during starting / stopping / offline
 * states, over a route tree that stays mounted.
 *
 * R5's second half: this used to return a replacement element instead of its
 * children, so a degraded banner unmounted every page in the app and threw away
 * its state — an open form, a running scan view, an unsent edit — and remounted
 * the whole tree from scratch on recovery. A health blip is not a reason to
 * destroy what the user was doing. The overlay says the same thing without
 * touching the tree underneath it.
 *
 * The delay applies to all three states, not just offline. `starting` and
 * `stopping` were shown immediately with no streak and no delay, so one health
 * response during a rolling worker restart or a migration lock blanked the app
 * instantly.
 */
export default function ServerLifecycleBanner({ children }) {
  const { state, isReady, offlineSince } = useServerLifecycle();
  const [showBanner, setShowBanner] = useState(false);

  useEffect(() => {
    if (isReady || state === 'checking' || !getStateConfig(state)) {
      setShowBanner(false);
      return;
    }
    const timer = setTimeout(() => setShowBanner(true), MAX_OFFLINE_BEFORE_NOTIFY_MS);
    return () => clearTimeout(timer);
  }, [state, offlineSince, isReady]);

  const config = getStateConfig(state);
  const visible = showBanner && Boolean(config) && !isReady && state !== 'checking';

  return (
    <>
      {children}
      {visible && (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9000,
            background: 'var(--color-bg, #0a0f1a)ee',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
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
          <style>{`@keyframes cb-spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}
    </>
  );
}

ServerLifecycleBanner.propTypes = {
  children: PropTypes.node.isRequired,
};
