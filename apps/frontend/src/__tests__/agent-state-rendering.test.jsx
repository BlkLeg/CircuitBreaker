import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetRow from '../components/agents/FleetRow';
import AgentStateChip from '../components/agents/AgentStateChip';
import { STATE_ORDER, agentStateDefinition, deriveAgentStates } from '../lib/agentState';

/**
 * AGT-14 as it reaches an operator: "Each state needs a distinct, unambiguous
 * visual treatment and accessible text — not just a colour."
 *
 * lib/agentState decides WHICH states hold (covered in agent-state.test.js);
 * this file is about what a screen reader and a colour-blind operator actually
 * get. The load-bearing assertions are the ones about `.sr-only` text and
 * about the glyph, because those are the two channels that survive when colour
 * is unavailable.
 */

vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return { normalizeCapability: actual.normalizeCapability };
});

const RECENT = () => new Date(Date.now() - 10_000).toISOString();
const OLD = () => new Date(Date.now() - 6 * 3600 * 1000).toISOString();

const BASE = {
  id: 3,
  status: 'active',
  hostname: 'edge-01',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.9.0',
  fingerprint: 'c'.repeat(32),
  last_seen_at: RECENT(),
  online: true,
  capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
  latest: { collected_at: RECENT(), cpu_pct: 12, mem_pct: 30 },
  spool_depth: 0,
};

const renderRow = (agent, props = {}) =>
  render(
    <MemoryRouter>
      <table>
        <tbody>
          <FleetRow agent={agent} {...props} />
        </tbody>
      </table>
    </MemoryRouter>
  );

describe('every state carries its own text and its own glyph', () => {
  it('renders a label, a reason and an operator action for each state in the contract', () => {
    for (const code of STATE_ORDER) {
      const definition = agentStateDefinition(code);
      const { unmount } = render(<AgentStateChip state={{ code, ...definition }} />);
      // By class, not by a regex built from the copy: the assertions below are
      // about the chip's contents, and constructing a pattern out of the very
      // string under test would make the lookup pass for the wrong reason.
      const chip = document.querySelector('.fleet-chip');
      // The label is visible text, never replaced by the icon.
      expect(chip.textContent, code).toContain(definition.label);
      // The reason and the remedy are both in the accessible name, because a
      // screen-reader user cannot hover the tooltip that carries them.
      expect(chip.textContent, code).toContain(definition.summary);
      expect(chip.textContent, code).toContain(definition.action);
      // …and a glyph, so the state is separable without reading the colour.
      expect(chip.querySelector('svg'), code).not.toBeNull();
      unmount();
    }
  });

  it('marks the glyph decorative so it is never read out as a second label', () => {
    render(<AgentStateChip state={{ code: 'offline', ...agentStateDefinition('offline') }} />);
    const svg = document.querySelector('.fleet-chip svg');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('spells out the numbers behind a state rather than only its name', () => {
    const state = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: RECENT(),
      clockSkewSeconds: 3600,
    }).find((s) => s.code === 'clock_skew');
    render(<AgentStateChip state={state} />);
    // "Clock skew" alone leaves an operator with nowhere to start.
    expect(screen.getByTitle(/3600s ahead of the server/)).toBeInTheDocument();
  });
});

describe('the fleet row', () => {
  it('says nothing beyond "online" for an agent that is genuinely fine', () => {
    renderRow(BASE);
    expect(screen.getByText('online')).toBeInTheDocument();
    expect(screen.queryByText('Stale telemetry')).toBeNull();
    expect(screen.queryByText('Capability degraded')).toBeNull();
  });

  it('shows stale telemetry on a connected agent whose samples stopped', () => {
    renderRow({ ...BASE, latest: { collected_at: OLD() } });
    const chip = screen.getByText(/Stale telemetry/);
    // Distinct from "offline": the link is up, the collector is not producing.
    expect(screen.getByText('online')).toBeInTheDocument();
    expect(chip.textContent).toMatch(/What to do: Check the host telemetry collector/);
  });

  it('distinguishes "granted but never reported" from "stale"', () => {
    renderRow({ ...BASE, latest: null });
    expect(screen.getByText(/No samples yet/)).toBeInTheDocument();
    expect(screen.queryByText(/Stale telemetry/)).toBeNull();
  });

  it('says an agent with every grant withheld does nothing, rather than showing it as healthy', () => {
    renderRow({
      ...BASE,
      capabilities: {
        host_telemetry: { enabled: false, config: {} },
        remote_probe: { enabled: false, config: {} },
      },
      latest: null,
    });
    expect(screen.getByText(/No capabilities/)).toBeInTheDocument();
  });

  it('does not stack a stale-sample warning on an agent that is simply offline', () => {
    renderRow({ ...BASE, online: false, latest: { collected_at: OLD() }, last_seen_at: OLD() });
    expect(screen.getByText('offline')).toBeInTheDocument();
    expect(screen.queryByText(/Stale telemetry/)).toBeNull();
  });

  it('gives the revoked chip the same reason and remedy every other state has', () => {
    renderRow({ ...BASE, status: 'revoked', online: false });
    const chip = screen.getByText('revoked');
    expect(chip.textContent).toMatch(/credential has been revoked/);
    expect(chip.textContent).toMatch(/What to do:/);
  });

  it('marks a drifted version without relying on the colour to say so', () => {
    const { container } = renderRow(
      { ...BASE, agent_version: '0.8.1' },
      { latestFleetVersion: '0.9.0' }
    );
    const cell = container.querySelector('[data-drift="behind"]');
    expect(cell).not.toBeNull();
    expect(cell.textContent).toContain('0.8.1');
    // The caret and the sr-only clause carry the fact on their own.
    expect(cell.textContent).toMatch(/Behind the newest agent in this fleet \(0\.9\.0\)/);
  });

  it('leaves an agent on the newest version unmarked', () => {
    const { container } = renderRow(BASE, { latestFleetVersion: '0.9.0' });
    expect(container.querySelector('[data-drift]')).toBeNull();
  });

  it('sorts 0.10.0 after 0.9.0 rather than marking the whole fleet drifted', () => {
    const { container } = renderRow(
      { ...BASE, agent_version: '0.10.0' },
      { latestFleetVersion: '0.9.0' }
    );
    expect(container.querySelector('[data-drift="behind"]')).toBeNull();
  });

  it('carries the browser clock warning on a row without claiming the agent is at fault', () => {
    renderRow(BASE, { clockSkewSeconds: 4000 });
    const chip = screen.getByText(/Clock skew/);
    expect(chip.textContent).toMatch(/This browser’s clock/);
    expect(chip.textContent).toMatch(/Correct the clock on this workstation/);
  });

  it('keeps a pending row an inbox item rather than a diagnosis', () => {
    const { container } = renderRow({
      id: 4,
      status: 'pending',
      hostname: 'newbie',
      os: 'linux',
      arch: 'arm64',
      fingerprint: 'd'.repeat(32),
      online: null,
      capabilities: {},
    });
    const row = container.querySelector('tr');
    expect(row).toHaveAttribute('data-state', 'pending');
    expect(within(row).getByText('pending').textContent).toMatch(/Compare the fingerprint/);
  });
});
