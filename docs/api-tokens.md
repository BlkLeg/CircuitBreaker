# API tokens and service accounts

Admins manage machine credentials on **Govern → Access Tokens** (`/admin/tokens`).
That workbench is where least privilege is chosen: inventory across every
administrator, scope presets from the server catalog, rotate, revoke, and a
one-time secret dialog.

Profile → **API tokens** remains a personal mint: label and expiry only. Those
tokens inherit the creator's effective scopes (INC-04 / INC-14). Use the admin
page when you need a narrower grant or a service account.

## Rules operators must keep

1. **The secret is shown once** after create or rotate. Acknowledge “I've stored
   it” only after the value is in your secret manager. It cannot be retrieved
   later from the inventory.
2. **HTTP rotation kills the old secret immediately.** There is no overlap
   window on the API. The CLI `cb token rotate --overlap-hours` path is separate
   and stays CLI-only.
3. **Rotate preserves label, scopes, and expiry.** The rotating admin becomes
   the recorded `created_by` of the replacement row.
4. **Revoke is permanent.** Typed confirmation uses the credential label, or
   `ROTATE` / `REVOKE` when the row has no label.
5. **Export is metadata only** (CSV/JSON): id, label, type, scopes, creator,
   timestamps. Secrets are never exported.
6. **Audit:** Browser create / rotate / revoke write `api_token_created`,
   `api_token_rotated`, and `api_token_revoked` to the audit log (same action
   names as the CLI, with `via=http` in the details). Secrets never appear in
   those entries.

## Posture strip

Counts are derived from the currently loaded inventory (`All tokens` or
`My tokens`):

| Metric | Meaning |
| --- | --- |
| Active credentials | Not expired (`expires_at` null or in the future) |
| Service accounts | `is_service_account` |
| Expiring soon | Expires within 14 days |
| Privileged | Scopes include `*:*` or `admin:*` |

`last_used_at` is updated on successful API-token and service-account
authentication (throttled). The posture strip does **not** treat “active” as
“recently used.”

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/api-token` | Create user API token |
| `POST` | `/api/v1/auth/service-account` | Create service-account JWT |
| `GET` | `/api/v1/auth/api-tokens?scope=mine\|all` | Inventory |
| `POST` | `/api/v1/auth/api-tokens/{id}/rotate` | Replace secret |
| `DELETE` | `/api/v1/auth/api-tokens/{id}` | Revoke |
| `GET` | `/api/v1/auth/scopes` | Grantable scopes and UI presets |

All routes require an admin. Presets always come from `GET /auth/scopes` — the
UI does not hardcode the grantable set.
