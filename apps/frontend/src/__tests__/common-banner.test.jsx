import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Banner from '../components/common/Banner';
import EmptyState from '../components/common/EmptyState';

const VERBATIM =
  'The machine has enrolled but nobody has approved it yet. It collects nothing. ' +
  'What to do: Compare the fingerprint against the one the agent printed, then approve or reject it.';

describe('Banner', () => {
  it('shows the short body without requiring any interaction', () => {
    render(
      <Banner tone="warn" title="Awaiting approval" body="Compare the fingerprint, then approve." />
    );
    expect(screen.getByText('Awaiting approval')).toBeTruthy();
    expect(screen.getByText('Compare the fingerprint, then approve.')).toBeTruthy();
  });

  it('keeps the full operator prose in the DOM behind a disclosure', async () => {
    render(
      <Banner
        tone="warn"
        title="Awaiting approval"
        body="Compare the fingerprint."
        detail={VERBATIM}
      />
    );
    // In the DOM from the start — searchable, and reachable by a screen reader
    // walking the document — but visually collapsed until asked for.
    expect(screen.getByText(VERBATIM)).toBeTruthy();
    const disclosure = screen.getByText('Why?').closest('details');
    expect(disclosure.open).toBe(false);
    await userEvent.click(screen.getByText('Why?'));
    expect(disclosure.open).toBe(true);
  });

  it('renders no disclosure when there is no extra detail', () => {
    const { container } = render(<Banner tone="ok" title="Online" body="Reporting normally." />);
    expect(container.querySelector('details')).toBeNull();
  });

  it('announces itself as a status region', () => {
    render(<Banner tone="danger" title="Revoked" body="Its credential no longer works." />);
    expect(screen.getByRole('status').textContent).toContain('Revoked');
  });

  it('carries its tone as a data attribute', () => {
    const { container } = render(<Banner tone="danger" title="Revoked" body="x" />);
    expect(container.querySelector('.cb-banner').getAttribute('data-tone')).toBe('danger');
  });

  it('renders actions when given', () => {
    render(
      <Banner
        tone="warn"
        title="Awaiting approval"
        body="x"
        actions={<button type="button">Approve</button>}
      />
    );
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });
});

describe('EmptyState', () => {
  it('states what is absent and what to do about it', () => {
    render(
      <EmptyState
        message="No monitors run from this agent"
        hint="Assign one with “Run from” on a monitor’s form."
      />
    );
    expect(screen.getByText('No monitors run from this agent')).toBeTruthy();
    expect(screen.getByText('Assign one with “Run from” on a monitor’s form.')).toBeTruthy();
  });

  it('hides a decorative icon from assistive technology', () => {
    const { container } = render(<EmptyState icon="◎" message="Nothing here" />);
    expect(container.querySelector('.cb-empty__icon').getAttribute('aria-hidden')).toBe('true');
  });

  it('renders without a hint', () => {
    const { container } = render(<EmptyState message="No hardware linked" />);
    expect(container.querySelector('.cb-empty__hint')).toBeNull();
  });
});
