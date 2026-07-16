import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

describe('useDiscoveryReadiness', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it('returns readiness data when fetch succeeds', async () => {
    // Mock the discovery API module before importing the hook
    vi.doMock('../api/discovery', () => ({
      getDiscoveryReadiness: vi.fn().mockResolvedValue({
        data: {
          helper_installed: true,
          capabilities: [
            {
              name: 'docker',
              last_healed_at: '2026-07-16T10:00:00Z',
              last_error: null,
            },
          ],
        },
      }),
    }));

    const { useDiscoveryReadiness } = await import('../hooks/useDiscoveryReadiness');
    const { result } = renderHook(() => useDiscoveryReadiness());

    expect(result.current.loading).toBe(true);
    expect(result.current.readiness).toBeNull();

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.readiness).toEqual({
      helper_installed: true,
      capabilities: [
        {
          name: 'docker',
          last_healed_at: '2026-07-16T10:00:00Z',
          last_error: null,
        },
      ],
    });

    vi.doUnmock('../api/discovery');
  });

  it('returns fallback shape on fetch error', async () => {
    // Mock the discovery API module to reject before importing the hook
    vi.doMock('../api/discovery', () => ({
      getDiscoveryReadiness: vi.fn().mockRejectedValue(new Error('Network error')),
    }));

    const { useDiscoveryReadiness } = await import('../hooks/useDiscoveryReadiness');
    const { result } = renderHook(() => useDiscoveryReadiness());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.readiness).toEqual({
      helper_installed: false,
      capabilities: [],
    });

    vi.doUnmock('../api/discovery');
  });
});
