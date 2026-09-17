import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/intel/FleetAssessmentTab.jsx', () => ({
  default: () => <p>fleet tab</p>,
}));
vi.mock('../components/intel/OperationsTab.jsx', () => ({
  default: () => <p>operations tab</p>,
}));

import IntelPage from '../pages/IntelPage.jsx';

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <IntelPage />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

describe('IntelPage', () => {
  it('opens on the vulnerability console', async () => {
    renderAt('/intel');

    await waitFor(() => expect(screen.getByText('fleet tab')).toBeInTheDocument());
  });

  it('honours a deep link to the operations tab', async () => {
    renderAt('/intel?tab=operations');

    await waitFor(() => expect(screen.getByText('operations tab')).toBeInTheDocument());
  });

  it('falls back to the default tab for an unknown value', async () => {
    renderAt('/intel?tab=nonsense');

    await waitFor(() => expect(screen.getByText('fleet tab')).toBeInTheDocument());
  });

  it('exposes the tabs as a tablist', async () => {
    renderAt('/intel');

    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    expect(screen.getAllByRole('tab')).toHaveLength(2);
  });
});
