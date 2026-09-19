import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import EnrollmentTokensSection from '../components/settings/EnrollmentTokensSection';
import { listEnrollmentTokens, revokeEnrollmentToken } from '../api/agents';

// This section exists so `revoke` is reachable at all: the design gives tokens
// a revoke endpoint and names only the wizard as a surface, which would leave
// revocation as backend capability with no way to use it.
vi.mock('../api/agents', () => ({
  listEnrollmentTokens: vi.fn(),
  revokeEnrollmentToken: vi.fn(),
}));

const FUTURE = '2099-01-01T00:00:00Z';
const PAST = '2020-01-01T00:00:00Z';

const LIVE = {
  id: 1,
  label: 'warehouse',
  endpoint_url: 'https://cb.example.com',
  capabilities: {},
  max_uses: 5,
  uses: 2,
  expires_at: FUTURE,
  revoked_at: null,
  created_at: '2026-09-06T00:00:00Z',
  agent_count: 2,
};

describe('EnrollmentTokensSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listEnrollmentTokens.mockResolvedValue({ data: [] });
  });

  it('renders a loading state before the list arrives', () => {
    listEnrollmentTokens.mockReturnValue(new Promise(() => {}));
    render(<EnrollmentTokensSection />);

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders an error state when the list cannot be read', async () => {
    listEnrollmentTokens.mockRejectedValue({ response: { data: { detail: 'boom' } } });
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });

  it('says plainly when there are no tokens', async () => {
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText(/no enrollment tokens/i)).toBeInTheDocument();
  });

  it('shows a live token with its remaining uses and never its value', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText('warehouse')).toBeInTheDocument();
    expect(screen.getByText('2 / 5')).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
    // The row cannot carry the plaintext — the server keeps only a hash.
    expect(screen.queryByText(/cbe_/)).not.toBeInTheDocument();
  });

  it('says how many agents came through a token, since that is why it is kept', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText(/2 agents/i)).toBeInTheDocument();
  });

  it('revokes a token and reflects it without a reload', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    revokeEnrollmentToken.mockResolvedValue({
      data: { ...LIVE, revoked_at: '2026-09-06T01:00:00Z' },
    });
    render(<EnrollmentTokensSection />);

    fireEvent.click(await screen.findByRole('button', { name: /revoke/i }));

    await waitFor(() => expect(revokeEnrollmentToken).toHaveBeenCalledWith(1));
    expect(await screen.findByText('Revoked')).toBeInTheDocument();
  });

  it('surfaces a failed revoke instead of showing the token as shut', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    revokeEnrollmentToken.mockRejectedValue({ response: { data: { detail: 'nope' } } });
    render(<EnrollmentTokensSection />);

    fireEvent.click(await screen.findByRole('button', { name: /revoke/i }));

    expect(await screen.findByText(/nope/)).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it.each([
    ['revoked', { revoked_at: '2026-09-06T01:00:00Z' }, 'Revoked'],
    ['expired', { expires_at: PAST }, 'Expired'],
    ['spent', { uses: 5, max_uses: 5 }, 'Spent'],
  ])('shows a %s token as such, with no revoke button', async (_name, patch, expected) => {
    listEnrollmentTokens.mockResolvedValue({ data: [{ ...LIVE, ...patch }] });
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument();
  });

  it('keeps revoked ahead of expired, because revoking is a decision someone made', async () => {
    // A token that was revoked and has since expired is still, to an auditor,
    // the one somebody shut off.
    listEnrollmentTokens.mockResolvedValue({
      data: [{ ...LIVE, revoked_at: '2026-09-06T01:00:00Z', expires_at: PAST }],
    });
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText('Revoked')).toBeInTheDocument();
    expect(screen.queryByText('Expired')).not.toBeInTheDocument();
  });
});
