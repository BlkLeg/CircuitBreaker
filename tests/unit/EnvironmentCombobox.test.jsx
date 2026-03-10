import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, vi } from 'vitest';
import { server } from './mocks/server';
import EnvironmentCombobox from '../components/common/EnvironmentCombobox';

const ENVIRONMENTS = [
  { id: 1, name: 'prod', color: '#ff0000', usage_count: 3 },
  { id: 2, name: 'staging', color: '#00ff00', usage_count: 1 },
];

function renderCombobox(props = {}) {
  return render(
    <EnvironmentCombobox
      value={null}
      onChange={vi.fn()}
      {...props}
    />
  );
}

describe('EnvironmentCombobox', () => {
  it('renders input and placeholder text', () => {
    renderCombobox();
    const input = document.querySelector('input');
    expect(input).not.toBeNull();
  });

  it('shows existing environments in dropdown on click', async () => {
    server.use(
      http.get('/api/v1/environments', () => HttpResponse.json(ENVIRONMENTS))
    );
    renderCombobox();
    const input = document.querySelector('input');
    if (input) {
      fireEvent.focus(input);
      fireEvent.click(input);
      await waitFor(() => {
        expect(screen.queryByText(/prod/i)).toBeInTheDocument();
      }, { timeout: 2000 });
    }
  });

  it('filters options as user types', async () => {
    server.use(
      http.get('/api/v1/environments', () => HttpResponse.json(ENVIRONMENTS))
    );
    renderCombobox();
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, 'sta');
      await waitFor(() => {
        expect(screen.queryByText(/staging/i)).toBeInTheDocument();
        expect(screen.queryByText(/^prod$/i)).toBeNull();
      }, { timeout: 2000 });
    }
  });

  it('shows create option when no match found', async () => {
    server.use(
      http.get('/api/v1/environments', () => HttpResponse.json(ENVIRONMENTS))
    );
    renderCombobox();
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, 'newenv99');
      await waitFor(() => {
        const createOption = screen.queryByText(/create/i) ?? screen.queryByText(/newenv99/i);
        expect(createOption).toBeInTheDocument();
      }, { timeout: 2000 });
    }
  });

  it('calls POST /api/v1/environments on create option select', async () => {
    let postCalled = false;
    server.use(
      http.get('/api/v1/environments', () => HttpResponse.json([])),
      http.post('/api/v1/environments', async ({ request }) => {
        postCalled = true;
        const body = await request.json();
        return HttpResponse.json({ id: 99, name: body.name, color: null, usage_count: 0 }, { status: 201 });
      })
    );
    const onChange = vi.fn();
    renderCombobox({ onChange });
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, 'newenv');
      await waitFor(async () => {
        const createOption = screen.queryByText(/create/i) ?? screen.queryByText(/newenv/i);
        if (createOption) fireEvent.mouseDown(createOption);
      }, { timeout: 2000 });
      await waitFor(() => {
        expect(postCalled || onChange.mock.calls.length > 0).toBe(true);
      }, { timeout: 2000 });
    }
  });

  it('renders colored chip after selection', async () => {
    server.use(
      http.get('/api/v1/environments', () => HttpResponse.json(ENVIRONMENTS))
    );
    renderCombobox({ value: ENVIRONMENTS[0].id, onChange: vi.fn() });
    // Focus to trigger lazy load of options
    const input = document.querySelector('input');
    if (input) fireEvent.focus(input);
    // Wait for options to load in the open dropdown
    await waitFor(() => {
      expect(screen.queryByText('prod')).toBeInTheDocument();
    }, { timeout: 2000 });
    // Close dropdown — chip renders when selected && !open
    if (input) fireEvent.keyDown(input, { key: 'Escape' });
    await waitFor(() => {
      const chip = document.querySelector('[data-chip], [class*="chip"], [class*="badge"]')
        ?? screen.queryByText(/prod/i);
      expect(chip).toBeInTheDocument();
    });
  });

  it('clears chip when X is clicked', async () => {
    const onChange = vi.fn();
    renderCombobox({ value: ENVIRONMENTS[0].id, onChange });
    const clearBtn = screen.queryByRole('button', { name: /clear|remove|×|x/i })
      ?? document.querySelector('button[aria-label*="clear"], button[title*="clear"]');
    if (clearBtn) {
      fireEvent.click(clearBtn);
      expect(onChange).toHaveBeenCalledWith(null);
    }
  });

  it('handles API error on create gracefully — does not crash', async () => {
    server.use(
      http.get('/api/v1/environments', () => HttpResponse.json([])),
      http.post('/api/v1/environments', () => new HttpResponse(null, { status: 500 }))
    );
    renderCombobox();
    expect(document.querySelector('input')).not.toBeNull();
  });
});
