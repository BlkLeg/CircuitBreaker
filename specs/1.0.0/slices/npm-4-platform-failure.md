# NPM-4 — Platform and Failure Acceptance

**Requirements:** NPM-08, NPM-09, NPM-10, NPM-11
**Depends on:** NPM-3

## Build sequence

1. Build the `.tgz` once, checksum it, and fan out clean runner tests for every claimed Linux/macOS/
   Windows, Node LTS, CPU, shell, and package-manager combination. Do not rebuild per runner.
2. Install globally/locally or import exactly as documented; verify bin permissions/shebang/quoting or
   ESM/types behavior, help/version, uninstall, and no files outside expected package-manager locations.
3. Test unsupported OS/CPU, old/new Node boundary, offline, proxy/auth proxy, TLS failure, interrupted
   download, timeout, checksum/signature/provenance mismatch, read-only/insufficient privilege, disk full,
   update, rollback where promised, and uninstall with retained user data policy.
4. Observe install in a network/filesystem/process sandbox: `preinstall`/`postinstall` must perform no
   download or privileged/system mutation. Explicit user commands alone may do so.
5. Compare package version to `VERSION`, tag, release, server artifact/manifest, container labels, SBOM,
   and CLI/SDK reported compatibility.

## Verification and done

Retain runner logs and exact tarball digest. Done means every published command/platform passes, errors
are actionable/recoverable, lifecycle installation is inert, and identity parity is exact.
