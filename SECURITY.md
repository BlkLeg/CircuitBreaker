# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| v0.1.0-beta | ✅ Active (beta) |

Circuit Breaker is currently in **beta**. It has not undergone a full third-party security audit.
Run it only on a secure, trusted local network. Do not expose it directly to the public internet.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately via
[GitHub Security Advisories](https://github.com/BlkLeg/circuitbreaker/security/advisories/new).

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce (version, configuration, request/response if applicable)
- Any suggested fix or mitigation if you have one

You will receive an acknowledgement within **72 hours** and a status update within **7 days**.
We will credit reporters in the release notes unless you prefer to remain anonymous.

## Scope

**In scope:**
- Authentication and session management
- Audit log data exposure
- Injection vulnerabilities (SQL, command, template)
- Container escape or privilege escalation
- Sensitive data leakage in API responses or logs

**Out of scope for beta:**
- Denial-of-service attacks requiring high traffic volume
- Issues requiring physical access to the host machine
- Vulnerabilities in third-party dependencies not yet patched upstream
- Security issues arising from misconfiguration (e.g., exposing the app to the public internet
  against the documented beta warning)

## Beta Security Posture

This release includes the following protections:

- Passwords stored as bcrypt hashes (never plaintext)
- JWT secrets auto-generated at runtime; never hardcoded
- Audit logs scrub sensitive fields (`password`, `token`, `jwt_secret`) before storage
- Rate limiting on all API endpoints
- Non-root container user (`breaker26`)
- No external service dependencies (SQLite only; no network egress)

Known limitations acknowledged for beta:
- No TLS termination (use a reverse proxy such as Caddy or Nginx for HTTPS)
- No WAF or DDoS protection (assume trusted local network)
- Full security audit planned before v1.0 general availability
