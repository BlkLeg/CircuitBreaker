import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/monitors/MonitorsListTab.jsx', () => ({
  default: () => <p>monitor list</p>,
}));
vi.mock('../components/monitors/MetricAlertRulesPanel.jsx', () => ({
  default: () => <p>alert rules</p>,
}));

import MonitorsPage from '../pages/MonitorsPage.jsx';

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <MonitorsPage />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

describe('MonitorsPage tabs', () => {
  it('opens on the monitor list', async () => {
    renderAt('/monitors');

    await waitFor(() => expect(screen.getByText('monitor list')).toBeInTheDocument());
  });

  it('honours a deep link to alert rules', async () => {
    renderAt('/monitors?tab=alert-rules');

    await waitFor(() => expect(screen.getByText('alert rules')).toBeInTheDocument());
  });

  it('falls back to the list for an unknown tab', async () => {
    renderAt('/monitors?tab=nonsense');

    await waitFor(() => expect(screen.getByText('monitor list')).toBeInTheDocument());
  });

  it('keeps the list tab mounted when other params are present', async () => {
    renderAt('/monitors?status=down&q=nas');

    await waitFor(() => expect(screen.getByText('monitor list')).toBeInTheDocument());
  });

  it('exposes both tabs as a tablist', async () => {
    renderAt('/monitors');

    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    expect(screen.getAllByRole('tab')).toHaveLength(2);
  });
});
