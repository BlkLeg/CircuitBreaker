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
});
