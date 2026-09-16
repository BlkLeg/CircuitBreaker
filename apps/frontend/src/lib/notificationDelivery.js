/**
 * Presentation for a notification delivery test result (plan 05).
 *
 * The backend already classifies every outcome and ships a sanitized
 * `message` with it, so this module deliberately does not restate the reason in
 * its own words — it frames the server's copy and adds what only the UI knows:
 * what an operator should do next.
 *
 * The rule the whole module exists to enforce: acceptance by a provider is not
 * receipt by a person. `ACCEPTANCE_CAVEAT` says so on every accepted result,
 * because the surface this replaced rendered a bare "Test delivered".
 */

export const DELIVERY_ACCEPTED = 'accepted';
export const DELIVERY_RETRYABLE = 'retryable';
export const DELIVERY_TERMINAL = 'terminal';

export const ACCEPTANCE_CAVEAT =
  'The provider accepted the request. That is not proof a person received it.';

const TONE_BY_STATE = {
  [DELIVERY_ACCEPTED]: 'accepted',
  [DELIVERY_RETRYABLE]: 'retrying',
  [DELIVERY_TERMINAL]: 'failed',
};

/**
 * What to do next, keyed by the reason codes the backend actually emits
 * (services/notification_delivery.py). An unknown code yields no guidance
 * rather than a guess — inventing advice for an outcome we do not recognise is
 * how a UI starts lying about a system it no longer understands.
 */
const GUIDANCE_BY_REASON = {
  authentication_rejected: 'Check the destination credentials, then test again.',
  rate_limited: 'The provider asked for a pause. Wait for the retry window before testing again.',
  upstream_unavailable: 'The provider is down. Test again once it is reachable.',
  timeout: 'The provider did not answer in time. Test again once it is responsive.',
  network_error: 'The destination could not be reached. Check the URL and your egress rules.',
  missing_configuration: 'Complete the destination configuration, then test again.',
  missing_recipient: 'Add a recipient address to this destination, then test again.',
  smtp_not_configured: 'Configure SMTP in settings before testing an email destination.',
  policy_rejected: 'Outbound policy refused this destination. Check it against your egress rules.',
  redirect_rejected: 'Point the destination at the provider’s webhook URL, not a redirect.',
  provider_rejected: 'The provider refused the request. Check the destination URL.',
  invalid_response: 'The destination did not answer like the provider it claims to be.',
  unsupported_provider: 'This provider is not supported for delivery.',
  retry_exhausted: 'Every attempt failed. Fix the destination, then test again.',
  destination_unavailable: 'The destination is disabled or removed. Re-enable it, then test again.',
  no_route: 'No severity route points at this destination yet.',
};

function providerLabel(provider) {
  if (!provider) return 'The destination';
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

function factsFor(result) {
  const facts = [];
  if (Number.isFinite(result.attempt_count)) {
    facts.push({ label: 'Attempts', value: String(result.attempt_count) });
  }
  if (Number.isFinite(result.http_status)) {
    facts.push({ label: 'HTTP status', value: String(result.http_status) });
  }
  if (Number.isFinite(result.retry_after)) {
    facts.push({ label: 'Retry after', value: `${result.retry_after}s` });
  }
  return facts;
}

/**
 * Project a `TestResult` onto what the panel renders.
 *
 * @param {object|null} result - the server's TestResult, or null if none arrived.
 * @returns {{tone: string, title: string, detail: string, guidance: string|null,
 *            facts: Array<{label: string, value: string}>, caveat: string|null}}
 */
export function describeDeliveryResult(result) {
  if (!result || typeof result !== 'object') {
    return {
      tone: 'failed',
      title: 'No result',
      detail: 'The test finished but its result could not be read.',
      guidance: null,
      facts: [],
      caveat: null,
    };
  }

  const tone = TONE_BY_STATE[result.state] ?? 'failed';
  const accepted = tone === 'accepted';
  const who = providerLabel(result.provider);

  return {
    tone,
    title: accepted ? `Accepted by ${who}` : `${who} did not accept it`,
    detail: result.message || result.error || 'No reason was reported.',
    guidance: GUIDANCE_BY_REASON[result.reason_code] ?? null,
    facts: factsFor(result),
    caveat: accepted ? ACCEPTANCE_CAVEAT : null,
  };
}
