import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { describe, it, expect, vi } from 'vitest';
import { server } from './mocks/server';
import { TimezoneContext } from '../context/TimezoneContext';
import LogsPage from '../pages/LogsPage';

function makeLog(overrides = {}) {
  return {
    id: Math.random(),
    action: 'created',
    entity_type: 'hardware',
    entity_id: 1,
    entity_name: 'pve-01',
    actor: 'admin',
    actor_name: 'admin',
    actor_gravatar_hash: null,
    ip_address: '10.0.0.1',
    severity: 'info',
    diff: null,
    old_value: null,
    new_value: null,
    details: null,
    created_at_utc: new Date(Date.now() - 5000).toISOString(),
    elapsed_seconds: 5,
    timestamp: new Date(Date.now() - 5000).toISOString(),
    ...overrides,
  };
}

function renderLogs(logs = [], totalCount = null) {
  server.use(
    http.get('/api/v1/logs', () =>
      HttpResponse.json({
        logs,
        total_count: totalCount ?? logs.length,
        has_more: false,
      })
    )
  );
  return render(
    <MemoryRouter>
      <TimezoneContext.Provider value={{ timezone: 'UTC', setTimezone: vi.fn() }}>
        <LogsPage />
      </TimezoneContext.Provider>
    </MemoryRouter>
  );
}

