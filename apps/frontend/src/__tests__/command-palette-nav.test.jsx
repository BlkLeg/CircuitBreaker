import React from 'react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockUser = { current: { role: 'admin' } };

vi.mock('../api/client', () => ({
  searchApi: { search: vi.fn().mockResolvedValue({ data: [] }) },
}));
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ openAuthModal: vi.fn(), openProfileModal: vi.fn(), user: mockUser.current }),
}));

import CommandPalette from '../components/CommandPalette.jsx';

function open(user) {
  mockUser.current = user;
  render(
    <MemoryRouter>
      <CommandPalette isOpen onClose={() => {}} />
    </MemoryRouter>
  );
}

// jsdom does not implement scrollIntoView, which the palette calls on every
// selection change. Nothing rendered this component in a test before now.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe('command palette navigation entries', () => {
  it('offers the destinations it used to omit', () => {
    open({ role: 'admin' });
    for (const label of ['Discovery', 'Agents', 'Monitors', 'IPAM', 'Intel', 'Access Tokens']) {
      expect(screen.getByText(`Go to: ${label}`)).toBeTruthy();
    }
  });

  it('no longer offers the dead /networks redirect', () => {
    open({ role: 'admin' });
    expect(screen.queryByText('Go to: Networks')).toBeNull();
  });

  it('hides admin destinations from a viewer', () => {
    open({ role: 'viewer' });
    expect(screen.queryByText('Go to: Logs')).toBeNull();
    expect(screen.queryByText('Go to: Access Tokens')).toBeNull();
    expect(screen.getByText('Go to: Map')).toBeTruthy();
  });

  it('keeps the settings deep-links, which are anchors rather than routes', () => {
    open({ role: 'admin' });
    expect(screen.getByText('Settings: Appearance')).toBeTruthy();
  });

  it('offers "Go to: Settings" exactly once', () => {
    open({ role: 'admin' });
    expect(screen.getAllByText('Go to: Settings')).toHaveLength(1);
  });
});

const sectionLabels = (container) =>
  [...container.querySelectorAll('.palette-section-label')].map((el) => el.textContent);

describe('command palette section labels', () => {
  // Spec §7: the group name is rendered as a section label. 21 "Go to:" rows are not
  // scannable as one flat list.
  it('heads each nav group once, in NAV_GROUPS order', () => {
    open({ role: 'admin' });
    expect(sectionLabels(document.body)).toEqual([
      'Acquire',
      'Inventory',
      'Observe',
      'Govern',
      'System',
      'Settings & Account',
    ]);
  });

  it('drops a heading whose whole group the role cannot see', () => {
    open({ role: 'viewer' });
    expect(sectionLabels(document.body)).not.toContain('Govern');
    expect(sectionLabels(document.body)).toContain('Acquire');
  });

  it('does not group search results, which are ranked by match', () => {
    open({ role: 'admin' });
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'map' } });
    expect(sectionLabels(document.body)).toEqual([]);
  });
});
