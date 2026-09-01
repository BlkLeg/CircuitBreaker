import React, { useState } from 'react';
import SettingField from './SettingField';
import { getEntries, clearEntries, exportJson } from '../../lib/diagnosticsBuffer';

/**
 * Admin-only export/clear controls for the browser-side diagnostics ring
 * buffer (`lib/diagnosticsBuffer.js`) — the last 200 navigation and HTTP
 * request records, kept so a browser navigation can be correlated to the
 * server-side work (request IDs, slow-query logs) it caused.
 *
 * Lives inside the "Host Diagnostics" `SettingSection` in SettingsPage.jsx,
 * admin-gated exactly as that section already is.
 */
export default function DiagnosticsPanel() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [entryCount, setEntryCount] = useState(() => getEntries().length);

  const handleExport = () => {
    setBusy(true);
    setError(null);
    try {
      const json = exportJson();
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `circuitbreaker-diagnostics-${new Date().toISOString()}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'Failed to export diagnostics.');
    } finally {
      setBusy(false);
    }
  };

  const handleClear = () => {
    setBusy(true);
    setError(null);
    try {
      clearEntries();
      setEntryCount(getEntries().length);
    } catch (err) {
      setError(err.message || 'Failed to clear diagnostics.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SettingField
        label="Navigation & Request Log"
        hint={`Last ${entryCount} browser-side navigation and request record${
          entryCount === 1 ? '' : 's'
        }, correlated to server logs by X-Request-ID. No request/response bodies, headers, or query strings are recorded.`}
      >
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleExport}
            disabled={busy}
          >
            {busy ? 'Working…' : 'Download Diagnostics'}
          </button>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={handleClear}
            disabled={busy}
          >
            {busy ? 'Working…' : 'Clear Diagnostics'}
          </button>
        </div>
      </SettingField>
      {error && (
        <div style={{ color: 'var(--color-danger)', fontSize: 13 }} role="alert">
          {error}
        </div>
      )}
    </>
  );
}
