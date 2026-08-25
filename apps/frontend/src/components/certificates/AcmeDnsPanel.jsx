import React, { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { KeyRound, CheckCircle2, XCircle } from 'lucide-react';
import { settingsApi } from '../../api/client';
import { useToast } from '../common/Toast';

/**
 * DNS-01 provider credentials for Let's Encrypt (INC-07).
 *
 * It lives on the Certificates page rather than under Settings because that is where an
 * operator goes to get a certificate. The alternative — the challenge chosen here and the
 * credential it needs configured two screens apart — is the split-surface shape most of the
 * 1.0.0 findings have.
 *
 * The stored credential is never sent back by the API, in masked form or otherwise: a
 * `*_set` flag is the whole answer to "is it configured". So the secret inputs start empty
 * and an empty input means *leave it alone*, which is also what the API does with an absent
 * field. Typing into one replaces it.
 */

const PROVIDERS = [
  { value: '', label: 'Not configured — HTTP-01 only' },
  { value: 'cloudflare', label: 'Cloudflare' },
  { value: 'rfc2136', label: 'RFC2136 (BIND, Knot, PowerDNS)' },
];

// Which fields each provider takes. `secret: true` means it is write-only: never returned,
// blank input leaves the stored value in place. A Map rather than an object literal so the
// provider string, which comes from the server, indexes nothing on Object.prototype.
const FIELDS = new Map([
  [
    'cloudflare',
    [
      {
        name: 'api_token',
        label: 'API Token',
        secret: true,
        setFlag: 'api_token_set',
        hint: 'A scoped token with Zone:DNS:Edit on the zone this certificate covers. Not the Global API Key.',
      },
    ],
  ],
  [
    'rfc2136',
    [
      { name: 'server', label: 'Nameserver', placeholder: 'ns1.example.com' },
      { name: 'port', label: 'Port', type: 'number', placeholder: '53' },
      { name: 'tsig_name', label: 'TSIG Key Name', placeholder: 'circuitbreaker-key' },
      { name: 'tsig_secret', label: 'TSIG Secret', secret: true, setFlag: 'tsig_secret_set' },
      {
        name: 'tsig_algorithm',
        label: 'TSIG Algorithm',
        placeholder: 'HMAC-SHA512',
        hint: 'Defaults to HMAC-SHA512 when left blank.',
      },
    ],
  ],
]);

const S = {
  panel: {
    marginBottom: 16,
    padding: 20,
    borderRadius: 12,
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
  },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 },
  title: { fontSize: 14, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' },
  description: {
    fontSize: 13,
    color: 'var(--color-text-muted)',
    lineHeight: 1.6,
    marginBottom: 16,
  },
  grid: { display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' },
  hint: { fontSize: 12, color: 'var(--color-text-muted)', margin: '4px 0 0' },
  actions: { display: 'flex', gap: 8, alignItems: 'center', marginTop: 16 },
};

function StoredBadge({ isSet }) {
  return isSet ? (
    <span style={{ color: 'var(--color-online, #4caf50)', fontSize: 12 }}>
      <CheckCircle2 size={12} style={{ verticalAlign: '-2px' }} /> stored
    </span>
  ) : (
    <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
      <XCircle size={12} style={{ verticalAlign: '-2px' }} /> not set
    </span>
  );
}

StoredBadge.propTypes = { isSet: PropTypes.bool };

export default function AcmeDnsPanel({ acmeDns, onSaved }) {
  const toast = useToast();
  const [provider, setProvider] = useState('');
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setProvider(acmeDns?.provider ?? '');
    setValues({
      server: acmeDns?.server ?? '',
      port: acmeDns?.port ?? '',
      tsig_name: acmeDns?.tsig_name ?? '',
      tsig_algorithm: acmeDns?.tsig_algorithm ?? '',
    });
  }, [acmeDns]);

  const fields = useMemo(() => FIELDS.get(provider) ?? [], [provider]);

  const handleSave = async () => {
    setSaving(true);
    try {
      if (!provider) {
        await settingsApi.acmeDnsUpdate({ provider: null });
        toast.success('DNS-01 turned off. The stored credential was erased.');
      } else {
        // Only non-empty values are sent. An omitted secret keeps the stored one; an
        // omitted plain field would be dropped, so those are always sent.
        const payload = { provider };
        for (const field of fields) {
          const value = values[field.name];
          if (field.secret) {
            if (value) payload[field.name] = value;
          } else {
            payload[field.name] = field.type === 'number' ? Number(value) || null : (value ?? '');
          }
        }
        await settingsApi.acmeDnsUpdate(payload);
        toast.success('DNS-01 provider saved.');
      }
      // Clear the secret inputs: what is on screen is no longer what is stored.
      setValues((v) => {
        const next = { ...v };
        for (const field of fields) if (field.secret) delete next[field.name];
        return next;
      });
      onSaved?.();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={S.panel}>
      <div style={S.header}>
        <KeyRound size={16} className="tw-text-cb-primary" aria-hidden="true" />
        <span style={S.title}>Let&apos;s Encrypt DNS-01</span>
      </div>
      <p style={S.description}>
        DNS-01 proves control of a domain by publishing a record instead of answering on port 80, so
        it works on an install with no inbound access from the internet. Configure a provider here,
        then choose DNS-01 when adding a Let&apos;s Encrypt certificate. Leave this unset if port 80
        reaches this host — HTTP-01 needs no credentials.
      </p>

      <div style={S.grid}>
        <div>
          <label htmlFor="acme-dns-provider">DNS Provider</label>
          <select
            id="acme-dns-provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        {fields.map((field) => (
          <div key={field.name}>
            <label htmlFor={`acme-dns-${field.name}`}>
              {field.label} {field.secret && <StoredBadge isSet={!!acmeDns?.[field.setFlag]} />}
            </label>
            <input
              id={`acme-dns-${field.name}`}
              type={field.secret ? 'password' : (field.type ?? 'text')}
              autoComplete="off"
              placeholder={
                field.secret && acmeDns?.[field.setFlag]
                  ? 'Leave blank to keep the stored value'
                  : field.placeholder
              }
              value={values[field.name] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
            />
            {field.hint && <p style={S.hint}>{field.hint}</p>}
          </div>
        ))}
      </div>

      <div style={S.actions}>
        <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
          {saving ? 'Saving…' : 'Save DNS-01 Settings'}
        </button>
        {!provider && acmeDns?.provider && (
          <span style={S.hint}>Saving with no provider erases the stored credential.</span>
        )}
      </div>
    </div>
  );
}

AcmeDnsPanel.propTypes = {
  acmeDns: PropTypes.shape({
    provider: PropTypes.string,
    api_token_set: PropTypes.bool,
    tsig_secret_set: PropTypes.bool,
    server: PropTypes.string,
    port: PropTypes.number,
    tsig_name: PropTypes.string,
    tsig_algorithm: PropTypes.string,
  }),
  onSaved: PropTypes.func,
};
