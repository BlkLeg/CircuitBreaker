# TLS Lifecycle and Honest Surfaces — Design

**Date:** 2026-08-24
**Status:** Approved design, not yet implemented
**Branch context:** `dev` at `de9ff24c`; `VERSION` = `1.0.0-rc.3`
**Register:** Batch B — INC-07, INC-08, INC-16, INC-18, plus **INC-22**, a finding this
design surfaced and which is not in the register yet.
**Precedes:** Batch C (INC-15, restore) and Batch D (INC-09, i18n).

**Standing policy for 1.0.0:** *when a surface promises more than the build delivers, remove
the scaffolding and state the boundary.* Three of the five findings here resolve that way.
**INC-07 is the deliberate exception** — product chose to finish the feature rather than
remove it, and INC-22 is why that choice costs more than it first appeared.

## 1. Problem

Four register findings and one this design found. They are batched because each is a surface
that claims a capability the build does not have; three are closed by deletion and two by
making the claim true.

### 1.1 INC-22 — the Certificates feature does not affect the TLS the product serves

**Not in the register.** Found while scoping INC-07, and it subsumes it.

`nginx.mono.conf:81-82` serves TLS from two files:

```nginx
ssl_certificate     /data/tls/fullchain.pem;
ssl_certificate_key /data/tls/privkey.pem;
```

Who writes them, per mode:

| Mode | Writer | When | Reloads nginx |
|---|---|---|---|
| Mono / Docker | `docker/entrypoint-mono.sh:153-160` | first boot, **only if both files are absent** | never |
| Native install | `cb_helperd.action_configure_domain` (`deploy/helper/cb_helperd.py:365`) | on domain configuration | `systemctl reload nginx` |
| **`services/certificate_service.py`** | **never** | — | **never** |

`certificate_service.py` contains no write to `/data/tls` and no reload of anything. So every
certificate the Certificates page creates, imports, renews, or auto-renews is a database row
that no TLS listener reads. The bytes nginx serves are the self-signed pair the entrypoint
generated at first boot and never touches again.

This reframes INC-07. The register records that "self-signed renewal works correctly" —
correct only in the sense that it updates a row nobody serves. What is inert is not the ACME
half; it is the feature's connection to the running server. **Issuing a real Let's Encrypt
certificate changes nothing observable until this is fixed**, which is why it is designed
first and why it is the precondition for §1.2.

### 1.2 INC-07 — Let's Encrypt is worse than inert; it mislabels

Two defects, and the register records only the second.

**Creation silently substitutes.** `certificate_service.create_certificate:85-108` branches on
whether a PEM was pasted, never on `data.type`:

```python
if data.cert_pem and data.key_pem:
    ...
else:
    cert_pem, raw_key_pem, expires_at = generate_selfsigned(data.domain)
```

Choose **Let's Encrypt** in the UI (`CertificatesPage.jsx:57-58`) without pasting a PEM and
the product generates a self-signed certificate and stores it with `type="letsencrypt"`. The
table then renders it as "Let's Encrypt" (`CertificatesPage.jsx:119`). The operator is told
they hold a CA-issued certificate and they hold a self-signed one.

**Renewal cannot work and reports success anyway.** `renew_certificate:156-208` shells out to
`certbot certonly --standalone`, which fails for four independent reasons: certbot is in
neither `Dockerfile` nor `Dockerfile.mono`; `--standalone` binds port 80 while application
processes run as `breaker:1000`; the ACME account email is hardcoded to `admin@localhost`
while `docker/.env.example:32` advertises a `CB_TLS_EMAIL` that no code reads; and on
`FileNotFoundError` the function logs a warning and `return cert` — unchanged. `POST
/certificates/{id}/renew` therefore answers `200` with the old expiry and the UI shows
success. The same swallowing happens on a non-zero certbot exit.

### 1.3 INC-08 — email password reset is disabled, and its scaffolding is orphaned

`POST /auth/forgot-password` and `POST /auth/reset-password` both raise `410 Gone`
(`api/auth.py:195,208`), and the UI says so in two places.

