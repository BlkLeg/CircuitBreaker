/**
 * Phase 6 — Integrations tab and Settings cohesion tests.
 *
 * Tests the SETTINGS_TABS configuration, the Integrations tab structure,
 * and the useCapabilities cache behavior without rendering the full
 * SettingsPage (which has open-handle issues, see SettingsPage.test.jsx).
 */

import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

// ---------------------------------------------------------------------------
// SETTINGS_TABS configuration
// ---------------------------------------------------------------------------

describe('SETTINGS_TABS includes Integrations tab', () => {
  it('has an integrations entry', async () => {
    const { SETTINGS_TABS } = await import('../components/settings/SettingsNav.jsx');
    const ids = SETTINGS_TABS.map((t) => t.id);
    expect(ids).toContain('integrations');
  });

  it('integrations tab has correct label and description', async () => {
    const { SETTINGS_TABS } = await import('../components/settings/SettingsNav.jsx');
    const tab = SETTINGS_TABS.find((t) => t.id === 'integrations');
    expect(tab).toBeDefined();
    expect(tab.label).toBe('Integrations');
    expect(tab.description).toBeTruthy();
  });

  it('tabs are in expected order (general first, system last)', async () => {
    const { SETTINGS_TABS } = await import('../components/settings/SettingsNav.jsx');
    expect(SETTINGS_TABS[0].id).toBe('general');
    expect(SETTINGS_TABS[SETTINGS_TABS.length - 1].id).toBe('system');
  });
});

// ---------------------------------------------------------------------------
// useCapabilities — cache and fallback behaviour
// ---------------------------------------------------------------------------

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
    const { renderHook, waitFor } = await import('@testing-library/react');

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
    const { renderHook, waitFor } = await import('@testing-library/react');

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(getMock).toHaveBeenCalled();
    expect(result.current.caps).toEqual(mockCaps);
  });
});

// ---------------------------------------------------------------------------
// SettingsNav renders Integrations tab button
// ---------------------------------------------------------------------------

describe('SettingsNav renders Integrations tab', () => {
  it('renders all tab buttons including integrations', async () => {
    const SettingsNav = (await import('../components/settings/SettingsNav.jsx')).default;
    const { SETTINGS_TABS } = await import('../components/settings/SettingsNav.jsx');

    render(
      <SettingsNav
        activeTab="general"
        onTabChange={vi.fn()}
        searchQuery=""
        onSearchChange={vi.fn()}
        tabs={SETTINGS_TABS}
      />,
    );

    expect(screen.getByText('Integrations')).toBeInTheDocument();
    expect(screen.getByText('General')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
  });

  it('calls onTabChange with "integrations" when button clicked', async () => {
    const SettingsNav = (await import('../components/settings/SettingsNav.jsx')).default;
    const { SETTINGS_TABS } = await import('../components/settings/SettingsNav.jsx');
    const onTabChange = vi.fn();

    render(
      <SettingsNav
        activeTab="general"
        onTabChange={onTabChange}
        searchQuery=""
        onSearchChange={vi.fn()}
        tabs={SETTINGS_TABS}
      />,
    );

    fireEvent.click(screen.getByText('Integrations'));
    expect(onTabChange).toHaveBeenCalledWith('integrations');
  });
});

// ---------------------------------------------------------------------------
// MapToolbar — viewOptions props
// ---------------------------------------------------------------------------

describe('MapToolbar viewOptions', () => {
  it('renders link mode selector with smoothstep default', async () => {
    const MapToolbar = (await import('../components/MapToolbar.jsx')).default;

    render(
      <MapToolbar
        layout="dagre"
        onChange={vi.fn()}
        viewOptions={{ edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 }}
        onViewOptionsChange={vi.fn()}
      />,
    );

    // Labels toggle button should be visible
    expect(screen.getByTitle('Toggle edge labels')).toBeInTheDocument();

    // Links selector should show
    expect(screen.getByTitle('Edge rendering style')).toBeInTheDocument();
  });

  it('calls onViewOptionsChange when edge mode changes', async () => {
    const MapToolbar = (await import('../components/MapToolbar.jsx')).default;
    const onChange = vi.fn();
    const onViewOptionsChange = vi.fn();

    render(
      <MapToolbar
        layout="dagre"
        onChange={onChange}
        viewOptions={{ edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 }}
        onViewOptionsChange={onViewOptionsChange}
      />,
    );

    const edgeModeSelect = screen.getByTitle('Edge rendering style');
    fireEvent.change(edgeModeSelect, { target: { value: 'straight' } });
    expect(onViewOptionsChange).toHaveBeenCalledWith(
      expect.objectContaining({ edgeMode: 'straight' }),
    );
  });

  it('toggles edge label visibility on button click', async () => {
    const MapToolbar = (await import('../components/MapToolbar.jsx')).default;
    const onViewOptionsChange = vi.fn();

    render(
      <MapToolbar
        layout="dagre"
        onChange={vi.fn()}
        viewOptions={{ edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 }}
        onViewOptionsChange={onViewOptionsChange}
      />,
    );

    fireEvent.click(screen.getByTitle('Toggle edge labels'));
    expect(onViewOptionsChange).toHaveBeenCalledWith(
      expect.objectContaining({ edgeLabelVisible: false }),
    );
  });
});
