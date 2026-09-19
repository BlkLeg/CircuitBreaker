import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DetailHeader from '../components/common/DetailHeader';

function renderHeader(props = {}) {
  return render(
    <MemoryRouter>
      <DetailHeader backTo="/agents" backLabel="Agents" title="73235d37c4a3" {...props} />
    </MemoryRouter>
  );
}

describe('DetailHeader', () => {
  it('renders the title as the page heading', () => {
    renderHeader();
    expect(screen.getByRole('heading', { level: 1, name: '73235d37c4a3' })).toBeTruthy();
  });

  it('links back to the list it came from', () => {
    renderHeader();
    expect(screen.getByRole('link', { name: /Agents/ }).getAttribute('href')).toBe('/agents');
  });

  it('wraps every meta entry in its own element so separators can apply', () => {
    // The list page's PendingCells emitted a bare text node beside a span, and
    // the CSS separator is an adjacent-sibling rule that a text node cannot
    // satisfy — the fields ran together on screen. This component owns the
    // wrapper so a caller cannot reintroduce that.
    const { container } = renderHeader({ meta: ['pending', 'linux / amd64', 'v0.0.0-dev'] });
    const items = container.querySelectorAll('.cb-meta__item');
    expect(items).toHaveLength(3);
    expect(items[1].textContent).toBe('linux / amd64');
  });

  it('renders no meta row when there is nothing to put in it', () => {
    const { container } = renderHeader({ meta: [] });
    expect(container.querySelector('.cb-meta')).toBeNull();
  });

  it('renders chips, actions and the strip slot', () => {
    renderHeader({
      chips: <span>Online</span>,
      actions: <button type="button">Revoke</button>,
      strip: <div data-testid="strip">sparklines</div>,
    });
    expect(screen.getByText('Online')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeTruthy();
    expect(screen.getByTestId('strip')).toBeTruthy();
  });

  it('omits the strip slot entirely when there is nothing live to show', () => {
    // A pending agent has no telemetry. Reserving empty space for a strip that
    // will never fill reads as something failing to load.
    const { container } = renderHeader({ strip: null });
    expect(container.querySelector('.cb-detail-head__strip')).toBeNull();
  });
});
