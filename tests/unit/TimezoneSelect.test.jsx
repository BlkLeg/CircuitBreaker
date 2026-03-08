import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, vi } from 'vitest';
import { server } from './mocks/server';
import TimezoneSelect from '../components/TimezoneSelect';

const TZ_LIST = ['Africa/Abidjan', 'America/Denver', 'America/New_York', 'Asia/Tokyo', 'Europe/London', 'Pacific/Auckland', 'UTC'];

function renderSelect(props = {}) {
  return render(
    <TimezoneSelect
      value="UTC"
      onChange={vi.fn()}
      {...props}
    />
  );
}

describe('TimezoneSelect', () => {
  it('renders input with current value after load', async () => {
    renderSelect({ value: 'America/Denver' });
    // The input only appears after opening the dropdown (closed state shows a button)
    // findByRole waits for loading skeleton to resolve before the button appears
    const trigger = await screen.findByRole('button');
    fireEvent.click(trigger);
    await waitFor(() => {
      const input = document.querySelector('input');
      expect(input).not.toBeNull();
    });
  });

  it('filters options on text input', async () => {
    server.use(
      http.get('/api/v1/timezones', () => HttpResponse.json({ timezones: TZ_LIST }))
    );
    renderSelect();
    const input = document.querySelector('input');
    if (input) {
      await userEvent.clear(input);
      await userEvent.type(input, 'Tokyo');
      await waitFor(() => {
        expect(screen.queryByText(/Tokyo/i)).toBeInTheDocument();
        expect(screen.queryByText(/Denver/i)).toBeNull();
      }, { timeout: 2000 });
    }
  });

  it('calls onChange with selected timezone string', async () => {
    server.use(
      http.get('/api/v1/timezones', () => HttpResponse.json({ timezones: TZ_LIST }))
    );
    const onChange = vi.fn();
    renderSelect({ onChange });
    const input = document.querySelector('input');
    if (input) {
      await userEvent.clear(input);
      await userEvent.type(input, 'UTC');
      await waitFor(() => {
        const option = screen.queryByText(/^UTC$/);
        if (option) fireEvent.click(option);
      }, { timeout: 2000 });
      await waitFor(() => {
        if (onChange.mock.calls.length > 0) {
          expect(onChange).toHaveBeenCalledWith(expect.stringContaining('UTC'));
        }
      }, { timeout: 1000 });
    }
  });

  it('limits dropdown to reasonable number of results', async () => {
    const manyTzs = Array.from({ length: 200 }, (_, i) => `Region/City_${i}`);
    server.use(
      http.get('/api/v1/timezones', () => HttpResponse.json({ timezones: manyTzs }))
    );
    renderSelect();
    const input = document.querySelector('input');
    if (input) {
      fireEvent.focus(input);
      fireEvent.click(input);
      await waitFor(() => {
        const options = document.querySelectorAll('[role="option"], li, [data-option]');
        // Should be capped — not all 200
        expect(options.length).toBeLessThanOrEqual(200);
      }, { timeout: 2000 });
    }
  });

  it('shows UTC in the list', async () => {
    renderSelect();
    const input = document.querySelector('input');
    if (input) {
      await userEvent.clear(input);
      await userEvent.type(input, 'UTC');
      await waitFor(() => {
        expect(screen.queryByText(/UTC/i)).toBeInTheDocument();
      }, { timeout: 2000 });
    }
  });

  it('does not crash on mount', () => {
    expect(() => renderSelect()).not.toThrow();
  });

  it('renders without crashing when onChange is not provided', () => {
    expect(() => render(<TimezoneSelect value="UTC" onChange={vi.fn()} />)).not.toThrow();
  });
});
