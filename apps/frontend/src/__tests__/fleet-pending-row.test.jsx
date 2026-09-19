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
    // PENDING carries a fingerprint, so there are exactly three fields: the
    // label, the platform, and the fingerprint chip. An exact count means a
    // future regression that reverted only the label to a bare text node
    // (leaving the other two fields wrapped) cannot pass this test.
    expect(items.length).toBe(3);
    items.forEach((item) => {
      expect(item.tagName).toBe('SPAN');
    });
  });

  it('no longer concatenates the status with the platform', () => {
    // screen.getByText / queryByText match a node's own direct text-node
    // children only (@testing-library/dom's getNodeText), never descendant
    // text — so a query for /approvallinux/ can never match here whether the
    // cell is buggy or fixed, and asserted nothing. `cell.textContent` DOES
    // concatenate descendants, so it can actually see what the user sees.
    const { container } = renderRow();
    const cell = container.querySelector('.fleet-pending');
    expect(cell.textContent).toContain('Waiting for approval');
    expect(cell.textContent).toContain('linux / amd64');
    // The property that makes the defect class unreachable: no bare text
    // node can sit between the fields, because a text node cannot satisfy an
    // adjacent-sibling separator rule.
    const bareText = [...cell.childNodes].filter(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim() !== ''
    );
    expect(bareText).toEqual([]);
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
