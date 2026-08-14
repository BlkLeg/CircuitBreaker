# SEC-5 Outbound and Dependency Safety Evidence

**Status:** Local implementation complete; packaged RC evidence still pending
**Generated:** 2026-08-11
**Requirements:** SEC-11, SEC-12, SEC-13, SEC-14
**Depends on:** SEC-1

## Implemented controls

- Upgraded the production backend lock and generated requirements from `click==8.3.1` to
  `click==8.3.3`, the fixed release for CVE-2026-7246 / PYSEC-2026-2132.
- Changed the GitHub security workflow to audit `apps/backend/requirements.txt` as the production
  dependency graph and fail the job on pip-audit findings.
- Replaced the one-off SSRF helper with a shared outbound URL policy in
  `apps/backend/src/app/core/url_validation.py`.
- The shared policy now validates:
  - allowed schemes;
  - missing hosts and invalid ports;
  - embedded URL userinfo;
  - literal IPv4 and IPv6 addresses;
  - resolved DNS answers, including mixed public/private answer sets;
  - loopback, link-local, unspecified, multicast, private, and reserved ranges;
  - redirect targets before following them.
- Public outbound HTTP clients can be forced through `CB_EGRESS_PROXY_URL`. Strict production startup
  requires a configured egress proxy unless the host explicitly records that it has none via
  `CB_ALLOW_DIRECT_EGRESS=true`, or `CB_ALLOW_DEGRADED_DEPENDENCIES=true` is set for tests or approved
  break-glass operation. `CB_ALLOW_DIRECT_EGRESS` waives the proxy requirement and nothing else: the
  shared outbound URL policy still validates every public request, and Redis, NATS, rate-limit storage
  and secret gates all still fail closed. Every shipped deployment template sets it, because a
  single-node install has no proxy to name and an empty `CB_EGRESS_PROXY_URL` would otherwise stop the
  backend from starting at all.
- `validate_egress_proxy()` returns a failure message or `None`; it previously returned the validated
  proxy URL on success, which the caller read as a truthy error, so a correctly configured
  `CB_EGRESS_PROXY_URL` failed startup with the URL itself as the message. No egress configuration
  could start the backend before that fix — only blanket degraded mode.
- Notification webhook delivery and notification sink tests now use the shared outbound request
  wrapper before POSTing.
- Threat-feed downloads now use HTTPS-only policy and validate every redirect hop before streaming
  a capped response body.
- Uptime Kuma HTTP fallback and connection tests now validate runtime outbound targets and disable
  automatic redirects. LAN integrations keep the documented private-network exception while still
  rejecting loopback and link-local targets.
- Custom S3 backup endpoints are validated with the shared outbound policy and boto3 receives the
  configured egress proxy when present. Admin settings reject unsafe custom S3 endpoint URLs before
  persistence.
- SlowAPI rate limits now derive storage from `CB_RATE_LIMIT_STORAGE_URL` or the shared Redis URL.
  `memory://` is rejected in strict production startup.
- Rate-limit identity uses `X-Forwarded-For` only when the immediate peer is within
  `CB_TRUSTED_PROXY_CIDRS`; untrusted peers are keyed by the socket peer address.
- Tenant-aware rate-limit middleware fails closed with 503 when Redis is unavailable instead of
  silently allowing traffic.
- Startup validation rejects empty or placeholder JWT/session signing secrets, rejects unusable vault
  key state when encrypted secrets exist, and fails closed on missing Redis, NATS, egress policy, or
  shared rate-limit storage unless degraded mode is explicitly enabled.
- Operator-facing templates and docs now describe `CB_EGRESS_PROXY_URL`,
  `CB_RATE_LIMIT_STORAGE_URL`, `CB_TRUSTED_PROXY_CIDRS`, and
  `CB_ALLOW_DEGRADED_DEPENDENCIES`.

## Covered cases

- Generic webhooks reject loopback, link-local metadata, private, encoded loopback, and mixed DNS
  answers.
- LAN integrations allow RFC1918 targets but reject link-local metadata targets.
- LAN integration validation can store unresolved private DNS names without failing setup.
- Redirect validation rejects private redirect targets before a second outbound request is sent.
- Public outbound clients pass through the configured egress proxy.
- Custom S3 backup endpoints reject link-local metadata and DNS answers that resolve to private
  addresses.
- Spoofed `X-Forwarded-For` is ignored from untrusted peers and honored only from configured trusted
  proxy CIDRs.
- Strict startup rejects missing Redis/NATS, `memory://` rate-limit storage, missing egress proxy,
  empty secrets, and placeholder secrets. Explicit degraded mode bypasses the dependency gate.
- A valid `CB_EGRESS_PROXY_URL` starts cleanly; an invalid one is rejected whether or not
  `CB_ALLOW_DIRECT_EGRESS` is set, because opting out of a proxy is a choice and a malformed proxy
  value is a mistake.
- `CB_ALLOW_DIRECT_EGRESS` waives only the proxy requirement: with it set, missing Redis, missing
  NATS and `memory://` rate-limit storage still fail startup. Falsey and empty values do not opt out.
- Existing Proxmox URL tests continue to prove loopback/link-local rejection and LAN allowance.
- Threat-feed URL tests continue to enforce HTTPS-only public feed URLs.

## Verification commands

```bash
cd apps/backend
ruff check src/app/core/url_validation.py src/app/core/rate_limit.py \
  src/app/core/startup_validation.py src/app/middleware/rate_limit_middleware.py \
  src/app/services/threat_feed.py src/app/services/backup/s3_client.py \
  src/app/workers/notification_worker.py src/app/api/notifications.py \
  src/app/api/admin_db.py src/app/integrations/uptime_kuma.py \
  tests/unit/test_url_validation.py tests/unit/test_rate_limit_security.py \
  tests/unit/test_startup_validation.py tests/services/test_backup_s3_ssrf.py
PYTHONPATH=src pytest -q --no-cov tests/unit/test_url_validation.py \
  tests/unit/test_rate_limit_security.py tests/unit/test_startup_validation.py \
  tests/services/test_backup_s3_ssrf.py tests/services/test_threat_feed.py \
  tests/test_integrations.py tests/test_admin_db.py

cd ../..
.venv/bin/pip-audit -r apps/backend/requirements.txt --no-deps --disable-pip --format=json \
  --output /tmp/cb-sec5-pip-audit.json
```

`pip-audit` reported: `No known vulnerabilities found`.

## Release-candidate evidence still pending

- Repeat pip-audit and the outbound SSRF suite against the packaged release candidate.
- Add controllable-DNS integration evidence for DNS rebinding in the RC topology.
- Prove shared rate-limit behavior across a multi-instance RC topology.
- Attach startup/readiness fail-closed evidence from packaged mono and split deployments.
