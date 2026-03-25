import React from 'react';
import { useAuth } from '../context/AuthContext.jsx';

/**
 * Renders a persistent amber banner when an admin is masquerading as another user.
 * Exposes a "Return to Admin" button that clears the masquerade token and reloads.
 */
export default function MasqueradeBanner() {
  const { isMasquerade, user, endMasquerade } = useAuth();

  if (!isMasquerade) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 'var(--header-height, 60px)',
        left: 0,
        right: 0,
        zIndex: 99,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        padding: '8px 16px',
        background: '#f59e0b33',
        borderBottom: '2px solid #f59e0b99',
        color: '#f59e0b',
        fontSize: 13,
        fontWeight: 500,
      }}
    >
      <span>
        Viewing as <strong>{user?.email || 'unknown user'}</strong> — your admin session is
        preserved.
      </span>
      <button
        type="button"
        onClick={endMasquerade}
        style={{
          padding: '3px 10px',
          borderRadius: 'var(--radius)',
          border: '1px solid #f59e0b88',
          background: '#f59e0b22',
          color: '#f59e0b',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
      >
        Return to Admin
      </button>
    </div>
  );
}
