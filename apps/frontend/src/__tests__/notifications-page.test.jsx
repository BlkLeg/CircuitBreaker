import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NotificationsPage from '../pages/NotificationsPage.jsx';

// Mock api client
vi.mock('../api/client', () => ({
  notificationsApi: {
    listSinks: vi.fn(),
    createSink: vi.fn(),
    updateSink: vi.fn(),
    deleteSink: vi.fn(),
    toggleSink: vi.fn(),
    testSink: vi.fn(),
    listRoutes: vi.fn(),
    createRoute: vi.fn(),
    deleteRoute: vi.fn(),
  },
}));

import { notificationsApi } from '../api/client';

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: { show_page_hints: true },
  }),
}));

const mockToast = {
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
};
vi.mock('../components/common/Toast', () => ({
  useToast: () => mockToast,
}));

// Mock sub-components
vi.mock('../components/EntityTable', () => ({
  default: ({ data, onEdit, onDelete, rowActions }) => (
    <div data-testid="entity-table">
      {data.map((item) => (
        <div key={item.id}>
          <span>{item.name || item.id}</span>
          <button onClick={() => onEdit?.(item)}>Edit</button>
          <button onClick={() => onDelete?.(item.id)}>Delete</button>
          {rowActions?.map((action) => (
            <button key={action.label} onClick={() => action.onClick(item)}>
              {action.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
}));

vi.mock('../components/common/FormModal', () => ({
  default: ({ open, title, initialValues, onSubmit, onClose }) =>
    open ? (
      <div data-testid="form-modal">
        <h3>{title}</h3>
        <button onClick={() => onSubmit({ name: 'new.destination', provider_type: 'slack' })}>
          Submit
        </button>
        {/* Mirrors EntityForm, which submits every value it was seeded with. */}
        <button onClick={() => onSubmit({ ...initialValues })}>Save As Seeded</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    ) : null,
}));

describe('NotificationsPage', () => {
  const mockSinks = [
    {
      id: 1,
      name: 'Slack Sink',
      provider_type: 'slack',
      enabled: true,
      provider_config: { webhook_url: 'http://slack' },
    },
    {
      id: 2,
      name: 'Email Sink',
      provider_type: 'email',
      enabled: false,
      provider_config: { to: 'test@local' },
    },
  ];
  const mockRoutes = [{ id: 1, sink_id: 1, alert_severity: '*', enabled: true }];

  beforeEach(() => {
    vi.clearAllMocks();
    notificationsApi.listSinks.mockResolvedValue({ data: mockSinks });
    notificationsApi.listRoutes.mockResolvedValue({ data: mockRoutes });
  });

  it('renders sinks list by default', async () => {
    render(<NotificationsPage />);
    await waitFor(() => expect(notificationsApi.listSinks).toHaveBeenCalled());
    expect(screen.getByText('Slack Sink')).toBeDefined();
    expect(screen.getByText('Email Sink')).toBeDefined();
  });

  it('switches to routing rules tab', async () => {
    render(<NotificationsPage />);
    fireEvent.click(screen.getByText(/Routing Rules/));
    await waitFor(() => expect(notificationsApi.listRoutes).toHaveBeenCalled());
    // Use getAllByText and check the one inside the table or just check length
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
  });

  it('reports acceptance without claiming the message was delivered', async () => {
    render(<NotificationsPage />);
    await waitFor(() => screen.getByText('Slack Sink'));

    notificationsApi.testSink.mockResolvedValue({
      data: {
        ok: true,
        state: 'accepted',
        reason_code: 'provider_accepted',
        message: 'Slack accepted the request.',
        provider: 'slack',
        sink_id: 1,
        attempt_count: 1,
        http_status: 200,
      },
    });
    fireEvent.click(screen.getAllByText('Test')[0]);

    await waitFor(() => expect(notificationsApi.testSink).toHaveBeenCalledWith(1));
    await waitFor(() => screen.getByText('Accepted by Slack'));

    // The forbidden claim, which this surface must not make on any 2xx.
    expect(mockToast.success).not.toHaveBeenCalledWith('Test notification sent successfully.');
    expect(screen.getByText(/not proof a person received it/i)).toBeInTheDocument();
  });

  it('shows a rejected provider response as a failure, not a success', async () => {
    render(<NotificationsPage />);
    await waitFor(() => screen.getByText('Slack Sink'));

    notificationsApi.testSink.mockResolvedValue({
      data: {
        ok: false,
        state: 'terminal',
        reason_code: 'retry_exhausted',
        message: 'The provider is temporarily unavailable.',
        error: 'The provider is temporarily unavailable.',
        provider: 'slack',
        sink_id: 1,
        attempt_count: 3,
        http_status: 500,
      },
    });
    fireEvent.click(screen.getAllByText('Test')[0]);

    await waitFor(() => screen.getByText('Slack did not accept it'));
    expect(screen.getByText('500')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(mockToast.success).not.toHaveBeenCalled();
  });

  it('names which destination the result belongs to', async () => {
    render(<NotificationsPage />);
    await waitFor(() => screen.getByText('Slack Sink'));

    notificationsApi.testSink.mockResolvedValue({
      data: {
        ok: false,
        state: 'terminal',
        reason_code: 'authentication_rejected',
        message: 'The provider rejected the destination credentials.',
        provider: 'slack',
        sink_id: 1,
        attempt_count: 1,
        http_status: 401,
      },
    });
    fireEvent.click(screen.getAllByText('Test')[0]);

    await waitFor(() => screen.getByText('Slack did not accept it'));
    // A provider name alone cannot identify one of several Slack destinations.
    expect(
      screen.getByText('Slack Sink', { selector: '.delivery-result__destination' })
    ).toBeInTheDocument();
  });

  it('tells the operator what to do when stored credentials cannot be read', async () => {
    render(<NotificationsPage />);
    await waitFor(() => screen.getByText('Slack Sink'));

    notificationsApi.testSink.mockResolvedValue({
      data: {
        ok: false,
        state: 'terminal',
        reason_code: 'credential_unavailable',
        message: 'Destination credentials are unavailable.',
        provider: 'slack',
        sink_id: 1,
        attempt_count: 0,
      },
    });
    fireEvent.click(screen.getAllByText('Test')[0]);

    expect(await screen.findByText(/re-enter them for this destination/i)).toBeInTheDocument();
  });

  it('names the provider when the request never reaches the server', async () => {
    render(<NotificationsPage />);
    await waitFor(() => screen.getByText('Slack Sink'));

    notificationsApi.testSink.mockRejectedValue(new Error('Network Error'));
    fireEvent.click(screen.getAllByText('Test')[0]);

    // Read from the sink's `provider_type`; the row has no `type` field at all.
    await waitFor(() => screen.getByText('Slack did not accept it'));
    expect(screen.getByText(/never left Circuit Breaker/i)).toBeInTheDocument();
  });

  it('adds a new destination', async () => {
    render(<NotificationsPage />);
    fireEvent.click(screen.getByText(/Add Destination/));
    expect(screen.getByTestId('form-modal')).toBeDefined();

    notificationsApi.createSink.mockResolvedValue({ data: { id: 3, name: 'new.destination' } });
    fireEvent.click(screen.getByText('Submit'));

    await waitFor(() => expect(notificationsApi.createSink).toHaveBeenCalled());
    expect(mockToast.success).toHaveBeenCalledWith('Sink created.');
  });
});

describe('NotificationsPage sink editing', () => {
  // A sink as the API now serves it: the webhook URL is masked and carries a
  // read-only set-flag alongside it (INC-06).
  const MASK = 'https://hooks.slack.com/services/•••';
  const maskedSink = {
    id: 7,
    name: 'Ops Slack',
    provider_type: 'slack',
    enabled: true,
    provider_config: { webhook_url: MASK, webhook_url_set: true },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    notificationsApi.listSinks.mockResolvedValue({ data: [maskedSink] });
    notificationsApi.listRoutes.mockResolvedValue({ data: [] });
    notificationsApi.updateSink.mockResolvedValue({ data: maskedSink });
  });

  async function editAndSave() {
    render(<NotificationsPage />);
    await waitFor(() => screen.getByText('Ops Slack'));
    fireEvent.click(screen.getAllByText('Edit')[0]);
    fireEvent.click(screen.getByText('Save As Seeded'));
    await waitFor(() => expect(notificationsApi.updateSink).toHaveBeenCalled());
    return notificationsApi.updateSink.mock.calls[0][1].provider_config;
  }

  it('sends back only the sink config fields, not the row envelope', async () => {
    const config = await editAndSave();
    expect(config).not.toHaveProperty('id');
    expect(config).not.toHaveProperty('provider_config');
  });

  it('does not write the read-only webhook_url_set flag into the config', async () => {
    const config = await editAndSave();
    expect(config).not.toHaveProperty('webhook_url_set');
  });

  it('round-trips the masked webhook URL so the backend keeps the stored secret', async () => {
    const config = await editAndSave();
    expect(config.webhook_url).toBe(MASK);
  });
});
