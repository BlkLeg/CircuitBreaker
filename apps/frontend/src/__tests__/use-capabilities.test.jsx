/**
 * useCapabilities — real fetch success / fetch failure / fallback branching.
 *
 * Every other live reference to this hook (map-page, settings-page,
 * settings-import, settings-notifications-admin-only) mocks it away with
 * vi.mock('../hooks/useCapabilities.js', ...), so none of them exercise the
 * hook's own logic. This file imports the real hook and mocks only its one
 * dependency, capabilitiesApi, per the repo's vi.mock('../api/client')
 * convention.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

describe('useCapabilities', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns all-false fallback when fetch fails', async () => {
    vi.doMock('../api/client.jsx', () => ({
      capabilitiesApi: {
        get: vi.fn().mockRejectedValue(new Error('network error')),
      },
    }));

    const { useCapabilities } = await import('../hooks/useCapabilities.js');

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const { caps } = result.current;
    expect(caps.nats.available).toBe(false);
    expect(caps.realtime.available).toBe(false);
    expect(caps.cve.available).toBe(false);
    expect(caps.listener.available).toBe(false);
    expect(caps.docker.available).toBe(false);
    expect(caps.auth.enabled).toBe(false);
  });

  it('returns data from successful fetch', async () => {
    const mockCaps = {
      nats: { available: true },
      realtime: { available: true, transport: 'auto' },
      cve: { available: true, last_sync: null },
      listener: { available: false, mdns: true, ssdp: true },
      docker: { available: false, discovery_enabled: false },
      auth: { enabled: true },
    };

    const getMock = vi.fn().mockResolvedValue({ data: mockCaps });
    vi.doMock('../api/client.jsx', () => ({
      capabilitiesApi: {
        get: getMock,
      },
    }));

    const { useCapabilities } = await import('../hooks/useCapabilities.js');

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(getMock).toHaveBeenCalled();
    expect(result.current.caps).toEqual(mockCaps);
  });
});
