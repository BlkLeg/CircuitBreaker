import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { ShieldCheck, ShieldAlert } from 'lucide-react';
import { REPAIR_AUTHORIZATION, repairChain, verifyChain } from '../../api/audit';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import { useToast } from '../common/Toast';

/**
 * Hash-chain integrity for the audit log (INC-12).
 *
 * Intact is deliberately one quiet line: an operator should be able to glance
 * past it. Broken is escalated, because a break means entries were altered or
 * removed after being written, and the panel is the only place that says so.
 *
 * Repair is guarded by the server's own contract — the exact REPAIR_AUDIT_CHAIN
 * authorization string and a reason of at least 12 characters — rather than by
 * a confirmation invented here.
 */
function AuditChainPanel({ onRepaired = undefined }) {
  const toast = useToast();
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairError, setRepairError] = useState(null);

  const verify = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await verifyChain();
      setResult(res.data);
    } catch (err) {
      setError(err?.userMessage || 'Could not verify the audit chain.');
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    verify();
  }, [verify]);

  const handleRepair = useCallback(
    async ({ reason }) => {
      setRepairing(true);
      setRepairError(null);
      try {
        await repairChain({ reason });
        setConfirmOpen(false);
        toast.success('Chain repaired. A repair record was appended to the audit log.');
        await verify();
        if (onRepaired) onRepaired();
      } catch (err) {
        setRepairError(err?.userMessage || 'Repair failed.');
      } finally {
        setRepairing(false);
      }
    },
    [toast, verify, onRepaired]
  );

  if (loading) return null;

  if (error) {
    return (
      <div role="alert" className="audit-chain-panel audit-chain-panel--error">
        <span>{error}</span>
        <button type="button" className="btn btn-sm" onClick={verify}>
          Retry
        </button>
      </div>
    );
  }

  if (!result) return null;

  if (result.valid) {
    return (
      <div className="audit-chain-panel audit-chain-panel--ok">
        <ShieldCheck size={14} />
        <span>chain intact</span>
        <span className="audit-chain-panel__detail">
          {result.checked_count.toLocaleString()} entries verified
        </span>
        <button type="button" className="btn btn-sm" onClick={verify}>
          Re-verify
        </button>
      </div>
    );
  }

  return (
    <div className="audit-chain-panel audit-chain-panel--bad">
      <div className="audit-chain-panel__row">
        <ShieldAlert size={14} />
        <span>chain broken</span>
        <span className="audit-chain-panel__detail">
          Verification failed at entry #{result.first_failure_id} ·{' '}
          {result.checked_count.toLocaleString()} checked
        </span>
        <button type="button" className="btn btn-sm" onClick={verify}>
          Re-verify
        </button>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          onClick={() => {
            setRepairError(null);
            setConfirmOpen(true);
          }}
        >
          Repair chain…
        </button>
      </div>
      <p className="audit-chain-panel__note">
        A break means entries were altered or removed after being written. Repair relinks the chain
        and appends a repair record; it does not recover the original entries.
      </p>

      <HighRiskConfirmDialog
        open={confirmOpen}
        title="Repair the audit hash chain"
        body={
          <>
            <p>
              This rewrites the hash links from entry #{result.first_failure_id} onward so the chain
              verifies again, and appends a repair record naming you and your reason.
            </p>
            <p>
              It does <strong>not</strong> recover altered or deleted entries. If you have not yet
              established why the chain broke, investigate before repairing — repairing first
              removes the signal.
            </p>
          </>
        }
        confirmPhrase={REPAIR_AUTHORIZATION}
        confirmLabel="Confirm"
        reason={{ required: true, minLength: 12, label: 'Reason' }}
        busy={repairing}
        error={repairError}
        onConfirm={handleRepair}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

AuditChainPanel.propTypes = {
  onRepaired: PropTypes.func,
};

export default AuditChainPanel;
