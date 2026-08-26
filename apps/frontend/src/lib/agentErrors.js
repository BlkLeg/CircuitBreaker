/**
 * Everything the agent surfaces are allowed to SAY about a failure (AGT-15).
 *
 * The requirement has two halves and they pull in opposite directions:
 * install and enrollment errors must be *actionable*, and they must not expose
 * keys or protocol internals. Passing the server's text straight through
 * satisfies the first and abandons the second; replacing it with "an error
 * occurred" does the reverse. This module is the place the trade is made once,
 * so no individual component has to get it right on its own.
 *
 * Two mechanisms, in this order, because the second alone is not enough:
 *
 *  1. **Allow-list the shape.** `describeAgentEvent` renders an
 *     `agent_events.detail` blob by naming the keys it is willing to show, per
 *     event type. Anything else is dropped without being inspected. This is
 *     structural: a key added to a backend payload later cannot appear on
 *     screen by default, so the UI cannot be made to leak by a change made
 *     somewhere else. The Events list on Agent Detail previously rendered
 *     `JSON.stringify(e.detail)` — which put `frame_type`, `seq`, `last_seq`
 *     and raw validation-error strings from the wire in front of the operator,
 *     the exact "protocol internals" the requirement rules out.
 *
 *  2. **Redact the values.** `redactSensitive` scrubs secret-shaped substrings
 *     out of any free text that does get rendered — server `detail` strings,
 *     a collector's own reason, an agent-authored update error. The allow-list
 *     decides *whether* text is shown; this decides what may be inside it.
 *
 * Deliberately NOT redacted: the 32-hex agent fingerprint. It is public
 * identity material, it is what an operator compares against the string the
 * agent printed on the machine, and blurring it would break the one control
 * that stops an impostor being approved. Key material is 64 hex (an X25519
 * public key) and is redacted; the threshold between the two is stated in
 * SECRET_HEX_MIN_LENGTH below.
 */

// A fingerprint is 32 hex (sha256[:32]); a device or server public key is 64.
// Redacting from 40 up therefore covers every key this system moves without
// touching the identity string the approval flow is built on.
const SECRET_HEX_MIN_LENGTH = 40;

const REDACTED = '[redacted]';

