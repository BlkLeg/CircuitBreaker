import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import StatusPill from '../components/monitors/StatusPill.jsx';
import CheckHistoryBar from '../components/monitors/CheckHistoryBar.jsx';

describe('monitor status colours', () => {
  it('pulls every status colour from a theme token', () => {
    for (const status of ['up', 'down', 'pending', 'maintenance']) {
      const { unmount } = render(<StatusPill status={status} />);
      const pill = screen.getByText(new RegExp(status, 'i'));
      expect(pill.style.background).toContain('var(--color-');
      expect(pill.style.background).not.toMatch(/#[0-9a-f]{6}/i);
      unmount();
    }
  });

  it('renders a paused pill from the muted token', () => {
    render(<StatusPill status="up" enabled={false} />);
    const pill = screen.getByText('Paused');
    expect(pill.style.background).toBe('var(--color-muted)');
  });

  it('sizes check-history segments by the size prop', () => {
    const events = [{ id: 1, status_to: 'up', msg: 'ok', created_at: '2026-07-26T00:00:00Z' }];
    const { container, unmount } = render(<CheckHistoryBar events={events} />);
    expect(container.querySelector('div > span').style.width).toBe('4px');
    unmount();

    const { container: md } = render(<CheckHistoryBar events={events} size="md" />);
    expect(md.querySelector('div > span').style.width).toBe('6px');
  });
});
