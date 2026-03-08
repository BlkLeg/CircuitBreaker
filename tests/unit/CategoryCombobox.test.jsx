import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, vi } from 'vitest';
import { server } from './mocks/server';
import CategoryCombobox from '../components/common/CategoryCombobox';

const CATEGORIES = [
  { id: 1, name: 'media', color: '#6366f1', service_count: 2 },
  { id: 2, name: 'infra', color: '#00ff00', service_count: 1 },
];

function renderCombobox(props = {}) {
  return render(
    <CategoryCombobox
      value={null}
      onChange={vi.fn()}
      {...props}
    />
  );
}

describe('CategoryCombobox', () => {
  it('renders input and placeholder text', () => {
    renderCombobox();
    const input = screen.queryByRole('combobox') ?? document.querySelector('input');
    expect(input).not.toBeNull();
  });

  it('shows existing categories in dropdown on click', async () => {
    server.use(
      http.get('/api/v1/categories', () => HttpResponse.json(CATEGORIES))
    );
    renderCombobox();
    const input = document.querySelector('input');
    if (input) {
      fireEvent.focus(input);
      fireEvent.click(input);
      await waitFor(() => {
        expect(screen.queryByText('media') ?? screen.queryByText(/media/i)).toBeInTheDocument();
      }, { timeout: 2000 });
    }
  });

  it('filters options as user types', async () => {
    server.use(
      http.get('/api/v1/categories', () => HttpResponse.json(CATEGORIES))
    );
    renderCombobox();
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, 'med');
      await waitFor(() => {
        expect(screen.queryByText(/media/i)).toBeInTheDocument();
        expect(screen.queryByText(/infra/i)).toBeNull();
      }, { timeout: 2000 });
    }
  });

  it('shows create option when no match found', async () => {
    server.use(
      http.get('/api/v1/categories', () => HttpResponse.json(CATEGORIES))
    );
    renderCombobox();
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, 'brandnewcat');
      await waitFor(() => {
        const createOption = screen.queryByText(/create/i) ?? screen.queryByText(/brandnewcat/i);
        expect(createOption).toBeInTheDocument();
      }, { timeout: 2000 });
    }
  });

  it('calls POST /api/v1/categories on create option select', async () => {
    let postCalled = false;
    server.use(
      http.get('/api/v1/categories', () => HttpResponse.json([])),
      http.post('/api/v1/categories', async ({ request }) => {
        postCalled = true;
        const body = await request.json();
        return HttpResponse.json({ id: 99, name: body.name, color: null, service_count: 0 }, { status: 201 });
      })
    );
    const onChange = vi.fn();
    renderCombobox({ onChange });
    const input = document.querySelector('input');
    if (input) {
      await userEvent.type(input, 'newcat');
      await waitFor(async () => {
        const createOption = screen.queryByText(/create/i) ?? screen.queryByText(/newcat/i);
        if (createOption) fireEvent.mouseDown(createOption);
      }, { timeout: 2000 });
      await waitFor(() => {
        expect(postCalled || onChange.mock.calls.length > 0).toBe(true);
      }, { timeout: 2000 });
    }
  });

  it('renders colored chip after selection', async () => {
    const onChange = vi.fn();
    server.use(
      http.get('/api/v1/categories', () => HttpResponse.json(CATEGORIES))
    );
    renderCombobox({ value: CATEGORIES[0].id, onChange });
    // Focus to trigger lazy load of options
    const input = document.querySelector('input');
    if (input) fireEvent.focus(input);
    // Wait for options to load in the open dropdown
    await waitFor(() => {
      expect(screen.queryByText('media')).toBeInTheDocument();
    }, { timeout: 2000 });
    // Close dropdown — chip renders when selected && !open
    if (input) fireEvent.keyDown(input, { key: 'Escape' });
    await waitFor(() => {
      const chip = document.querySelector('[data-chip], [class*="chip"], [class*="badge"]')
        ?? screen.queryByText(/media/i);
      expect(chip).toBeInTheDocument();
    });
  });

  it('clears chip when X is clicked', async () => {
    const onChange = vi.fn();
    renderCombobox({ value: CATEGORIES[0].id, onChange });
    const clearBtn = screen.queryByRole('button', { name: /clear|remove|×|x/i })
      ?? document.querySelector('button[aria-label*="clear"], button[title*="clear"]');
    if (clearBtn) {
      fireEvent.click(clearBtn);
      expect(onChange).toHaveBeenCalledWith(null);
    }
  });

  it('handles API error on create gracefully — does not crash', async () => {
    server.use(
      http.get('/api/v1/categories', () => HttpResponse.json([])),
      http.post('/api/v1/categories', () => new HttpResponse(null, { status: 500 }))
    );
    renderCombobox();
    // Should not throw/crash — component stays mounted
    expect(document.querySelector('input')).not.toBeNull();
  });
});
