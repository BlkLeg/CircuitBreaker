/**
 * The banner is the surface that ends silent stranding. It must appear for an
 * admin on a stale build, stay hidden otherwise, and come back when a NEWER
 * release lands after a dismissal.
 */
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

const mockGetUpdate = vi.fn();
vi.mock('../api/client.jsx', () => ({
  adminApi: { updateStatus: (...a) => mockGetUpdate(...a) },
}));

const mockUser = { current: { role: 'admin' } };
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser.current }),
}));

import UpdateBanner from '../components/UpdateBanner.jsx';

const AVAILABLE = {
  current: '1.0.0-rc.2',
  available: '1.0.0-rc.4',
  update_available: true,
  channel: 'prerelease',
  install_method: 'binary',
  upgrade_command: 'curl -fsSL https://example/install.sh | sudo bash -s -- --upgrade',
  release_url: 'https://github.com/BlkLeg/CircuitBreaker/releases/tag/v1.0.0-rc.4',
  enabled: true,
  checked_at: '2026-08-25T21:00:00+00:00',
  status: 'ok',
};

beforeEach(() => {
  localStorage.clear();
  mockUser.current = { role: 'admin' };
  mockGetUpdate.mockReset();
  mockGetUpdate.mockResolvedValue({ data: AVAILABLE });
});

test('shows the available version and the command for this install', async () => {
  render(<UpdateBanner />);
  expect(await screen.findByText(/1\.0\.0-rc\.4/)).toBeInTheDocument();
  expect(screen.getByText(/sudo bash -s -- --upgrade/)).toBeInTheDocument();
});

test('renders nothing when up to date', async () => {
  mockGetUpdate.mockResolvedValue({
    data: { ...AVAILABLE, available: null, update_available: false, release_url: null },
  });
  const { container } = render(<UpdateBanner />);
  await vi.waitFor(() => expect(mockGetUpdate).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test('renders nothing for a non-admin and never calls the admin endpoint', async () => {
  mockUser.current = { role: 'viewer' };
  const { container } = render(<UpdateBanner />);
  await Promise.resolve();
  expect(mockGetUpdate).not.toHaveBeenCalled();
  expect(container).toBeEmptyDOMElement();
});

test('dismissal hides it', async () => {
  render(<UpdateBanner />);
  await userEvent.click(await screen.findByRole('button', { name: /dismiss/i }));
  expect(screen.queryByText(/1\.0\.0-rc\.4/)).not.toBeInTheDocument();
});

test('a dismissal does not suppress a later, newer release', async () => {
  localStorage.setItem('cb.updateDismissed', '1.0.0-rc.4');
  mockGetUpdate.mockResolvedValue({
    data: { ...AVAILABLE, available: '1.0.0-rc.5' },
  });
  render(<UpdateBanner />);
  expect(await screen.findByText(/1\.0\.0-rc\.5/)).toBeInTheDocument();
});

test('a dismissal does suppress the same release', async () => {
  localStorage.setItem('cb.updateDismissed', '1.0.0-rc.4');
  const { container } = render(<UpdateBanner />);
  await vi.waitFor(() => expect(mockGetUpdate).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test('an unreachable endpoint clears a stale update claim on the next check', async () => {
  // A fresh assertion on `status === null` proves nothing — that's the hook's
  // initial state regardless of whether the catch runs. So first let a real
  // update render, then make the hourly refresh fail, and check the
  // previously-shown version is actually retracted.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    render(<UpdateBanner />);
    expect(await screen.findByText(/1\.0\.0-rc\.4/)).toBeInTheDocument();

    mockGetUpdate.mockRejectedValueOnce(new Error('network down'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000); // REFRESH_MS
    });

    expect(screen.queryByText(/1\.0\.0-rc\.4/)).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

test('a blocked localStorage read does not crash the banner', async () => {
  const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  try {
    render(<UpdateBanner />);
    expect(await screen.findByText(/1\.0\.0-rc\.4/)).toBeInTheDocument();
  } finally {
    spy.mockRestore();
  }
});

test('a blocked localStorage write does not crash dismissal', async () => {
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  try {
    render(<UpdateBanner />);
    await userEvent.click(await screen.findByRole('button', { name: /dismiss/i }));
    expect(screen.queryByText(/1\.0\.0-rc\.4/)).not.toBeInTheDocument();
  } finally {
    spy.mockRestore();
  }
});
