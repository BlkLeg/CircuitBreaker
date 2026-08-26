import React, { useState } from 'react';
import { ArrowUpCircle, X } from 'lucide-react';
import { useUpdateStatus } from '../hooks/useUpdateStatus.js';

const DISMISS_KEY = 'cb.updateDismissed';

function readDismissed() {
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null; // private mode / blocked storage must not break the banner
  }
}

/**
 * Admin-only notice that a newer release exists in this install's channel.
 *
 * Dismissal is stored per-version, not as a boolean: dismissing rc.4 must not
 * hide rc.5. Silent stranding is the bug this component exists to prevent.
 */
export default function UpdateBanner() {
  const { status } = useUpdateStatus();
  const [dismissed, setDismissed] = useState(() => readDismissed());

  if (!status?.update_available || !status.available) return null;
  if (dismissed === status.available) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, status.available);
    } catch {
      /* storage unavailable — hide for this session only */
    }
    setDismissed(status.available);
  };

  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        background: 'var(--color-info-bg, #1e3a5f)',
        color: 'var(--color-text, #e5e7eb)',
        fontSize: 13,
      }}
    >
      <ArrowUpCircle size={16} aria-hidden="true" />
      <span>
        <strong>{status.available}</strong> is available — you are on {status.current}.
      </span>
      <code style={{ opacity: 0.85 }}>{status.upgrade_command}</code>
      {status.release_url && (
        <a href={status.release_url} target="_blank" rel="noreferrer noopener">
          Release notes
        </a>
      )}
      <button type="button" onClick={dismiss} aria-label="Dismiss" style={{ marginLeft: 'auto' }}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
