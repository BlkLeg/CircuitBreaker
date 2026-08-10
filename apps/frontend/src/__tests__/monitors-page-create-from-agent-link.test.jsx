import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// The receiving half of Slice 3 §7's "Create monitor from this agent": Agent
// Detail links to /monitors?new=1&…, and this page has to turn that into an
// open CREATE form seeded with the device and the agent vantage.
//
// Mock shape mirrors monitors-dashboard.test.jsx, except MonitorForm records
// the props it was handed instead of rendering — the seed IS the assertion.
vi.mock('../api/monitor', () => ({
  getMonitorsOverview: vi.fn(),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorHistory: vi.fn().mockResolvedValue({ data: [] }),
  createMonitor: vi.fn().mockResolvedValue({ data: {} }),
  updateMonitor: vi.fn().mockResolvedValue({ data: {} }),
  deleteMonitor: vi.fn().mockResolvedValue({ data: {} }),
  pauseMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: new Map(), connected: true }),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

const formProps = [];
vi.mock('../components/monitors/MonitorForm', () => ({
  default: (props) => {
    formProps.push(props);
    return (
      <div data-testid="form">
        <button onClick={props.onCancel}>close form</button>
      </div>
    );
  },
}));
vi.mock('../components/monitors/LatencyChart', () => ({ default: () => <div>chart</div> }));
vi.mock('../styles/monitors.css', () => ({}));

import { getMonitorsOverview } from '../api/monitor';
import MonitorsPage from '../pages/MonitorsPage.jsx';

const renderAt = (entry) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <MonitorsPage />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
  formProps.length = 0;
  getMonitorsOverview.mockResolvedValue({ data: [] });
});

describe('MonitorsPage — the "Create monitor from this agent" deep link', () => {
  it('opens a create form seeded with the device and the agent vantage', async () => {
    renderAt(
      '/monitors?new=1&host=10.77.0.11&target_type=hardware&target_id=55&probe_agent_id=7&name=branch-nas'
    );

    expect(await screen.findByTestId('form')).toBeInTheDocument();
    const props = formProps.at(-1);
    // A create, never an edit.
    expect(props.initial).toBeNull();
    expect(props.prefill).toMatchObject({
      name: 'branch-nas',
      host: '10.77.0.11',
      target_type: 'hardware',
      target_id: 55,
      probe_agent_id: 7,
    });
    // Numbers, not strings: RunFromSelect matches with === on a numeric
    // agent_id, so a string would silently break its eligibility warnings.
    expect(typeof props.prefill.probe_agent_id).toBe('number');
    expect(typeof props.prefill.target_id).toBe('number');
    // The seed stops there — check type, interval and alert policy stay the
    // operator's, which is what §7 requires.
    expect(props.prefill.check_type).toBeUndefined();
    expect(props.prefill.interval_secs).toBeUndefined();
  });

  it('does not re-open the form after it is closed', async () => {
    renderAt('/monitors?new=1&host=10.77.0.11&probe_agent_id=7');

    expect(await screen.findByTestId('form')).toBeInTheDocument();
    fireEvent.click(screen.getByText('close form'));

    await waitFor(() => expect(screen.queryByTestId('form')).toBeNull());
  });

  it('opens nothing at all without the link', async () => {
    renderAt('/monitors');

    await waitFor(() => expect(getMonitorsOverview).toHaveBeenCalled());
    expect(screen.queryByTestId('form')).toBeNull();
  });

  it('ignores a malformed agent id rather than sending a string vantage', async () => {
    renderAt('/monitors?new=1&host=10.77.0.11&probe_agent_id=not-a-number');

    expect(await screen.findByTestId('form')).toBeInTheDocument();
    const props = formProps.at(-1);
    expect(props.prefill.host).toBe('10.77.0.11');
    expect(props.prefill.probe_agent_id).toBeUndefined();
  });
});
