import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const update = vi.fn().mockResolvedValue({});
const mockSettings = { current: {} };

vi.mock('../api/client', () => ({ settingsApi: { update: (...a) => update(...a) } }));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: mockSettings.current, reloadSettings: vi.fn() }),
}));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }));

import DockSettings from '../components/settings/DockSettings.jsx';

function setup(settings) {
  mockSettings.current = settings;
  render(<DockSettings />);
}

describe('dock settings', () => {
  beforeEach(() => update.mockClear());

  it('groups the list under the same headings as the menu', () => {
    setup({ dock_order: ['/map'] });
    for (const label of ['Acquire', 'Inventory', 'Observe', 'Govern', 'System']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it('offers every nav destination, not a shorter hardcoded list', () => {
    setup({ dock_order: ['/map'] });
    expect(screen.getByLabelText('Other Assets')).toBeTruthy();
    expect(screen.getByLabelText('Access Tokens')).toBeTruthy();
    expect(screen.getByLabelText('Intel')).toBeTruthy();
  });

  it('checks exactly what the dock is currently showing', () => {
    setup({ dock_order: ['/map', '/hardware'] });
    expect(screen.getByLabelText('Map').checked).toBe(true);
    expect(screen.getByLabelText('Hardware').checked).toBe(true);
    expect(screen.getByLabelText('Storage').checked).toBe(false);
  });

  it('writes dock_order, never dock_hidden_items', async () => {
    setup({ dock_order: ['/map'] });
    fireEvent.click(screen.getByLabelText('Storage'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    const payload = update.mock.calls[0][0];
    expect(payload).toHaveProperty('dock_order');
    expect(payload).not.toHaveProperty('dock_hidden_items');
    expect(payload.dock_order).toEqual(['/map', '/storage']);
  });

  it('migrates a legacy preference on first save', async () => {
    setup({ dock_hidden_items: ['/storage'] });
    expect(screen.getByLabelText('Certificates').checked).toBe(true);
    expect(screen.getByLabelText('Storage').checked).toBe(false);
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0].dock_order).not.toContain('/storage');
    expect(update.mock.calls[0][0].dock_order).toContain('/certificates');
  });

  it('moves an item up, changing the saved order', async () => {
    setup({ dock_order: ['/map', '/hardware'] });
    fireEvent.click(screen.getByLabelText('Move Hardware up'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0].dock_order).toEqual(['/hardware', '/map']);
  });

  it('does not tell the user to drag the dock', () => {
    setup({ dock_order: ['/map'] });
    expect(screen.queryByText(/drag items in the dock/i)).toBeNull();
  });

  const dockRowText = () => screen.getAllByRole('listitem').map((li) => li.textContent);

  // The picker is grouped by taxonomy, so it can never show position. These lock in the
  // separate ordered list: /map sits in Acquire and /hardware in Inventory, so a taxonomy
  // rendering would always put Map first no matter what dock_order says.
  it('lists the dock in stored order, not taxonomy order', () => {
    setup({ dock_order: ['/hardware', '/map'] });
    expect(dockRowText()).toEqual(['1Hardware', '2Map']);
  });

  it('moves the row on screen, not just in the saved payload', async () => {
    setup({ dock_order: ['/hardware', '/map'] });
    fireEvent.click(screen.getByLabelText('Move Map up'));
    expect(dockRowText()).toEqual(['1Map', '2Hardware']);
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0].dock_order).toEqual(['/map', '/hardware']);
  });

  it('announces the new position for screen readers', () => {
    setup({ dock_order: ['/hardware', '/map'] });
    fireEvent.click(screen.getByLabelText('Move Map up'));
    expect(screen.getByText('Map moved to position 1 of 2.')).toBeTruthy();
  });

  it('adds and removes rows as the picker is ticked', () => {
    setup({ dock_order: ['/map'] });
    expect(dockRowText()).toEqual(['1Map']);
    fireEvent.click(screen.getByLabelText('Storage'));
    expect(dockRowText()).toEqual(['1Map', '2Storage']);
    fireEvent.click(screen.getByLabelText('Map'));
    expect(dockRowText()).toEqual(['1Storage']);
  });

  it('says nothing false about where the order is read from', () => {
    setup({ dock_order: ['/map'] });
    expect(screen.queryByText(/in the order listed here/i)).toBeNull();
  });

  it('offers no move controls when the dock is empty', () => {
    setup({ dock_order: [] });
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    expect(screen.getByText(/Nothing is on the dock/i)).toBeTruthy();
  });
});