The register describes the supporting code as "all still present and maintained". Present,
but not maintained and not referenced: **nothing under `app/` imports
`services/password_reset_service.py` or `services/magic_link_service.py`.** The only mentions
outside the files themselves are in `tests/test_auth_e2e.py`, whose own docstring at line 20
already records them as "specified but never wired into a router".

What the register frames as an open question — whether a non-admin has any recovery path —
has an answer it does not mention. `POST /admin/users/{user_id}/reset-password`
(`api/admin_users.py:377`) is complete and careful: it generates a temporary password,
returns it exactly once, sets `force_password_change`, revokes every session, and writes an
audit entry. Recovery exists; it is administrator-mediated.

### 1.4 INC-16 — two of four valid providers work, and the other two work at nothing

`schemas/integration_provider.py:9` declares `VALID_PROVIDERS = {"proxmox", "docker",
"truenas", "unifi"}`, enforced at `api/integration_provider.py:35`.
`integration_provider_service.test_config:157-160` dispatches to `_test_proxmox` and
`_test_docker` and returns an error string for anything else.

The register calls this "the UI can create a config it cannot validate". It is worse: there
is **no sync implementation for truenas or unifi either**. The only other mentions of those
names in the backend are in discovery fingerprinting and inference, which match device
names and have nothing to do with integration configs. An operator can therefore store
TrueNAS or UniFi credentials in a configuration the product will never use for anything.

### 1.5 INC-18 — a settings field nothing reads

`show_experimental_features` exists on `AppSettings` (`db/models.py:1299`), in
`schemas/settings.py:98`, and has its own migration (`0011_pg_show_experimental_boolean`).
No backend or frontend code reads it.

## 2. Decisions

1. **INC-22 first.** A certificate becomes servable: activation writes it to `/data/tls` and
   reloads the TLS server. §3.
2. **INC-07 is finished, not removed** — the batch's one exception to the standing policy.
   ACME issuance and renewal via HTTP-01 (webroot) and DNS-01 (Cloudflare, RFC2136). §4.
3. **INC-08 removes.** The orphaned services are deleted; the routes keep answering `410` and
   the message names the real recovery path. §5.
4. **INC-16 removes.** `VALID_PROVIDERS` narrows to what works; a migration deletes the
   orphaned configurations and their stored credentials, audited. §6.
5. **INC-18 removes.** The field leaves the settings schema. §7.

## 3. INC-22 — making a certificate servable

### 3.1 An active certificate

`Certificate` has `domain` (unique), `type`, `cert_pem`, `key_pem`, `expires_at`,
`auto_renew` — and no notion of which row is the one in use. Migration adds:

```python
is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

with a partial unique index so at most one row can hold it:

```sql
CREATE UNIQUE INDEX ix_certificates_single_active
  ON certificates (is_active) WHERE is_active;
