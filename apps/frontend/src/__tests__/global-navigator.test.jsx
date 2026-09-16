import React from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const searchPage = vi.fn().mockResolvedValue({ data: { items: [], limit: 25, has_more: false } });
vi.mock('../api/client', () => ({ searchApi: { searchPage: (...a) => searchPage(...a) } }));

const mockAuth = { current: { user: { id: 1, role: 'admin' }, isMasquerade: false } };
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => mockAuth.current }));
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false }));

import GlobalNavigator from '../components/navigation/GlobalNavigator.jsx';

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

function open(props = {}) {
  const onClose = props.onClose ?? vi.fn();
  const onNavigate = props.onNavigate ?? vi.fn();
  const utils = render(
    <MemoryRouter>
      <GlobalNavigator isOpen onClose={onClose} onNavigate={onNavigate} />
    </MemoryRouter>
  );
  return { ...utils, onClose, onNavigate };
}

beforeEach(() => {
  localStorage.clear();
  searchPage.mockClear();
  mockAuth.current = { user: { id: 1, role: 'admin' }, isMasquerade: false };
});

afterEach(cleanup);

describe('GlobalNavigator', () => {
  it('renders nothing when closed', () => {
    render(
      <MemoryRouter>
        <GlobalNavigator isOpen={false} onClose={vi.fn()} onNavigate={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the approved browse groups by default', () => {
    open();
    for (const group of ['Acquire', 'Inventory', 'Observe', 'Govern', 'System']) {
      expect(screen.getByTestId(`navigator-group-count-${group.toLowerCase()}`)).toBeTruthy();
    }
  });

  it('shows only approved modes and all lifecycle category filters', () => {
    open();
    expect(screen.getByRole('button', { name: /All pages/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Recent/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Planned/i })).toBeNull();
    for (const label of ['Everything', 'Acquire', 'Inventory', 'Observe', 'Govern', 'System']) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy();
    }
  });

  it('filters browse rows by category without limiting search', async () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'Observe' }));
    expect(screen.getByText('Monitors')).toBeTruthy();
    expect(screen.queryByText('Hardware')).toBeNull();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'hardware' } });
    await waitFor(() => expect(screen.getByText('Hardware')).toBeTruthy());
  });

  it('focuses the search field on open', async () => {
    open();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('searchbox')));
  });

  it('derives group counts from visible pages rather than a fixed number', () => {
    // Plan 01: "Counts derive from visible registered pages; do not hard-code
    // 21 for every role or release."
    open();
    const acquire = screen.getByTestId('navigator-group-count-acquire');
    expect(acquire.textContent).toBe('2');
  });

  it('shows fewer destinations to a viewer', () => {
    mockAuth.current = { user: { id: 2, role: 'viewer' }, isMasquerade: false };
    open();
    expect(screen.queryByText('Audit Log')).toBeNull();
    expect(screen.getByText('Map')).toBeTruthy();
  });

  it('filters as you type and labels the groups', async () => {
    open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'hardware' } });
    await waitFor(() => expect(screen.getByText('Pages & Settings')).toBeTruthy());
    expect(screen.getByText('Hardware')).toBeTruthy();
  });

  it('navigates with Enter on the highlighted row', async () => {
    const { onNavigate } = open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'map' } });
    await waitFor(() => expect(screen.getByText('Map')).toBeTruthy());
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'Enter' });
    expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({ path: '/map' }));
  });

  it('moves the highlight with the arrow keys', async () => {
    open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'a' } });
    await waitFor(() =>
      expect(document.querySelectorAll('.navigator-row-main').length).toBeGreaterThan(1)
    );
    const rows = [...document.querySelectorAll('.navigator-row-main')];
    const first = rows[0];
    expect(first.getAttribute('data-active')).toBe('true');
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'ArrowDown' });
    expect(rows[1].getAttribute('data-active')).toBe('true');
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'ArrowUp' });
    expect(rows[0].getAttribute('data-active')).toBe('true');
  });

  it('closes on Escape', () => {
    const { onClose } = open();
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('announces result counts in a live region', async () => {
    open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'map' } });
    await waitFor(() => {
      const status = screen.getByRole('status');
      expect(status.textContent).toMatch(/result/i);
    });
  });

  it('reports an asset search failure with a retry, not "no results"', async () => {
    searchPage.mockRejectedValueOnce(new Error('boom'));
    open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nas' } });
    await waitFor(() => expect(screen.getByText(/could not be searched/i)).toBeTruthy(), {
      timeout: 2000,
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeTruthy();
    expect(screen.queryByText(/no results/i)).toBeNull();
  });

  it('keeps page results visible while asset search is failing', async () => {
    searchPage.mockRejectedValueOnce(new Error('boom'));
    open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'map' } });
    await waitFor(() => expect(screen.getByText(/could not be searched/i)).toBeTruthy(), {
      timeout: 2000,
    });
    expect(screen.getByText('Map')).toBeTruthy();
  });

  it('pins a destination and shows it in the Pinned group', async () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'Pin Map' }));
    await waitFor(() => expect(screen.getByText('Pinned')).toBeTruthy());
  });

  it('does not leak pins between users', async () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'Pin Map' }));
    await waitFor(() => expect(screen.getByText('Pinned')).toBeTruthy());
    cleanup();
    mockAuth.current = { user: { id: 999, role: 'admin' }, isMasquerade: false };
    open();
    expect(document.querySelector('.navigator-pinned button')).toBeNull();
  });

  it('traps focus inside the panel when it lands outside after Tab', async () => {
    // A mouse click can move focus to a row's Pin button, off the search
    // input where the Tab handler lives -- from there a plain Tab should not
    // be able to walk out of the panel and under aria-modal="true".
    open();
    const pinButton = screen.getByRole('button', { name: 'Pin Map' });
    pinButton.focus();
    expect(document.activeElement).toBe(pinButton);

    const outside = document.createElement('button');
    outside.textContent = 'outside';
    document.body.appendChild(outside);
    outside.focus();

    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('searchbox')));
    document.body.removeChild(outside);
  });

  it('loops Tab and Shift+Tab across every interactive control', () => {
    open();
    const dialog = screen.getByRole('dialog');
    const controls = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled])')];
    const first = controls[0];
    const last = controls.at(-1);

    last.focus();
    fireEvent.keyDown(last, { key: 'Tab' });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('marks the current page without relying on color alone', () => {
    render(
      <MemoryRouter initialEntries={['/hardware']}>
        <GlobalNavigator isOpen onClose={vi.fn()} onNavigate={vi.fn()} />
      </MemoryRouter>
    );
    const hardware = document.querySelector('.navigator-row-main[aria-current="page"]');
    expect(hardware).toBeTruthy();
    expect(hardware).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Current')).toBeTruthy();
  });

  it('exposes each result group as a labelled ARIA group', () => {
    open();
    const label = document.getElementById('navigator-group-label-acquire');
    expect(label).toBeTruthy();
    expect(label.textContent).toMatch(/Acquire/);
    const group = label.closest('[role="group"]');
    expect(group).toBeTruthy();
    expect(group.getAttribute('aria-labelledby')).toBe('navigator-group-label-acquire');
  });

  it('does not yank focus back after an action hands off to a modal', async () => {
    const { onNavigate, onClose } = open();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'login' } });
    await waitFor(() => expect(screen.getByText('Login')).toBeTruthy());
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'Enter' });
    expect(onClose).toHaveBeenCalled();
    expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({ actionFn: 'openAuthModal' }));

    // Simulate the modal the action opened grabbing focus. The trap must not
    // fight this and drag focus back into the (still-mounted, in this test)
    // navigator panel.
    const modalField = document.createElement('input');
    document.body.appendChild(modalField);
    modalField.focus();
    expect(document.activeElement).toBe(modalField);
    document.body.removeChild(modalField);
  });

  it('restores focus to the real opener on Escape', () => {
    const trigger = document.createElement('button');
    trigger.textContent = 'Open navigator';
    document.body.appendChild(trigger);
    trigger.focus();

    const { onClose } = open();
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
    document.body.removeChild(trigger);
  });

  it('uses no literal colours', async () => {
    // Plan 00: a component using var(...) with a permanently dark value is not
    // theme-aware, and a literal hex is worse.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const url = await import('node:url');
    const here = path.dirname(url.fileURLToPath(import.meta.url));
    for (const file of ['components/navigation/GlobalNavigator.jsx', 'styles/navigator.css']) {
      const source = fs.readFileSync(path.resolve(here, '..', file), 'utf8');
      const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
      expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
  });
});
