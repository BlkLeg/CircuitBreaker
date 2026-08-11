# GOV-3 — Version, License, and Contributor Truth

**Requirements:** GOV-09, GOV-10, GOV-11, GOV-14
**Depends on:** RC versioning/governance decisions

## Primary touchpoints

- `VERSION`, root and frontend `package.json`, `apps/backend/pyproject.toml`
- `scripts/build_native_release.py`, release/build workflows, container labels, agent manifests
- `CONTRIBUTING.md`, `LICENSE`, future root `SECURITY.md`, root developer scripts

## Build sequence

1. Inventory every version and license source plus runtime display/artifact name/tag. Classify generated,
   validated, or obsolete; `VERSION` remains the sole hand-edited product version.
2. Replace side-effecting manifest sync with build-time generation or a check mode. Align/remove legacy
   Poetry `0.2.0` metadata and nonfunctional duplicate package identity.
3. Add a parity verifier for manifests, backend metadata, UI/API/CLI, agent manifest, Docker labels,
   package filenames, Git tag, release notes, and artifact metadata.
4. Replace root `npm test` intentional failure with a useful orchestrator/check or remove the misleading
   script and document authoritative workspace commands.
5. Correct contribution branch/check names, MIT license statement, and real monitored security contact.
   Add root `SECURITY.md` with supported versions and private reporting/response process.
6. Verify build/test/release commands leave tracked manifests clean.

## Verification and done

Run parity against a deliberate mismatch and a candidate build; it must fail then pass. Validate package
metadata and all contributor/security links. Done means one version/license truth exists and no standard
root command fails by design.
