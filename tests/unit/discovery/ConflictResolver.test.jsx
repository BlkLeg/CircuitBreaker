import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ConflictResolver from '../../components/discovery/ConflictResolver';

const CONFLICTS = [
  { field: 'mac_address', stored: 'AA:BB:CC:11:22:33', discovered: 'AA:BB:CC:44:55:66' },
  { field: 'hostname',    stored: 'old-hostname',       discovered: 'new-hostname.lan' },
];

describe('ConflictResolver', () => {
  it('renders one row per conflicting field', () => {
    render(<ConflictResolver conflicts={CONFLICTS} onChange={vi.fn()} />);
    expect(screen.getByText('mac_address')).toBeInTheDocument();
    expect(screen.getByText('hostname')).toBeInTheDocument();
  });

  it('defaults all rows to keep-existing selection', () => {
    render(<ConflictResolver conflicts={CONFLICTS} onChange={vi.fn()} />);
    const radios = screen.getAllByRole('radio');
    // 2 fields × 2 radios each = 4; existing ones (index 0, 2) should be checked
    expect(radios[0]).toBeChecked();   // mac_address existing
    expect(radios[1]).not.toBeChecked(); // mac_address discovered
    expect(radios[2]).toBeChecked();   // hostname existing
    expect(radios[3]).not.toBeChecked(); // hostname discovered
  });

  it('selecting use-discovered updates overrides via onChange', () => {
    const onChange = vi.fn();
    render(<ConflictResolver conflicts={CONFLICTS} onChange={onChange} />);
    // Click "discovered" radio for hostname
    const radios = screen.getAllByRole('radio');
    fireEvent.click(radios[3]); // hostname discovered
    expect(onChange).toHaveBeenCalledWith({ hostname: 'new-hostname.lan' });
  });

  it('onChange called with only fields where use-discovered is selected', () => {
    const onChange = vi.fn();
    render(<ConflictResolver conflicts={CONFLICTS} onChange={onChange} />);
    const radios = screen.getAllByRole('radio');
    // Select discovered for both
    fireEvent.click(radios[1]); // mac discovered
    fireEvent.click(radios[3]); // hostname discovered
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall).toEqual({
      mac_address: 'AA:BB:CC:44:55:66',
      hostname: 'new-hostname.lan',
    });
  });

  it('empty conflicts array renders nothing', () => {
    const { container } = render(<ConflictResolver conflicts={[]} onChange={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('switching back to existing removes field from overrides', () => {
    const onChange = vi.fn();
    render(<ConflictResolver conflicts={CONFLICTS} onChange={onChange} />);
    const radios = screen.getAllByRole('radio');
    fireEvent.click(radios[3]); // hostname discovered
    fireEvent.click(radios[2]); // hostname existing
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall).toEqual({});
  });
});
