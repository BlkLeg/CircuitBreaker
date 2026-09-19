import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StatTile from '../components/common/StatTile';
import Toggle from '../components/common/Toggle';

describe('StatTile', () => {
  it('renders the value the caller formatted', () => {
    render(<StatTile label="CPU" value="12%" />);
    expect(screen.getByText('CPU')).toBeTruthy();
    expect(screen.getByText('12%')).toBeTruthy();
  });

  it('renders an em dash when there is no value', () => {
    // The fleet table left these cells blank, which reads as a rendering
    // failure rather than as "this agent has never reported".
    render(<StatTile label="CPU" value={null} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('draws a sparkline once there are at least two points', () => {
    const { container } = render(<StatTile label="CPU" value="12%" points={[1, 4, 2, 8]} />);
    expect(container.querySelector('polyline').getAttribute('points')).toBeTruthy();
  });

  it('draws no sparkline for a single point, which has no shape', () => {
    const { container } = render(<StatTile label="CPU" value="12%" points={[4]} />);
    expect(container.querySelector('polyline')).toBeNull();
  });

  it('marks a threshold crossing with data-hot rather than a colour class', () => {
    const { container } = render(<StatTile label="CPU" value="93%" points={[90, 93]} hot />);
    expect(container.querySelector('.cb-tile').getAttribute('data-hot')).toBe('true');
  });

  it('hides the sparkline from assistive technology, since the value is text', () => {
    const { container } = render(<StatTile label="CPU" value="12%" points={[1, 2]} />);
    expect(container.querySelector('svg').getAttribute('aria-hidden')).toBe('true');
  });
});

describe('Toggle', () => {
  it('exposes itself as a switch with its checked state', () => {
    render(<Toggle checked label="Host telemetry" onChange={() => {}} />);
    const el = screen.getByRole('switch', { name: /Host telemetry/ });
    expect(el.getAttribute('aria-checked')).toBe('true');
  });

  it('reports the flipped value, not the current one', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} label="Remote probe" onChange={onChange} />);
    await userEvent.click(screen.getByRole('switch', { name: /Remote probe/ }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('does not fire when disabled', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} label="Local discovery" onChange={onChange} disabled />);
    await userEvent.click(screen.getByRole('switch', { name: /Local discovery/ }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('puts the note in the accessible name, so the reason is not colour-only', () => {
    // A capability locked until approval must say so to a screen reader, not
    // only to an eye reading dimmed text beside it.
    render(
      <Toggle
        checked={false}
        label="Host telemetry"
        note="locked until approved"
        disabled
        onChange={() => {}}
      />
    );
    expect(
      screen.getByRole('switch', { name: 'Host telemetry — locked until approved' })
    ).toBeTruthy();
  });
});
