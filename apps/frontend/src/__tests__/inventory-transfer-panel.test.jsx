import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({
  useToast: () => mockToast,
  ToastProvider: ({ children }) => children,
}));

vi.mock('../api/inventoryTransfer', () => ({
  getTransferSummary: vi.fn(),
  exportPortableInventory: vi.fn(),
  previewTransfer: vi.fn(),
  applyTransfer: vi.fn(),
  getTransferResult: vi.fn(),
}));

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  adminApi: {
    export: vi.fn(),
    recentChanges: vi.fn(),
    clearLab: vi.fn(),
    listSnapshots: vi.fn(),
    triggerSnapshot: vi.fn(),
  },
  hardwareApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  computeUnitsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  servicesApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  storageApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  networksApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  miscApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  docsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  tagsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  clustersApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  externalNodesApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}));

import { adminApi } from '../api/client.jsx';
import {
  applyTransfer,
  exportPortableInventory,
  getTransferSummary,
  previewTransfer,
} from '../api/inventoryTransfer';
import InventoryTransferPanel from '../components/settings/InventoryTransferPanel.jsx';

const SUMMARY = {
  format: 'circuitbreaker.inventory',
  version: 1,
  assets: {
    hardware: 240,
    compute_units: 3,
    services: 3,
    storage: 1,
    networks: 1,
    misc_items: 0,
    external_nodes: 0,
  },
  assets_total: 248,
  relationships: { entity_tags: 392 },
  relationships_total: 392,
};

const SNAPSHOT = {
  filename: 'cb-snapshot-20260910.tar.zst',
  created_at: '2026-09-10T08:00:00Z',
  size_mb: 42.8,
};

const DOCUMENT = {
  format: 'circuitbreaker.inventory',
  version: 1,
  exported_at: '2026-09-10T00:00:00Z',
  manifest: { included: [], excluded: [] },
  entities: {
    services: [{ id: 7, name: 'grafana', slug: 'grafana' }],
  },
  relationships: {},
};

const CONFLICT_PREVIEW = {
  plan_id: 'plan-1',
  plan_digest: 'a'.repeat(64),
  can_apply: false,
  creates: { services: 0 },
  matches: {},
  relationships: { entity_tags: 1 },
  conflicts: [
    {
      entity_type: 'services',
      source_id: 7,
      reason_code: 'unique_identity_conflict',
      message:
        'A local services record uses the same slug; choose it explicitly or revise the source inventory.',
      candidates: [42],
      candidate_labels: ['grafana'],
      field: 'slug',
    },
  ],
  warnings: ['This merge creates new local IDs.'],
};

const CLEAN_PREVIEW = {
  ...CONFLICT_PREVIEW,
  can_apply: true,
  conflicts: [],
  creates: { services: 1 },
};

const APPLY_RESULT = {
  operation_id: 'op-1',
  state: 'completed',
  created: { services: 1 },
  matched: {},
  relationships_created: { entity_tags: 1 },
  warnings: ['Operational history was not imported.'],
};

