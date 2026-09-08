import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';

const searchPage = vi.fn();
vi.mock('../api/client', () => ({ searchApi: { searchPage: (...args) => searchPage(...args) } }));

import { useNavigatorSearch } from '../hooks/useNavigatorSearch';

const ADMIN = { role: 'admin' };

function Probe({ query, user = ADMIN, enabled = true }) {
  const state = useNavigatorSearch({ query, user, enabled });
  return (
    <div>
      <span data-testid="local">{state.localResults.map((r) => r.label).join('|')}</span>
      <span data-testid="assets">{state.assetResults.map((r) => r.label).join('|')}</span>
      <span data-testid="loading">{String(state.assetsLoading)}</span>
      <span data-testid="error">{String(state.assetsError)}</span>
      <span data-testid="more">{String(state.hasMore)}</span>
      <button onClick={state.retryAssets}>retry</button>
    </div>
  );
}

function page(items, hasMore = false) {
  return { data: { items, limit: 25, has_more: hasMore } };
}

function hit(id, title, type = 'hardware') {
  return {
    id: `${type}-${id}`,
    type,
    title,
    description: null,
    action_url: '/hardware',
    entity_type: type,
    entity_id: id,
  };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchPage.mockReset();
  searchPage.mockResolvedValue(page([]));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('useNavigatorSearch', () => {
  it('returns local matches with no network call at all', () => {
    render(<Probe query="map" />);
    expect(screen.getByTestId('local').textContent).toContain('Map');
    expect(searchPage).not.toHaveBeenCalled();
  });

  it('debounces the remote call by about 200ms', async () => {
    const { rerender } = render(<Probe query="n" />);
    rerender(<Probe query="na" />);
    rerender(<Probe query="nas" />);
    expect(searchPage).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(searchPage).toHaveBeenCalledTimes(1));
    expect(searchPage.mock.calls[0][0]).toBe('nas');
  });

  it('deep-links the assets it returns', async () => {
    searchPage.mockResolvedValue(page([hit(42, 'nas-01')]));
    render(<Probe query="nas" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('assets').textContent).toBe('nas-01'));
  });

  it('ignores a stale response that lands after a newer one', async () => {
    // Plan 01: "ignore out-of-order responses". Without the guard, a slow
    // query for "n" overwrites the results for "nas" the moment it resolves.
    let resolveSlow;
    searchPage
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSlow = resolve;
          })
      )
      .mockResolvedValueOnce(page([hit(2, 'fresh')]));

    const { rerender } = render(<Probe query="slow" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    rerender(<Probe query="fresh" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('assets').textContent).toBe('fresh'));

    await act(async () => {
      resolveSlow(page([hit(1, 'stale')]));
    });
    expect(screen.getByTestId('assets').textContent).toBe('fresh');
  });

  it('reports a failure explicitly instead of showing "no results"', async () => {
    searchPage.mockRejectedValue(new Error('boom'));
    render(<Probe query="nas" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('true'));
  });

  it('keeps local results usable while assets are failing', async () => {
    searchPage.mockRejectedValue(new Error('boom'));
    render(<Probe query="map" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('true'));
    expect(screen.getByTestId('local').textContent).toContain('Map');
  });

  it('retries on demand', async () => {
    searchPage.mockRejectedValueOnce(new Error('boom')).mockResolvedValue(page([hit(9, 'back')]));
    render(<Probe query="nas" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('true'));
    await act(async () => {
      screen.getByText('retry').click();
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('assets').textContent).toBe('back'));
    expect(screen.getByTestId('error').textContent).toBe('false');
  });

  it('surfaces the truncation signal the backend sends', async () => {
    searchPage.mockResolvedValue(page([hit(1, 'a')], true));
    render(<Probe query="a" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('more').textContent).toBe('true'));
  });

  it('makes no call while disabled, so a closed navigator is silent', async () => {
    render(<Probe query="nas" enabled={false} />);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(searchPage).not.toHaveBeenCalled();
  });

  it('makes no call for an empty query and clears prior assets', async () => {
    searchPage.mockResolvedValue(page([hit(1, 'a')]));
    const { rerender } = render(<Probe query="a" />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await waitFor(() => expect(screen.getByTestId('assets').textContent).toBe('a'));
    rerender(<Probe query="  " />);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.getByTestId('assets').textContent).toBe('');
  });
});
