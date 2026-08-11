# NPM-3 — Package Manifest and Allowlisted Tarball

**Requirements:** NPM-05, NPM-06, NPM-07
**Depends on:** NPM-1 and selected NPM-2 path

## Build sequence

1. Add accurate scoped name/version/description/keywords, MIT license, repository/directory, homepage,
   bugs/support/funding, engines, OS/CPU, bin or exports/types, package-manager support, and publish config.
2. Use `files` as the primary allowlist and `.npmignore` as defense. Include only compiled runtime,
   types if SDK, README, LICENSE, notices, and required small data files.
3. Exclude `.env`, credentials, uploads, secret fixtures, reports, tests unless intentionally shipped,
   caches, CI/config, unrelated monorepo code, frontend/Python/Go/database assets, and source maps unless approved.
4. Make builds run before packing without writing unexpected tracked files. Normalize timestamps/modes
   where practical and define compressed/unpacked size plus file-count budgets.
5. Inspect `npm pack --dry-run --json` and unpacked `.tgz`; fail unexpected path, symlink, executable,
   secret pattern, oversized file, undeclared dependency, or lifecycle script.

## Verification and done

Install the tarball in an empty project and execute its public entrypoint/import. Done means the registry
artifact is minimal and self-consistent, and packing the repository root remains impossible.
