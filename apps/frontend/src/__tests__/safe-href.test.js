/**
 * `service.url` is operator-supplied and rendered into an anchor href, so a stored
 * `javascript:` payload ran with the viewer's session — an editor could escalate
 * through any admin who opened the service.
 *
 * The schema validator refuses new rows, but rows written before it existed are still
 * in the database. This helper is what protects those, so it is the load-bearing half.
 */
import { describe, it, expect } from 'vitest';
import { safeHref } from '../utils/validation';

describe('safeHref', () => {
  it.each([
    'javascript:alert(document.cookie)',
    'JaVaScRiPt:alert(1)',
    '  javascript:alert(1)',
    'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    '//evil.test/phishing',
  ])('returns undefined for %s', (url) => {
    expect(safeHref(url)).toBeUndefined();
  });

  it.each([
    'https://grafana.example.test/d/abc',
    'http://nas.lan:8080',
    'HTTPS://EXAMPLE.TEST',
    'mailto:ops@example.test',
    '/hardware/12',
  ])('passes %s through unchanged', (url) => {
    expect(safeHref(url)).toBe(url);
  });

  it.each([null, undefined, ''])('returns undefined for the empty value %s', (url) => {
    expect(safeHref(url)).toBeUndefined();
  });

  it('returns undefined rather than an empty string, so the anchor cannot navigate', () => {
    // href="" resolves to the current page and still follows on click; no href at all
    // renders inert, which is the correct shape for a URL we have decided not to trust.
    expect(safeHref('javascript:alert(1)')).not.toBe('');
  });
});