```

The index is the constraint, not application code — two active certificates is a state where
the question "what are we serving?" has no answer, and the database should refuse it.

**Upgrade:** the migration marks active the row whose `domain` matches `CB_DOMAIN`, or the
single row if only one exists, or none. It must not guess between several: an install with
three certificates gets none marked and a Certificates page that says so, which is honest.
This is a widening of what the page reports, not of what nginx serves — nginx keeps serving
the entrypoint's self-signed pair until an operator activates something.

### 3.2 `services/certificate_activation.py`

New, and the only place that decides what is on disk. One entry point:

```python
def activate_certificate(db: Session, cert: Certificate) -> ActivationResult
```

It writes `fullchain.pem` and `privkey.pem` into `${CB_DATA_DIR}/tls/`, **atomically** —
write to a temporary file in the same directory, `os.chmod` to `0600` for the key and `0644`
for the chain, then `os.replace`. A partial write here is a TLS server that will not start;
`os.replace` is atomic within a filesystem and is what keeps a crash mid-write from producing
one.

The key is decrypted through the existing vault (`cert.key_pem` is stored encrypted, per
`create_certificate:90`). It is written in plaintext to `/data/tls` because that is what nginx
reads — the design does not pretend otherwise, and `/data/tls` inherits the data volume's
permissions.

Then it reloads, and **the reload is part of activation, not a separate step an operator can
forget**: a certificate written and not reloaded is the old certificate still being served.

### 3.3 Reload, per mode

One function, three branches, each detected rather than configured:

| Mode | Detection | Reload |
|---|---|---|
| Mono | nginx's pidfile (`/tmp/nginx.pid`, `nginx.mono.conf:5`) names a live process | `os.kill(pid, SIGHUP)` — nginx reloads on SIGHUP, and both its master and the backend run as `breaker` (`supervisord.mono.conf` `[program:nginx]` / `[program:backend-api]`), so no privilege is needed. **Not** `supervisorctl signal HUP nginx`: supervisorctl talks to supervisord's control socket, which is root-owned `chmod=0700` with supervisord running as root, so a breaker-uid backend gets EACCES on every call and activation would report `reloaded=false` forever |
| Native | `helper_client` can reach `/run/circuitbreaker/helper.sock` | a new `reload_nginx` action on `cb_helperd`, added to `ALLOWED_ACTIONS` beside `configure_domain`, which already runs `systemctl reload nginx` |
| Plain image / external proxy | neither of the above | no reload; `ActivationResult.reloaded=False` with a reason the UI shows |

The third is not a failure. `Dockerfile` is API-only — uvicorn on 8080, no nginx — and is
meant to sit behind a proxy the operator runs. Writing the files is all this product can do
there, and saying so is better than claiming a reload happened.

`ActivationResult` carries `written: bool`, `reloaded: bool`, and `detail: str`. The API
returns it; the page renders "active and served" distinctly from "active, written to disk,
reload it yourself" — the same discipline INC-13 used to keep "no rotation in progress" from
looking like "cannot read status".

### 3.4 Where activation is called

- `POST /certificates/{id}/activate` — new, admin-only, the operator's explicit choice.
- After a successful renewal, **if the renewed certificate was already active**. A renewal
  that silently activated an inactive certificate would change what the server presents
  without anyone asking.
- Never on create. A newly imported certificate is not automatically the one to serve.

The `cert_auto_renewal` scheduled job (`main.py:1270`) therefore gains the ability to change
what nginx serves. That is the point of it, and it is why §4.4's failure handling matters:
the job must not be able to activate something it failed to renew.

## 4. INC-07 — ACME that works

### 4.1 Challenge types

**HTTP-01 via `--webroot`**, never `--standalone`. The shipped deployment publishes
`80:8080` and `443:8443` to a container whose nginx listens on 8080
(`docker-compose.yml:25`, `nginx.mono.conf:42,80`). A CA reaching `http://domain/` therefore
arrives at nginx, and certbot only needs to drop a file where nginx will serve it. This
deletes the port-80 and non-root problems rather than solving them.

The webroot is `${CB_DATA_DIR}/acme-challenge`. Two servers read it:

- **nginx** — a location block in the **HTTP** server, placed *above* any HTTPS redirect:

  ```nginx
  location ^~ /.well-known/acme-challenge/ {
      root /data/acme-challenge;
      default_type "text/plain";
  }
  ```

  `^~` matters: it stops a later regex location from taking the request, and its position
  above the redirect is what keeps the challenge from being 301'd to HTTPS, which is the
  single most common way webroot HTTP-01 fails.

- **the plain image**, which has no nginx: a `StaticFiles` mount at
  `/.well-known/acme-challenge`. One webroot, two servers, one mechanism.

That mount is public and unauthenticated, so it needs an entry in
`security/endpoint_policy.json` under `static_surfaces` or the SEC-06 gate fails:

```json
{
  "transport": "http",
  "methods": ["GET", "HEAD"],
  "path": "/.well-known/acme-challenge/{path:path}",
  "policy": "public-acme-challenge",
  "public_reason": "ACME HTTP-01 validation must be readable by the CA before any certificate exists.",
  "disclosure": "single-use ACME challenge tokens written by certbot; no application data"
}
```

