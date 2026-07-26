import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/monitors/MonitorCard.jsx', () => ({
  default: ({ monitor }) => <div data-testid="card">{monitor.name}</div>,
}));

import MonitorGroup from '../components/monitors/MonitorGroup.jsx';

const monitors = [
  { id: 1, name: 'grafana' },
  { id: 2, name: 'unifi' },
];

const handlers = {
  onToggle: vi.fn(),
  onCheckNow: vi.fn(),
  onPause: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
};

describe('MonitorGroup', () => {
  it('labels the group, counts it, and pings in its status colour', () => {
    const { container } = render(
      <MemoryRouter>
        <MonitorGroup
          status="down"
          monitors={monitors}
          expandedIds={new Set()}
          detailsById={{}}
          {...handlers}
        />
      </MemoryRouter>
    );
    expect(screen.getByRole('heading', { name: /Down · 2/ })).toBeTruthy();
    expect(container.querySelector('.mon-ping').dataset.status).toBe('down');
    expect(screen.getAllByTestId('card')).toHaveLength(2);
  });

  it('renders nothing for an empty group', () => {
    const { container } = render(
      <MemoryRouter>
        <MonitorGroup
          status="up"
          monitors={[]}
          expandedIds={new Set()}
          detailsById={{}}
          {...handlers}
        />
      </MemoryRouter>
    );
    expect(container.querySelector('.mon-group')).toBeNull();
  });
});
