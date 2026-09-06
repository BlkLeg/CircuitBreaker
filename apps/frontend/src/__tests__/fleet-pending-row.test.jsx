import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetRow from '../components/agents/FleetRow';

const PENDING = {
  id: 7,
  status: 'pending',
  hostname: '73235d37c4a3',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.0.0-dev',
  fingerprint: '5a8253d7b7af678c4fcd7872631139d8',
  last_seen_at: null,
  online: false,
  capabilities: {},
};

function renderRow(agent = PENDING) {
  return render(
    <MemoryRouter>
      <table>
        <tbody>
          <FleetRow agent={agent} />
        </tbody>
      </table>
    </MemoryRouter>
  );
}

describe('FleetRow pending cells', () => {
  it('keeps every field in its own element so the separator rule applies', () => {
    // The separator is `.fleet-muted + .fleet-muted::before` — an adjacent
    // SIBLING selector. A bare text node cannot satisfy it, which is why the
    // cell rendered "Waiting for approvallinux / amd64".
    const { container } = renderRow();
    const cell = container.querySelector('.fleet-pending');
    const items = cell.querySelectorAll('.fleet-pending__item');
    expect(items.length).toBeGreaterThanOrEqual(2);
    items.forEach((item) => {
      expect(item.tagName).toBe('SPAN');
    });
  });

  it('no longer concatenates the status with the platform', () => {
    renderRow();
    expect(screen.queryByText(/approvallinux/)).toBeNull();
    expect(screen.getByText('Waiting for approval')).toBeTruthy();
    expect(screen.getByText('linux / amd64')).toBeTruthy();
  });

  it('still abbreviates the fingerprint while keeping the full value reachable', () => {
    renderRow();
    const chip = screen.getByTitle(PENDING.fingerprint);
    expect(chip.textContent).toContain('…');
    expect(chip.textContent.length).toBeLessThan(PENDING.fingerprint.length);
  });

  it('omits the fingerprint field entirely when the agent has not reported one', () => {
    renderRow({ ...PENDING, fingerprint: null });
    expect(screen.getByText('Waiting for approval')).toBeTruthy();
    expect(screen.queryByText(/…/)).toBeNull();
  });
});
