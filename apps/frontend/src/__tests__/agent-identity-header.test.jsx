import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentStateBanner from '../components/agents/AgentStateBanner';
import AgentIdentityHeader from '../components/agents/AgentIdentityHeader';
import { agentStateDefinition } from '../lib/agentState';
import { FRESHNESS } from '../lib/agentFreshness';

const pending = { code: 'pending_approval', ...agentStateDefinition('pending_approval') };
const online = { code: 'online', ...agentStateDefinition('online') };
const revoked = { code: 'revoked', ...agentStateDefinition('revoked') };

const AGENT = {
  id: 7,
  status: 'pending',
  hostname: '73235d37c4a3',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.0.0-dev',
  fingerprint: '5a8253d7b7af678c4fcd7872631139d8',
  last_seen_at: null,
};

const FRESH = { level: FRESHNESS.OFFLINE, label: 'OFFLINE', ageSeconds: null, animate: false };

describe('AgentStateBanner', () => {
  it('leads with the imperative, not the explanation', () => {
    render(<AgentStateBanner state={pending} />);
    expect(screen.getByText(pending.label)).toBeTruthy();
    expect(screen.getByText(pending.action)).toBeTruthy();
  });

  it('keeps the full original wording verbatim behind the disclosure', () => {
    // The AGT-14 prose is relocated, never reworded. This assertion is what
    // makes a future "tidy-up" of that string fail loudly.
    render(<AgentStateBanner state={pending} />);
    const expected = `${pending.summary}  What to do: ${pending.action}`.replace(/\s+/g, ' ');
    const body = document.querySelector('.cb-banner__why-body');
    expect(body.textContent.replace(/\s+/g, ' ').trim()).toBe(expected.trim());
  });

  it('takes its tone from the state rather than deciding one', () => {
    const { container } = render(<AgentStateBanner state={pending} />);
    expect(container.querySelector('.cb-banner').getAttribute('data-tone')).toBe(pending.tone);
  });

  it("maps the agent-specific critical tone to the banner primitive's danger tone", () => {
    // Banner only knows ok|warn|danger|info. agentState.js's `critical` is
    // this component's word to translate, not Banner's to learn.
    const { container } = render(<AgentStateBanner state={revoked} />);
    expect(container.querySelector('.cb-banner').getAttribute('data-tone')).toBe('danger');
  });

  it('renders nothing for a healthy agent', () => {
    // "Online" is not news. A banner that is always present is chrome.
    const { container } = render(<AgentStateBanner state={online} />);
    expect(container.querySelector('.cb-banner')).toBeNull();
  });

  it('renders nothing when there is no state at all', () => {
    const { container } = render(<AgentStateBanner state={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('places actions inside the banner where the decision is being read', () => {
    render(<AgentStateBanner state={pending} actions={<button type="button">Approve</button>} />);
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });
});

describe('AgentIdentityHeader', () => {
  function renderHeader(props = {}) {
    return render(
      <MemoryRouter>
        <AgentIdentityHeader agent={AGENT} online={false} freshness={FRESH} {...props} />
      </MemoryRouter>
    );
  }

  it('titles the page with the agent display name', () => {
    renderHeader();
    expect(screen.getByRole('heading', { level: 1, name: '73235d37c4a3' })).toBeTruthy();
  });

  it('puts status, platform and version in separate meta elements', () => {
    const { container } = renderHeader();
    const items = [...container.querySelectorAll('.cb-meta__item')].map((el) => el.textContent);
    expect(items).toContain('pending');
    expect(items).toContain('linux / amd64');
    expect(items).toContain('v0.0.0-dev');
  });

  it('offers the fingerprint as a copyable field, abbreviated at both ends', () => {
    renderHeader();
    expect(screen.getByRole('button', { name: 'Copy fingerprint' })).toBeTruthy();
    expect(screen.getByTitle(AGENT.fingerprint)).toBeTruthy();
  });

  it('says an agent has never connected rather than showing an empty last-seen', () => {
    const { container } = renderHeader();
    const items = [...container.querySelectorAll('.cb-meta__item')].map((el) => el.textContent);
    expect(items).toContain('never connected');
  });

  it('omits the strip slot when there is nothing live to show', () => {
    const { container } = renderHeader({ strip: null });
    expect(container.querySelector('.cb-detail-head__strip')).toBeNull();
  });

  it('renders chips and actions passed by the page', () => {
    renderHeader({
      chips: <span>Awaiting approval</span>,
      actions: <button type="button">Approve</button>,
    });
    expect(screen.getByText('Awaiting approval')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });
});
