import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Trash2, Plus } from 'lucide-react';
import { ipCheckApi } from '../api/client';
import IPConflictBanner from './IPConflictBanner';

const DEBOUNCE_MS = 600;
const PROTOCOL_OPTIONS = ['tcp', 'udp', 'sctp'];

function emptyRow() {
  return { ip: '', port: '', protocol: 'tcp', label: '' };
}

/**
 * Structured port binding editor. Replaces the freeform ports text input.
 *
 * Props
 * -----
 * value       – array of { ip, port, protocol, label }
 * onChange    – called with the updated array
 * entityType  – "service" (for exclude in ip-check)
 * entityId    – numeric id of the entity being edited (undefined on create)
 * serviceIp   – the service's own ip_address (used as effective IP for blank port-level IPs)
 * onOpenEntity – called when the user clicks "Open →" on a conflict item
 */
function PortsEditor({ value, onChange, entityType, entityId, serviceIp, onOpenEntity }) {
  const [conflicts, setConflicts] = useState([]);
  const timerRef = useRef(null);

  const rows = value && value.length > 0 ? value : [];

  const triggerCheck = (updatedRows, serviceIpOverride) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const effectiveIp = serviceIpOverride !== undefined ? serviceIpOverride : serviceIp;
    if (!effectiveIp) {
      setConflicts([]);
      return;
    }
    timerRef.current = setTimeout(async () => {
      const validPorts = updatedRows
        .filter((r) => r.port !== '' && r.port !== null && r.port !== undefined)
        .map((r) => ({
          ip: r.ip || null,
          port: Number(r.port),
          protocol: r.protocol || 'tcp',
          label: r.label || null,
        }));
      if (validPorts.length === 0) {
        setConflicts([]);
        return;
      }
      try {
        const res = await ipCheckApi.check({
          ip: effectiveIp,
          ports: validPorts,
          exclude_entity_type: entityType || undefined,
          exclude_entity_id: entityId || undefined,
        });
        setConflicts(res.data.conflicts || []);
      } catch {
        setConflicts([]);
      }
    }, DEBOUNCE_MS);
  };

  // Re-check when serviceIp changes externally
  useEffect(() => {
    triggerCheck(rows, serviceIp);
    return () => clearTimeout(timerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceIp]);

  const updateRow = (index, field, val) => {
    const updated = rows.map((r, i) => (i === index ? { ...r, [field]: val } : r));
    onChange(updated);
    triggerCheck(updated);
  };

  const addRow = () => {
    const updated = [...rows, emptyRow()];
    onChange(updated);
  };

  const removeRow = (index) => {
    const updated = rows.filter((_, i) => i !== index);
    onChange(updated);
    triggerCheck(updated);
  };

  return (
    <div>
      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['IP (opt)', 'Port', 'Protocol', 'Label', ''].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: 'left',
                      padding: '4px 6px',
                      borderBottom: '1px solid var(--color-border, #374151)',
                      color: 'var(--color-text-muted, #9ca3af)',
                      fontWeight: 500,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td style={{ padding: '3px 4px' }}>
                    <input
                      type="text"
                      value={row.ip || ''}
                      onChange={(e) => updateRow(i, 'ip', e.target.value)}
                      placeholder="inherit"
                      style={{ width: 110, fontSize: 12 }}
                    />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input
                      type="number"
                      value={row.port ?? ''}
                      min={1}
                      max={65535}
                      onChange={(e) => updateRow(i, 'port', e.target.value === '' ? '' : Number(e.target.value))}
                      placeholder="e.g. 80"
                      style={{ width: 72, fontSize: 12 }}
                    />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <select
                      value={row.protocol || 'tcp'}
                      onChange={(e) => updateRow(i, 'protocol', e.target.value)}
                      style={{ fontSize: 12 }}
                    >
                      {PROTOCOL_OPTIONS.map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input
                      type="text"
                      value={row.label || ''}
                      onChange={(e) => updateRow(i, 'label', e.target.value)}
                      placeholder="e.g. Web UI"
                      style={{ width: 100, fontSize: 12 }}
                    />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: '#ef4444',
                        padding: '2px 4px',
                        display: 'flex',
                        alignItems: 'center',
                      }}
                      title="Remove row"
                    >
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button
        type="button"
        onClick={addRow}
        className="btn btn-sm"
        style={{ marginTop: rows.length > 0 ? 6 : 0, display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
      >
        <Plus size={12} /> Add port
      </button>

      <IPConflictBanner conflicts={conflicts} onOpenEntity={onOpenEntity} />
    </div>
  );
}

PortsEditor.propTypes = {
  value: PropTypes.arrayOf(
    PropTypes.shape({
      ip: PropTypes.string,
      port: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
      protocol: PropTypes.string,
      label: PropTypes.string,
    })
  ),
  onChange: PropTypes.func.isRequired,
  entityType: PropTypes.string,
  entityId: PropTypes.number,
  serviceIp: PropTypes.string,
  onOpenEntity: PropTypes.func,
};

export default PortsEditor;
