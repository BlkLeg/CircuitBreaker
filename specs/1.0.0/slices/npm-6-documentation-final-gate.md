# NPM-6 — npm Documentation and Final Gate

**Completes:** NPM-01, NPM-02, NPM-03, NPM-04, NPM-05, NPM-06, NPM-07, NPM-08, NPM-09,
NPM-10, NPM-11, NPM-12, NPM-13, NPM-14, NPM-15
**Depends on:** NPM-5

## Build sequence

1. Publish an unambiguous first sentence: CLI/installer or SDK. State what npm does not install and
   keep native/container server methods prominent.
2. Document Node/package-manager/platform support, prerequisites, privileges, proxy/offline, network
   endpoints/telemetry, verification, configuration, error recovery, update, rollback, and uninstall.
3. For CLI, document signature/provenance verification and installed server artifact relationship.
   For SDK, document auth safety, API compatibility, errors/retries, runtime and migration policy.
4. Put every `npm`, `npx`, pnpm/yarn, import, and command example into a clean-runner docs test. Do not
   publish an untested convenience path.
5. From the staged registry or exact `.tgz`, verify provenance, contents/SBOM, install/import, version,
   and the applicable status/update/uninstall or API contract journey.
6. Reconcile registry version, tarball integrity, Git tag, application/SDK version, artifact checksums,
   release manifest, SBOM, documentation, and dist-tag before promotion.

## Done

The exact tarball passes the complete gate on every supported platform, documentation examples are
executable, identity matches everywhere, and `latest` remains untouched until EXEC-9 authorization.