**DNS-01** for installs with no public inbound — which, for a homelab inventory tool, is most
of them. Two plugins and no more: `certbot-dns-cloudflare` and `certbot-dns-rfc2136`.
Cloudflare covers the common managed case; RFC2136 is standard DNS UPDATE and covers any
self-hosted BIND/Knot/PowerDNS. **INC-16 in this same batch is the argument for stopping at
two**: a provider nobody has exercised is worse than a provider that is absent, and this
design must not reproduce the finding it is shipping alongside.

### 4.2 Configuration and credentials

`CB_TLS_EMAIL` (`docker/.env.example:32`) becomes the ACME account email, read at last. It is
required for issuance; absent, issuance refuses with that as the reason rather than falling
back to `admin@localhost`.

DNS-01 credentials are per-provider and secret:

| Provider | Fields |
|---|---|
| `cloudflare` | `api_token` |
| `rfc2136` | `server`, `port`, `tsig_name`, `tsig_secret`, `tsig_algorithm` |

They are stored following `services/notification_secrets.py` (INC-06) exactly: one module
that decides which keys are secret, encrypt on write, redact on read with a `*_set` flag,
decrypt only at use. Reusing that shape rather than inventing a second one also means
`vault_service.rotate_vault_key` must re-encrypt them — INC-06 records that omitting this
silently orphans every stored secret at the next rotation, and the same applies here.

certbot needs the credentials as a file. They are written to a `0600` temporary file inside
a `TemporaryDirectory` under `/data/tmp` for the duration of the call and never persisted —
the same pattern `renew_certificate` already uses for its temporary output paths.

**Staging.** A `use_staging` flag selects Let's Encrypt's staging directory. Production ACME
rate limits are punishing (five failed validations per hostname per hour), and an operator
debugging DNS credentials will hit them. Staging defaults **off**, so nobody accidentally
installs an untrusted certificate, but the preflight failure message names it as the way to
test safely.

### 4.3 Preflight

Before spending an ACME attempt, and before spending a rate-limit slot on a validation that
cannot succeed:

- The domain is not a reserved or non-public suffix (`.local`, `.internal`, `.lan`, a bare
  hostname, an IP literal). Let's Encrypt will never issue for these, and saying so instantly
  is the difference between a clear refusal and a mysterious failure.
- `CB_TLS_EMAIL` is set.
- For HTTP-01: the domain resolves publicly, and a self-check `GET` of a token we just wrote
  under the webroot comes back through the public name. This catches the 301-to-HTTPS trap
  and split-horizon DNS before the CA does.
- For DNS-01: credentials for the selected provider are present.

Each failure names the specific unmet condition. A LAN-only install is told plainly that
public ACME cannot issue for its domain and that self-signed remains its path — which is the
standing policy's "state the boundary" applied inside a feature we are finishing.

### 4.4 Failure surfaces

`renew_certificate` stops returning the unchanged certificate. Every failure path —
`FileNotFoundError`, non-zero exit, timeout, preflight refusal — raises a typed
`CertificateRenewalError` carrying the reason and certbot's stderr tail. The API turns it
into a non-200 with that reason, so the UI cannot show success for a renewal that did not
happen. **This is the defect that made INC-07 dangerous rather than merely incomplete**, and
it is fixed independently of whether ACME is configured.

The `cert_auto_renewal` job catches the error, logs it, and writes an audit entry an operator
can find; it does not activate a certificate it failed to renew (§3.4).

### 4.5 Creation stops substituting

`create_certificate` branches on `data.type`:

- `selfsigned` — generate, as now.
- `imported` — require `cert_pem` and `key_pem`; 422 without them.
- `letsencrypt` — run preflight and attempt issuance. On failure, **no row is created** and
  the error explains why. The one thing it may never do is store a self-signed certificate
  under another type's name.

`type` gains `imported` and the schema pattern widens to
`^(letsencrypt|selfsigned|imported)$`. A migration retypes existing rows: any row with
`type='letsencrypt'` whose certificate is self-signed (issuer equals subject) becomes
`imported` if it was pasted, `selfsigned` otherwise — determined by parsing the stored PEM,
not guessed. Mislabelled rows are exactly what §1.2 produced, so the upgrade has to clean
them or the page keeps lying about history.

