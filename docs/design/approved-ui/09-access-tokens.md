# 09 · Access Tokens — SOC credential operations

Status: implemented against the canvas redesign. Visual baseline:
[Access Tokens — SOC Credential Operations](https://p.superdesign.dev/draft/7ee1e075-ef76-4eb3-a1e0-73d9e2a15a88)
(v1; baseline reproduction
[Current Access Tokens — Baseline](https://p.superdesign.dev/draft/5fb3b4b6-74e2-4420-830f-d62757c7b7b8)).
Depends on plan 00. Does not reopen INC-14 scope enforcement; that capability already shipped.

## Outcome and location

`/admin/tokens` remains the single admin home for fleet credential operations: inventory,
least-privilege issuance, one-time secret reveal, rotate, and revoke. The page keeps the
existing six auth endpoints and admin route guard. The redesign turns the functional INC-14
screen into a dense, theme-aware credential workbench matching the approved SOC composition
without inventing a second token subsystem.

Existing integration points:

- Frontend: `pages/AccessTokensPage.jsx`, `components/settings/AccessTokensManager.jsx`,
  `api/tokens.js`, `components/common/HighRiskConfirmDialog.jsx`, `components/common/Toast.jsx`,
  `components/auth/ProfileModal.jsx` (personal mint only), `data/routeGuards.js`,
  `data/navigation.js`
- Backend: `api/auth.py` (`create_api_token`, `create_service_account`, `list_api_tokens`,
  `revoke_api_token`, `rotate_api_token`, `list_grantable_scopes`), `core/token_scopes.py`,
  `core/security.py`, `core/rbac.py`, `db/models/auth.py` (`APIToken`),
  `scripts/cli_admin.py` (CLI parity + audit actions today)

Preserve ProfileModal’s label-only personal mint (defaults to the creator’s effective scopes
per INC-14). The admin page is where least privilege is chosen; do not duplicate the SOC
issuance panel into Profile.

## Canvas translation invariants

Keep from the approved draft:

- Page chrome: Administration breadcrumb, “Identity & access / Credential operations”
  eyebrow, Access Tokens title, primary **Create token** action
- Posture strip with four derived metrics (definitions below)
- Credential inventory panel: All tokens / My tokens, search, type filter, metadata table,
  row actions for rotate/revoke
- Issue credential side panel: label, identity (user vs service account), expiry, access
  profile presets from `GET /auth/scopes`, effective-scope chips, risk badge, create CTA
- One-time secret dialog after create/rotate: secret shown once, copy, explicit “I’ve
  stored it” acknowledgement
- Persistent dock and GlobalHeader branding stay the application’s real chrome; do not
  paste canvas CDN scripts, hard-coded Gruvbox hex, or uploaded prototype asset URLs into
  production

Omit as review scaffolding:

- Fabricated control-plane health strip / wall-clock in the header center
- Hard-coded sample inventory counts that disagree with the loaded list
- Export that includes secrets or raw token material
- Any claim that HTTP create/rotate/revoke is “audited” until backend audit events exist

Theme: Gruvbox is presentation only. Use plan 00 tokens (`--color-bg`, `--color-surface`,
`--color-primary`, semantic status pairs, etc.). Status must remain readable from
labels/icons when the palette changes.

## Posture and inventory contract

Derive posture from the loaded inventory (`scope=all` for fleet posture; when the operator
is on “My tokens”, show metrics for the currently visible set and label that clearly).

| Metric | Honest definition |
| --- | --- |
| Active credentials | Rows that are not expired (`expires_at` null or in the future). Do **not** call this “in use” until `last_used_at` is written on successful auth. |
| Service accounts | Rows with `is_service_account === true` (current label-prefix heuristic until a real column exists). |
| Expiring soon | Non-null `expires_at` within 14 days (constant named and tested). |
| Privileged | Scopes include `*:*` or `admin:*`. |

Search and filters are client-side over the already-fetched list for this delivery:

- Text: case-insensitive match on label, creator name, and scope strings
- Type: All / User token / Service account
- Inventory scope: existing `mine` \| `all` (server query), default remains product choice;
  the canvas default of “all” is acceptable for the admin workbench if tests and empty
  states stay coherent

Empty, loading, and error states replace the whole workbench content with existing patterns
(`EmptyState`, inline alert + Retry). Never leave an empty `<tbody>` with no explanation.

Export (optional work package): client-side CSV or JSON of **metadata only** — id, label,
type, scopes, creator, created/expires/last_used timestamps. Never export the secret. Air-gap
safe: no outbound calls.

## Issuance, secret, and destructive actions

- Presets continue to come from `GET /auth/scopes`; never hardcode `SCOPE_PRESETS` in the UI.
- Selecting Full access (`*:*`) or Never expiry must raise visible risk framing (badge +
  short warning). Do not block create — least privilege is the default, not a hard gate.
- Create calls existing `POST /auth/api-token` or `POST /auth/service-account` based on
  identity. Labels stay freeform (including empty → null).
- One-time secret UI becomes a modal (focus trap, Escape does not discard without an
  explicit path, Copy uses the existing clipboard helper with a visible failure toast).
  Clearing acknowledgement clears local secret state; reload cannot recover it.
- Rotate and revoke keep `HighRiskConfirmDialog`. Confirm phrase must work for unlabeled
  tokens (use a stable fallback such as the truncated id or a fixed verb like `REVOKE` /
  `ROTATE` — pick one approach, document it, and test empty labels). Do not enable Confirm
  on an empty phrase.
- HTTP rotate remains immediate kill of the old secret (CLI overlap windows stay CLI-only
  unless a separate, tested API lands later).

## Backend honesty (required for SOC claims)

These are small correctness fixes, not a new token service:

1. **Audit:** HTTP create, rotate, and revoke must call the same `log_audit` actions the CLI
   already uses (`api_token_created`, `api_token_rotated`, `api_token_revoked`) with safe
   metadata (id, label, scopes, actor) and **never** the secret.
2. **`last_used_at`:** either start writing it on successful API-token / service-account
   authentication, or keep the posture strip free of “last used / active usage” language.
   Prefer writing the timestamp (throttled if needed) so the existing column stops lying.
3. **Unlabeled confirm / rotate `created_by`:** document current rotate ownership behavior;
   do not silently change creator semantics without a test and operator note.
4. **No schema rename/drop.** If promoting service-account detection beyond the label
   prefix, add a nullable boolean with `ADD COLUMN IF NOT EXISTS` and dual-read; do not
   require a rewrite of existing rows to ship the UI.

No new list endpoint is required for v1 if posture and search stay client-side over
`GET /auth/api-tokens`.

## UI boundaries and work packages

Keep `AccessTokensPage` as a thin shell. Concentrate behavior in `AccessTokensManager` or
small focused children extracted only when they have a clear responsibility (posture strip,
inventory table, issue panel, secret modal). Feature-local helpers for posture derivation,
metadata export, and risk labeling belong next to the manager — not in a generic workflow
engine.

- [x] **A1:** Lock contracts in tests: posture derivations, 14-day expiry window, privileged
  scope detection, search/filter matching, unlabeled confirm-phrase behavior, and “secret
  cleared after acknowledge.” Extend `access-tokens-manager.test.jsx` and
  `test_api_tokens_admin.py` / CLI audit tests as needed.
- [x] **A2:** Theme-aware page composition from the canvas: posture strip, inventory toolbar,
  issue panel, empty/loading/error. Reuse Panel / EmptyState / Banner / button primitives;
  no page-local hex palette.
- [x] **A3:** Wire search, type filter, and mine/all to the existing list payload. Preserve
  create/rotate/revoke API payloads and server-driven presets.
- [x] **A4:** Replace the inline reveal with a one-time secret modal; cover create and rotate
  paths; clipboard failure is visible and non-destructive.
- [x] **A5:** Fix destructive confirms for unlabeled tokens; keep typed confirmation; ensure
  busy/error paths do not lose dialog context incorrectly.
- [x] **A6:** Backend audit events on HTTP create/rotate/revoke; optional throttled
  `last_used_at` writes on successful token auth. Regenerate endpoint inventory only if
  routes change (they should not).
- [x] **A7:** Optional metadata-only export control. Document what is and is not included.
- [x] **A8:** Operator docs (`docs/api-tokens.md` or equivalent): admin workbench vs Profile
  personal mint, one-time secret rule, rotation kills the old secret immediately, audit
  visibility. Update MkDocs nav if a new page is added.

## Acceptance and tests

- Admin gate unchanged: non-admins hitting `/admin/tokens` redirect; API stays
  `require_role("admin")`.
- Creating with each server preset stores exactly those scopes; unknown scopes still 422.
- Service-account checkbox hits `POST /auth/service-account`; user path hits
  `POST /auth/api-token`.
- Secret appears once after create/rotate, never in list/export/audit payloads or after
  acknowledgement.
- Rotate invalidates the previous secret; revoke removes the row; cache invalidation remains.
- Posture numbers match the filtered list under the documented definitions; theme switches
  do not leave hard-coded dark colors.
- Unlabeled token rotate/revoke cannot confirm with an empty phrase.
- HTTP create/rotate/revoke produce audit events comparable to CLI.
- Existing suites stay green: `access-tokens-manager.test.jsx`, `access-tokens-page.test.jsx`,
  `tokens-api.test.js`, `test_api_tokens_admin.py`, `test_token_scopes.py`,
  `test_service_account_revocation.py`, relevant CLI audit tests.
- Browser-check Gruvbox dark/light plus one contrasting preset; keyboard focus through
  issue panel, modal, and confirm dialog; reduced-motion respected.

## Out of scope

- HTTP rotation overlap windows (CLI-only today)
- Soft-delete / credential history tables
- New grantable scopes or a per-resource ACL matrix
- Moving Profile personal mint onto this page, or adding a scope picker there
- Enrollment tokens, vault-stored third-party API tokens, or deprecated `CB_API_TOKEN`
- Shipping canvas sample data or prototype-only controls as live capabilities