// Ordered, and each pattern is anchored on something a secret has and prose
// does not — a long unbroken run, a dotted three-segment token, the grouped
// shape a pairing code is printed in.
const SECRET_PATTERNS = [
  // X25519/Ed25519 public or private keys, session keys, raw device_pk values.
  new RegExp(`\\b[0-9a-fA-F]{${SECRET_HEX_MIN_LENGTH},}\\b`, 'g'),
  // PEM blocks, whole or partial.
  /-----BEGIN[^-]*-----[\s\S]*?(-----END[^-]*-----|$)/g,
  // JWT / signed-token shape.
  /\b[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
  // A pairing code as AddAgentPairingCode's placeholder spells it.
  /\b[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}\b/g,
  // Long base64 runs — spooled frame bodies, encoded payload fragments.
  /\b[A-Za-z0-9+/]{40,}={0,2}\b/g,
  // A private key on disk. The public certificate's path is left alone: it is
  // the actionable half of the TLS-pin failure and naming it is the whole
  // point of that message.
  /\S*(?:privkey|private|\.key)\S*\.(?:pem|key)\b/gi,
];

// Key names whose *value* is never shown, whatever the allow-list says. A
// second line of defence for the one case the allow-list cannot cover: a key
// that is on the list and whose value later starts carrying material.
const SECRET_KEY_RE = /(^|_)(key|token|secret|password|pk|nonce|cipher|psk)($|_)/i;

/** Scrub secret-shaped substrings out of free text. Never throws on non-strings. */
export function redactSensitive(text) {
  if (typeof text !== 'string' || text === '') return text ?? '';
  return SECRET_PATTERNS.reduce((value, pattern) => value.replace(pattern, REDACTED), text);
}

/** True when a detail key's value must never be rendered regardless of type. */
export function isSecretKey(name) {
  return typeof name === 'string' && SECRET_KEY_RE.test(name);
}

// ── Agent events ─────────────────────────────────────────────────────────────

/**
 * Per-event-type: the operator-facing label, and the ONLY detail keys that may
 * be rendered for it.
 *
 * The two violation types are the interesting entries: they get `[]`. Their
 * detail carries `frame_type`, `seq`, `last_seq` and validation-error text
 * straight off the wire, all of which describe the protocol rather than
 * anything an operator can act on. The event is still listed — it is an audit
 * record and hiding it would be worse — with a sentence saying what happened
 * and where the detail lives.
 */
const EVENT_TYPES = {
  enrolled: { label: 'Enrolled', keys: [] },
  connected: { label: 'Connected', keys: [] },
  disconnected: { label: 'Disconnected', keys: [] },
  approved: { label: 'Approved', keys: ['host_link_action'] },
  rejected: { label: 'Rejected', keys: ['reason'] },
  revoked: { label: 'Revoked', keys: ['reason'] },
  host_link_changed: { label: 'Linked hardware changed', keys: [] },
  capability_changed: { label: 'Capabilities changed', keys: [] },
  version_changed: { label: 'Version changed', keys: ['version'] },
  update_queued: { label: 'Update queued', keys: ['target_version'] },
  update_started: { label: 'Update started', keys: ['version'] },
  update_succeeded: { label: 'Update succeeded', keys: ['version'] },
  update_failed: { label: 'Update failed', keys: ['version', 'error'] },
  update_rolled_back: { label: 'Update rolled back', keys: ['version', 'error'] },
  key_rotated: { label: 'Device key rotated', keys: ['old_fingerprint', 'new_fingerprint'] },
  key_rotation_started: { label: 'Device key rotation started', keys: ['successor_fingerprint'] },
  key_rotation_expired: { label: 'Device key rotation expired', keys: [] },
  key_rotation_rejected: { label: 'Device key rotation refused', keys: ['reason'] },
  capability_violation: { label: 'Capability violation', keys: [] },
  protocol_violation: { label: 'Protocol violation', keys: [] },
};

// What the two violation rows say instead of their payload.
const VIOLATION_NOTE =
  'The server refused something this agent sent. The wire-level detail is deliberately not shown here; it is in the server log.';

/** Prose for the machine-readable reasons that DO reach an operator. */
const REASON_TEXT = new Map([
  ['pending_expired', 'the enrollment was never approved and timed out'],
  ['successor_pk_malformed', 'the agent offered a replacement key the server could not read'],
  ['successor_matches_current', 'the agent offered the key it is already using'],
  ['successor_key_in_use', 'another agent is already using that key'],
  ['uninstalled by agent', 'the agent reported that it had been uninstalled'],
]);

/** Humanize one allow-listed detail value. */
function detailValueText(key, value) {
  if (value == null || value === '') return null;
  if (isSecretKey(key)) return REDACTED;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return String(value);
  if (typeof value !== 'string') return null;
  return redactSensitive(REASON_TEXT.get(value) ?? value);
}

/**
 * One agent event, rendered safely.
 *
 * @returns {{label: string, tone: string, detail: string|null, isKnown: boolean}}
 */
export function describeAgentEvent(event) {
  const type = event?.event_type ?? '';
  const known = Object.hasOwn(EVENT_TYPES, type) ? EVENT_TYPES[type] : null; // eslint-disable-line security/detect-object-injection -- guarded by Object.hasOwn against a module-level literal
  const tone =
    type === 'protocol_violation' || type === 'capability_violation' || type.endsWith('_failed')
      ? 'critical'
      : type === 'revoked' || type === 'rejected' || type === 'update_rolled_back'
        ? 'warn'
        : 'ok';

  if (!known) {
    // An event type this build has never heard of. Its name is server-authored
    // and matches [a-z_]+ everywhere it is written, but it is still rendered
    // through the redactor rather than trusted — and its payload is dropped
    // entirely, because nothing here knows which of its keys are safe.
    return {
      label: redactSensitive(type.replaceAll('_', ' ')) || 'Event',
      tone,
      detail: null,
      isKnown: false,
    };
  }

  if (type === 'protocol_violation' || type === 'capability_violation') {
    return { label: known.label, tone, detail: VIOLATION_NOTE, isKnown: true };
  }

  const parts = [];
  for (const key of known.keys) {
    // eslint-disable-next-line security/detect-object-injection -- `key` is an element of a module-level literal array
    const text = detailValueText(key, event?.detail?.[key]);
    if (text) parts.push(`${key.replaceAll('_', ' ')}: ${text}`);
  }
  return {
    label: known.label,
    tone,
    detail: parts.length ? parts.join(' · ') : null,
    isKnown: true,
  };
}

// ── Install and enrollment failures ──────────────────────────────────────────

const HTTP_FORBIDDEN = 403;
const HTTP_NOT_FOUND = 404;
const HTTP_CONFLICT = 409;
const HTTP_UNAVAILABLE = 503;

/**
 * Turn an axios error from an install/enrollment call into something an
 * operator can act on, without echoing anything they should not see.
 *
 * The server's own `detail` is preferred where it exists, because on this path
 * it is written to be actionable (an unreadable TLS certificate names the file
 * and the chmod that fixes it). It is redacted on the way through rather than
 * trusted: this function has no way to know that every future 503 on this route
 * will be as careful, and a UI that depends on the server never making a
 * mistake is one change away from leaking.
 *
 * @param {*} error axios error
 * @param {{fallback: string, forbidden?: string}} copy
 */
export function operatorErrorMessage(error, copy) {
  const status = error?.response?.status;
  if (status === HTTP_FORBIDDEN && copy.forbidden) return copy.forbidden;
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail !== '') return redactSensitive(detail);
  // A 422's detail is an array of pydantic errors — a request-shape problem,
  // which is a bug on this side rather than something an operator can fix, and
  // whose `input` field can echo whatever was sent. Never rendered.
  return copy.fallback;
}

