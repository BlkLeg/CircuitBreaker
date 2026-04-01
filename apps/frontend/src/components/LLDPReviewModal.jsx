/**
 * LLDPReviewModal — review proposed LLDP connections before committing to the map.
 *
 * Props:
 *   jobId (number)     — completed LLDP scan job ID
 *   onApply ()         — called after successful apply (triggers map refresh)
 *   onClose ()         — called to dismiss
 */
import React, { useState, useEffect } from 'react';
import { discoveryApi } from '../api/client';
import { useToast } from './common/Toast';

export default function LLDPReviewModal({ jobId, onApply, onClose }) {
  const [neighbors, setNeighbors] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const toast = useToast();

  useEffect(() => {
    discoveryApi.lldpJobResults(jobId)
      .then((res) => {
        const items = res.data.neighbors;
        setNeighbors(items);
        setSelected(new Set(items.map((_, i) => i)));
      })
      .catch((err) => {
        toast.error('Failed to load LLDP results: ' + (err.response?.data?.detail || err.message));
        onClose();
      })
      .finally(() => setLoading(false));
  }, [jobId, onClose, toast]);

  const toggle = (idx) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) { next.delete(idx); } else { next.add(idx); }
      return next;
    });
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      const connections = Array.from(selected).map((idx) => {
        // eslint-disable-next-line security/detect-object-injection
        const neighbor = neighbors[idx];
        return {
          source_scan_result_id: neighbor.source_scan_result_id,
          neighbor_index: neighbor.neighbor_index,
        };
      });
      const res = await discoveryApi.lldpApply(jobId, { connections });
      const { edges_created, stubs_created } = res.data;
      toast.success(`Applied: ${edges_created} connection${edges_created !== 1 ? 's' : ''}${stubs_created ? `, ${stubs_created} new stub${stubs_created !== 1 ? 's' : ''}` : ''} added`);
      onApply?.();
      onClose();
    } catch (err) {
      toast.error('Apply failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setApplying(false);
    }
  };

  const stubCount = neighbors.filter((n) => n.is_new_stub).length;

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-container" style={{ maxWidth: 620, width: '90%' }}>
        <div className="modal-header">
          <div>
            <h3 style={{ margin: 0 }}>LLDP Topology Results</h3>
            {!loading && (
              <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted, #aaa)' }}>
                {neighbors.length} connection{neighbors.length !== 1 ? 's' : ''} proposed
                {stubCount > 0 && ` · ${stubCount} new device${stubCount !== 1 ? 's' : ''} discovered`}
              </p>
            )}
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div style={{ maxHeight: 360, overflowY: 'auto', padding: '4px 0' }}>
          {loading && (
            <p style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted, #aaa)' }}>
              Loading LLDP results…
            </p>
          )}

          {!loading && neighbors.length === 0 && (
            <p style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted, #aaa)' }}>
              No LLDP neighbors found on selected devices.
            </p>
          )}

          {!loading && neighbors.map((n, idx) => (
            <label
              key={idx}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 20px', cursor: 'pointer', fontSize: 13,
                borderBottom: '1px solid var(--border, #222)',
              }}
            >
              <input
                type="checkbox"
                checked={selected.has(idx)}
                onChange={() => toggle(idx)}
                style={{ flexShrink: 0 }}
              />
              <span style={{ fontWeight: 500, minWidth: 120 }}>{n.source_hardware_name}</span>
              <span style={{ color: 'var(--text-muted, #888)', fontSize: 12, minWidth: 140 }}>
                {n.local_port_desc || '?'} ↔ {n.remote_port_desc || '?'}
              </span>
              <span style={{ flex: 1, color: n.is_new_stub ? '#f39c12' : 'inherit' }}>
                {n.remote_hardware_name || n.remote_sys_name || n.remote_chassis_id || 'Unknown'}
              </span>
              <span style={{
                fontSize: 11, padding: '2px 7px', borderRadius: 3, flexShrink: 0,
                background: n.is_new_stub ? '#f39c12' : '#2ecc71',
                color: '#000',
              }}>
                {n.is_new_stub ? 'new stub' : 'exists'}
              </span>
            </label>
          ))}
        </div>

        <div style={{
          padding: '12px 20px', display: 'flex', justifyContent: 'flex-end',
          alignItems: 'center', gap: 10, borderTop: '1px solid var(--border, #333)',
        }}>
          {!loading && neighbors.length > 0 && (
            <span style={{ marginRight: 'auto', fontSize: 12, color: 'var(--text-muted, #aaa)' }}>
              {selected.size} of {neighbors.length} selected
            </span>
          )}
          <button onClick={onClose} disabled={applying} className="btn-secondary">
            Cancel
          </button>
          {!loading && neighbors.length > 0 && (
            <button
              onClick={handleApply}
              disabled={applying || selected.size === 0}
              className="btn-primary"
            >
              {applying ? 'Applying…' : `Apply Selected (${selected.size})`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
