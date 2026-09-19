/**
 * Pure helpers for the Access Tokens admin workbench.
 *
 * Posture and filter rules live here so the UI and tests share one contract
 * (docs/design/approved-ui/09-access-tokens.md).
 */

export const TOKEN_EXPIRING_SOON_DAYS = 14;

export const PRIVILEGED_SCOPES = Object.freeze(['*:*', 'admin:*']);

/** Fixed confirm phrases when a token has no label (HighRiskConfirmDialog). */
export const CONFIRM_PHRASE_ROTATE = 'ROTATE';
export const CONFIRM_PHRASE_REVOKE = 'REVOKE';

export function displayTokenLabel(token) {
  const label = token?.label?.trim();
  if (label) return label;
  return token?.id != null ? `token #${token.id}` : 'token';
}

/**
 * Phrase the operator must type to confirm rotate/revoke.
 * Prefer the real label; fall back to a fixed verb so unlabeled rows cannot
 * arm Confirm with an empty string.
 */
export function confirmPhraseForToken(token, mode) {
  const label = token?.label?.trim();
  if (label) return label;
  return mode === 'rotate' ? CONFIRM_PHRASE_ROTATE : CONFIRM_PHRASE_REVOKE;
}

export function isTokenExpired(token, now = new Date()) {
  if (!token?.expires_at) return false;
  const expires = new Date(token.expires_at);
  if (Number.isNaN(expires.getTime())) return false;
  return expires.getTime() <= now.getTime();
}

export function isTokenActive(token, now = new Date()) {
  return !isTokenExpired(token, now);
}

export function isTokenExpiringSoon(token, now = new Date()) {
  if (!token?.expires_at) return false;
  const expires = new Date(token.expires_at);
  if (Number.isNaN(expires.getTime())) return false;
  const ms = expires.getTime() - now.getTime();
  if (ms <= 0) return false;
  return ms <= TOKEN_EXPIRING_SOON_DAYS * 86400000;
}

export function isTokenPrivileged(token) {
  const scopes = token?.scopes;
  if (!Array.isArray(scopes) || scopes.length === 0) return false;
  return scopes.some((s) => PRIVILEGED_SCOPES.includes(s));
}

/**
 * Derive posture metrics from the currently loaded inventory set.
 * "Active" means not expired — never "in use" (that requires last_used writes).
 */
export function derivePosture(tokens, now = new Date()) {
  const list = Array.isArray(tokens) ? tokens : [];
  return {
    active: list.filter((t) => isTokenActive(t, now)).length,
    serviceAccounts: list.filter((t) => t.is_service_account).length,
    expiringSoon: list.filter((t) => isTokenExpiringSoon(t, now)).length,
    privileged: list.filter((t) => isTokenPrivileged(t)).length,
  };
}

/**
 * Client-side inventory filter over an already-fetched list.
 * @param {'all'|'user'|'service'} [typeFilter]
 */
export function filterTokens(tokens, { query = '', typeFilter = 'all' } = {}) {
  const list = Array.isArray(tokens) ? tokens : [];
  const q = String(query || '')
    .trim()
    .toLowerCase();

  return list.filter((t) => {
    if (typeFilter === 'service' && !t.is_service_account) return false;
    if (typeFilter === 'user' && t.is_service_account) return false;
    if (!q) return true;
    const hay = [
      t.label,
      t.created_by_name,
      ...(Array.isArray(t.scopes) ? t.scopes : []),
      t.is_service_account ? 'service account' : 'user token',
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return hay.includes(q);
  });
}

/**
 * Risk framing for the issuance panel. Does not block create.
 */
export function issuanceRisk({ scopes = [], expiryDays = 90 } = {}) {
  const privileged = scopes.some((s) => PRIVILEGED_SCOPES.includes(s));
  const neverExpires = expiryDays == null;
  if (privileged) {
    return {
      level: 'high',
      label: 'High risk',
      hint: neverExpires
        ? 'Full access with no expiry. Prefer a shorter life and a narrower profile.'
        : 'Full access grants unrestricted API power. Prefer the least privilege that works.',
    };
  }
  if (scopes.some((s) => String(s).includes('write:'))) {
    return {
      level: 'elevated',
      label: 'Elevated',
      hint: neverExpires
        ? 'Write scopes with no expiry. Prefer a finite lifetime.'
        : 'Write scopes can modify inventory and integrations.',
    };
  }
  if (neverExpires) {
    return {
      level: 'elevated',
      label: 'Elevated',
      hint: 'Credentials that never expire stay valid until revoked. Prefer a finite lifetime.',
    };
  }
  return {
    level: 'low',
    label: 'Low risk',
    hint: 'Least privilege by default. The secret is shown once after creation.',
  };
}

/** Metadata-only rows for export — never includes secrets. */
export function tokensToExportRows(tokens) {
  return (Array.isArray(tokens) ? tokens : []).map((t) => ({
    id: t.id,
    label: t.label ?? '',
    type: t.is_service_account ? 'service_account' : 'user_token',
    scopes: Array.isArray(t.scopes) ? t.scopes.join('|') : '',
    created_by: t.created_by_name ?? '',
    created_at: t.created_at ?? '',
    expires_at: t.expires_at ?? '',
    last_used_at: t.last_used_at ?? '',
  }));
}

export function tokensToCsv(tokens) {
  const rows = tokensToExportRows(tokens);
  const headers = [
    'id',
    'label',
    'type',
    'scopes',
    'created_by',
    'created_at',
    'expires_at',
    'last_used_at',
  ];
  const escape = (value) => {
    const s = String(value ?? '');
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  return [
    headers.join(','),
    ...rows.map((r) =>
      [
        escape(r.id),
        escape(r.label),
        escape(r.type),
        escape(r.scopes),
        escape(r.created_by),
        escape(r.created_at),
        escape(r.expires_at),
        escape(r.last_used_at),
      ].join(',')
    ),
  ].join('\n');
}

export function tokensToJson(tokens) {
  return `${JSON.stringify(tokensToExportRows(tokens), null, 2)}\n`;
}

export function downloadTextFile(filename, contents, mime = 'text/plain') {
  const blob = new Blob([contents], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