/**
 * The pairing-code lookup's failure. Deliberately one message for every cause.
 *
 * The endpoint is reachable by any authenticated user and takes a guessable
 * short code, so distinguishing "no such code" from "expired" from "already
 * approved" would turn the form into an oracle for enumerating them. It also
 * never echoes the code that was typed: the operator has it on screen already,
 * and a code in a toast is a code in a screenshot.
 */
export const PAIRING_LOOKUP_FAILED =
  'That pairing code did not match a machine waiting to be approved. Check it against what the agent printed — codes are short-lived, so re-run the installer if it has expired.';

/**
 * Update dispatch failures, mapped to the operator's next move.
 * The server's `detail` is used where present (it names the missing OS/arch
 * and version), redacted on the way through like every other passthrough.
 */
export function updateDispatchMessage(error) {
  const status = error?.response?.status;
  if (status === HTTP_FORBIDDEN) {
    return 'Only an administrator can dispatch an agent update.';
  }
  if (status === HTTP_NOT_FOUND) {
    return operatorErrorMessage(error, {
      fallback:
        'No agent binary is published for this host’s OS and architecture at that version. Publish one, or pick a version that has one.',
    });
  }
  if (status === HTTP_CONFLICT) {
    return 'An update is already in flight for this agent. Wait for it to report an outcome.';
  }
  if (status === HTTP_UNAVAILABLE) {
    return operatorErrorMessage(error, {
      fallback: 'The server cannot reach the update service right now. Try again shortly.',
    });
  }
  return operatorErrorMessage(error, {
    fallback: 'Could not queue the update. Check the agent is active and try again.',
  });
}
