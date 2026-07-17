import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

globalThis.ResizeObserver =
  globalThis.ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

const mockGetIgnoredFindings = vi.fn();
const mockIgnoreFinding = vi.fn();
const mockUnignoreFinding = vi.fn();
const mockGetNetworkPrivacyScore = vi.fn();
const mockGetNetworkPrivacyScoreHistory = vi.fn();
const mockGetAttackSurface = vi.fn();
const mockHardwareList = vi.fn();

vi.mock('../api/client', () => ({
  windscribeApi: {
    getIgnoredFindings: (...args) => mockGetIgnoredFindings(...args),
    ignoreFinding: (...args) => mockIgnoreFinding(...args),
    unignoreFinding: (...args) => mockUnignoreFinding(...args),
    getNetworkPrivacyScore: (...args) => mockGetNetworkPrivacyScore(...args),
    getNetworkPrivacyScoreHistory: (...args) => mockGetNetworkPrivacyScoreHistory(...args),
    getAttackSurface: (...args) => mockGetAttackSurface(...args),
  },
  hardwareApi: { list: (...args) => mockHardwareList(...args) },
}));

vi.mock('../api/discovery', () => ({ startAdHocScan: vi.fn() }));

// jsdom has no layout engine, so recharts' ResponsiveContainer measures 0x0 via
// ResizeObserver and never renders its children. Give the wrapped chart a fixed
// size directly, the way ResponsiveContainer would once it had a real measurement.
vi.mock('recharts', async () => {
  const actual = await vi.importActual('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }) =>
      React.cloneElement(children, { width: 400, height: 200 }),
  };
});

import FlaggedDevicesTable from '../components/privacy/FlaggedDevicesTable';
import FindingsByCategoryChart from '../components/privacy/FindingsByCategoryChart';
import PrivacyPage from '../pages/PrivacyPage';

const DEDUCTIONS = [
  {
    rule_id: 'telnet_open',
    title: 'Telnet service exposed',
    points: 15,
    severity: 'critical',
    remediation_id: 'disable_telnet',
    hardware_id: 1,
    category: 'services',
  },
  {
    rule_id: 'upnp_exposed',
    title: 'UPnP service exposed',
    points: 10,
    severity: 'warning',
    remediation_id: 'disable_upnp',
    hardware_id: 2,
    category: 'protocols',
  },
  {
    rule_id: 'dns_tamper',
    title: 'DNS responses appear tampered with',
    points: 30,
    severity: 'critical',
    remediation_id: 'dns_tamper_response',
    hardware_id: null,
    category: 'dns',
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FlaggedDevicesTable ignore persistence', () => {
  it('seeds already-ignored rows from the backend and hides them', async () => {
    mockGetIgnoredFindings.mockResolvedValue({
      data: { ignores: [{ rule_id: 'telnet_open', hardware_id: 1 }] },
    });
    render(<FlaggedDevicesTable deductions={DEDUCTIONS} hardwareMap={new Map()} />, {
      wrapper: MemoryRouter,
    });

    await waitFor(() => expect(mockGetIgnoredFindings).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText('Telnet service exposed')).not.toBeInTheDocument()
    );
    expect(screen.getByText('UPnP service exposed')).toBeInTheDocument();
  });

  it('persists an Ignore click to the backend and hides the row', async () => {
    mockGetIgnoredFindings.mockResolvedValue({ data: { ignores: [] } });
    mockIgnoreFinding.mockResolvedValue({ data: { ok: true } });
    const { default: userEvent } = await import('@testing-library/user-event');
    const user = userEvent.setup();

    render(<FlaggedDevicesTable deductions={DEDUCTIONS} hardwareMap={new Map()} />, {
      wrapper: MemoryRouter,
    });
    await waitFor(() => expect(mockGetIgnoredFindings).toHaveBeenCalled());

    const row = screen.getByText('Telnet service exposed').closest('tr');
    await user.click(within(row).getByText('Ignore'));

    expect(mockIgnoreFinding).toHaveBeenCalledWith('telnet_open', 1);
    await waitFor(() =>
      expect(screen.queryByText('Telnet service exposed')).not.toBeInTheDocument()
    );
  });

  it('Show all calls unignoreFinding for each restored row and un-hides them', async () => {
    mockGetIgnoredFindings.mockResolvedValue({
      data: { ignores: [{ rule_id: 'telnet_open', hardware_id: 1 }] },
    });
    mockUnignoreFinding.mockResolvedValue({});
    const { default: userEvent } = await import('@testing-library/user-event');
    const user = userEvent.setup();

    render(<FlaggedDevicesTable deductions={DEDUCTIONS} hardwareMap={new Map()} />, {
      wrapper: MemoryRouter,
    });
    await waitFor(() =>
      expect(screen.queryByText('Telnet service exposed')).not.toBeInTheDocument()
    );

    await user.click(screen.getByText('Show all'));

    expect(mockUnignoreFinding).toHaveBeenCalledWith('telnet_open', 1);
    expect(screen.getByText('Telnet service exposed')).toBeInTheDocument();
  });
});

describe('FindingsByCategoryChart', () => {
  it('categorizes findings using the backend-provided category field', () => {
    render(<FindingsByCategoryChart deductions={DEDUCTIONS} />);
    expect(screen.getByText('Services')).toBeInTheDocument();
    expect(screen.getByText('Protocols')).toBeInTheDocument();
    expect(screen.getByText('DNS')).toBeInTheDocument();
    expect(screen.getByText('Network')).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.queryByText('Scans')).not.toBeInTheDocument();
    expect(screen.queryByText('Companies')).not.toBeInTheDocument();
  });

  it('falls back uncategorized findings into "Other"', () => {
    render(
      <FindingsByCategoryChart deductions={[{ rule_id: 'unknown_rule', hardware_id: null }]} />
    );
    expect(screen.getByText('Other')).toBeInTheDocument();
  });
});

describe('PrivacyPage history wiring', () => {
  it('fetches and passes real day-bucketed history instead of the old inline history', async () => {
    mockGetNetworkPrivacyScore.mockResolvedValue({
      data: { enabled: true, score: 85, grade: 'B', deductions: [], checks: [], history: [] },
    });
    mockGetNetworkPrivacyScoreHistory.mockResolvedValue({
      data: {
        days: [
          { date: '2026-07-16', score: 85, critical_count: 0, warning_count: 1, info_count: 0 },
        ],
      },
    });
    mockGetAttackSurface.mockResolvedValue({ data: { attack_surface: [] } });
    mockHardwareList.mockResolvedValue({ data: [] });

    render(<PrivacyPage />, { wrapper: MemoryRouter });

    await waitFor(() => expect(mockGetNetworkPrivacyScoreHistory).toHaveBeenCalledWith(30));
  });
});
