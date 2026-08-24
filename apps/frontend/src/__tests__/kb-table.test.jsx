import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../components/EntityTable', () => ({
  default: ({ data, onDelete, onCellSave, editableColumns }) => (
    <div data-testid="entity-table" data-editable={(editableColumns || []).join(',')}>
      {data.map((row) => (
        <div key={row.id} data-testid={`row-${row.id}`}>
          <span>{row.vendor}</span>
          <button onClick={() => onDelete(row.id)}>Delete {row.id}</button>
          <button onClick={() => onCellSave(row, 'vendor', 'Edited Vendor')}>Edit {row.id}</button>
        </div>
      ))}
    </div>
  ),
}));

import KbTable from '../components/kb/KbTable.jsx';

function makeTab(overrides = {}) {
  return {
    key: 'oui',
    label: 'MAC OUI Prefixes',
    identityKey: 'prefix',
    exportFilename: 'kb-oui.json',
    editableColumns: ['vendor', 'device_type', 'os_family'],
    columns: [{ key: 'vendor', label: 'Vendor' }],
    formFields: [{ name: 'prefix', label: 'Prefix', required: true }],
    validateCreate: () => null,
    serializeCreate: (v) => v,
    api: {
      list: vi.fn(),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      remove: vi.fn(() => Promise.resolve({ data: null })),
      exportAll: vi.fn(() => Promise.resolve({ data: {} })),
    },
    ...overrides,
  };
}

const row = (prefix, vendor) => ({
  prefix,
  vendor,
  device_type: null,
  os_family: null,
  source: 'learned',
  seen_count: 3,
  last_seen_at: '2026-08-24T10:00:00Z',
});

beforeEach(() => vi.clearAllMocks());

describe('KbTable', () => {
  it('keys rows by the descriptor identity key, not by a missing id', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);

    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());
  });

  it('requests the first server-side page on mount', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [] });

    render(<KbTable tab={tab} />);

    await waitFor(() => expect(tab.api.list).toHaveBeenCalledWith({ offset: 0, limit: 100 }));
  });

  it('sends the source filter as a query param and refetches from offset 0', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(tab.api.list).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'manual' } });

    await waitFor(() =>
      expect(tab.api.list).toHaveBeenLastCalledWith({ offset: 0, limit: 100, source: 'manual' })
    );
  });

  it('loads the next server-side page and appends it', async () => {
    const tab = makeTab();
    const first = Array.from({ length: 100 }, (_, i) =>
      row(String(i).padStart(6, '0'), `Vendor ${i}`)
    );
    tab.api.list
      .mockResolvedValueOnce({ data: first })
      .mockResolvedValueOnce({ data: [row('FFFFFF', 'Last Vendor')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-000000')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /load more/i }));

    await waitFor(() => expect(tab.api.list).toHaveBeenLastCalledWith({ offset: 100, limit: 100 }));
    await waitFor(() => expect(screen.getByTestId('row-FFFFFF')).toBeInTheDocument());
    expect(screen.getByTestId('row-000000')).toBeInTheDocument();
  });

  it('hides Load more once a short page comes back', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());

    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();
  });

  it('renders an error with retry instead of an empty table when the fetch fails', async () => {
    const tab = makeTab();
    tab.api.list.mockRejectedValue(new Error('boom'));

    render(<KbTable tab={tab} />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByTestId('entity-table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('says the text filter only covers loaded entries when more remain', async () => {
    const tab = makeTab();
    const first = Array.from({ length: 100 }, (_, i) =>
      row(String(i).padStart(6, '0'), `Vendor ${i}`)
    );
    tab.api.list.mockResolvedValue({ data: first });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-000000')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Filter loaded entries'), {
      target: { value: 'Vendor 1' },
    });

    expect(screen.getByText(/load more to search further/i)).toBeInTheDocument();
  });

  it('saves an inline edit through the descriptor update call', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Edit 001122' }));

    await waitFor(() =>
      expect(tab.api.update).toHaveBeenCalledWith('001122', { vendor: 'Edited Vendor' })
    );
  });

  it('deletes only after the confirmation is accepted', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Delete 001122' }));
    expect(tab.api.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    await waitFor(() => expect(tab.api.remove).toHaveBeenCalledWith('001122'));
  });

  it('passes only the descriptor editable columns to the table', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);

    await waitFor(() =>
      expect(screen.getByTestId('entity-table')).toHaveAttribute(
        'data-editable',
        'vendor,device_type,os_family'
      )
    );
  });
});
