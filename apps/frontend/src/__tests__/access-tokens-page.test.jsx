import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AccessTokensPage from '../pages/AccessTokensPage.jsx';
import { NAV_MAP } from '../data/navigation';

vi.mock('../components/settings/AccessTokensManager', () => ({
  __esModule: true,
  default: () => <div data-testid="access-tokens-manager" />,
}));

describe('AccessTokensPage', () => {
  it('renders the access-token manager', () => {
    render(<AccessTokensPage />);
    expect(screen.getByTestId('access-tokens-manager')).toBeTruthy();
  });

  it('carries a page heading, which the embedded manager does not provide', () => {
    render(<AccessTokensPage />);
    expect(screen.getByRole('heading', { name: /access tokens/i })).toBeTruthy();
  });

  it('shows administration breadcrumb without a duplicate create CTA', () => {
    render(<AccessTokensPage />);
    expect(screen.getByLabelText(/breadcrumb/i)).toHaveTextContent(/administration/i);
    expect(screen.queryByRole('button', { name: /create token/i })).toBeNull();
  });

  it('is the destination the Govern group points at', () => {
    expect(NAV_MAP['/admin/tokens'].label).toBe('Access Tokens');
    expect(NAV_MAP['/admin/tokens'].require).toBe('admin');
  });
});
