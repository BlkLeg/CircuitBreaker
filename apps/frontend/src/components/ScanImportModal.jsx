/**
 * ScanImportModal — batch confirm dialog for importing discovered devices.
 *
 * Props:
 *   scanId (number)     — the ScanJob id to import from
 *   results (array)     — pre-fetched InferredScanResultOut array
 *   onClose ()          — called when user dismisses without importing
 *   onImported (resp)   — called after successful import
 */
import React, { useState, useMemo, useCallback } from 'react';
import { discoveryApi } from '../api/client';
import { useToast } from './common/Toast';
import LLDPReviewModal from './LLDPReviewModal';

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
  const [importedIds, setImportedIds] = useState(null);   // set on success → shows LLDP button
  const [lldpJobId, setLldpJobId] = useState(null);
  const [lldpEnriching, setLldpEnriching] = useState(false);

  const toggleRow = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
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
    setImporting(true);
    try {
      const items = results
        .filter((r) => selected.has(r.id) && !r._conflict)
        .map((r) => ({
          scan_result_id: r.id,
          overrides: roleOverrides[r.id] ? { role: roleOverrides[r.id] } : {},
        }));
      const resp = await discoveryApi.importAsNetwork(scanId, { items });
      const allIds = [
        ...(resp.data.created || []),
        ...(resp.data.updated || []),
      ].map((n) => n.id).filter(Boolean);
      setImportedIds(allIds);
      onImported?.();
    } catch (err) {
      toast.error('Import failed: ' + err.message);
    } finally {
      setImporting(false);
    }
  };

  const handleLLDPEnrich = useCallback(async () => {
    if (!importedIds?.length) return;
    setLldpEnriching(true);
    try {
      const res = await discoveryApi.lldpEnrich({ hardware_ids: importedIds });
      const jobId = res.data.job_id;
      const poll = setInterval(async () => {
        try {
          const jobRes = await discoveryApi.getJob(jobId);
          if (jobRes.data.status === 'completed' || jobRes.data.status === 'failed') {
            clearInterval(poll);
            setLldpEnriching(false);
            if (jobRes.data.status === 'completed') setLldpJobId(jobId);
            else toast.error('LLDP scan failed');
          }
        } catch { clearInterval(poll); setLldpEnriching(false); }
      }, 2000);
    } catch (err) {
      toast.error('LLDP enrichment failed: ' + err.message);
      setLldpEnriching(false);
    }
  }, [importedIds, toast]);

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
                      value={roleOverrides[r.id] || r.existing_role || r.inferred_role || ''}
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
          {importedIds ? (
            <>
              <span style={{ marginRight: 'auto', fontSize: 13, color: 'var(--text-muted, #aaa)' }}>
                Import complete — {importedIds.length} device{importedIds.length !== 1 ? 's' : ''}
              </span>
              <button
                onClick={handleLLDPEnrich}
                disabled={lldpEnriching}
                className="btn-secondary"
              >
                {lldpEnriching ? 'Running LLDP…' : 'Enrich with LLDP'}
              </button>
              <button onClick={onClose} className="btn-primary">
                Close
              </button>
            </>
          ) : (
            <>
              <button onClick={onClose} className="btn-secondary" disabled={importing}>
                Skip all
              </button>
              <button
                onClick={handleImport}
                className="btn-primary"
                disabled={importing || selectedCount === 0}
              >
                {importing ? 'Importing…' : 'Import as Network'}
              </button>
            </>
          )}
        </div>
      </div>

      {lldpJobId && (
        <LLDPReviewModal
          jobId={lldpJobId}
          onApply={() => setLldpJobId(null)}
          onClose={() => setLldpJobId(null)}
        />
      )}
    </div>
  );
}
