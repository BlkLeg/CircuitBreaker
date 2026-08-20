# Security Policy

## Supported versions

| Version         | Supported                                  |
| --------------- | ------------------------------------------ |
| 1.0.x (incl. release candidates) | ✅ Security fixes         |
| < 1.0           | ❌ Pre-release; upgrade to the 1.0 line     |

Security fixes land on the current 1.0 line only. The full support boundary —
platforms, architectures, deployment modes and browsers — is in the
[1.0.0 support contract](docs/release/1.0.0-support-contract.md); a deployment
mode listed there as unsupported is also out of scope for a security fix.

## Reporting a vulnerability

Report privately through GitHub:
**[Security → Report a vulnerability](https://github.com/BlkLeg/CircuitBreaker/security/advisories/new)**

Please do not open a public issue for a security report.

Include where practical: affected version (`cb version`), the deployment mode
— native or mono, the two modes that ship, as defined in the
[installation overview](docs/installation/index.md#deployment-modes) — and the
install method you used (quick install, Proxmox LXC, Docker Compose, single
Docker container, or from source), reproduction steps, impact, and whether the
issue is reachable without authentication.
Redact secrets from any log or `cb doctor` output you attach.

## What to expect

| Stage                                                    | Target            |
| -------------------------------------------------------- | ----------------- |
| Acknowledgement                                          | 3 business days   |
| Initial assessment                                       | 10 business days  |
| Fix or mitigation plan for a confirmed high-impact issue | 30 days           |

This is a self-hosted project maintained by a small team; the targets above are
what we aim for, not a contractual SLA. We will credit reporters in the release
notes unless you ask us not to.

## Scope

In scope: the server (API, workers, web UI), `cb-agent`, the installers and
packaging, and the published container images.

Out of scope: findings that require an already-compromised host or database;
denial of service by resource exhaustion on a self-hosted deployment the
reporter controls; missing hardening headers with no demonstrated impact;
exposing the deployment directly to the internet, which the support contract
already documents as unsupported.

## Verifying releases

Every release ships SBOMs (CycloneDX and SPDX, generated with syft) and a
`SHA256SUMS` file, and the container image is signed keylessly with cosign with
its SBOM attached to the image. GPG detached signatures — over the artifacts and
over `SHA256SUMS` — are produced only when the release workflow has a signing
key available; a release published without one carries checksums and cosign
signatures but no `.asc` files, and its `SHA256SUMS` does not cover the SBOM
files. Check for the `.asc` files on the release before relying on a GPG
signature. Verification steps are in the
[security verification checklist](docs/installation/security-verification.md).
