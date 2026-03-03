import React, { useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import IconPickerModal, { IconImg } from '../common/IconPickerModal';

function BulkQuickCreateModal({
  open,
  modal,
  rows,
  rowErrors,
  saving,
  onSubmit,
  onUpdateRow,
  onAddRow,
  onRemoveRow,
  onClose,
}) {
  const [iconPickerRowId, setIconPickerRowId] = useState(null);
  const [dragPosition, setDragPosition] = useState(null);
  const dragStateRef = useRef(null);

  const iconPickerRow = useMemo(
    () => rows.find((row) => row.id === iconPickerRowId) || null,
    [iconPickerRowId, rows],
  );

  useEffect(() => {
    if (open) {
      setDragPosition(null);
    }

    return () => {
      if (dragStateRef.current?.move) {
        globalThis.removeEventListener('pointermove', dragStateRef.current.move);
      }
      if (dragStateRef.current?.up) {
        globalThis.removeEventListener('pointerup', dragStateRef.current.up);
      }
      dragStateRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  const itemLabel = rows.length === 1 ? 'Item' : 'Items';
  const createButtonLabel = saving
    ? 'Creating…'
    : `Create ${rows.length} ${itemLabel}`;

  const modalHeadingId = 'bulk-quick-create-title';
  const modalDescId = 'bulk-quick-create-desc';

  const fieldStyle = {
    width: '100%',
    background: 'var(--color-surface)',
    color: 'var(--color-text)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius)',
    padding: '6px 10px',
  };

  const portalTarget = globalThis.document?.body;

  const handleDragStart = (event) => {
    if (event.button !== 0) return;

    const modalEl = event.currentTarget.closest('.bulk-quick-create-modal');
    if (!modalEl) return;

    const rect = modalEl.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const offsetY = event.clientY - rect.top;

    const onMove = (moveEvent) => {
      const width = rect.width;
      const height = rect.height;
      const maxX = Math.max(8, window.innerWidth - width - 8);
      const maxY = Math.max(8, window.innerHeight - height - 8);
      const nextX = Math.min(maxX, Math.max(8, moveEvent.clientX - offsetX));
      const nextY = Math.min(maxY, Math.max(8, moveEvent.clientY - offsetY));
      setDragPosition({ x: nextX, y: nextY });
    };

    const onUp = () => {
      globalThis.removeEventListener('pointermove', onMove);
      globalThis.removeEventListener('pointerup', onUp);
      dragStateRef.current = null;
    };

    dragStateRef.current = { move: onMove, up: onUp };
    globalThis.addEventListener('pointermove', onMove);
    globalThis.addEventListener('pointerup', onUp);
  };

  const modalPositionStyle = dragPosition
    ? {
      position: 'fixed',
      left: dragPosition.x,
      top: dragPosition.y,
      transform: 'none',
    }
    : {
      position: 'fixed',
      left: '50%',
      top: '50%',
      transform: 'translate(-50%, -50%)',
    };

  const modalContent = (
    <div className="modal-overlay" style={{ padding: 16, zIndex: 1200 }}>
      <dialog
        open
        className="modal bulk-quick-create-modal"
        aria-labelledby={modalHeadingId}
        aria-describedby={modalDescId}
        style={{ width: 860, maxWidth: '95vw', margin: 0, ...modalPositionStyle }}
      >
        <div
          onPointerDown={handleDragStart}
          style={{
            margin: '-24px -24px 10px',
            padding: '8px 12px',
            borderBottom: '1px solid var(--color-border)',
            background: 'var(--color-surface-secondary)',
            cursor: 'grab',
            userSelect: 'none',
            color: 'var(--color-text-muted)',
            fontSize: 11,
            letterSpacing: '0.03em',
          }}
        >
          Drag to move
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div>
            <h3 id={modalHeadingId}>{modal.title}</h3>
            <p id={modalDescId} style={{ marginTop: 6, fontSize: 12, color: 'var(--color-text-muted)' }}>
              Add multiple {modal.mode}s for <strong>{modal.sourceLabel}</strong> in one submit.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn"
            aria-label="Close bulk add dialog"
            style={{
              width: 28,
              height: 28,
              padding: 0,
              borderRadius: 999,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <X size={14} />
          </button>
        </div>

        <form onSubmit={onSubmit}>
          <div style={{ marginTop: 12, maxHeight: '50vh', overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--color-surface-secondary)' }}>
                  <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Name</th>
                  <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Icon</th>
                  {modal.mode === 'service' && (
                    <>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Port</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Protocol</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>IP</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Status</th>
                    </>
                  )}
                  {modal.mode === 'compute' && (
                    <>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Kind</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>IP</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>OS</th>
                    </>
                  )}
                  {modal.mode === 'storage' && (
                    <>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Kind</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Capacity (GB)</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Path</th>
                      <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Protocol</th>
                    </>
                  )}
                  <th style={{ width: 90, textAlign: 'center', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                      <input
                        className="input"
                        style={fieldStyle}
                        aria-label={`Name for ${modal.mode} row`}
                        value={row.name}
                        onChange={(e) => onUpdateRow(row.id, 'name', e.target.value)}
                        placeholder="Name"
                      />
                      {rowErrors[row.id] && (
                        <div style={{ marginTop: 4, color: 'var(--color-danger)', fontSize: 11 }}>
                          {rowErrors[row.id]}
                        </div>
                      )}
                    </td>

                    <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                      <button
                        type="button"
                        className="btn"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 130 }}
                        onClick={() => setIconPickerRowId(row.id)}
                        disabled={saving}
                      >
                        {row.icon_slug ? <IconImg slug={row.icon_slug} size={16} /> : <span>🖼️</span>}
                        <span>{row.icon_slug ? 'Change' : 'Pick icon'}</span>
                      </button>
                    </td>

                    {modal.mode === 'service' && (
                      <>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Service port"
                            value={row.port}
                            onChange={(e) => onUpdateRow(row.id, 'port', e.target.value)}
                            placeholder="32400"
                          />
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <select
                            className="filter-select"
                            style={fieldStyle}
                            aria-label="Service protocol"
                            value={row.protocol}
                            onChange={(e) => onUpdateRow(row.id, 'protocol', e.target.value)}
                          >
                            <option value="tcp">tcp</option>
                            <option value="udp">udp</option>
                          </select>
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Service IP address"
                            value={row.ip_address}
                            onChange={(e) => onUpdateRow(row.id, 'ip_address', e.target.value)}
                            placeholder="optional"
                          />
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <select
                            className="filter-select"
                            style={fieldStyle}
                            aria-label="Service status"
                            value={row.status}
                            onChange={(e) => onUpdateRow(row.id, 'status', e.target.value)}
                          >
                            <option value="running">running</option>
                            <option value="stopped">stopped</option>
                            <option value="degraded">degraded</option>
                            <option value="maintenance">maintenance</option>
                          </select>
                        </td>
                      </>
                    )}

                    {modal.mode === 'compute' && (
                      <>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <select
                            className="filter-select"
                            style={fieldStyle}
                            aria-label="Compute kind"
                            value={row.kind}
                            onChange={(e) => onUpdateRow(row.id, 'kind', e.target.value)}
                          >
                            <option value="vm">vm</option>
                            <option value="container">container</option>
                          </select>
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Compute IP address"
                            value={row.ip_address}
                            onChange={(e) => onUpdateRow(row.id, 'ip_address', e.target.value)}
                            placeholder="optional"
                          />
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Compute OS"
                            value={row.os}
                            onChange={(e) => onUpdateRow(row.id, 'os', e.target.value)}
                            placeholder="optional"
                          />
                        </td>
                      </>
                    )}

                    {modal.mode === 'storage' && (
                      <>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <select
                            className="filter-select"
                            style={fieldStyle}
                            aria-label="Storage kind"
                            value={row.kind}
                            onChange={(e) => onUpdateRow(row.id, 'kind', e.target.value)}
                          >
                            <option value="disk">disk</option>
                            <option value="pool">pool</option>
                            <option value="dataset">dataset</option>
                            <option value="share">share</option>
                          </select>
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Storage capacity in GB"
                            value={row.capacity_gb}
                            onChange={(e) => onUpdateRow(row.id, 'capacity_gb', e.target.value)}
                            placeholder="optional"
                          />
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Storage path"
                            value={row.path}
                            onChange={(e) => onUpdateRow(row.id, 'path', e.target.value)}
                            placeholder="optional"
                          />
                        </td>
                        <td style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                          <input
                            className="input"
                            style={fieldStyle}
                            aria-label="Storage protocol"
                            value={row.protocol}
                            onChange={(e) => onUpdateRow(row.id, 'protocol', e.target.value)}
                            placeholder="optional"
                          />
                        </td>
                      </>
                    )}

                    <td style={{ textAlign: 'center', padding: '8px 10px', borderBottom: '1px solid var(--color-border)' }}>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => onRemoveRow(row.id)}
                        disabled={rows.length <= 1 || saving}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 14 }}>
            <button type="button" className="btn" onClick={onAddRow} disabled={saving}>
              + Add Row
            </button>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="btn" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {createButtonLabel}
              </button>
            </div>
          </div>
        </form>
      </dialog>

      {iconPickerRow && (
        <IconPickerModal
          currentSlug={iconPickerRow.icon_slug || null}
          onSelect={(slug) => {
            onUpdateRow(iconPickerRow.id, 'icon_slug', slug || '');
          }}
          onClose={() => setIconPickerRowId(null)}
        />
      )}
    </div>
  );

  if (!portalTarget) return modalContent;
  return createPortal(modalContent, portalTarget);
}

BulkQuickCreateModal.propTypes = {
  open: PropTypes.bool.isRequired,
  modal: PropTypes.shape({
    mode: PropTypes.string,
    title: PropTypes.string,
    sourceLabel: PropTypes.string,
  }).isRequired,
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  rowErrors: PropTypes.object.isRequired,
  saving: PropTypes.bool.isRequired,
  onSubmit: PropTypes.func.isRequired,
  onUpdateRow: PropTypes.func.isRequired,
  onAddRow: PropTypes.func.isRequired,
  onRemoveRow: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default BulkQuickCreateModal;
