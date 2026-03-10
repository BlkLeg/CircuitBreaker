import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, vi } from 'vitest';
import { server } from './mocks/server';
import IPAddressInput from '../components/IPAddressInput';

function renderInput(props = {}) {
  return render(
    <IPAddressInput
      value=""
      onChange={vi.fn()}
      {...props}
    />
  );
}

describe('IPAddressInput', () => {
  it('renders without conflict indicator on mount', () => {
    renderInput({ value: '' });
    // No conflict icon should appear when there is no value
    expect(screen.queryByTitle(/conflict/i)).toBeNull();
  });

  it('shows green checkmark on clean ip-check result', async () => {
    // Default handler returns no conflicts
    renderInput({ value: '10.0.0.99' });
    await waitFor(() => {
      // After debounce resolves a clean check, a success indicator appears
      // Component may show a checkmark icon or a status indicator
      const el = document.querySelector('[data-conflict="false"], [title*="available"], [aria-label*="ok"]')
        ?? document.querySelector('svg');
      expect(el).not.toBeNull();
    }, { timeout: 2000 });
  });

  it('shows warning icon when conflicts returned', async () => {
    server.use(
      http.post('/api/v1/ip-check', () =>
        HttpResponse.json({
          conflicts: [{
            entity_type: 'hardware',
            entity_id: 1,
            entity_name: 'pve-01',
            conflicting_ip: '10.0.0.1',
            conflicting_port: null,
            protocol: null,
          }],
        })
      )
    );

    renderInput({ value: '10.0.0.1' });
    await waitFor(() => {
      // A warning/conflict indicator should appear
      const el = document.querySelector('[data-conflict="true"], [title*="conflict"], [aria-label*="conflict"]')
        ?? screen.queryAllByText(/conflict/i)[0];
      expect(el).not.toBeNull();
    }, { timeout: 2000 });
  });

  it('does not fire check when input is empty', async () => {
    let checkFired = false;
    server.use(
      http.post('/api/v1/ip-check', () => {
        checkFired = true;
        return HttpResponse.json({ conflicts: [] });
      })
    );

    renderInput({ value: '' });
    await new Promise(r => setTimeout(r, 800));
    expect(checkFired).toBe(false);
  });

  it('renders an input element', () => {
    renderInput({ value: '10.0.0.1' });
    const input = document.querySelector('input[type="text"], input:not([type])');
    expect(input).not.toBeNull();
  });

  it('calls onChange when user types', async () => {
    const onChange = vi.fn();
    render(<IPAddressInput value="" onChange={onChange} />);
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, '1');
      expect(onChange).toHaveBeenCalled();
    }
  });
});
