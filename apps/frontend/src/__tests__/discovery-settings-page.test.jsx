import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import DiscoverySettingsPage from '../pages/settings/DiscoverySettingsPage.jsx';

const mockUpdate = vi.fn().mockResolvedValue({ data: {} });
const mockGet = vi.fn();

vi.mock('../api/client.jsx', () => ({
  settingsApi: {
    get: (...args) => mockGet(...args),
    update: (...args) => mockUpdate(...args),
  },
}));

const mockReloadSettings = vi.fn().mockResolvedValue();
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {},
    reloadSettings: mockReloadSettings,
  }),
}));

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({
    success: mockToastSuccess,
    error: mockToastError,
    warn: vi.fn(),
    info: vi.fn(),
  }),
}));

const mockUseDiscoveryReadiness = vi.fn();
vi.mock('../hooks/useDiscoveryReadiness.js', () => ({
  useDiscoveryReadiness: (...args) => mockUseDiscoveryReadiness(...args),
}));

const baseSettings = {
  discovery_enabled: true,
  discovery_auto_merge: false,
  discovery_default_cidr: '192.168.1.0/24',
  discovery_nmap_args: '-sV -O --open -T4',
  discovery_http_probe: true,
  discovery_retention_days: 30,
  scan_ack_accepted: false,
  nmap_enabled: false,
  discovery_mode: 'safe',
  docker_discovery_enabled: false,
  docker_socket_path: '/var/run/docker.sock',
  docker_sync_interval_minutes: 5,
  self_cluster_enabled: false,
  lan_discovery_desired: false,
};

function fourCapabilities({
  arpState = 'needs-helper-action',
  lanState = 'needs-helper-action',
} = {}) {
  return [
    {
      key: 'nmap_present',
      title: 'Nmap scanner',
      state: 'ready',
      explanation: 'The nmap scanner is installed and available.',
      reason_code: 'nmap_ok',
      last_healed_at: null,
      last_error: null,
    },
    {
      key: 'nmap_raw',
      title: 'Fast host discovery & OS detection',
      state: 'auto-fixable',
      explanation: 'Raw-socket privilege is missing.',
      reason_code: 'raw_priv_missing',
      last_healed_at: null,
      last_error: null,
    },
    {
      key: 'arp_l2',
      title: 'ARP / MAC address resolution',
      state: arpState,
      explanation: 'ARP scanning status.',
      reason_code: 'arp_status',
      last_healed_at: null,
      last_error: null,
    },
    {
      key: 'lan_adjacency',
      title: 'Direct LAN reachability',
      state: lanState,
      explanation: 'LAN adjacency status.',
      reason_code: 'lan_status',
      last_healed_at: null,
      last_error: null,
    },
  ];
}

describe('DiscoverySettingsPage — Readiness panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUpdate.mockResolvedValue({ data: {} });
    mockReloadSettings.mockResolvedValue();
    mockGet.mockResolvedValue({ data: { ...baseSettings } });
    mockUseDiscoveryReadiness.mockReturnValue({
      loading: false,
      readiness: {
        helper_installed: true,
        capabilities: fourCapabilities(),
      },
    });
  });

  it('renders each of the 4 capabilities with its state badge', async () => {
    render(<DiscoverySettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Nmap scanner')).toBeInTheDocument();
    });

    expect(screen.getByText('Fast host discovery & OS detection')).toBeInTheDocument();
    expect(screen.getByText('ARP / MAC address resolution')).toBeInTheDocument();
    expect(screen.getByText('Direct LAN reachability')).toBeInTheDocument();

    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('Auto-heals')).toBeInTheDocument();
    expect(screen.getAllByText('Needs LAN discovery').length).toBeGreaterThanOrEqual(1);
  });

  it('shows "Last healed …" / "Last attempt failed: …" lines when metadata is present', async () => {
    mockUseDiscoveryReadiness.mockReturnValue({
      loading: false,
      readiness: {
        helper_installed: true,
        capabilities: [
          {
            key: 'arp_l2',
            title: 'ARP / MAC address resolution',
            state: 'needs-helper-action',
            explanation: 'ARP scanning status.',
            reason_code: 'arp_status',
            last_healed_at: new Date(Date.now() - 5 * 60_000).toISOString(),
            last_error: null,
          },
          {
            key: 'lan_adjacency',
            title: 'Direct LAN reachability',
            state: 'needs-helper-action',
            explanation: 'LAN adjacency status.',
            reason_code: 'bridged_no_l2',
            last_healed_at: null,
            last_error: 'helper unreachable: connection refused',
          },
        ],
      },
    });

    render(<DiscoverySettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Direct LAN reachability')).toBeInTheDocument();
    });

    expect(screen.getByText(/Last healed/)).toBeInTheDocument();
    expect(
      screen.getByText(/Last attempt failed:.*helper unreachable: connection refused/)
    ).toBeInTheDocument();
  });

  it('disables the LAN discovery toggle when helper_installed is false', async () => {
    mockUseDiscoveryReadiness.mockReturnValue({
      loading: false,
      readiness: {
        helper_installed: false,
        capabilities: fourCapabilities(),
      },
    });

    render(<DiscoverySettingsPage />);

    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Enable LAN Discovery' })).toBeInTheDocument();
    });

    expect(screen.getByRole('switch', { name: 'Enable LAN Discovery' })).toBeDisabled();
  });

  it('disables the LAN discovery toggle when arp_l2/lan_adjacency report unavailable-on-platform', async () => {
    mockUseDiscoveryReadiness.mockReturnValue({
      loading: false,
      readiness: {
        helper_installed: true,
        capabilities: fourCapabilities({
          arpState: 'unavailable-on-platform',
          lanState: 'unavailable-on-platform',
        }),
      },
    });

    render(<DiscoverySettingsPage />);

    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Enable LAN Discovery' })).toBeInTheDocument();
    });

    expect(screen.getByRole('switch', { name: 'Enable LAN Discovery' })).toBeDisabled();
    expect(screen.getAllByText('Not available here').length).toBeGreaterThanOrEqual(1);
  });

  it('round-trips the LAN discovery toggle through settingsApi.update on click', async () => {
    render(<DiscoverySettingsPage />);

    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Enable LAN Discovery' })).toBeInTheDocument();
    });

    const toggle = screen.getByRole('switch', { name: 'Enable LAN Discovery' });
    expect(toggle).not.toBeDisabled();
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith({ lan_discovery_desired: true });
    });

    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Enable LAN Discovery' })).toHaveAttribute(
        'aria-checked',
        'true'
      );
    });

    expect(mockReloadSettings).toHaveBeenCalled();
    expect(mockToastSuccess).toHaveBeenCalled();
  });
});
