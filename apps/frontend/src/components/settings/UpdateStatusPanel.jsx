import React from 'react';
import { useUpdateStatus } from '../../hooks/useUpdateStatus.js';

const STATUS_TEXT = {
  ok: 'Up to date.',
  disabled: 'Update checking is disabled (CB_UPDATE_CHECK=false).',
  airgap: 'Update checking is disabled by air-gap mode.',
  unreachable: 'Could not reach the release source at the last check.',
  never_checked: 'No check has run yet.',
  unknown_version: 'This build is not a published release, so no comparison was made.',
};

function Row({ label, value }) {
  return (
    <div
      style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}
    >
      <span style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      <span style={{ fontWeight: 500 }}>{value ?? '—'}</span>
    </div>
  );
}

/**
 * Permanent home for version facts. Each status renders its own sentence:
 * "disabled" and "unreachable" must never read as "you are up to date".
 */
export default function UpdateStatusPanel() {
  const { status } = useUpdateStatus();
  if (!status) return null;

  const summary = status.update_available
    ? `Version ${status.available} is available.`
    : STATUS_TEXT[status.status] || STATUS_TEXT.never_checked;

  return (
    <div>
      <Row label="Installed version" value={status.current} />
      <Row label="Available version" value={status.available} />
      <Row label="Channel" value={status.channel} />
      <Row label="Install method" value={status.install_method} />
      <Row label="Last checked" value={status.checked_at} />
      <p style={{ fontSize: 13, marginTop: 8 }}>{summary}</p>
      {status.update_available && (
        <>
          <p style={{ fontSize: 13, marginBottom: 4 }}>To upgrade:</p>
          <code
            style={{ display: 'block', padding: 8, background: 'var(--color-bg-subtle, #111827)' }}
          >
            {status.upgrade_command}
          </code>
        </>
      )}
    </div>
  );
}
