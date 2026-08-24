import client from './client.jsx';

/**
 * Must equal REPAIR_AUTHORIZATION in apps/backend/src/app/core/audit_chain.py:19.
 * Exported so the confirmation dialog's typed phrase and the request body read
 * from ONE constant — two spellings of the same magic string is exactly the
 * kind of drift this register catalogues.
 */
export const REPAIR_AUTHORIZATION = 'REPAIR_AUDIT_CHAIN';

// Returns {valid, first_failure_id, message, checked_count}.
export const verifyChain = () => client.get('/admin/audit-log/verify-chain');

// Returns {repaired, before, changed, after}. The server requires `reason` to
// be at least 12 characters; the dialog enforces that before we get here.
export const repairChain = ({ reason }) =>
  client.post('/admin/audit-log/repair-chain', {
    authorization: REPAIR_AUTHORIZATION,
    reason,
  });
