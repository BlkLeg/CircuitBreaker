import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import TimestampCell from '../components/TimestampCell';
import { TimezoneContext } from '../context/TimezoneContext';

function renderCell(isoString, elapsedSeconds = null, timezone = 'UTC') {
  return render(
    <TimezoneContext.Provider value={{ timezone, setTimezone: vi.fn() }}>
      <TimestampCell isoString={isoString} elapsedSeconds={elapsedSeconds} />
    </TimezoneContext.Provider>
  );
}

const EPOCH_SENTINEL = '1970-01-01T00:00:00+00:00';

describe('TimestampCell', () => {
  it('renders "just now" for timestamps under 60 seconds old', () => {
    const recent = new Date(Date.now() - 10_000).toISOString();
    renderCell(recent, 10);
    expect(screen.getByText(/just now/i)).toBeInTheDocument();
  });

  it('renders "N minutes ago" for timestamps under 1 hour old', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    renderCell(fiveMinAgo, 5 * 60);
    expect(screen.getByText(/minute/i)).toBeInTheDocument();
  });

  it('renders "N hours ago" for timestamps under 24 hours old', () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 3_600_000).toISOString();
    renderCell(twoHoursAgo, 2 * 3600);
    expect(screen.getByText(/hour/i)).toBeInTheDocument();
  });

  it('renders date string for timestamps older than 24 hours', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    renderCell(twoDaysAgo, 2 * 86400);
    // Should show a formatted date, not "ago" phrasing
    const text = screen.getByText(/.+/).textContent;
    expect(text).toBeTruthy();
    expect(text).not.toMatch(/^just now/i);
  });

  it('renders "Unknown time" for epoch sentinel', () => {
    renderCell(EPOCH_SENTINEL, null);
    expect(screen.getByText(/unknown time/i)).toBeInTheDocument();
  });

  it('title attribute contains full absolute timestamp', () => {
    const iso = new Date(Date.now() - 10_000).toISOString();
    const { container } = renderCell(iso, 10);
    const span = container.querySelector('[title]');
    expect(span).not.toBeNull();
    expect(span.getAttribute('title')).toBeTruthy();
  });

  it('reads timezone from TimezoneContext', () => {
    const iso = new Date(Date.now() - 10_000).toISOString();
    // Just verify it renders without error when a non-UTC timezone is provided
    renderCell(iso, 10, 'America/Denver');
    expect(screen.getByText(/just now/i)).toBeInTheDocument();
  });

  it('re-renders when TimezoneContext timezone value changes', () => {
    const iso = new Date(Date.now() - 10_000).toISOString();
    const { rerender } = render(
      <TimezoneContext.Provider value={{ timezone: 'UTC', setTimezone: vi.fn() }}>
        <TimestampCell isoString={iso} elapsedSeconds={10} />
      </TimezoneContext.Provider>
    );
    expect(screen.getByText(/just now/i)).toBeInTheDocument();

    rerender(
      <TimezoneContext.Provider value={{ timezone: 'Asia/Tokyo', setTimezone: vi.fn() }}>
        <TimestampCell isoString={iso} elapsedSeconds={10} />
      </TimezoneContext.Provider>
    );
    expect(screen.getByText(/just now/i)).toBeInTheDocument();
  });
});
