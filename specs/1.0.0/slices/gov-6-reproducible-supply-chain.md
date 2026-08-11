# GOV-6 — Reproducible Supply Chain

**Requirements:** GOV-18, GOV-19, GOV-20
**Depends on:** Supported artifact matrix and governance

## Primary touchpoints

- `scripts/install-build-deps.sh` (`NFPM_VERSION=latest`), build/release workflows
- `scripts/build_native_release.py`, Docker builds, `packaging/`, release signing key/process

## Build sequence

1. Inventory compilers, runtimes, actions, base images, package managers, downloaded tools, and plugins
   with immutable version/digest, checksum/signature source, update owner, and cadence.
2. Replace floating nfpm and other mutable inputs with reviewed pins; verify downloads before execution.
   Pin actions by immutable commit where policy requires and track human-readable versions separately.
3. Produce artifact manifest linking version, commit, build inputs, filenames, SHA-256, signatures,
   CycloneDX/SPDX SBOMs, SLSA-style provenance/attestations, and container digest.
4. Sign in protected CI using short-lived identity or secured key procedure; separate build from promote.
5. Test user verification on clean/offline-capable systems and scan source, packages, containers, SBOMs,
   and installed trees.
6. Require ACC artifact installation before stable/latest promotion; promotion references existing
   accepted digests and never rebuilds. Define compromise, revoke/deprecate, and corrected patch flow.

## Verification and done

Rebuild twice in controlled identical inputs and explain any non-reproducible bytes; verify all metadata
against the artifact. Done means mutable build inputs are governed, every artifact is attributable and
verifiable, and an unaccepted digest cannot reach stable channels.
