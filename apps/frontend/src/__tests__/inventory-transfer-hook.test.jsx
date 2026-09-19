import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { TRANSFER_STEPS, useInventoryTransfer } from '../hooks/useInventoryTransfer';

vi.mock('../api/inventoryTransfer', () => ({
  getTransferSummary: vi.fn(),
  exportPortableInventory: vi.fn(),
  previewTransfer: vi.fn(),
  applyTransfer: vi.fn(),
  getTransferResult: vi.fn(),
}));

import { applyTransfer, previewTransfer } from '../api/inventoryTransfer';

const DOCUMENT = {
  format: 'circuitbreaker.inventory',
  version: 1,
  manifest: { included: [], excluded: [] },
  entities: { hardware: [{ id: 1, name: 'pve-01' }] },
  relationships: {},
};

const CLEAN_PREVIEW = {
  plan_id: 'plan-1',
  plan_digest: 'a'.repeat(64),
  can_apply: true,
  conflicts: [],
  creates: { hardware: 1 },
  matches: {},
  relationships: {},
  warnings: ['This merge creates new local IDs.'],
};

const apiError = (statusCode, errorCode, message) =>
  Object.assign(new Error(message), { statusCode, errorCode });

function jsonFile(payload, overrides = {}) {
  return {
    name: 'lab.json',
    size: 1024,
    text: async () => JSON.stringify(payload),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useInventoryTransfer', () => {
  it('rejects oversized files before any request leaves the page', async () => {
    const { result } = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await result.current.selectFile(jsonFile(DOCUMENT, { size: 6 * 1024 * 1024 }));
    });
    expect(result.current.error.message).toMatch(/5 MiB/);
    expect(previewTransfer).not.toHaveBeenCalled();
    expect(result.current.step).toBe(TRANSFER_STEPS.validate);
  });

  it('rejects invalid JSON with a safe message and no request', async () => {
    const { result } = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await result.current.selectFile({ name: 'x.json', size: 10, text: async () => '{oops' });
    });
    expect(result.current.error.message).toMatch(/valid JSON/);
    expect(previewTransfer).not.toHaveBeenCalled();
  });

  it('lands on review when the file applies cleanly, and on resolve when decisions are needed', async () => {
    previewTransfer.mockResolvedValueOnce({
      data: { ...CLEAN_PREVIEW, can_apply: true, conflicts: [] },
    });
    const clean = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await clean.result.current.selectFile(jsonFile(DOCUMENT));
    });
    expect(clean.result.current.step).toBe(TRANSFER_STEPS.review);

    previewTransfer.mockResolvedValueOnce({
      data: {
        ...CLEAN_PREVIEW,
        can_apply: false,
        conflicts: [
          {
            entity_type: 'services',
            source_id: 7,
            reason_code: 'unique_identity_conflict',
            message: 'A local services record uses the same slug.',
            field: 'slug',
          },
        ],
      },
    });
    const conflicted = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await conflicted.result.current.selectFile(jsonFile(DOCUMENT));
    });
    expect(conflicted.result.current.step).toBe(TRANSFER_STEPS.resolve);
    expect(conflicted.result.current.documentEntities).toBe(1);
  });

  it('commits a decision only when the preview accepts it', async () => {
    previewTransfer.mockResolvedValueOnce({
      data: { ...CLEAN_PREVIEW, can_apply: false, conflicts: [] },
    });
    const { result } = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await result.current.selectFile(jsonFile(DOCUMENT));
    });

    const conflict = {
      entity_type: 'services',
      source_id: 7,
      field: 'slug',
      reason_code: 'unique_identity_conflict',
    };
    previewTransfer.mockRejectedValueOnce(
      apiError(400, 'validation_error', 'The proposed slug is already used.')
    );
    await act(async () => {
      await result.current.saveDecision(conflict, { action: 'rename', newValue: 'taken' });
    });
    expect(result.current.error.message).toMatch(/already used/);
    expect(Object.keys(result.current.decisions)).toHaveLength(0);

    previewTransfer.mockResolvedValueOnce({ data: CLEAN_PREVIEW });
    await act(async () => {
      await result.current.saveDecision(conflict, { action: 'rename', newValue: 'grafana-lab' });
    });
    expect(result.current.decisions['services:7:slug'].newValue).toBe('grafana-lab');
    expect(result.current.resolvedCount).toBe(1);
    expect(previewTransfer).toHaveBeenLastCalledWith(DOCUMENT, [
      { entity_type: 'services', source_id: 7, action: 'rename', new_value: 'grafana-lab' },
    ]);
  });

  it('applies with a digest-bound idempotency key, and replays the same key on retry', async () => {
    previewTransfer.mockResolvedValue({ data: CLEAN_PREVIEW });
    applyTransfer.mockResolvedValueOnce({
      data: {
        operation_id: 'op-1',
        state: 'completed',
        created: { hardware: 1 },
        matched: {},
        relationships_created: {},
        warnings: [],
      },
    });
    const { result } = renderHook(() => useInventoryTransfer({ onApplied: vi.fn() }));
    await act(async () => {
      await result.current.selectFile(jsonFile(DOCUMENT));
    });
    await act(async () => {
      await result.current.apply();
    });
    expect(result.current.step).toBe(TRANSFER_STEPS.result);
    expect(result.current.result.operation_id).toBe('op-1');
    const firstKey = applyTransfer.mock.calls[0][2];

    // A retry of the same confirmation reuses the key; a new digest mints one.
    await act(async () => {
      await result.current.apply();
    });
    expect(applyTransfer.mock.calls[1][2]).toBe(firstKey);

    previewTransfer.mockResolvedValue({ data: { ...CLEAN_PREVIEW, plan_digest: 'b'.repeat(64) } });
    await act(async () => {
      await result.current.revalidate();
    });
    await act(async () => {
      await result.current.apply();
    });
    expect(applyTransfer.mock.calls[2][2]).not.toBe(firstKey);
  });

  it('flags stale preview outcomes so the UI can offer a re-review path', async () => {
    previewTransfer.mockResolvedValue({ data: CLEAN_PREVIEW });
    applyTransfer.mockRejectedValueOnce(
      apiError(409, 'preview_stale', 'Inventory changed after this preview.')
    );
    const { result } = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await result.current.selectFile(jsonFile(DOCUMENT));
    });
    await act(async () => {
      await result.current.apply();
    });
    expect(result.current.error.stale).toBe(true);
    expect(result.current.step).toBe(TRANSFER_STEPS.review);
    expect(result.current.result).toBeNull();
  });

  it('resets to a fresh validate step for the next transfer', async () => {
    previewTransfer.mockResolvedValue({ data: CLEAN_PREVIEW });
    applyTransfer.mockResolvedValueOnce({
      data: {
        operation_id: 'op-2',
        state: 'completed',
        created: { hardware: 1 },
        matched: {},
        relationships_created: {},
        warnings: [],
      },
    });
    const { result } = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await result.current.selectFile(jsonFile(DOCUMENT));
    });
    await act(async () => {
      await result.current.apply();
    });
    act(() => {
      result.current.reset();
    });
    expect(result.current.step).toBe(TRANSFER_STEPS.validate);
    expect(result.current.document).toBeNull();
    expect(result.current.result).toBeNull();
  });

  it('keeps the operator on resolve after a decision, waiting for their review click', async () => {
    previewTransfer.mockResolvedValue({ data: CLEAN_PREVIEW });
    const { result } = renderHook(() => useInventoryTransfer());
    await act(async () => {
      await result.current.selectFile(jsonFile(DOCUMENT));
    });
    act(() => {
      result.current.backToResolve();
    });
    const conflict = {
      entity_type: 'services',
      source_id: 7,
      reason_code: 'missing_reference',
      field: 'hardware_id',
    };
    await act(async () => {
      await result.current.saveDecision(conflict, {
        action: 'reassign',
        field: 'hardware_id',
        targetId: 1,
      });
    });
    // Still on resolve; goReview moves only when the plan applies.
    expect(result.current.step).toBe(TRANSFER_STEPS.resolve);
    act(() => {
      result.current.goReview();
    });
    expect(result.current.step).toBe(TRANSFER_STEPS.review);
  });
});
