import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const list = vi.fn();
const requeue = vi.fn();
const discard = vi.fn();

vi.mock('../api/client', () => ({
  failedMessagesApi: {
    list: (...a) => list(...a),
    requeue: (...a) => requeue(...a),
    discard: (...a) => discard(...a),
  },
}));

import ParkedMessagesPage from '../pages/ParkedMessagesPage.jsx';

const parked = (over = {}) => ({
  id: 1,
  stream: 'CB_MONITOR',
  subject: 'monitor.result',
  consumer: 'monitor-poll',
  error: 'ValueError: expected a dict, got list',
  delivered_count: 5,
  parked_at: '2026-09-17T10:00:00Z',
  requeued_at: null,
  discarded_at: null,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue({ data: [parked()] });
  requeue.mockResolvedValue({ data: parked({ requeued_at: '2026-09-17T11:00:00Z' }) });
  discard.mockResolvedValue({ data: parked({ discarded_at: '2026-09-17T11:00:00Z' }) });
});

describe('ParkedMessagesPage', () => {
  it('shows a skeleton while loading, not a bare string', () => {
    render(<ParkedMessagesPage />);

    expect(screen.getByTestId('parked-loading')).toBeInTheDocument();
  });

  it('shows what an operator triages on', async () => {
    render(<ParkedMessagesPage />);

    await waitFor(() => expect(screen.getByText('monitor.result')).toBeInTheDocument());
    expect(screen.getByText(/monitor-poll/)).toBeInTheDocument();
    expect(screen.getByText(/expected a dict, got list/)).toBeInTheDocument();
    expect(screen.getByText(/5/)).toBeInTheDocument();
  });

  it('reads an empty queue as the healthy state it is', async () => {
    list.mockResolvedValue({ data: [] });

    render(<ParkedMessagesPage />);

    await waitFor(() => expect(screen.getByText(/no parked messages/i)).toBeInTheDocument());
  });

  it('hides resolved rows until asked for them', async () => {
    render(<ParkedMessagesPage />);
    await waitFor(() => expect(list).toHaveBeenCalled());

    expect(list.mock.calls[0][0]).toMatchObject({ include_resolved: false });

    fireEvent.click(screen.getByLabelText(/show resolved/i));

    await waitFor(() =>
      expect(list.mock.calls.at(-1)[0]).toMatchObject({ include_resolved: true })
    );
  });

  it('requeues a message and refreshes the page', async () => {
    render(<ParkedMessagesPage />);
    await waitFor(() => expect(screen.getByText('monitor.result')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /requeue/i }));

    await waitFor(() => expect(requeue).toHaveBeenCalledWith(1));
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('says the bus is down rather than blaming the message', async () => {
    // 502 is the service refusing to stamp a row while nats_client.publish
    // buffers into an outage. The message is fine; the bus is not.
    requeue.mockRejectedValue({
      statusCode: 502,
      userMessage: 'Message bus is not connected.',
    });

    render(<ParkedMessagesPage />);
    await waitFor(() => expect(screen.getByText('monitor.result')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /requeue/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent(/still parked/i);
    expect(screen.getByRole('alert')).not.toHaveTextContent(/could not be recovered/i);
  });

  it('treats an already-resolved message as news, not failure', async () => {
    requeue.mockRejectedValue({
      statusCode: 409,
      userMessage: 'Message already resolved.',
    });

    render(<ParkedMessagesPage />);
    await waitFor(() => expect(screen.getByText('monitor.result')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /requeue/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/already acted on/i));
    // It refetches, because someone else's action is the current truth.
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('confirms a discard and names the message', async () => {
    render(<ParkedMessagesPage />);
    await waitFor(() => expect(screen.getByText('monitor.result')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /discard/i }));

    // The dialog names the message and what is lost; nothing is discarded until
    // the operator confirms.
    expect(screen.getByText(/discard the parked message monitor\.result/i)).toBeInTheDocument();
    expect(screen.getByText(/stops being recoverable/i)).toBeInTheDocument();
    expect(discard).not.toHaveBeenCalled();
  });

  it('pages without putting its offset in the URL', async () => {
    list.mockResolvedValue({ data: Array.from({ length: 100 }, (_, i) => parked({ id: i + 1 })) });

    render(<ParkedMessagesPage />);
    await waitFor(() => expect(screen.getByRole('button', { name: /older/i })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: /older/i }));

    await waitFor(() => expect(list.mock.calls.at(-1)[0]).toMatchObject({ offset: 100 }));
    expect(window.location.search).toBe('');
  });

  it('renders an error with retry rather than an empty table', async () => {
    list.mockRejectedValue({ userMessage: 'boom' });

    render(<ParkedMessagesPage />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
