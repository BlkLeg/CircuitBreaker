import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import HeaderWidgets from '../components/HeaderWidgets.jsx';

describe('HeaderWidgets', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('falls back to city-only geocoding when location includes region suffix', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ generationtime_ms: 0.3 }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ results: [{ latitude: 33.44838, longitude: -112.07404 }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          current_weather: {
            temperature: 72,
            weathercode: 0,
          },
        }),
      });

    globalThis.fetch = fetchMock;

    render(
      <HeaderWidgets
        settings={{
          show_header_widgets: true,
          show_time_widget: false,
          show_weather_widget: true,
          weather_location: 'Phoenix, AZ',
          timezone: 'UTC',
        }}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('72°F | Clear')).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0][0]).toContain('name=Phoenix%2C%20AZ');
    expect(fetchMock.mock.calls[1][0]).toContain('name=Phoenix');
  });

  it('renders weather when API responds with current payload fields', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          results: [{ latitude: 40.7128, longitude: -74.006 }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          current: {
            temperature_2m: 65,
            weather_code: 3,
          },
        }),
      });

    globalThis.fetch = fetchMock;

    render(
      <HeaderWidgets
        settings={{
          show_header_widgets: true,
          show_time_widget: false,
          show_weather_widget: true,
          weather_location: 'New York',
          timezone: 'UTC',
        }}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('65°F | Overcast')).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain('current=temperature_2m,weather_code');
  });
});
