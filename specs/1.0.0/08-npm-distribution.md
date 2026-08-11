# npm Distribution Specification

**Status:** Draft; product decision required

## Outcome

If npm is a supported 1.0 channel, it installs a deliberately scoped, secure, independently testable
package. The repository root is not published as an application package.

## Package contract

| ID | Requirement | Acceptance |
|---|---|---|
| NPM-01 | Choose and document one purpose: administration/installer CLI or API client/SDK. | Name, commands/API, supported platforms, versioning, and relationship to server artifacts are approved before implementation. |
| NPM-02 | Use a dedicated package such as `@blkleg/circuitbreaker` or `@blkleg/cb-cli`; keep the root repository manifest private. | `npm pack` operates only on the dedicated package and root publication is blocked. |
| NPM-03 | For a CLI, explicitly download the correct signed server artifact, verify checksum/signature/provenance, and expose documented management commands. | Install/status/update/rollback/uninstall journey succeeds and verification failures are fail-closed. |
| NPM-04 | For an SDK, provide TypeScript declarations, API-version range, generated contract tests, and independent semver. | SDK compatibility matrix passes against every claimed server version. |
| NPM-05 | Do not embed frontend dependencies, Python environment, PostgreSQL, Redis, NATS, Go agent, or unrelated monorepo assets in a generic tarball. | Allowlist inspection and size/file-count budgets pass. |

## Metadata, contents, and behavior

| ID | Requirement | Acceptance |
|---|---|---|
| NPM-06 | Provide accurate name, canonical version, description, keywords, MIT license, repository/homepage/bugs/support, engines, OS, CPU, bin, files, exports, and package-manager support. | Registry metadata and installed package inspection match documentation. |
| NPM-07 | Use `files` allowlisting plus `.npmignore` defense; exclude env files, credentials, uploads, secret fixtures, caches, internal reports, unintended source maps, and unrelated content. | `npm pack --dry-run` and unpacked-tarball CI enforce inventory, size, and count limits. |
| NPM-08 | Smoke the packed `.tgz` on every claimed Linux/macOS/Windows and Node/package-manager combination. | Tests install the exact candidate tarball in clean runners and execute documented commands. |
| NPM-09 | Test offline/error, unsupported OS/arch, proxy, interruption, integrity mismatch, permissions, update, rollback, and uninstall. | Errors are actionable, safe, and leave recoverable state. |
| NPM-10 | `preinstall`/`postinstall` perform no downloads or privileged mutations; system changes occur only after an explicit confirmed command. | Lifecycle-script inspection and sandbox test observe no undeclared network or privileged action. |
| NPM-11 | Package, `VERSION`, Git tag, GitHub Release, downloaded artifacts, container labels, and reported version agree exactly. | Automated parity gate blocks promotion. |

## Registry and supply-chain controls

| ID | Requirement | Acceptance |
|---|---|---|
| NPM-12 | Reserve/verify namespace; require organization MFA, two maintainers, documented recovery ownership, and periodic access review. | Registry settings and owner review are retained as release evidence. |
| NPM-13 | Publish through GitHub Actions trusted publishing/OIDC with provenance and protected environment; no long-lived token where avoidable. | Only the accepted commit can publish and provenance verifies publicly. |
| NPM-14 | Publish RCs under `next`; move `latest` only after installed-tarball acceptance. Correct stable defects by deprecation plus patch, not overwrite/unpublish. | Promotion and incident procedures are tested or table-topped. |
| NPM-15 | Include package in SBOM, scan packed and installed dependency trees, monitor integrity, and document compromise/revocation. | Release gate retains scans, provenance, access owner, and emergency procedure. |

## Documentation

The npm page must say whether the package is a CLI, installer, or SDK; prerequisites; supported Node
and platforms; privileges; proxy/offline behavior; network/telemetry behavior; verification;
update/uninstall; and why native/container methods remain authoritative. Copy-paste `npm`/`npx` or
other package-manager examples are published only after their exact paths are automated.

## Release gate

A clean runner installs the exact `.tgz`, verifies npm provenance and any downloaded server artifact,
performs the applicable install/status/update/uninstall journey, and confirms registry version, Git
tag, application version, checksums, and SBOM parity.
