import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const ACK_KEY = 'cb:security-banner-ack';

/**
 * SecurityBanner — fetches /api/v1/security/status on mount and displays a
 * warning banner when authentication is disabled.
 *
 * The banner can be dismissed via "Acknowledge" (persisted in localStorage).
 * The ack is cleared automatically if auth is later enabled, so re-disabling
 * auth will surface the warning again.
 */
export default function SecurityBanner() {
  const [show, setShow] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetch('/api/v1/security/status')
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (!data) return;
        if (data.auth_enabled) {
          // Clear any stale ack so re-disabling auth will show the banner again
          localStorage.removeItem(ACK_KEY);
          return;
        }
        if (!localStorage.getItem(ACK_KEY)) {
          setShow(true);
        }
      })
      .catch(() => {});
  }, []);

  const handleAcknowledge = () => {
    localStorage.setItem(ACK_KEY, '1');
    setShow(false);
  };

  if (!show) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '9px 16px',
        background: 'rgba(234, 179, 8, 0.15)',
        borderBottom: '1px solid rgba(234, 179, 8, 0.5)',
        fontSize: 13,
        color: 'rgb(234, 179, 8)',
        backdropFilter: 'blur(4px)',
      }}
    >
      <span style={{ fontSize: 16 }}>⚠️</span>
      <span style={{ flex: 1 }}>
        <strong>Authentication is disabled.</strong>{' '}
        All data is publicly writable by anyone who can reach this server.
      </span>
      <button
        onClick={() => navigate('/settings?tab=auth')}
        style={{
          background: 'rgba(234, 179, 8, 0.2)',
          border: '1px solid rgba(234, 179, 8, 0.5)',
          color: 'rgb(234, 179, 8)',
          borderRadius: 6,
          padding: '4px 10px',
          cursor: 'pointer',
          fontSize: 12,
          fontFamily: 'inherit',
          whiteSpace: 'nowrap',
        }}
      >
        Enable in Settings →
      </button>
      <button
        onClick={handleAcknowledge}
        aria-label="Dismiss security warning"
        style={{
          background: 'transparent',
          border: '1px solid rgba(234, 179, 8, 0.4)',
          color: 'rgba(234, 179, 8, 0.8)',
          borderRadius: 6,
          padding: '4px 10px',
          cursor: 'pointer',
          fontSize: 12,
          fontFamily: 'inherit',
          whiteSpace: 'nowrap',
        }}
      >
        Acknowledge
      </button>
    </div>
  );
}
