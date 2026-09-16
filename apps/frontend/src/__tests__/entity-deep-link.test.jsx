import React, { useCallback, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { useEntityDeepLink } from '../hooks/useEntityDeepLink';

function Harness({ loadEntity, onError = () => {} }) {
  const [selected, setSelected] = useState(null);
  const location = useLocation();
  const reportError = useCallback((message) => onError(message), [onError]);
  const { openEntity, closeEntity } = useEntityDeepLink({
    loadEntity,
    selectedId: selected?.id,
    onSelect: setSelected,
    onError: reportError,
  });

  return (
    <div>
      <output aria-label="location">{`${location.pathname}${location.search}`}</output>
      <output aria-label="selection">{selected?.name ?? 'none'}</output>
      <button type="button" onClick={() => openEntity({ id: 9, name: 'row-nine' })}>
        Open row
      </button>
      <button type="button" onClick={closeEntity}>
        Close detail
      </button>
    </div>
  );
}

function renderHarness(initialEntry, props) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Harness {...props} />
    </MemoryRouter>
  );
}

describe('useEntityDeepLink', () => {
  it('resolves a direct URL independently of the current list', async () => {
    const loadEntity = vi.fn().mockResolvedValue({ id: 42, name: 'direct-target' });
    renderHarness('/hardware?entity=42&tag=prod', { loadEntity });

    await waitFor(() =>
      expect(screen.getByLabelText('selection')).toHaveTextContent('direct-target')
    );
    expect(loadEntity).toHaveBeenCalledWith(42);
    expect(screen.getByLabelText('location')).toHaveTextContent('/hardware?entity=42&tag=prod');
  });

  it('pushes row selection and removes only entity on close', async () => {
    renderHarness('/hardware?tag=prod', { loadEntity: vi.fn() });
    fireEvent.click(screen.getByRole('button', { name: 'Open row' }));
    expect(screen.getByLabelText('selection')).toHaveTextContent('row-nine');
    expect(screen.getByLabelText('location')).toHaveTextContent('/hardware?tag=prod&entity=9');

    fireEvent.click(screen.getByRole('button', { name: 'Close detail' }));
    expect(screen.getByLabelText('selection')).toHaveTextContent('none');
    expect(screen.getByLabelText('location')).toHaveTextContent('/hardware?tag=prod');
  });

  it('rejects malformed IDs without making a request', async () => {
    const loadEntity = vi.fn();
    const onError = vi.fn();
    renderHarness('/hardware?entity=not-an-id', { loadEntity, onError });

    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringMatching(/invalid/i)));
    expect(loadEntity).not.toHaveBeenCalled();
    expect(screen.getByLabelText('location')).toHaveTextContent('/hardware');
  });

  it('removes an inaccessible target and shows only a sanitized error', async () => {
    const loadEntity = vi.fn().mockRejectedValue(new Error('secret backend detail'));
    const onError = vi.fn();
    renderHarness('/hardware?entity=77', { loadEntity, onError });

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).not.toContain('secret backend detail');
    expect(screen.getByLabelText('location')).toHaveTextContent('/hardware');
  });
});