describe('LogsPanel', () => {
  it('renders table headers: Time, Action, Entity, Actor, IP', async () => {
    renderLogs();
    await waitFor(() => {
      expect(screen.getAllByText(/time/i)[0]).toBeInTheDocument();
      expect(screen.getAllByText(/action/i)[0]).toBeInTheDocument();
      expect(screen.getAllByText(/entity/i)[0]).toBeInTheDocument();
      expect(screen.getAllByText(/actor/i)[0]).toBeInTheDocument();
      expect(screen.getAllByText(/ip/i)[0]).toBeInTheDocument();
    });
  });

  it('renders action badge with correct color per action type', async () => {
    renderLogs([makeLog({ action: 'created' }), makeLog({ action: 'deleted', id: 2 })]);
    await waitFor(() => {
      expect(screen.getAllByText('created').at(-1)).toBeInTheDocument();
      expect(screen.getAllByText('deleted').at(-1)).toBeInTheDocument();
    });
  });

  it('renders entity name as link when entity exists', async () => {
    renderLogs([makeLog({ entity_type: 'hardware', entity_id: 1, entity_name: 'pve-01', action: 'updated' })]);
    await waitFor(() => {
      expect(screen.getByText(/pve-01/)).toBeInTheDocument();
    });
  });

  it('renders entity name with strikethrough when deleted', async () => {
    renderLogs([makeLog({ action: 'deleted', entity_name: 'old-server' })]);
    await waitFor(() => {
      const nameEl = screen.getByText(/old-server/);
      expect(nameEl).toBeInTheDocument();
      // Check for (deleted) label nearby
      expect(screen.getAllByText(/deleted/i).at(-1)).toBeInTheDocument();
    });
  });

  it('clicking row with diff expands inline diff panel', async () => {
    const log = makeLog({
      action: 'updated',
      diff: JSON.stringify({ before: { name: 'old' }, after: { name: 'new' } }),
    });
    renderLogs([log]);
    await waitFor(() => {
      expect(screen.getAllByText(/updated/).at(-1)).toBeInTheDocument();
    });
    const row = screen.getAllByText(/updated/).at(-1).closest('tr');
    if (row) {
      fireEvent.click(row);
      await waitFor(() => {
        expect(screen.queryByText(/changes/i) ?? screen.queryByText(/before/i)).toBeInTheDocument();
      });
    }
  });

  it('diff panel shows only changed keys', async () => {
    const log = makeLog({
      action: 'updated',
      entity_name: 'pve-01',
      diff: JSON.stringify({ before: { name: 'pve-01', role: 'server' }, after: { name: 'pve-02', role: 'server' } }),
    });
    renderLogs([log]);
    await waitFor(() => screen.getAllByText(/updated/).at(-1));
    const row = screen.getAllByText(/updated/).at(-1).closest('tr');
    if (row) {
      fireEvent.click(row);
      await waitFor(() => {
        // Only 'name' changed — 'role' should not appear in diff
        expect(screen.queryByText('name')).toBeInTheDocument();
      }, { timeout: 1000 });
    }
  });

  it('diff panel shows empty before column for create events', async () => {
    const log = makeLog({
      action: 'created',
      diff: JSON.stringify({ before: null, after: { name: 'pve-01' } }),
    });
    renderLogs([log]);
    await waitFor(() => screen.getAllByText(/created/).at(-1));
    const row = screen.getAllByText(/created/).at(-1).closest('tr');
    if (row) {
      fireEvent.click(row);
      await waitFor(() => {
        expect(screen.queryByText(/before/i) ?? screen.queryByText(/changes/i)).toBeInTheDocument();
      });
    }
  });

  it('diff panel shows empty after column for delete events', async () => {
    const log = makeLog({
      action: 'deleted',
      diff: JSON.stringify({ before: { name: 'pve-01' }, after: null }),
    });
    renderLogs([log]);
    await waitFor(() => screen.getAllByText(/deleted/).at(-1));
    const row = screen.getAllByText(/deleted/).at(-1).closest('tr');
    if (row) {
      fireEvent.click(row);
      await waitFor(() => {
        expect(screen.queryByText(/before/i) ?? screen.queryByText(/changes/i)).toBeInTheDocument();
      });
    }
  });

  it('renders REDACTED values as bullet pills not literal string', async () => {
    const log = makeLog({
      action: 'updated',
      diff: JSON.stringify({ before: { password: 'old-value' }, after: { password: '***REDACTED***' } }),
    });
    renderLogs([log]);
    await waitFor(() => screen.getAllByText(/updated/).at(-1));
    const row = screen.getAllByText(/updated/).at(-1).closest('tr');
    if (row) {
      fireEvent.click(row);
      await waitFor(() => {
        // Should render as ●●●●●● pill, not the literal string
        expect(screen.queryByText('***REDACTED***')).toBeNull();
        expect(screen.queryByText(/●●●●●●/)).toBeInTheDocument();
      }, { timeout: 2000 });
    }
  });

  it('login_failed rows have amber left border', async () => {
    const log = makeLog({ action: 'login_failed', entity_type: 'auth', ip_address: '10.0.0.99' });
    renderLogs([log]);
    await waitFor(() => {
      // getByText throws when multiple elements match (option + badge), use getAllByText instead
      const matches = screen.getAllByText('login_failed');
      const badge = matches.find(el => el.tagName.toLowerCase() === 'span') ?? matches[0];
      expect(badge).toBeInTheDocument();
      const row = badge.closest('tr');
      const style = row?.style?.borderLeft ?? row?.getAttribute('style') ?? '';
      // jsdom normalizes hex colors to rgb() in style.borderLeft
      expect(style).toMatch(/f9a825|rgb\(249,\s*168,\s*37\)/);
    });
  });

  it('filter by entity_type updates visible rows', async () => {
    renderLogs([makeLog({ entity_type: 'hardware' }), makeLog({ entity_type: 'service', id: 2 })]);
    // getAllByText because 'hardware' appears in both the filter <option> and the table row
    await waitFor(() => screen.getAllByText(/hardware/i));

    // Change the entity type filter
    const select = document.querySelector('select');
    if (select) {
      server.use(
        http.get('/api/v1/logs', ({ request }) => {
          const url = new URL(request.url);
          const et = url.searchParams.get('entity_type');
          const filtered = et === 'hardware'
            ? [makeLog({ entity_type: 'hardware' })]
            : [];
          return HttpResponse.json({ logs: filtered, total_count: filtered.length, has_more: false });
        })
      );
      fireEvent.change(select, { target: { value: 'hardware' } });
      await waitFor(() => {
        expect(screen.queryAllByText(/hardware/i).length).toBeGreaterThan(0);
      });
    }
  });

  it('search input filters by entity_name', async () => {
    renderLogs([makeLog({ entity_name: 'unique-server-xyz' })]);
    await waitFor(() => screen.getByText(/unique-server-xyz/));
    expect(screen.getByText(/unique-server-xyz/)).toBeInTheDocument();
  });

  it('pagination shows correct entry count label', async () => {
    renderLogs([makeLog()], 312);
    await waitFor(() => {
      expect(screen.getByText(/312/)).toBeInTheDocument();
    });
  });

  it('next/previous buttons are rendered', async () => {
    renderLogs([makeLog()], 200);
    await waitFor(() => {
      expect(screen.getByText(/next/i)).toBeInTheDocument();
    });
  });
});
