import { describe, expect, it } from 'vitest';
import {
  CONFIRM_PHRASE_REVOKE,
  CONFIRM_PHRASE_ROTATE,
  TOKEN_EXPIRING_SOON_DAYS,
  confirmPhraseForToken,
  derivePosture,
  displayTokenLabel,
  filterTokens,
  issuanceRisk,
  isTokenActive,
  isTokenExpiringSoon,
  isTokenPrivileged,
  tokensToCsv,
  tokensToExportRows,
} from '../lib/accessTokens';

const NOW = new Date('2026-09-10T12:00:00Z');

describe('accessTokens helpers', () => {
  it('uses label for confirm phrase and fixed verbs when unlabeled', () => {
    expect(confirmPhraseForToken({ label: 'ci-deploy' }, 'revoke')).toBe('ci-deploy');
    expect(confirmPhraseForToken({ label: '  ' }, 'rotate')).toBe(CONFIRM_PHRASE_ROTATE);
    expect(confirmPhraseForToken({ label: null, id: 3 }, 'revoke')).toBe(CONFIRM_PHRASE_REVOKE);
    expect(confirmPhraseForToken({}, 'rotate')).toBe(CONFIRM_PHRASE_ROTATE);
  });

  it('never returns an empty confirm phrase', () => {
    expect(confirmPhraseForToken({ label: '' }, 'revoke').length).toBeGreaterThan(0);
  });

  it('treats null expiry as active and finite past expiry as inactive', () => {
    expect(isTokenActive({ expires_at: null }, NOW)).toBe(true);
    expect(isTokenActive({ expires_at: '2026-09-09T00:00:00Z' }, NOW)).toBe(false);
    expect(isTokenActive({ expires_at: '2026-09-20T00:00:00Z' }, NOW)).toBe(true);
  });

  it(`flags expiry within ${TOKEN_EXPIRING_SOON_DAYS} days`, () => {
    expect(isTokenExpiringSoon({ expires_at: '2026-09-20T00:00:00Z' }, NOW)).toBe(true);
    expect(isTokenExpiringSoon({ expires_at: '2026-10-01T00:00:00Z' }, NOW)).toBe(false);
    expect(isTokenExpiringSoon({ expires_at: null }, NOW)).toBe(false);
    expect(isTokenExpiringSoon({ expires_at: '2026-09-01T00:00:00Z' }, NOW)).toBe(false);
  });

  it('detects privileged scopes', () => {
    expect(isTokenPrivileged({ scopes: ['read:*'] })).toBe(false);
    expect(isTokenPrivileged({ scopes: ['*:*'] })).toBe(true);
    expect(isTokenPrivileged({ scopes: ['admin:*'] })).toBe(true);
    expect(isTokenPrivileged({ scopes: [] })).toBe(false);
  });

  it('derives posture from the loaded set', () => {
    const posture = derivePosture(
      [
        {
          id: 1,
          is_service_account: true,
          scopes: ['read:*'],
          expires_at: '2026-09-18T00:00:00Z',
        },
        {
          id: 2,
          is_service_account: false,
          scopes: ['*:*'],
          expires_at: null,
        },
        {
          id: 3,
          is_service_account: false,
          scopes: ['read:*'],
          expires_at: '2026-08-01T00:00:00Z',
        },
      ],
      NOW
    );
    expect(posture).toEqual({
      active: 2,
      serviceAccounts: 1,
      expiringSoon: 1,
      privileged: 1,
    });
  });

  it('filters by query and type', () => {
    const tokens = [
      {
        id: 1,
        label: 'grafana-collector',
        created_by_name: 'Shawn',
        scopes: ['write:telemetry'],
        is_service_account: true,
      },
      {
        id: 2,
        label: 'home-assistant',
        created_by_name: 'Shawn',
        scopes: ['read:*'],
        is_service_account: false,
      },
    ];
    expect(filterTokens(tokens, { query: 'grafana' })).toHaveLength(1);
    expect(filterTokens(tokens, { query: 'write:telemetry' })).toHaveLength(1);
    expect(filterTokens(tokens, { typeFilter: 'service' })).toHaveLength(1);
    expect(filterTokens(tokens, { typeFilter: 'user' })).toHaveLength(1);
    expect(filterTokens(tokens, { query: 'shawn', typeFilter: 'user' })).toHaveLength(1);
  });

  it('frames issuance risk without blocking create', () => {
    expect(issuanceRisk({ scopes: ['read:*'], expiryDays: 90 }).level).toBe('low');
    expect(issuanceRisk({ scopes: ['*:*'], expiryDays: 90 }).level).toBe('high');
    expect(issuanceRisk({ scopes: ['read:*'], expiryDays: null }).level).toBe('elevated');
  });

  it('exports metadata only', () => {
    const rows = tokensToExportRows([
      {
        id: 1,
        label: 'ci',
        is_service_account: false,
        scopes: ['read:*'],
        created_by_name: 'a',
        created_at: 't0',
        expires_at: null,
        last_used_at: null,
        token: 'secret-must-not-appear',
      },
    ]);
    expect(rows[0]).not.toHaveProperty('token');
    expect(tokensToCsv([{ id: 1, label: 'ci', scopes: ['read:*'] }])).toContain('id,label,type');
    expect(displayTokenLabel({ id: 9, label: '' })).toBe('token #9');
  });
});
