# Actionable Security Triage

Date: 2026-06-30

Source: [security_scan_report.md](/home/shawnji/Documents/Projects/CircuitBreaker/security_scan_report.md)

Scope: only findings that still look worth manual review or remediation. I excluded scanner noise, vendored environment artifacts, and findings that are already explicitly marked as intentional or nosec-gated.

## Immediate Review

| Priority | Finding | Evidence | Why it is actionable | Next step |
| --- | --- | --- | --- | --- |
| Critical | JWT decode disables signature verification | [apps/backend/src/app/core/security.py](/home/shawnji/Documents/Projects/CircuitBreaker/apps/backend/src/app/core/security.py) | A token decode path with verification disabled is an authentication integrity break, not just a hardening issue. | Remove the bypass and require verified JWT parsing on every path. |
| High | Reverse-proxy h2c smuggling exposure | [docker/nginx.conf](/home/shawnji/Documents/Projects/CircuitBreaker/docker/nginx.conf), [docker/nginx.mono.conf](/home/shawnji/Documents/Projects/CircuitBreaker/docker/nginx.mono.conf) | Forwarding `Upgrade` / `Connection` handling in a broad proxy config can create HTTP/2 cleartext upgrade abuse paths. | Restrict upgrade forwarding to explicit websocket locations or stop forwarding upgrade headers. |
| High | Logging of secret-handling failures | [apps/backend/src/app/services/db_backup.py](/home/shawnji/Documents/Projects/CircuitBreaker/apps/backend/src/app/services/db_backup.py), [apps/backend/src/app/services/discovery_dhcp.py](/home/shawnji/Documents/Projects/CircuitBreaker/apps/backend/src/app/services/discovery_dhcp.py) | These logs can expose sensitive material or recovery context during decryption failures. | Redact exception payloads and replace with opaque request IDs. |
| Medium | JWT secret fallback is logged | [apps/backend/src/app/core/users.py](/home/shawnji/Documents/Projects/CircuitBreaker/apps/backend/src/app/core/users.py) | Logging the fallback path leaks internal secret-handling behavior and should not appear in routine logs. | Remove the secret-source message and keep only operational context. |

## Dependency Upgrades To Review

The Trivy run reported many dependency CVEs. These are the ones that look most actionable for the current backend runtime because they have fixed versions and direct security impact.

| Package | Installed | Fixed | Risk | Notes |
| --- | --- | --- | --- | --- |
| cryptography | 46.0.5 | 48.0.1 | High | Wheel-bundled OpenSSL advisory and related crypto issues. |
| pyjwt | 2.12.1 | 2.13.0 | High | Authentication bypass risk if JWT handling is reachable in-app. |
| starlette | 0.52.1 | 1.1.0 | High | Includes SSRF / NTLM credential theft exposure via path handling. |
| urllib3 | 2.6.3 | 2.7.0 | High | Sensitive-header forwarding on redirects is directly relevant to HTTP clients. |
| python-engineio | 4.13.1 | 4.13.2 | High | Unbounded thread allocation can turn into a practical DoS. |
| python-socketio | 5.16.1 | 5.16.2 | High | Binary attachment accumulation DoS risk. |
| mako | 1.3.10 | 1.3.11 / 1.3.12 | High | Path-traversal information disclosure. |
| authlib | 1.6.10 | 1.6.11 / 1.7.1 | Medium | OAuth/CSRF and verifier-side bypass issues; review if OAuth flows are enabled. |
| python-multipart | 0.0.22 | 0.0.27 / 0.0.30 / 0.0.31 | Medium | Multipart parser DoS and disclosure issues; relevant if upload routes are exposed. |
| requests | 2.32.5 | 2.33.0 | Medium | Predictable temp-file creation can matter in sensitive execution contexts. |
| pydantic-settings | 2.13.1 | 2.14.2 | Medium | Symlink-following in nested secrets can become local file read if secrets dirs are used. |
| zeroconf | 0.148.0 | 0.149.5+ | Medium | LAN-local DoS and cache corruption family of issues. |

## Excluded From Actionable Triage

These showed up in the scan output, but I did not keep them in the actionable list because they are either scanner artifacts or already intentional in context.

| Item | Reason excluded |
| --- | --- |
| Gitleaks hits inside [security_scan_report.md](/home/shawnji/Documents/Projects/CircuitBreaker/security_scan_report.md) | The private-key samples are embedded in the report output itself, not evidence of a live repository secret in application code. |
| Secret findings under [.venv](/home/shawnji/Documents/Projects/CircuitBreaker/.venv) | Vendored site-packages and test fixtures are environment noise, not project source. |
| mDNS bind warning in [apps/backend/src/app/services/discovery_fingerprint.py](/home/shawnji/Documents/Projects/CircuitBreaker/apps/backend/src/app/services/discovery_fingerprint.py) | The code already marks the multicast bind as required and suppresses the rule. |
| Hadolint DL3008 warnings | Pinning apt packages is a hygiene improvement, not a direct vulnerability in the current scan. |
| Checkov and npm audit outputs | The reported configs were clean or non-blocking for this run. |

## Suggested Order

1. Fix the JWT verification bypass.
2. Tighten nginx upgrade forwarding.
3. Redact secret-handling logs.
4. Batch the dependency upgrades with the auth and transport stack first.
