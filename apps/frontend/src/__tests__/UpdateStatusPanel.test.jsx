/**
 * The permanent home for version facts, so dismissing the banner does not
 * destroy the only place they are visible.
 */
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

const mockStatus = { current: null };
vi.mock('../hooks/useUpdateStatus.js', () => ({
  useUpdateStatus: () => ({ status: mockStatus.current, loading: false }),
}));

import UpdateStatusPanel from '../components/settings/UpdateStatusPanel.jsx';

test('shows installed and available versions and the command', () => {
  mockStatus.current = {
    current: '1.0.0-rc.2',
    available: '1.0.0-rc.4',
    update_available: true,
    channel: 'prerelease',
    install_method: 'binary',
    upgrade_command: 'sudo bash install.sh --upgrade',
    release_url: 'https://example/tag/v1.0.0-rc.4',
    enabled: true,
    checked_at: '2026-08-25T21:00:00+00:00',
    status: 'ok',
  };
  render(<UpdateStatusPanel />);
  expect(screen.getByText('1.0.0-rc.2')).toBeInTheDocument();
  expect(screen.getByText('1.0.0-rc.4')).toBeInTheDocument();
  expect(screen.getByText(/sudo bash install\.sh --upgrade/)).toBeInTheDocument();
});

test('says checking is disabled rather than implying up to date', () => {
  mockStatus.current = {
    current: '1.0.0-rc.2',
    available: null,
    update_available: false,
    channel: 'prerelease',
    install_method: 'binary',
    upgrade_command: 'x',
    release_url: null,
    enabled: false,
    checked_at: null,
    status: 'disabled',
  };
  render(<UpdateStatusPanel />);
  expect(screen.getByText(/disabled/i)).toBeInTheDocument();
  expect(screen.queryByText(/up to date/i)).not.toBeInTheDocument();
});

test('says it could not reach the release source', () => {
  mockStatus.current = {
    current: '1.0.0-rc.2',
    available: null,
    update_available: false,
    channel: 'prerelease',
    install_method: 'binary',
    upgrade_command: 'x',
    release_url: null,
    enabled: true,
    checked_at: '2026-08-25T21:00:00+00:00',
    status: 'unreachable',
  };
  render(<UpdateStatusPanel />);
  expect(screen.getByText(/could not/i)).toBeInTheDocument();
});

test('renders nothing rather than a broken panel when status is unavailable', () => {
  mockStatus.current = null;
  const { container } = render(<UpdateStatusPanel />);
  expect(container).toBeEmptyDOMElement();
});
