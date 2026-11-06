# Circuit Breaker CLI

**Your whole homelab on one live map.** Circuit Breaker shows your hardware, VMs,
containers, services and networks in one place, with live health, auto-discovery
and remote agents. It is self-hosted, runs on your own machine, and never locks
your data in.

This package is its command-line tool: it installs Circuit Breaker on a Linux
host, keeps it up to date, and gives you one command for everyday management.

[![The Circuit Breaker topology map](https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/docs/assets/screenshots/cb_night-full.webp)](https://circuitbreaker.blkleg.app)

**[Website](https://circuitbreaker.blkleg.app)** · **[Live demo](https://circuitbreaker.blkleg.app/demo)** · **[User guide](https://blkleg.github.io/CircuitBreaker/)** · **[Discord](https://discord.gg/SBdBRfmD)**

## Quick start

```bash
npm install -g @blkleg/circuitbreaker

circuitbreaker install --plan   # see exactly what would be installed; changes nothing
circuitbreaker install --yes    # install it
```

When the install finishes it prints the address of the setup wizard, where you
create the first account. From then on:

```bash
circuitbreaker status           # is everything running?
circuitbreaker doctor           # health checks, with what to do about each problem
circuitbreaker update --check   # is there a newer release?
```

Installing needs root, so `circuitbreaker` asks for `sudo` when it reaches that
step. Everything before it, including the download and every check below, runs as
you.

## It shows you the plan first

Most installers ask you to pipe a script into a root shell and hope. This one
checks the release before anything runs as root, and `--plan` shows you the
result without touching the host:

```text
$ circuitbreaker install --plan
✓ verify (1.8s)
Install plan (no changes made)
Target     v0.4.7 (linux amd64)
Bundle     ~/.cache/circuitbreaker/…/circuit-breaker_0.4.7_linux_amd64.tar.gz
SHA256     ca0ffa96…
Signature  verified, key 5f2aa2af…
Provenance verified
Archive    15683 entries, 372.6 MiB unpacked; no unsafe paths or types
```

Four checks have to pass:

- **Signature.** The release's checksum file is signed with the project's release
  key, and the key list ships inside this package.
- **Checksum.** The download matches the signed checksum.
- **Build provenance.** The release was built by the project's own release
  workflow on GitHub, verified with [Sigstore](https://www.sigstore.dev).
- **Archive contents.** No file in the bundle escapes its directory or has an
  unsafe type.

If any of them fails, nothing is installed.

## Everyday use

| Command | What it does |
|---|---|
| `circuitbreaker status` | Show whether each service is running |
| `circuitbreaker doctor` | Run health checks and explain what to fix |
| `circuitbreaker logs -f` | Follow the logs |
| `circuitbreaker resources` | Show what the installation is using |
| `circuitbreaker backup` | Take a full snapshot: database, uploads, configuration and vault key |
| `circuitbreaker restore <file>` | Restore a snapshot |
| `circuitbreaker update` | Update to a newer release (`--check`, `--plan`, `--yes`) |
| `circuitbreaker rollback` | Go back to the release you had before the last update |
| `circuitbreaker history` | List the installs, updates and rollbacks on this host |
| `circuitbreaker uninstall` | Remove Circuit Breaker; your data is kept unless you ask otherwise |

`circuitbreaker help` lists everything, including user, token and agent
management.

## Updates you can undo

`circuitbreaker update --yes` takes a full backup first, keeps the release you
were running, and checks that the new one is healthy before it calls the update
done. If the new release does not come up, it puts the previous one back.

`circuitbreaker rollback` returns to the previous release whenever you choose.
It keeps your current data unless you add `--restore-data`, which also restores
the backup taken before the update.

`circuitbreaker uninstall` keeps your data and configuration. Deleting them takes
`--purge` and a typed confirmation.

## Requirements

- **Linux** with systemd: Ubuntu, Debian, Fedora, RHEL, Rocky Linux, AlmaLinux or
  Arch. **macOS and Windows support is next on the roadmap.**
- **Node.js 22** (22.22.2 or newer), **Node.js 24** (24.15.0 or newer), or
  **Node.js 26 and later**. Node 23 and 25 are not supported. The limits come from
  the Sigstore library that verifies each release.
- `sudo` access for installing, updating and removing.

The installer fetches what Circuit Breaker needs, including PostgreSQL 15 from the
PostgreSQL project's own package repository.

**No Node, or an older one?** The same installer runs without it:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | sudo bash
```

**Running Circuit Breaker in Docker?** The everyday commands above work with a
Docker install. Installing and updating a Docker deployment still goes through
[the Docker guides](https://blkleg.github.io/CircuitBreaker/).

**No internet on the host?** `--airgap --local-bundle <file>` installs from a
release you downloaded elsewhere and makes no network requests. Keep the
release's `SHA256SUMS` and `SHA256SUMS.sig` next to the bundle.

## Scripting

`--json` prints one final JSON result on stdout. For `install`, `update` and
`rollback`, `--events=jsonl` writes progress events to stderr, one JSON object
per line and nothing else. Exit codes are stable: `0` is success, and each kind
of failure has its own code.

`NO_COLOR` turns colour off, and `--no-animation` or `CB_REDUCED_MOTION=1` turns
motion off. Output sent to a file or a pipe is plain text.

To update this tool itself, run `npm install -g @blkleg/circuitbreaker@latest`.

## Before you expose it

Circuit Breaker has not been fully security-audited yet. Run it on a trusted
network or behind a VPN, not directly on the public internet.

## Help and feedback

- **Questions and chat:** [Discord](https://discord.gg/SBdBRfmD)
- **Bugs and requests:** [GitHub issues](https://github.com/BlkLeg/CircuitBreaker/issues)
- **Source:** [github.com/BlkLeg/CircuitBreaker](https://github.com/BlkLeg/CircuitBreaker)

Licensed MIT.
