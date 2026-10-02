# @blkleg/circuitbreaker

Linux management CLI for a self-hosted [Circuit Breaker](https://github.com/BlkLeg/CircuitBreaker)
install. It runs the server's own `cb` for everyday management and reports CLI and server
versions separately.

`circuitbreaker install --plan` shows what an install would do without doing it. It resolves one
exact release, downloads its bundle to a private per-user cache, and verifies the `SHA256SUMS`
signature, the bundle's hash, its build provenance and the archive's contents before printing the
plan. It changes nothing on the host. With `--airgap` and `--local-bundle` it makes no network
requests, verifying a bundle you already have against the `SHA256SUMS` and `SHA256SUMS.sig` beside it.

`circuitbreaker history` lists the lifecycle operations recorded on the host from their read-only
summary, without elevating. With `--json`, `install --plan` and `history` print one final JSON
result on stdout; `install --plan --events=jsonl` writes JSONL events, and nothing else, on stderr.

Publication is controlled by the protected release job. The release's
`npm-publication.json` records the accepted tarball integrity and verified registry
round trip. Public npm installation instructions remain gated on that evidence.

Review `circuitbreaker install --plan` or `update --plan`, then pass `--yes` to
apply a verified release. `update --check` only checks availability. Native updates
take a full-state backup, retain the previous release and check readiness/version.
A failed update attempts to restore the previous release; database restoration
remains an explicit `cb restore` action. Online backups do not promise a globally
consistent database/uploads snapshot.

`rollback [--restore-data] [--yes]` restores the last retained update. Without
`--restore-data`, it keeps current data; incompatible schemas can require manual
data restoration. `uninstall` forwards the native uninstaller with `--keep-data`.
`uninstall --purge` requires typing DELETE or explicit `--yes`. The npm tool remains
installed. Uninstall and management output/exit codes are passed through unchanged.

Native lifecycle apply is supported by the new installer adapter; Docker lifecycle
apply and package lifecycle apply remain with their existing management tools.
Docker management commands never request npm elevation. Downgrade and automated
recover are deferred. Update the npm tool manually with
`npm i -g @blkleg/circuitbreaker@VERSION` under its original npm owner; do not run
npm through sudo.

For install/update/rollback, `--json` prints one final result on stdout and
`--events=jsonl` writes framed events on stderr. Otherwise progress uses static
phase lines with durations and no ANSI. Interrupted-update history lists the
native rollback command; `cb doctor` provides read-only inspection.

Requires Linux and Node.js 22.22.2+, 24.15.0+ or 26+. Licensed MIT.
