import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/client', () => {
  const listMock = vi.fn(() => Promise.resolve({ data: { logs: [], total_count: 0 } }));
  return {
    logsApi: {
      list: listMock,
      actions: vi.fn(() => Promise.resolve({ data: { actions: [] } })),
      clear: vi.fn(),
      stream: vi.fn(() => '/api/v1/logs/stream'),
    },
  };
});

vi.mock('../components/logs/AuditChainPanel', () => ({
  default: () => <div data-testid="audit-chain-panel" />,
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

import { logsApi } from '../api/client';
import LogsPage from '../pages/LogsPage.jsx';

const renderPage = (props = {}) =>
  render(
    <MemoryRouter>
      <LogsPage {...props} />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

// LogsPage makes two logsApi.list calls: one with { limit: 500 } to load
// action/filter options (line 909), and one from fetchLogs with the full
// param set including category when auditMode is set. We find the fetchLogs
// call by looking for the one that includes `sort`.
function fetchLogsCall() {
  return logsApi.list.mock.calls.find((c) => c[0]?.sort != null)?.[0];
}

describe('LogsPage auditMode', () => {
  it('does not filter by category in the default mode', async () => {
    renderPage();
    await waitFor(() => expect(fetchLogsCall()).toBeDefined());
    expect(fetchLogsCall()).not.toHaveProperty('category');
  });

  it('pins category=audit in auditMode', async () => {
    renderPage({ auditMode: true });
    await waitFor(() => expect(fetchLogsCall()).toBeDefined());
    expect(fetchLogsCall()).toHaveProperty('category', 'audit');
  });

  it('titles the default page Logs, not Audit Log', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Logs' })).toBeInTheDocument());
    expect(screen.queryByRole('heading', { name: /audit log/i })).not.toBeInTheDocument();
  });

  it('titles the audit page Audit Log', async () => {
    renderPage({ auditMode: true });
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /audit log/i })).toBeInTheDocument()
    );
  });

  it('mounts the chain panel only in auditMode', async () => {
    const { unmount } = renderPage();
    await waitFor(() => expect(logsApi.list).toHaveBeenCalled());
    expect(screen.queryByTestId('audit-chain-panel')).not.toBeInTheDocument();
    unmount();

    renderPage({ auditMode: true });
    await waitFor(() => expect(screen.getByTestId('audit-chain-panel')).toBeInTheDocument());
  });
});
