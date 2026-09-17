import { describe, it, expect } from 'vitest';
import { ACCEPTANCE_CAVEAT, describeDeliveryResult } from '../lib/notificationDelivery';

/**
 * Plan 05's central rule: configuration saved, endpoint accepted, and message
 * read by a person are three different events. The UI previously collapsed all
 * three into "Test delivered", which is the claim these tests exist to prevent.
 */
describe('describeDeliveryResult', () => {
  it('reports acceptance without claiming the message reached anyone', () => {
    const view = describeDeliveryResult({
      ok: true,
      state: 'accepted',
      reason_code: 'provider_accepted',
      message: 'Slack accepted the request.',
      provider: 'slack',
      sink_id: 3,
      attempt_count: 1,
      http_status: 200,
    });

    expect(view.tone).toBe('accepted');
    expect(view.title).toBe('Accepted by Slack');
    expect(view.detail).toBe('Slack accepted the request.');
    expect(view.caveat).toBe(ACCEPTANCE_CAVEAT);
    // The bug this replaces.
    expect(JSON.stringify(view)).not.toMatch(/delivered|sent successfully/i);
  });

  it('treats an exhausted retry as a terminal failure, not an ongoing retry', () => {
    const view = describeDeliveryResult({
      ok: false,
      state: 'terminal',
      reason_code: 'retry_exhausted',
      message: 'The provider is temporarily unavailable.',
      error: 'The provider is temporarily unavailable.',
      provider: 'discord',
      sink_id: 4,
      attempt_count: 3,
      http_status: 500,
    });

    expect(view.tone).toBe('failed');
    expect(view.title).toBe('Discord did not accept it');
    expect(view.facts).toContainEqual({ label: 'Attempts', value: '3' });
    expect(view.facts).toContainEqual({ label: 'HTTP status', value: '500' });
    expect(view.caveat).toBeNull();
  });

  it('surfaces the retry-after window when a provider rate-limits', () => {
    const view = describeDeliveryResult({
      ok: false,
      state: 'retryable',
      reason_code: 'rate_limited',
      message: 'The provider rate-limited the request.',
      provider: 'teams',
      sink_id: 5,
      attempt_count: 2,
      http_status: 429,
      retry_after: 12,
    });

    expect(view.tone).toBe('retrying');
    expect(view.facts).toContainEqual({ label: 'Retry after', value: '12s' });
  });

  it('tells an operator what to do about rejected credentials', () => {
    const view = describeDeliveryResult({
      ok: false,
      state: 'terminal',
      reason_code: 'authentication_rejected',
      message: 'The provider rejected the destination credentials.',
      provider: 'slack',
      sink_id: 6,
      attempt_count: 1,
      http_status: 401,
    });

    expect(view.tone).toBe('failed');
    expect(view.guidance).toMatch(/credential/i);
  });

  it('never invents a reason the server did not give', () => {
    const view = describeDeliveryResult({
      ok: false,
      state: 'terminal',
      reason_code: 'some_code_the_ui_has_never_heard_of',
      message: 'The destination is not fully configured.',
      provider: 'webhook',
      sink_id: 7,
      attempt_count: 1,
    });

    // Server copy is shown verbatim; guidance is simply absent.
    expect(view.detail).toBe('The destination is not fully configured.');
    expect(view.guidance).toBeNull();
  });

  it('omits facts the server did not report rather than showing blanks', () => {
    const view = describeDeliveryResult({
      ok: false,
      state: 'terminal',
      reason_code: 'policy_rejected',
      message: 'The destination was rejected by outbound policy.',
      provider: 'webhook',
      sink_id: 8,
      attempt_count: 1,
    });

    const labels = view.facts.map((fact) => fact.label);
    expect(labels).not.toContain('HTTP status');
    expect(labels).not.toContain('Retry after');
  });

  it('degrades honestly when the request never produced a result', () => {
    const view = describeDeliveryResult(null);

    expect(view.tone).toBe('failed');
    expect(view.title).toBe('No result');
    expect(view.detail).toMatch(/could not be read/i);
    expect(view.facts).toEqual([]);
  });
});

describe('guidance covers every reason code the backend emits', () => {
  // The module claims to be keyed by the codes the backend actually emits. These
  // three were emitted with no next action, which is the gap this closes.
  it.each([
    ['credential_unavailable', /re-enter them/i],
    ['delivery_error', /test again/i],
    ['request_failed', /never left/i],
  ])('offers a next action for %s', (reason_code, expected) => {
    const view = describeDeliveryResult({
      state: 'terminal',
      reason_code,
      message: 'Something went wrong.',
      provider: 'slack',
    });

    expect(view.guidance).toMatch(expected);
  });

  it('still refuses to invent guidance for a code it does not know', () => {
    const view = describeDeliveryResult({
      state: 'terminal',
      reason_code: 'a_code_from_the_future',
      message: 'Something went wrong.',
      provider: 'slack',
    });

    expect(view.guidance).toBeNull();
  });
});
