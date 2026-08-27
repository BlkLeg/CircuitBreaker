import { describe, expect, it } from 'vitest';
import {
  PAIRING_LOOKUP_FAILED,
  describeAgentEvent,
  isSecretKey,
  operatorErrorMessage,
  redactSensitive,
  updateDispatchMessage,
} from '../lib/agentErrors';

/**
 * AGT-15's two halves, tested as two halves: an error must be actionable, and
 * it must not carry keys, tokens or wire-protocol detail.
 *
 * The corpus below is built from the material this system actually moves —
 * a 64-hex X25519 public key (`Agent.device_pk`), the 32-hex fingerprint that
 * is deliberately NOT a secret, the `XXXX-XXXX-XXXX` pairing code shape
 * AddAgentPairingCode prints, and the `agent_events.detail` payloads
 * agent_link.py writes for the two violation types.
 */

const DEVICE_PK = 'a3f1'.repeat(16); // 64 hex — an X25519 public key
const FINGERPRINT = 'b'.repeat(32); // sha256[:32] — public identity, shown on purpose

describe('redactSensitive', () => {
  it('removes key-length hex but leaves the fingerprint an operator has to compare', () => {
    expect(redactSensitive(`device ${DEVICE_PK} refused`)).not.toContain(DEVICE_PK);
    // The approval flow's entire security control is comparing this string
    // against what the agent printed. Redacting it would break that control.
    expect(redactSensitive(`fingerprint ${FINGERPRINT}`)).toContain(FINGERPRINT);
  });

  it('removes PEM blocks whole or truncated', () => {
    const pem = '-----BEGIN PRIVATE KEY-----\nMIIBVgIBADAN\n-----END PRIVATE KEY-----';
    expect(redactSensitive(`could not read ${pem}`)).not.toContain('MIIBVgIBADAN');
    expect(redactSensitive('-----BEGIN PRIVATE KEY-----\nMIIBVgIBADAN')).not.toContain(
      'MIIBVgIBADAN'
    );
  });

  it('removes signed-token and long base64 shapes', () => {
    // The jwt.io sample token, signed with the published key "your-256-bit-secret"
    // and carrying only {"sub":"1"}. It is here because redactSensitive's JWT
    // branch cannot be tested without a string of JWT shape, so Semgrep's
    // detected-jwt-token fires on the fixture that proves tokens get redacted.
    // Suppressed by rule id on this line alone: a real token anywhere else in
    // this file, including the line below, still fails the gate.
    // nosemgrep: generic.secrets.security.detected-jwt-token.detected-jwt-token
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g';
    expect(redactSensitive(`token ${jwt}`)).not.toContain('eyJhbGciOiJIUzI1NiJ9');
    const blob = 'QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbg==';
    expect(redactSensitive(`frame ${blob}`)).not.toContain(blob);
  });

  it('removes a pairing code even when it is embedded in prose', () => {
    expect(redactSensitive('code 7QK2-4M1X-9ZTP is unknown')).not.toContain('7QK2-4M1X-9ZTP');
  });

  it('removes a private key path but keeps the certificate path that makes the error fixable', () => {
    const message =
      'The TLS certificate at /data/tls/fullchain.pem exists but is not readable. Fix it with: chmod 644 /data/tls/fullchain.pem';
    const safe = redactSensitive(message);
    expect(safe).toContain('/data/tls/fullchain.pem');
    expect(safe).toContain('chmod 644');
    expect(redactSensitive('could not read /data/tls/privkey.pem')).not.toContain('privkey.pem');
  });

  it('leaves ordinary operator prose untouched and survives non-strings', () => {
    const plain = 'The agent is offline. Check the host is powered on.';
    expect(redactSensitive(plain)).toBe(plain);
    expect(redactSensitive(null)).toBe('');
    expect(redactSensitive(undefined)).toBe('');
  });
});

describe('isSecretKey', () => {
  it('recognises the detail keys whose values must never render', () => {
    ['device_pk', 'successor_pk', 'session_key', 'token', 'api_token', 'psk', 'nonce'].forEach(
      (name) => expect(isSecretKey(name), name).toBe(true)
    );
  });

  it('does not sweep up ordinary field names', () => {
    ['version', 'reason', 'hostname', 'monkey', 'keyboard_layout'].forEach((name) =>
      expect(isSecretKey(name), name).toBe(false)
    );
  });
});