function jsonFile(payload) {
  return new File([JSON.stringify(payload)], 'homelab-inventory.json', {
    type: 'application/json',
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  getTransferSummary.mockResolvedValue({ data: SUMMARY });
  adminApi.listSnapshots.mockResolvedValue({ data: { snapshots: [SNAPSHOT] } });
  exportPortableInventory.mockResolvedValue({
    data: {
      format: 'circuitbreaker.inventory',
      version: 1,
      manifest: { included: ['hardware', 'services'], excluded: ['users', 'credentials'] },
    },
  });
  adminApi.triggerSnapshot.mockResolvedValue({ data: {} });
});

function renderPanel() {
  return render(<InventoryTransferPanel />);
}

async function chooseFile() {
  // getByLabelText resolves to the wrapped <input type="file"> itself.
  const input = screen.getByLabelText(/Choose file/i);
  expect(input.tagName).toBe('INPUT');
  fireEvent.change(input, { target: { files: [jsonFile(DOCUMENT)] } });
  await waitFor(() => {
    expect(screen.getByText('homelab-inventory.json')).toBeTruthy();
  });
}

describe('InventoryTransferPanel', () => {
  it('renders the four honest summary tiles from real endpoints', async () => {
    renderPanel();
    expect(await screen.findByText('Inventory objects')).toBeTruthy();
    expect(screen.getByText('248')).toBeTruthy();
    expect(screen.getByText('Across 7 asset types')).toBeTruthy();
    expect(screen.getByText('392')).toBeTruthy();
    expect(screen.getByText('Snapshot available')).toBeTruthy();
    expect(screen.getByText('Restore verification is a separate step')).toBeTruthy();
  });

  it('validates a file and lands on resolve with its decision ledger', async () => {
    previewTransfer.mockResolvedValueOnce({ data: CONFLICT_PREVIEW });
    renderPanel();
    await chooseFile();

    expect(screen.getByText('circuitbreaker.inventory · v1')).toBeTruthy();
    expect(screen.getByText('1 record needs your attention')).toBeTruthy();
    expect(screen.getByText(/uses the same slug/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeTruthy();
    expect(screen.getByText('No changes have been applied')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Review changes/ })).toBeDisabled();
  });

  it('saves a rename decision, then reviews and applies the merge', async () => {
    previewTransfer.mockResolvedValueOnce({ data: CONFLICT_PREVIEW }).mockResolvedValueOnce({
      data: CLEAN_PREVIEW,
    });
    applyTransfer.mockResolvedValueOnce({ data: APPLY_RESULT });
    renderPanel();
    await chooseFile();

    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    const drawer = screen.getByRole('heading', { name: /Resolve grafana/ });
    expect(drawer).toBeTruthy();
    const renameInput = screen.getByLabelText(/New slug for the incoming record/i);
    expect(renameInput.value).toBe('grafana-imported');

    fireEvent.click(screen.getByRole('button', { name: 'Save decision' }));
    await waitFor(() => {
      expect(screen.getByText(/All decisions are recorded/)).toBeTruthy();
    });
    const review = screen.getByRole('button', { name: /Review changes/ });
    expect(review).not.toBeDisabled();
    fireEvent.click(review);

    expect(screen.getByText(/Ready to merge/)).toBeTruthy();
    expect(screen.getByText('Unrelated records overwritten')).toBeTruthy();
    const apply = screen.getByRole('button', { name: 'Apply import' });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I reviewed these changes/));
    expect(apply).not.toBeDisabled();
    fireEvent.click(apply);

    expect(await screen.findByText('Import completed')).toBeTruthy();
    expect(
      screen.getByText(/1 record created, 0 matched, and 1 relationship processed/)
    ).toBeTruthy();
    expect(applyTransfer).toHaveBeenCalledWith('plan-1', 'a'.repeat(64), expect.any(String));
  });

  it('keeps a bad rename in the drawer instead of saving it', async () => {
    previewTransfer
      .mockResolvedValueOnce({ data: CONFLICT_PREVIEW })
      .mockRejectedValueOnce(
        Object.assign(new Error('The proposed slug is already used.'), { statusCode: 400 })
      );
    renderPanel();
    await chooseFile();

    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    fireEvent.change(screen.getByLabelText(/New slug for the incoming record/i), {
      target: { value: 'taken' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save decision' }));

    await waitFor(() => {
      expect(screen.getByText('The proposed slug is already used.')).toBeTruthy();
    });
    expect(screen.getByRole('heading', { name: /Resolve grafana/ })).toBeTruthy();
  });

  it('offers a re-review path when the preview went stale at apply time', async () => {
    previewTransfer.mockResolvedValue({ data: CLEAN_PREVIEW });
    applyTransfer.mockRejectedValueOnce(
      Object.assign(new Error('Inventory changed after this preview.'), {
        statusCode: 409,
        errorCode: 'preview_stale',
      })
    );
    renderPanel();
    await chooseFile();

    fireEvent.click(screen.getByLabelText(/I reviewed these changes/));
    fireEvent.click(screen.getByRole('button', { name: 'Apply import' }));

    await waitFor(() => {
      expect(screen.getByText('Inventory changed after this preview.')).toBeTruthy();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review the transfer again' }));
    await waitFor(() => {
      expect(previewTransfer).toHaveBeenCalledTimes(2);
    });
  });

  it('blocks Replace honestly and returns to merge', async () => {
    previewTransfer.mockResolvedValue({ data: CONFLICT_PREVIEW });
    renderPanel();
    await chooseFile();

    const mode = screen.getByLabelText(/Import operation/);
    expect(mode.tagName).toBe('SELECT');
    fireEvent.change(mode, { target: { value: 'replace' } });

    expect(screen.getByText('This replaces the current inventory')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Return to merge' }));
    expect(screen.queryByText('This replaces the current inventory')).toBeNull();
    expect(mode.value).toBe('merge');
  });

  it('renders the export manifest verbatim and the offline-restore boundary', async () => {
    renderPanel();
    fireEvent.click(screen.getByRole('tab', { name: 'Export & recovery' }));

    expect(await screen.findByText(/Includes 2 record kinds/)).toBeTruthy();
    expect(screen.getByText('hardware, services')).toBeTruthy();
    expect(screen.getByText('users, credentials')).toBeTruthy();
    expect(screen.getByText('Restore is an offline operation')).toBeTruthy();
    expect(screen.getByText(/cb restore <archive>/)).toBeTruthy();
    expect(screen.getByText(/Latest: cb-snapshot-20260910.tar.zst/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Create snapshot' }));
    await waitFor(() => {
      expect(adminApi.triggerSnapshot).toHaveBeenCalled();
    });
  });

  it('says when the portable kinds cannot be settled here', async () => {
    previewTransfer.mockResolvedValueOnce({
      data: {
        ...CONFLICT_PREVIEW,
        conflicts: [
          {
            entity_type: 'entity_tags',
            source_id: 1,
            reason_code: 'unsupported_reference_type',
            message: 'The attachment entity type is not portable.',
          },
        ],
      },
    });
    renderPanel();
    await chooseFile();

    expect(screen.getByText('Attachment type is not portable')).toBeTruthy();
    expect(screen.getByText('Revise the source inventory')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Resolve' })).toBeNull();
  });
});
