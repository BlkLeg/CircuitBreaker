import React from 'react';
import PropTypes from 'prop-types';
import { Trash2, Plus } from 'lucide-react';

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
 * entityType  – unused (kept for API compatibility)
 * entityId    – unused (kept for API compatibility)
 * serviceIp   – unused (conflict detection moved to IPAddressInput)
 * onOpenEntity – unused (kept for API compatibility)
 */
function PortsEditor({ value, onChange }) {
  const rows = value && value.length > 0 ? value : [];

  const updateRow = (index, field, val) => {
    const updated = rows.map((r, i) => (i === index ? { ...r, [field]: val } : r));
    onChange(updated);
  };

  const addRow = () => {
    onChange([...rows, emptyRow()]);
  };

  const removeRow = (index) => {
    onChange(rows.filter((_, i) => i !== index));
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
                      onChange={(e) =>
                        updateRow(i, 'port', e.target.value === '' ? '' : Number(e.target.value))
                      }
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
                        <option key={p} value={p}>
                          {p}
                        </option>
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
        style={{
          marginTop: rows.length > 0 ? 6 : 0,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 12,
        }}
      >
        <Plus size={12} /> Add port
      </button>
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
