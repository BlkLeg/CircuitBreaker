import { useCallback, useRef, useState } from 'react';
import { applyTransfer, previewTransfer } from '../api/inventoryTransfer';
import {
  MAX_DOCUMENT_BYTES,
  STALE_ERROR_CODES,
  buildResolutions,
  countRecords,
  decisionKey,
} from '../lib/inventoryTransfer';

export const TRANSFER_STEPS = Object.freeze({
  validate: 'validate',
  resolve: 'resolve',
  review: 'review',
  result: 'result',
});

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `transfer-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * The import state machine (plan 02): one document in, honest previews out.
 *
 * Decisions are only committed when the preview accepts them, so a bad rename
 * or a vanished target never sticks. The apply idempotency key is bound to the
 * plan digest it was minted for: a retry or double-click replays the same
 * operation, while a re-reviewed preview mints a fresh key.
 */
export function useInventoryTransfer({ onApplied } = {}) {
  const [step, setStep] = useState(TRANSFER_STEPS.validate);
  const [fileName, setFileName] = useState(null);
  const [document, setDocument] = useState(null);
  const [preview, setPreview] = useState(null);
  const [decisions, setDecisions] = useState({});
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const idempotencyRef = useRef(null);

  const runPreview = useCallback(async (parsedDocument, nextDecisions) => {
    setBusy(true);
    setError(null);
    try {
      const res = await previewTransfer(parsedDocument, buildResolutions(nextDecisions));
      const body = res?.data ?? {};
      setPreview(body);
      return body;
    } catch (err) {
      setError({
        message: err?.message || 'The inventory file could not be validated.',
        errorCode: err?.errorCode ?? null,
      });
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const selectFile = useCallback(
    async (file) => {
      setError(null);
      if (!file) return null;
      if (file.size > MAX_DOCUMENT_BYTES) {
        setError({
          message: `The file exceeds the ${MAX_DOCUMENT_BYTES / (1024 * 1024)} MiB limit.`,
          errorCode: null,
        });
        return null;
      }
      let parsed;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        setError({ message: 'The file is not valid JSON.', errorCode: null });
        return null;
      }
      const body = await runPreview(parsed, {});
      if (body) {
        setFileName(file.name);
        setDocument(parsed);
        setDecisions({});
        setStep(body.can_apply ? TRANSFER_STEPS.review : TRANSFER_STEPS.resolve);
      }
      return body;
    },
    [runPreview]
  );

  const saveDecision = useCallback(
    async (conflict, decision) => {
      if (!document) return null;
      const key = decisionKey(conflict.entity_type, conflict.source_id, conflict.field);
      const merged = {
        ...decisions,
        [key]: {
          ...decision,
          kind: conflict.entity_type,
          sourceId: conflict.source_id,
          conflict,
        },
      };
      const body = await runPreview(document, merged);
      if (body) setDecisions(merged);
      return body;
    },
    [document, decisions, runPreview]
  );

  /** Re-preview after a stale/changed outcome so the operator re-reviews. */
  const revalidate = useCallback(async () => {
    if (!document) return null;
    const body = await runPreview(document, decisions);
    if (body) {
      setStep(body.can_apply ? TRANSFER_STEPS.review : TRANSFER_STEPS.resolve);
    }
    return body;
  }, [document, decisions, runPreview]);

  const removeFile = useCallback(() => {
    setDocument(null);
    setFileName(null);
    setPreview(null);
    setDecisions({});
    setError(null);
    setStep(TRANSFER_STEPS.validate);
  }, []);

  const goReview = useCallback(() => {
    if (preview?.can_apply) setStep(TRANSFER_STEPS.review);
  }, [preview]);

  const backToResolve = useCallback(() => {
    setStep(TRANSFER_STEPS.resolve);
  }, []);

  const apply = useCallback(async () => {
    if (!preview?.can_apply || applying) return null;
    setApplying(true);
    setError(null);
    try {
      if (idempotencyRef.current?.digest !== preview.plan_digest) {
        idempotencyRef.current = { digest: preview.plan_digest, key: newIdempotencyKey() };
      }
      const res = await applyTransfer(
        preview.plan_id,
        preview.plan_digest,
        idempotencyRef.current.key
      );
      const body = res?.data ?? {};
      setResult(body);
      setStep(TRANSFER_STEPS.result);
      onApplied?.(body);
      return body;
    } catch (err) {
      setError({
        message: err?.message || 'The transfer could not be applied.',
        errorCode: err?.errorCode ?? null,
        stale: STALE_ERROR_CODES.includes(err?.errorCode),
      });
      return null;
    } finally {
      setApplying(false);
    }
  }, [preview, applying, onApplied]);

  const reset = useCallback(() => {
    idempotencyRef.current = null;
    setStep(TRANSFER_STEPS.validate);
    setFileName(null);
    setDocument(null);
    setPreview(null);
    setDecisions({});
    setError(null);
    setResult(null);
    setBusy(false);
    setApplying(false);
  }, []);

  return {
    step,
    fileName,
    document,
    preview,
    decisions,
    busy,
    applying,
    error,
    result,
    documentEntities: countRecords(document?.entities),
    documentRelationships: countRecords(document?.relationships),
    resolvedCount: Object.keys(decisions).length,
    selectFile,
    saveDecision,
    removeFile,
    goReview,
    backToResolve,
    revalidate,
    apply,
    reset,
  };
}
