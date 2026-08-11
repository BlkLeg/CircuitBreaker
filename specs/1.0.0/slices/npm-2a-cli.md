# NPM-2A — Administration/Installer CLI

**Requirement:** NPM-03
**Run only if:** NPM-1 selects the CLI

## Build sequence

1. Define stable commands for prerequisite/status/config validation, artifact fetch/verify, install,
   update, rollback if supported, uninstall, diagnostics, and help/version. Separate remote admin from
   local privileged mutation.
2. Map supported OS/CPU to release-manifest entries; reject unknown combinations before download.
3. Download to an application-owned staging directory with proxy, timeout, resume policy, size limit,
   atomic finalization, and cleanup. Never select an artifact from mutable `latest` during execution.
4. Verify release manifest/provenance/signature/checksum and artifact checksum before any privileged
   action. Bind displayed version/digest to installed result.
5. Invoke documented native installer through explicit user command/confirmation; do not reproduce its
   privilege/file logic in JavaScript. Journal steps for interrupted recovery and redact secrets.
6. Define exit codes and JSON output; test unsupported platform, offline/proxy, interruption, tamper,
   insufficient permission, partial install, update, rollback, and uninstall.

## Verification and done

Run the packed `.tgz` on clean claimed platforms against signed staged artifacts. Done means tampered
input fails before mutation, interrupted operations recover deterministically, and installed status
matches package/release identity.
