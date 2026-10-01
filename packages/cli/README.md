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

This package is not published yet. Install Circuit Breaker with `install.sh` or the mono image;
see the project's installation guide.

Requires Linux and Node.js 22.22.2+, 24.15.0+ or 26+. Licensed MIT.
