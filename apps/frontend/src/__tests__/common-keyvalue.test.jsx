import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import KeyValue from '../components/common/KeyValue';
import CopyField from '../components/common/CopyField';

describe('KeyValue', () => {
  it('pairs every label with its value', () => {
    render(
      <KeyValue
        rows={[
          ['Scope mode', 'direct_private'],
          ['Concurrent hosts', 64],
        ]}
      />
    );
    expect(screen.getByText('Scope mode')).toBeTruthy();
    expect(screen.getByText('direct_private')).toBeTruthy();
    expect(screen.getByText('64')).toBeTruthy();
  });

  it('renders an em dash for a missing value rather than an empty cell', () => {
    // A blank cell is indistinguishable from a rendering bug. An em dash says
    // "this was asked for and there is no answer".
    render(<KeyValue rows={[['Host timeout', null]]} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('renders zero as zero, not as missing', () => {
    render(<KeyValue rows={[['Assigned', 0]]} />);
    expect(screen.getByText('0')).toBeTruthy();
  });
});

describe('CopyField', () => {
  beforeEach(() => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('copies the full value even when the display is truncated', async () => {
    const full = 'b030b0aa1cde5b3e9f77c2a10d4e6b81';
    render(<CopyField value={full} label="scope version" head={8} tail={4} />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy scope version' }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(full);
  });

  it('shows head and tail around an ellipsis so both ends stay comparable', () => {
    // Operators compare fingerprints character by character against what the
    // agent printed on the host. Truncating only the tail hides half of what
    // they are checking.
    render(<CopyField value="b030b0aa1cde5b3e9f77c2a10d4e6b81" label="fp" head={8} tail={4} />);
    expect(screen.getByText('b030b0aa…6b81')).toBeTruthy();
  });

  it('keeps the untruncated value available as a title', () => {
    const full = 'b030b0aa1cde5b3e9f77c2a10d4e6b81';
    const { container } = render(<CopyField value={full} label="fp" head={8} tail={4} />);
    expect(container.querySelector('code').getAttribute('title')).toBe(full);
  });

  it('shows the whole value when no truncation is asked for', () => {
    render(<CopyField value="direct_private" label="mode" />);
    expect(screen.getByText('direct_private')).toBeTruthy();
  });
});