describe('describeAgentEvent', () => {
  it('never renders the wire detail of a protocol violation', () => {
    // agent_link._record_protocol_violation writes exactly this shape.
    const described = describeAgentEvent({
      event_type: 'protocol_violation',
      detail: {
        reason: 'sequence_regression',
        seq: 41,
        last_seq: 92,
        frame_type: 'telemetry.host',
        error: '1 validation error for HostSamplePayload\\n  raw.cpu\\n  Input should be a number',
      },
    });
    expect(described.label).toBe('Protocol violation');
    expect(described.detail).not.toMatch(/telemetry\.host|seq|validation error|92/);
    // It is still an audit row and must still be listed, with something the
    // operator can read.
    expect(described.detail).toMatch(/server log/i);
  });

  it('never renders the frame type behind a capability violation', () => {
    const described = describeAgentEvent({
      event_type: 'capability_violation',
      detail: { frame_type: 'discovery.finding', reported_by: 'agent', repeated: 3 },
    });
    expect(described.detail).not.toContain('discovery.finding');
  });

  it('drops any detail key that is not on the event type’s allow list', () => {
    // The structural guarantee: a key added to a backend payload later cannot
    // reach the screen just by existing.
    const described = describeAgentEvent({
      event_type: 'version_changed',
      detail: { version: '0.9.2', device_pk: DEVICE_PK, internal_frame_seq: 12 },
    });
    expect(described.detail).toBe('version: 0.9.2');
    expect(described.detail).not.toContain(DEVICE_PK);
  });

  it('shows the allow-listed fields an operator needs', () => {
    expect(
      describeAgentEvent({ event_type: 'update_queued', detail: { target_version: '0.9.2' } })
    ).toMatchObject({ label: 'Update queued', detail: 'target version: 0.9.2' });
    expect(
      describeAgentEvent({ event_type: 'key_rotated', detail: { new_fingerprint: 'c'.repeat(16) } })
        .detail
    ).toContain('c'.repeat(16));
  });

  it('humanizes a machine-readable reason instead of printing the enum', () => {
    const described = describeAgentEvent({
      event_type: 'rejected',
      detail: { reason: 'pending_expired' },
    });
    expect(described.detail).toContain('never approved');
  });

  it('renders an unknown event type as a label only, with its payload dropped', () => {
    const described = describeAgentEvent({
      event_type: 'some_future_event',
      detail: { device_pk: DEVICE_PK },
    });
    expect(described.isKnown).toBe(false);
    expect(described.label).toBe('some future event');
    expect(described.detail).toBeNull();
  });

  it('tones failures so a violation is not styled as routine', () => {
    expect(describeAgentEvent({ event_type: 'protocol_violation' }).tone).toBe('critical');
    expect(describeAgentEvent({ event_type: 'update_failed' }).tone).toBe('critical');
    expect(describeAgentEvent({ event_type: 'connected' }).tone).toBe('ok');
  });
});

describe('operatorErrorMessage', () => {
  it('prefers the server’s actionable detail, redacted', () => {
    const error = {
      response: {
        status: 503,
        data: { detail: `pin ${DEVICE_PK}: chmod 644 /data/tls/fullchain.pem` },
      },
    };
    const message = operatorErrorMessage(error, { fallback: 'nope' });
    expect(message).toContain('chmod 644');
    expect(message).not.toContain(DEVICE_PK);
  });

  it('answers a 403 with who can act rather than "Not enough permissions"', () => {
    const message = operatorErrorMessage(
      { response: { status: 403, data: { detail: 'Not enough permissions' } } },
      { fallback: 'nope', forbidden: 'Ask an administrator for the install command' }
    );
    expect(message).toBe('Ask an administrator for the install command');
  });

  it('never renders a 422’s pydantic array, which echoes the submitted input', () => {
    const error = {
      response: {
        status: 422,
        data: { detail: [{ loc: ['body', 'code'], input: 'AAAA-BBBB-CCCC' }] },
      },
    };
    expect(operatorErrorMessage(error, { fallback: 'Could not do that' })).toBe(
      'Could not do that'
    );
  });

  it('falls back cleanly when there is no response at all', () => {
    expect(operatorErrorMessage(new Error('network down'), { fallback: 'Try again' })).toBe(
      'Try again'
    );
  });
});

describe('pairing-code lookup', () => {
  it('states no cause as fact, so the form cannot be used to enumerate codes', () => {
    // The distinction that matters is between "your code has expired" — which
    // confirms the code EXISTED — and "that did not match anything", which
    // confirms nothing. Offering expiry as one possible explanation is fine;
    // asserting it is what turns the form into an oracle.
    expect(PAIRING_LOOKUP_FAILED).not.toMatch(/that code (has )?expired/i);
    expect(PAIRING_LOOKUP_FAILED).not.toMatch(/already approved|unknown code|no such code/i);
    expect(PAIRING_LOOKUP_FAILED).toMatch(/did not match/i);
    // …and it still tells the operator what to do next.
    expect(PAIRING_LOOKUP_FAILED).toMatch(/re-run the installer/i);
  });
});

describe('updateDispatchMessage', () => {
  it('maps each failure to the operator’s next move', () => {
    expect(updateDispatchMessage({ response: { status: 403 } })).toMatch(/administrator/i);
    expect(updateDispatchMessage({ response: { status: 409 } })).toMatch(/already in flight/i);
    expect(
      updateDispatchMessage({
        response: { status: 404, data: { detail: 'No binary for linux/arm64 at version 0.9.2' } },
      })
    ).toContain('arm64');
  });

  it('redacts a passthrough detail like every other surface', () => {
    const message = updateDispatchMessage({
      response: { status: 400, data: { detail: `bad manifest key ${DEVICE_PK}` } },
    });
    expect(message).not.toContain(DEVICE_PK);
  });
});