### 4.6 Packaging

`certbot`, `certbot-dns-cloudflare`, and `certbot-dns-rfc2136` are added to `Dockerfile` and
`Dockerfile.mono`. certbot runs as `breaker` with all state under the data volume:

```
--config-dir /data/letsencrypt/config
--work-dir   /data/letsencrypt/work
--logs-dir   /data/letsencrypt/logs
```

Those directories join the `mkdir -p` list in `entrypoint-mono.sh:67`. Without the explicit
flags certbot writes to `/etc/letsencrypt` and `/var/log/letsencrypt`, which a non-root
process cannot create — this is the non-root failure reappearing in a new place, and the
flags are what prevent it.

`docker/.env.example` gains commentary for `CB_TLS_EMAIL` explaining it is now read, and the
image size increase is noted in the release notes.

## 5. INC-08 — remove the scaffolding, name the real path

- **Delete** `services/password_reset_service.py` and `services/magic_link_service.py`.
  Nothing imports them.
- **Keep** `POST /auth/forgot-password` and `POST /auth/reset-password` answering `410 Gone`.
  410 is the correct answer for a feature deliberately removed, and it tells an API client
  something a 404 does not. Deleting the routes would also mean the SPA fallback answers an
  unrouted `POST` with 405, which reads as "wrong verb" — the misleading symptom INC-05
  documented.
- **Change the message.** `_EMAIL_RESET_DISABLED_DETAIL` currently states only that the
  feature is disabled. It names the supported path instead: an administrator resets the
  password from Users → Reset Password, which issues a one-time temporary password and forces
  a change at next login.
- `components/auth/ForgotPasswordModal.jsx` and `pages/ResetPasswordPage.jsx` say the same
  thing, in the same words, read from one exported constant so the two surfaces cannot drift
  — the failure mode that produced INC-02 and INC-03.
- `tests/test_auth_e2e.py` keeps its assertions that the endpoints are not exposed; its
  docstrings are updated where they describe the now-deleted modules as existing.
- **SMTP stays.** It is not reset scaffolding: INC-02 made `notify_email` deliver through
  `SmtpService`, so `PATCH /settings/smtp`, `POST /settings/smtp/test` and the SMTP settings
  tab are load-bearing for notifications. Removing them because they were once also used for
  password reset would break a working feature.
- `docs/` gains the boundary statement: Circuit Breaker has no self-service password reset;
  recovery is administrator-mediated, and `Reset With Vault Key` remains for the case where
  no administrator can log in.

## 6. INC-16 — narrow the providers, delete the credentials

- `VALID_PROVIDERS` becomes `{"proxmox", "docker"}`. `api/integration_provider.py:35` already
  rejects anything outside it with a message that lists the valid set, so the API surface
  needs no other change.
- `test_config`'s `else` branch stops being reachable for a valid provider. It stays as a
  guard, but its message changes from "Test not implemented for provider" — which describes
  our gap — to one describing the caller's error.
- **A migration deletes orphaned configurations.** Rows in the integration config table whose
  provider is no longer valid are removed, along with their vault-stored credentials, and
  each deletion writes an audit entry naming the provider and the config id. They were never
  usable for sync or for test, so nothing functional is lost; what is gained is that
  credentials for a provider the product does not integrate with stop sitting in the
  database where nothing can reach them to delete them.
- A test pins that every provider in `VALID_PROVIDERS` has a `test_config` branch. This
  finding is the two lists disagreeing; the test is what stops them disagreeing again, and it
  is the same both-sides pin INC-11 and INC-05 used.

## 7. INC-18 — remove the field

`show_experimental_features` leaves `schemas/settings.py`, so the API stops advertising a
setting that changes nothing.

The **column stays**. Dropping it needs a migration that gains nothing, and
`0011_pg_show_experimental_boolean` and `0017` are required for upgrade paths regardless.
This matches INC-01's disposition of the rack migrations: history stays, the live surface
goes.

