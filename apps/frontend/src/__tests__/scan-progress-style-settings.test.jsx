import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockUpdate = vi.fn();
const mockReloadSettings = vi.fn();
const mockUseSettings = vi.fn();

vi.mock('../api/client', () => ({
  settingsApi: { update: (...args) => mockUpdate(...args) },
}));

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => mockUseSettings(),
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}));

import ScanProgressStyleSettings from '../components/settings/ScanProgressStyleSettings.jsx';

beforeEach(() => {
  vi.clearAllMocks();
  mockUpdate.mockResolvedValue({});
  mockReloadSettings.mockResolvedValue();
  mockUseSettings.mockReturnValue({
    settings: { scan_progress_style: 'circuit' },
    reloadSettings: mockReloadSettings,
  });
});

describe('ScanProgressStyleSettings', () => {
  it('shows all 4 styles with Circuit Trace marked active by default', () => {
    render(<ScanProgressStyleSettings />);
    expect(screen.getByText('Scanline Sweep')).toBeInTheDocument();
    expect(screen.getByText('Segmented Pulse')).toBeInTheDocument();
    expect(screen.getByText('Circuit Trace')).toBeInTheDocument();
    expect(screen.getByText('Minimal Gradient Glow')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Circuit Trace/ })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
  });

  it('saves and reloads settings when a different style is clicked', async () => {
    render(<ScanProgressStyleSettings />);
    screen.getByRole('button', { name: /Segmented Pulse/ }).click();

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ scan_progress_style: 'segmented' })
    );
    await waitFor(() => expect(mockReloadSettings).toHaveBeenCalled());
  });

  it('does not call the API again when clicking the already-active style', () => {
    render(<ScanProgressStyleSettings />);
    screen.getByRole('button', { name: /Circuit Trace/ }).click();
    expect(mockUpdate).not.toHaveBeenCalled();
  });
});
