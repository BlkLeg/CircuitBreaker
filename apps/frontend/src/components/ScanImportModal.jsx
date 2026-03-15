/**
 * ScanImportModal — batch confirm dialog for importing discovered devices.
 *
 * Props:
 *   scanId (number)     — the ScanJob id to import from
 *   results (array)     — pre-fetched InferredScanResultOut array
 *   onClose ()          — called when user dismisses without importing
 *   onImported (resp)   — called with BatchImportResponse after successful import
 */
import React, { useState, useMemo } from 'react';
import { discoveryApi } from '../api/client';
import { useToast } from './common/Toast';

const CONFIDENCE_DOTS = (c) => {
  if (c >= 0.75) return '●●●';
  if (c >= 0.4) return '●●○';
  if (c > 0) return '●○○';
  return '○○○';
};

const ROLE_OPTIONS = [
  'server',
  'router',
  'switch',
  'firewall',
  'hypervisor',
  'storage',
  'compute',
  'access_point',
  'sbc',
  'ups',
  'pdu',
  'misc',
];

export default function ScanImportModal({ scanId, results = [], onClose, onImported }) {
  const toast = useToast();

  // Pre-check all rows with confidence > 0 or that already exist on the map
  const initialSelected = useMemo(() => {
    const s = new Set();
    results.forEach((r) => {
      if (r.confidence > 0 || r.exists_in_hardware) s.add(r.id);
    });
    return s;
  }, [results]);

  const [selected, setSelected] = useState(initialSelected);
  const [roleOverrides, setRoleOverrides] = useState({});
  const [importing, setImporting] = useState(false);

  const toggleRow = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  const selectAll = () => setSelected(new Set(results.map((r) => r.id)));
  const selectNewOnly = () =>
    setSelected(new Set(results.filter((r) => r.is_new).map((r) => r.id)));

  const selectedCount = [...selected].filter((id) => {
    const r = results.find((r) => r.id === id);
    return r && !r._conflict;
  }).length;

  const handleImport = async () => {
    const items = results
      .filter((r) => selected.has(r.id) && !r._conflict)
      .map((r) => ({
        scan_result_id: r.id,
        overrides: roleOverrides[r.id] ? { role: roleOverrides[r.id] } : {},
      }));

    if (items.length === 0) {
      onClose();
      return;
    }

    setImporting(true);
    try {
      const { data: resp } = await discoveryApi.batchImport(scanId, items);
      const parts = [
        resp.created.length &&
          `${resp.created.length} device${resp.created.length !== 1 ? 's' : ''} added`,
        resp.updated.length && `${resp.updated.length} updated`,
      ].filter(Boolean);
      toast.success(parts.join('. ') || 'Import complete');
      onImported(resp);
    } catch (err) {
      toast.error(err.message || 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-container scan-import-modal">
        <div className="modal-header">
          <h2>Import Discovered Devices</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="scan-import-actions">
          <button onClick={selectAll} className="btn-text">
            Select all
          </button>
          <button onClick={selectNewOnly} className="btn-text">
            New only
          </button>
          <span className="scan-import-count">{selectedCount} selected</span>
        </div>

        <div className="scan-import-table-wrapper">
          <table className="scan-import-table">
            <thead>
              <tr>
                <th />
                <th>IP</th>
                <th>Hostname</th>
                <th>Vendor</th>
                <th>Role</th>
                <th>Status</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id} className={r._conflict ? 'row-conflict' : ''}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(r.id)}
                      disabled={!!r._conflict}
                      onChange={() => toggleRow(r.id)}
                    />
                  </td>
                  <td>{r.ip_address || '—'}</td>
                  <td>{r.hostname || '—'}</td>
                  <td>{r.inferred_vendor || '—'}</td>
                  <td>
                    <select
                      value={roleOverrides[r.id] || r.inferred_role || ''}
                      onChange={(e) =>
                        setRoleOverrides((prev) => ({ ...prev, [r.id]: e.target.value }))
                      }
                    >
                      <option value="">— auto —</option>
                      {ROLE_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <span
                      className={`badge ${r.exists_in_hardware ? 'badge-exists' : 'badge-new'}`}
                    >
                      {r.exists_in_hardware ? 'EXISTS' : 'NEW'}
                    </span>
                  </td>
                  <td title={`Signals: ${r.signals_used?.join(', ') || 'none'}`}>
                    {CONFIDENCE_DOTS(r.confidence)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="btn-secondary" disabled={importing}>
            Skip all
          </button>
          <button
            onClick={handleImport}
            className="btn-primary"
            disabled={importing || selectedCount === 0}
          >
            {importing ? 'Importing…' : `Import selected (${selectedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}
