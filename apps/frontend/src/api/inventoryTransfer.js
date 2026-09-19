import client from './client.jsx';

// Plan 02: portable inventory transfer. Every route is require_role("admin"),
// and apply is idempotent through the Idempotency-Key header.

export const getTransferSummary = () => client.get('/inventory-transfer/summary');

export const exportPortableInventory = () => client.get('/inventory-transfer/export');

export const previewTransfer = (document, resolutions = []) =>
  client.post('/inventory-transfer/preview', { document, resolutions });

export const applyTransfer = (planId, planDigest, idempotencyKey) =>
  client.post(
    `/inventory-transfer/plans/${planId}/apply`,
    { plan_digest: planDigest },
    { headers: { 'Idempotency-Key': idempotencyKey } }
  );

export const getTransferResult = (operationId) =>
  client.get(`/inventory-transfer/operations/${operationId}`);