Deliberately **not** reused as the gate for anything else. Batch A gave
`self_cluster_enabled` — a flag that is read but was not settable — its Settings toggle;
this is the inverse, a flag settable but read by nothing, and the answer to the inverse is
deletion, not finding it a job.

## 8. Testing

- **Activation** (§3): a certificate written to a temp `CB_DATA_DIR` lands at the expected
  paths with the expected modes; a mid-write failure leaves the previous files intact
  (`os.replace` atomicity); the single-active index rejects a second active row; each reload
  branch is exercised with its detector stubbed, including the no-reload branch asserting
  `reloaded=False` and a reason.
- **Creation** (§4.5): choosing `letsencrypt` without a working ACME path creates **no row**
  — the direct inversion of the defect. Choosing `imported` without a PEM is 422. No path
  stores a self-signed certificate under another type.
- **Renewal failure** (§4.4): certbot absent, non-zero exit, and timeout each raise and each
  produce a non-200. Verified against the defect: the pre-fix code returned 200 with an
  unchanged `expires_at`, so the test asserts the status *and* that `expires_at` did not move.
- **Preflight** (§4.3): `.local`, an IP literal, and a missing `CB_TLS_EMAIL` each refuse with
  their own reason and without invoking certbot at all — asserted by a certbot runner that
  fails the test if called.
- **DNS-01 credentials**: encrypted at rest, redacted on read with the `*_set` flag, and
  re-encrypted by `rotate_vault_key` — the last of these is the one INC-06 recorded as easy
  to omit and expensive to omit.
- **INC-16**: a test asserting every `VALID_PROVIDERS` member has a `test_config` branch, and
  a migration test that an orphaned truenas config and its credential are both gone.
- **INC-08**: both routes still answer 410; the detail string and the two frontend surfaces
  all read from one constant.

certbot itself is never invoked in tests. The seam is a runner function that tests replace,
and what is tested is every decision this codebase makes around it — which is where all five
of this batch's defects live.

## 9. Files touched

**Backend:** `services/certificate_service.py`, `services/certificate_activation.py` (new),
`services/acme_service.py` (new), `services/acme_secrets.py` (new, following
`notification_secrets.py`), `services/vault_service.py`, `services/helper_client.py`,
`api/certificates.py`, `api/auth.py`, `schemas/certificate.py`, `schemas/settings.py`,
`schemas/integration_provider.py`, `services/integration_provider_service.py`, `main.py`,
`security/endpoint_policy.json`, `security/endpoint_inventory.json`, three migrations
(`is_active` + partial index, certificate type retyping, orphaned integration config
deletion), and `services/password_reset_service.py` / `services/magic_link_service.py`
(deleted).

**Frontend:** `pages/CertificatesPage.jsx`, `components/auth/ForgotPasswordModal.jsx`,
`pages/ResetPasswordPage.jsx`, and an ACME configuration panel.

**Deployment:** `Dockerfile`, `Dockerfile.mono`, `docker/nginx.mono.conf`,
`docker/entrypoint-mono.sh`, `docker/.env.example`, `deploy/helper/cb_helperd.py`,
`deploy/nginx/circuitbreaker-tls.conf`.

**Docs:** `docs/1.0.0-incomplete-features.md` (INC-07, INC-08, INC-16, INC-18 closed; INC-22
added and closed), a TLS/ACME operator page in the MkDocs nav, and the password-recovery
boundary in the support contract.

## 10. Out of scope

- **Wildcard certificates.** DNS-01 makes them possible; nothing in the product needs one,
  and each is a distinct validation flow. YAGNI until asked for.
- **Multiple simultaneously-served certificates / SNI.** One active certificate, one TLS
  listener. The partial unique index in §3.1 states that as a constraint rather than leaving
  it implied.
- **Certificate revocation.** ACME supports it; no surface asks for it.
- **Additional DNS providers.** §4.1 gives the reason.
- **Batch C** (INC-15, restore) and **Batch D** (INC-09, i18n).
- **Dropping the `show_experimental_features` column.** §7.
