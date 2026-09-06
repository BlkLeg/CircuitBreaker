import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import AgentLiveStrip from '../components/agents/AgentLiveStrip';
import { FRESHNESS } from '../lib/agentFreshness';

const METRICS = [
  { key: 'cpu', label: 'CPU', value: '12%', points: [10, 12, 11, 12] },
  { key: 'mem', label: 'MEM', value: '38%', points: [37, 38] },
  { key: 'disk', label: 'DISK', value: null, points: [] },
];

const live = { level: FRESHNESS.LIVE, label: 'LIVE', animate: true };
const offline = { level: FRESHNESS.OFFLINE, label: 'OFFLINE', animate: false };

describe('AgentLiveStrip', () => {
  it('states the freshness in words, not only as a colour', () => {
    render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    expect(screen.getByText('LIVE')).toBeTruthy();
  });

  it('animates only while data is actually arriving', () => {
    // The rule this component exists to hold: a pulsing indicator over a dead
    // agent reports health the server has no evidence for.
    const { container, rerender } = render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    expect(container.querySelector('.agent-strip__pill').getAttribute('data-animate')).toBe('true');
    rerender(<AgentLiveStrip freshness={offline} metrics={METRICS} />);
    expect(container.querySelector('.agent-strip__pill').getAttribute('data-animate')).toBe(
      'false'
    );
  });

  it('carries the freshness level as data rather than as a class name', () => {
    const { container } = render(<AgentLiveStrip freshness={offline} metrics={METRICS} />);
    expect(container.querySelector('.agent-strip').getAttribute('data-level')).toBe('offline');
  });

  it('renders an em dash for a metric that has never reported', () => {
    render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('marks a metric over its threshold', () => {
    const { container } = render(
      <AgentLiveStrip
        freshness={live}
        metrics={[{ key: 'cpu', label: 'CPU', value: '93%', points: [90, 93], hot: true }]}
      />
    );
    expect(container.querySelector('[data-metric="cpu"]').getAttribute('data-hot')).toBe('true');
  });

  it('hides the sparklines from assistive technology', () => {
    // The numbers beside them are text, and the Telemetry tab carries the same
    // values. Asking a screen reader to track an animating polyline is asking
    // it to narrate noise.
    const { container } = render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    container.querySelectorAll('svg').forEach((svg) => {
      expect(svg.getAttribute('aria-hidden')).toBe('true');
    });
  });

  it('dims when the agent is not reporting but last known values remain', () => {
    const { container } = render(<AgentLiveStrip freshness={offline} metrics={METRICS} dimmed />);
    expect(container.querySelector('.agent-strip').getAttribute('data-dimmed')).toBe('true');
  });

  it('draws no sparkline for a series with fewer than two points', () => {
    const { container } = render(
      <AgentLiveStrip
        freshness={live}
        metrics={[{ key: 'net', label: 'NET', value: '0', points: [1] }]}
      />
    );
    expect(container.querySelector('polyline')).toBeNull();
  });
});
