import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DeliveryResult from '../components/notifications/DeliveryResult';

const accepted = {
  ok: true,
  state: 'accepted',
  reason_code: 'provider_accepted',
  message: 'Slack accepted the request.',
  provider: 'slack',
  sink_id: 1,
  attempt_count: 1,
  http_status: 200,
};

const failed = {
  ok: false,
  state: 'terminal',
  reason_code: 'authentication_rejected',
  message: 'The provider rejected the destination credentials.',
  provider: 'slack',
  sink_id: 1,
  attempt_count: 1,
  http_status: 401,
};

describe('DeliveryResult', () => {
  it('announces the outcome to assistive technology', () => {
    render(<DeliveryResult result={accepted} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('states acceptance and its limit, never delivery', () => {
    render(<DeliveryResult result={accepted} />);

    expect(screen.getByText('Accepted by Slack')).toBeInTheDocument();
    expect(screen.getByText(/not proof a person received it/i)).toBeInTheDocument();
    expect(screen.queryByText(/delivered/i)).not.toBeInTheDocument();
  });

  it('shows the server reason and what to do about it', () => {
    render(<DeliveryResult result={failed} />);

    expect(screen.getByText('Slack did not accept it')).toBeInTheDocument();
    expect(
      screen.getByText('The provider rejected the destination credentials.')
    ).toBeInTheDocument();
    expect(screen.getByText(/check the destination credentials/i)).toBeInTheDocument();
  });

  it('reports the attempt count and status the server returned', () => {
    render(<DeliveryResult result={failed} />);

    expect(screen.getByText('Attempts')).toBeInTheDocument();
    expect(screen.getByText('HTTP status')).toBeInTheDocument();
    expect(screen.getByText('401')).toBeInTheDocument();
  });

  it('renders a pending test without pretending to know the outcome', () => {
    render(<DeliveryResult pending />);

    expect(screen.getByRole('status')).toHaveTextContent(/testing/i);
    expect(screen.queryByText(/accepted|failed/i)).not.toBeInTheDocument();
  });

  it('renders nothing before a test has been run', () => {
    const { container } = render(<DeliveryResult />);
    expect(container).toBeEmptyDOMElement();
  });

  it('uses theme tokens rather than baked-in colours', () => {
    const { container } = render(<DeliveryResult result={failed} />);
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});

describe('DeliveryResult destination', () => {
  it('names the destination the result belongs to', () => {
    render(<DeliveryResult result={failed} destination="Ops Slack" />);
    expect(screen.getByText('Ops Slack')).toBeInTheDocument();
  });

  it('names the destination while the test is still running', () => {
    render(<DeliveryResult pending destination="Ops Slack" />);
    expect(screen.getByRole('status')).toHaveTextContent(/testing ops slack/i);
  });

  it('renders without one when the caller has no name to give', () => {
    render(<DeliveryResult result={failed} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
