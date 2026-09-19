import PropTypes from 'prop-types';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import LLDPReviewModal from '../../../components/LLDPReviewModal';
import IconPickerModal from '../../../components/common/IconPickerModal';
import ConfirmDialog from '../../../components/common/ConfirmDialog';
import FormModal from '../../../components/common/FormModal';
import BulkQuickCreateModal from './BulkQuickCreateModal';
import CreateNodeModal from './CreateNodeModal';
import DeleteConflictModal from './DeleteConflictModal';
import { STATUS_OPTION_LABEL } from '../model/mapConstants';

/**
 * Every modal the map opens: create node, LLDP review, icon picker, the
 * quick-action form, bulk quick-create, the role form, delete-conflict, and
 * the shared confirm dialog.
 *
 * Takes the two owner objects rather than the ~37 individual values this
 * markup reads. All of the state is transient editor UI, which is why it lives
 * on `editorUi`; the submit handlers are entity commands.
 */
export default function MapDialogs({ editorUi, commands, hardwareRoles }) {
  const {
    createNodeModal,
    setCreateNodeModal,
    iconPickerOpen,
    setIconPickerOpen,
    iconPickerNode,
    setIconPickerNode,
    quickActionModal,
    setQuickActionModal,
    quickActionValue,
    setQuickActionValue,
    quickActionSaving,
    quickCreateModal,
    setQuickCreateModal,
    quickCreateRows,
    setQuickCreateRows,
    quickCreateRowErrors,
    setQuickCreateRowErrors,
    quickCreateSaving,
    roleModal,
    setRoleModal,
    confirmState,
    setConfirmState,
    lldpJobId,
    setLldpJobId,
    deleteConflictModal,
    setDeleteConflictModal,
  } = editorUi;
  const {
    handleCreateNode,
    handleIconPick,
    handleSubmitQuickAction,
    handleSubmitRoleModal,
    handleBulkQuickCreateSubmit,
    forceRemoveDeleteConflicts,
    addQuickCreateRow,
    removeQuickCreateRow,
    updateQuickCreateRow,
    fetchData,
  } = commands;
  const HARDWARE_ROLES = hardwareRoles;

  return (
    <>
      {/* Create Node Modal */}
      <CreateNodeModal
        isOpen={createNodeModal.isOpen}
        position={createNodeModal.position}
        onClose={() => setCreateNodeModal({ isOpen: false, position: null })}
        onConfirm={handleCreateNode}
      />

      {lldpJobId && (
        <LLDPReviewModal
          jobId={lldpJobId}
          onApply={() => {
            setLldpJobId(null);
            fetchData();
          }}
          onClose={() => setLldpJobId(null)}
        />
      )}

      {iconPickerOpen && iconPickerNode && (
        <IconPickerModal
          currentSlug={iconPickerNode.data?.icon_slug ?? null}
          onSelect={handleIconPick}
          onClose={() => {
            setIconPickerOpen(false);
            setIconPickerNode(null);
          }}
        />
      )}

      {quickActionModal &&
        globalThis.document?.body &&
        createPortal(
          <div
            className="modal-overlay"
            style={{
              position: 'fixed',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 9999,
            }}
          >
            <dialog
              open
              className="modal"
              aria-labelledby="quick-action-title"
              style={{ width: 420, margin: 0 }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                }}
              >
                <h3 id="quick-action-title">
                  {quickActionModal.mode === 'alias' ? 'Set Alias' : 'Update Status'}
                </h3>
                <button
                  type="button"
                  className="btn"
                  aria-label="Close quick action dialog"
                  onClick={() => {
                    setQuickActionModal(null);
                    setQuickActionValue('');
                  }}
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
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSubmitQuickAction();
                }}
              >
                <div style={{ marginTop: 12 }}>
                  <div
                    style={{
                      marginBottom: 8,
                      fontSize: 12,
                      color: 'var(--color-text-muted)',
                    }}
                  >
                    {quickActionModal.label}
                  </div>
                  {quickActionModal.mode === 'alias' ? (
                    <input
                      className="input"
                      aria-label="Alias value"
                      style={{
                        width: '100%',
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 'var(--radius)',
                        padding: '6px 10px',
                      }}
                      autoFocus
                      value={quickActionValue}
                      onChange={(e) => setQuickActionValue(e.target.value)}
                      placeholder="Enter alias"
                    />
                  ) : (
                    <select
                      className="filter-select"
                      aria-label="Status value"
                      autoFocus
                      value={quickActionValue}
                      onChange={(e) => setQuickActionValue(e.target.value)}
                      style={{
                        width: '100%',
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 'var(--radius)',
                        padding: '6px 10px',
                      }}
                    >
                      {(quickActionModal.allowed || []).map((value) => (
                        <option key={value} value={value}>
                          {STATUS_OPTION_LABEL.get(value) || value}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: 8,
                    marginTop: 18,
                  }}
                >
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setQuickActionModal(null);
                      setQuickActionValue('');
                    }}
                    disabled={quickActionSaving}
                  >
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={quickActionSaving}>
                    {quickActionSaving ? 'Saving…' : 'Save'}
                  </button>
                </div>
              </form>
            </dialog>
          </div>,
          globalThis.document.body
        )}

      <BulkQuickCreateModal
        open={quickCreateModal.open}
        modal={quickCreateModal}
        rows={quickCreateRows}
        rowErrors={quickCreateRowErrors}
        saving={quickCreateSaving}
        onSubmit={handleBulkQuickCreateSubmit}
        onUpdateRow={updateQuickCreateRow}
        onAddRow={addQuickCreateRow}
        onRemoveRow={removeQuickCreateRow}
        onClose={() => {
          setQuickCreateModal({
            open: false,
            mode: null,
            title: '',
            sourceLabel: '',
            initialValues: {},
          });
          setQuickCreateRows([]);
          setQuickCreateRowErrors({});
        }}
      />

      <FormModal
        open={roleModal.open}
        title={roleModal.isEdit ? 'Edit Role' : 'Designate Role'}
        fields={[
          {
            name: 'role',
            label: `Role for ${roleModal.nodeLabel}`,
            type: 'select',
            required: true,
            options: HARDWARE_ROLES,
          },
        ]}
        initialValues={{ role: roleModal.currentRole || '' }}
        onSubmit={handleSubmitRoleModal}
        onValidate={(values) => {
          const errors = {};
          if (!values.role) errors.role = 'Role is required.';
          return errors;
        }}
        onClose={() =>
          setRoleModal({
            open: false,
            nodeRefId: null,
            nodeLabel: '',
            currentRole: '',
            isEdit: false,
          })
        }
        entityType="hardware"
        entityId={roleModal.nodeRefId}
      />

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm || (() => {})}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />

      <DeleteConflictModal
        modal={deleteConflictModal}
        onCancel={() => setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }))}
        onForceRemove={forceRemoveDeleteConflicts}
      />
    </>
  );
}

MapDialogs.propTypes = {
  editorUi: PropTypes.object.isRequired,
  commands: PropTypes.object.isRequired,
  hardwareRoles: PropTypes.array.isRequired,
};
