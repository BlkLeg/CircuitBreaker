import PropTypes from 'prop-types';
import { X } from 'lucide-react';

export default function DeleteConflictModal({ modal, onCancel, onForceRemove }) {
  if (!modal?.open) return null;

  return (
    <div className="modal-overlay">
      <dialog
        open
        className="modal"
        aria-labelledby="delete-conflict-title"
        style={{ width: 460, margin: 0 }}
      >
        <div
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
        >
          <h3 id="delete-conflict-title">Delete Conflict</h3>
          <button
            type="button"
            className="btn"
            aria-label="Close delete conflict dialog"
            onClick={onCancel}
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
        <p style={{ marginTop: 10, color: 'var(--color-text-muted)', fontSize: 13 }}>
          Could not delete <strong>{modal.nodeLabel}</strong> because related links/dependencies
          still exist.
        </p>
        {modal.reason && (
          <p style={{ marginTop: 8, color: 'var(--color-danger)', fontSize: 12 }}>{modal.reason}</p>
        )}
        {modal.blockers.length > 0 && (
          <div
            style={{
              marginTop: 12,
              maxHeight: 180,
              overflowY: 'auto',
              border: '1px solid var(--color-border)',
              borderRadius: 8,
            }}
          >
            {modal.blockers.map((b, i) => (
              <div
                key={`${b.edgeId}-${i}`}
                style={{
                  padding: '8px 10px',
                  borderBottom:
                    i < modal.blockers.length - 1 ? '1px solid var(--color-border)' : 'none',
                  fontSize: 12,
                }}
              >
                <span style={{ color: 'var(--color-text)' }}>{b.otherLabel}</span>
                <span style={{ color: 'var(--color-text-muted)' }}> · {b.relation}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button type="button" className="btn" disabled={modal.forcing} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={modal.forcing}
            onClick={onForceRemove}
          >
            {modal.forcing ? 'Removing…' : 'Force remove'}
          </button>
        </div>
      </dialog>
    </div>
  );
}

DeleteConflictModal.propTypes = {
  modal: PropTypes.shape({
    open: PropTypes.bool,
    nodeLabel: PropTypes.string,
    reason: PropTypes.string,
    forcing: PropTypes.bool,
    blockers: PropTypes.arrayOf(
      PropTypes.shape({
        edgeId: PropTypes.string,
        relation: PropTypes.string,
        otherLabel: PropTypes.string,
      })
    ),
  }).isRequired,
  onCancel: PropTypes.func.isRequired,
  onForceRemove: PropTypes.func.isRequired,
};
