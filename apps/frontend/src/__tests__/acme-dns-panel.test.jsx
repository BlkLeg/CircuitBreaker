import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AcmeDnsPanel from '../components/certificates/AcmeDnsPanel.jsx';
import { CERTIFICATE_FIELDS } from '../pages/CertificatesPage.jsx';
import { settingsApi } from '../api/client';

/**
 * INC-07. The DNS-01 credential is a bearer credential for the install's DNS zone: it is
 * write-only across the API, so the panel's whole job is to submit a new one without ever
 * destroying the stored one by accident. Every case below is a way that goes wrong.
 */

vi.mock('../api/client', () => ({
  settingsApi: { acmeDnsUpdate: vi.fn(() => Promise.resolve({ data: {} })) },
}));

const toast = { success: vi.fn(), error: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => toast }));

const CONFIGURED = { provider: 'cloudflare', api_token_set: true };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AcmeDnsPanel', () => {
  it('never renders the stored credential, masked or otherwise', () => {
    const { container } = render(<AcmeDnsPanel acmeDns={CONFIGURED} />);

    const token = container.querySelector('#acme-dns-api_token');
    expect(token.value).toBe('');
    expect(token.type).toBe('password');
    expect(screen.getByText(/stored/i)).toBeTruthy();
  });

  it('says a credential is not set when none is', () => {
    render(<AcmeDnsPanel acmeDns={{ provider: 'cloudflare', api_token_set: false }} />);

    expect(screen.getByText(/not set/i)).toBeTruthy();
  });

  it('submitting without retyping the token leaves it out of the payload', async () => {
    // The API carries the stored value forward for an absent field. Sending an empty
    // string instead would read as "clear it".
    render(<AcmeDnsPanel acmeDns={CONFIGURED} />);

    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(settingsApi.acmeDnsUpdate).toHaveBeenCalled());
    const payload = settingsApi.acmeDnsUpdate.mock.calls[0][0];
    expect(payload.provider).toBe('cloudflare');
    expect('api_token' in payload).toBe(false);
  });

  it('sends a newly typed token', async () => {
    const { container } = render(<AcmeDnsPanel acmeDns={CONFIGURED} />);

    fireEvent.change(container.querySelector('#acme-dns-api_token'), {
      target: { value: 'cf-new-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(settingsApi.acmeDnsUpdate).toHaveBeenCalled());
    expect(settingsApi.acmeDnsUpdate.mock.calls[0][0].api_token).toBe('cf-new-token');
  });

  it('clears the secret input after saving, so the screen matches what is stored', async () => {
    const { container } = render(<AcmeDnsPanel acmeDns={CONFIGURED} />);

    fireEvent.change(container.querySelector('#acme-dns-api_token'), {
      target: { value: 'cf-new-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(container.querySelector('#acme-dns-api_token').value).toBe(''));
  });

  it('selecting no provider sends an explicit null, which erases the credential', async () => {
    render(<AcmeDnsPanel acmeDns={CONFIGURED} />);

    fireEvent.change(screen.getByLabelText(/DNS Provider/i), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(settingsApi.acmeDnsUpdate).toHaveBeenCalledWith({ provider: null }));
  });

  it('offers only the two providers the build ships plugins for', () => {
    render(<AcmeDnsPanel acmeDns={null} />);

    const values = [...screen.getByLabelText(/DNS Provider/i).options].map((o) => o.value);
    expect(values).toEqual(['', 'cloudflare', 'rfc2136']);
  });

  it('shows the RFC2136 fields only for RFC2136', () => {
    const { container } = render(<AcmeDnsPanel acmeDns={{ provider: 'rfc2136' }} />);

    expect(container.querySelector('#acme-dns-tsig_secret')).toBeTruthy();
    expect(container.querySelector('#acme-dns-api_token')).toBeNull();
  });
});

describe('the certificate form can ask for what the panel configures', () => {
  // Otherwise DNS-01 is credentials with nothing that uses them — the same
  // implemented-with-no-surface shape as the findings this batch closes.
  const field = (name) => CERTIFICATE_FIELDS.find((f) => f.name === name);

  it('offers both challenges the backend accepts', () => {
    expect(field('challenge').options.map((o) => o.value)).toEqual(['http-01', 'dns-01']);
  });

  it('offers staging, and says what it costs', () => {
    expect(field('use_staging').type).toBe('checkbox');
    expect(field('use_staging').hint).toMatch(/untrusted/i);
  });
});
