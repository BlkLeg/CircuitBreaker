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
        // flexWrap + minWidth:0 on the code block: the docker upgrade command
        // is ~70 characters and .page-content has mobile breakpoints, so a
        // single unwrapping flex line pushed the page into horizontal scroll.
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        marginBottom: 12,
        // --color-surface / --color-text are the app's designed contrast pair:
        // both are defined in main.css :root and both are re-set together, per
        // theme variant, by theme/applyTheme.js. The previous
        // `var(--color-info-bg, #1e3a5f)` named a variable that is defined
        // nowhere in src/styles, so it always resolved to the hardcoded dark
        // navy while --color-text followed the theme -- dark text on a dark bar
        // under every light preset. jsdom cannot see that; see
        // UpdateThemeTokens.test.jsx for the guard that can.
        background: 'var(--color-surface)',
        color: 'var(--color-text)',
        border: '1px solid var(--color-border)',
        borderLeft: '3px solid var(--color-info)',
        borderRadius: 'var(--radius, 6px)',
        fontSize: 13,
      }}
    >
      <ArrowUpCircle size={16} aria-hidden="true" style={{ flexShrink: 0 }} />
      <span>
        <strong>{status.available}</strong> is available — you are on {status.current}.
      </span>
      <code
        style={{
          minWidth: 0,
          overflowX: 'auto',
          padding: '2px 6px',
          borderRadius: 'var(--radius, 6px)',
          background: 'var(--color-secondary)',
          color: 'var(--color-text)',
        }}
      >
        {status.upgrade_command}
      </code>
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
