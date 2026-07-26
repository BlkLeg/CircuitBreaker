import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import StatusPing from '../components/monitors/StatusPing.jsx';

describe('StatusPing', () => {
  it('pulses for every live status, with a faster ring while down', () => {
    const { container: down } = render(<StatusPing status="down" />);
    const downRing = down.querySelector('.mon-ping-ring');
    expect(downRing).toBeTruthy();
    expect(downRing.style.animationDuration).toBe('1.1s');

    const { container: up } = render(<StatusPing status="up" />);
    expect(up.querySelector('.mon-ping-ring').style.animationDuration).toBe('1.9s');

    const { container: pending } = render(<StatusPing status="pending" />);
    expect(pending.querySelector('.mon-ping-ring').style.animationDuration).toBe('1.5s');
  });

  it('is a static dot when paused — nothing is being checked', () => {
    const { container } = render(<StatusPing status="paused" />);
    expect(container.querySelector('.mon-ping-ring')).toBeNull();
    expect(container.querySelector('.mon-ping-core')).toBeTruthy();
  });

  it('carries the status for CSS and hides itself from screen readers', () => {
    const { container } = render(<StatusPing status="up" size={10} />);
    const ping = container.querySelector('.mon-ping');
    expect(ping.dataset.status).toBe('up');
    expect(ping.getAttribute('aria-hidden')).toBe('true');
    expect(ping.style.width).toBe('10px');
  });
});
