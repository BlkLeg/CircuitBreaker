# Installation and diagnosis simplification plan

**Status:** proposed.  
**Scope:** supported CircuitBreaker installation paths, operator CLI,
first-run setup, health reporting, and failure diagnosis.  
**Goal:** make a fresh install self-describing and make the same diagnosis
workflow work for native, package, mono-container, and Proxmox deployments.

## 1. Findings

### 1.1 Installation paths expose too many operational models

The documentation presents native installation, mono Docker/Compose,
Proxmox LXC, packages, AppImage, and archives. Native installation itself has
two materially different layouts:

| Surface | Installer/script layout | Package layout |
|---|---|---|
| Configuration | `/etc/circuitbreaker/.env` | `/etc/circuit-breaker/config.toml` and `circuit-breaker.env` |
| Data | `/var/lib/circuitbreaker` | `/var/lib/circuit-breaker` |
| Services | Several `circuitbreaker-*` units | One `circuit-breaker.service` |
| Operations | Installer/CLI conventions | Package/service conventions |

The distinction is documented in `packaging/README.md`, but it is not
represented in a common runtime identity. Consequently, an operator cannot
reliably infer the correct service names, paths, update procedure, or
diagnostic command from “native install.”

### 1.2 The CLI is duplicated and installers do not consistently configure it

`deploy/cli/cb` and the repository-root `cb` are independent Bash
implementations. They contain different command matrices and different
assumptions about containers, service names, ports, environment files, and
installation metadata.

The native installer installs its CLI, while Docker/Compose and package
installations do not consistently install or configure an equivalent command.
The root CLI can fall back to assumptions such as a container named
`circuit-breaker` on port `8080`; those assumptions are wrong for some
supported layouts. Compose environment files and CLI metadata also use
different directories and filenames.

Existing tests protect CLI exit-status contracts, but not cross-mode behavioral
parity or the complete install-to-diagnosis journey.

### 1.3 Diagnosis capabilities are strong but fragmented

The application already has valuable primitives:

- `/livez`, `/startupz`, `/readyz`, and compatibility `/health` endpoints.
- Shared dependency-aware readiness logic in `app.core.health`.
- Native `cb doctor` checks for PostgreSQL, PgBouncer, Redis, NATS, backend,
  Docker proxy, nginx, TLS, firewalld, and SELinux.
- Mono entrypoint validation for secrets, storage, TLS, database setup, and
  migrations.
- Worker heartbeat files.
- Installer diagnostics and redacted logs.

These capabilities are spread across shell scripts, container startup,
backend endpoints, systemd probes, and CLI implementations. There is no
single machine-readable diagnostic model that can power both a human CLI and a
future UI, nor a common adapter model for native versus mono environments.

### 1.4 First-run state can become inconsistent

`docker/30-oobe.sh` writes `.oobe-complete` before account creation and
onboarding finish. A container exit, failed migration, unreachable browser, or
lost setup token can therefore leave the filesystem marker saying OOBE was
complete while backend bootstrap state still requires setup.

The backend bootstrap APIs and frontend OOBE coverage are stronger than this
marker, but they currently represent separate state machines. First-run
security steps such as setup-token retrieval, vault-key backup, TLS
requirements, OAuth callbacks, and upload limits also impose a high recovery
burden when something goes wrong.

### 1.5 Documentation and tests do not fully model operator journeys

The documentation contains contradictions about Docker requirements, Compose
defaults, CLI availability, package paths, OOBE step details, and upload
limits. Existing tests cover many contracts, but not the complete sequence of:

1. install,
2. discover the correct operation command,
3. diagnose a dependency failure,
4. update,
5. back up and restore,
6. restart,
7. recover from interrupted OOBE.

## 2. Goals and non-goals

### Goals

1. Make every supported installation self-describing.
2. Provide one `cb` command contract across supported modes.
3. Replace implicit path/container/service guesses with explicit metadata and
   mode-aware errors.
4. Unify application health and host/deployment checks into a normalized,
   redacted diagnostic result.
5. Make interrupted first-run setup recoverable and backend-owned.
6. Reduce documentation branching and validate the documented operator journey
   in CI.

### Non-goals

- Replacing PostgreSQL, Redis, NATS, nginx, systemd, or supervisor.
- Removing supported deployment modes without an explicit support decision.
- Making `/health` expose secrets, credentials, setup tokens, vault keys, or
  unrestricted internal diagnostics.
- Changing liveness semantics used by restart probes.
- Making private-network validation reject legitimate LAN deployments.
- Adding a hosted control plane or requiring internet access at runtime.

## 3. Target operating model

Every installation writes one versioned, root-readable install identity
record. The record is the source of truth for operator tooling and contains:

```json
{
  "schema_version": 1,
  "mode": "native|package|mono|proxmox",
  "version": "0.4.2",
  "config_path": "...",
  "data_dir": "...",
  "env_file": "...",
  "service_names": ["..."],
  "container_name": "...",
  "compose_file": "...",
  "cli_path": "...",
  "health_url": "...",
  "installed_at": "..."
}
```

Fields that do not apply remain absent or empty; they must never be inferred
from a default container name, port, or current working directory.

The `cb` executable is one implementation distributed to every supported
mode. It reads the identity record, selects a mode adapter, and reports
unsupported operations with explicit remediation. A missing or malformed
identity is a diagnosis result, not permission to guess.

Diagnostics use a normalized result shape:

```json
{
  "component": "postgres",
  "check": "ready",
  "status": "pass|warn|fail|unknown|skipped",
  "severity": "info|warning|error|critical",
  "evidence": "...",
  "remediation": "...",
  "safe_to_retry": true
}
```

The same result can be rendered as concise terminal output, JSON for support
automation, and a future authenticated UI. Evidence is bounded and redacted.

## 4. Implementation phases

### Phase 0 - Establish the support vocabulary and compatibility matrix

- Declare the primary supported channels in the installation index:
  recommended native bundle, mono container/Compose, and Proxmox wrapper.
- Decide whether distro packages are first-class for the release. If retained,
  define their compatibility contract; if not, label them advanced/manual
  rather than presenting them as equivalent native installs.
- Inventory every installer, package, image, service, config, data, CLI,
  backup, restore, update, and uninstall path.
- Define the identity schema and normalized diagnostic schema.
- Add a generated compatibility matrix covering:
  - install command,
  - service/container identifiers,
  - config and data paths,
  - CLI availability,
  - health probe,
  - backup/restore support,
  - update support,
  - uninstall command.

**Deliverable:** one reviewed support matrix that documentation and contract
tests can consume.

### Phase 1 - Make installations self-describing

- Have the native installer, package post-install, mono entrypoint, Compose
  setup, and Proxmox wrapper write the install identity record.
- Define a stable location with safe ownership and permissions, while allowing
  the identity to reference mode-specific paths.
- Include schema version and installation version so future migrations can be
  explicit.
- Ensure identity writes are atomic and do not include secret values.
- Add an identity inspection command:
  `cb info` or an equivalent existing command, with human and JSON output.
- Fail clearly when metadata is missing or inconsistent:
  identify the missing file/field and provide the mode-specific repair command.
- Make all supported installers place the same CLI implementation or create a
  documented wrapper that invokes it.

**Acceptance:** a user can run the same initial command after any supported
  install and learn exactly which mode, paths, services, and health target are
  active.

### Phase 2 - Consolidate the CLI and remove unsafe fallbacks

- Select one canonical CLI implementation and retire the duplicated logic.
- Preserve existing command names and exit-status guarantees where possible.
- Add mode adapters for service control, logs, health, update, backup, restore,
  and uninstall.
- Read all paths and identifiers from install identity rather than hardcoded
  defaults.
- Make unsupported commands fail with:
  - detected installation mode,
  - why the operation is unavailable,
  - the supported alternative.
- Ensure Compose, package, and mono installs generate the metadata currently
  expected by the CLI.
- Keep secret-bearing environment files out of diagnostic output and command
  suggestions.
- Add shell-level contract tests that run each command against every supported
  mode fixture.

**Acceptance:** `cb status`, `cb doctor`, update, backup, restore, and
  restart instructions are consistent across all first-class modes.

### Phase 3 - Build a unified diagnosis pipeline

- Reuse `app.core.health` as the application-health source of truth.
- Preserve the existing meanings of `/livez`, `/startupz`, `/readyz`, and
  `/health`; do not use dependency readiness as a process restart probe.
- Add an authenticated detailed diagnostic endpoint or service that returns
  normalized checks without exposing secrets.
- Define check providers and mode adapters:
  - application adapter using live/startup/readiness state,
  - systemd/native adapter,
  - package-service adapter,
  - mono/container adapter,
  - Proxmox wrapper adapter.
- Port native `cb doctor` checks into shared check definitions where practical,
  retaining platform-specific implementations behind adapters.
- Include bounded evidence for:
  - database and migration state,
  - PgBouncer,
  - Redis,
  - NATS,
  - backend/API,
  - workers and heartbeat age,
  - nginx/TLS,
  - storage capacity and ownership,
  - Docker proxy/telemetry prerequisites,
  - firewall and SELinux only when relevant.
- Replace shell `eval`-based execution with argument-array subprocess calls or
  narrowly validated commands where the diagnostic implementation is changed.
- Preserve automatic redacted log tails, but include them only on failure and
  cap their size.
- Support `cb doctor --json` for support bundles and automation.

**Acceptance:** one command identifies the failing layer and gives a
mode-aware remediation without requiring the operator to know internal
service names first.

### Phase 4 - Make first-run state backend-owned and recoverable

- Stop `.oobe-complete` from overriding incomplete backend bootstrap state.
- Prefer backend bootstrap status as the sole source of truth; if the marker is
  retained as a startup optimization, it must never suppress required setup.
- Write a completion marker only after the backend confirms onboarding/account
  creation has completed, or remove the marker entirely if it is unnecessary.
- Add a safe `cb setup`/`cb setup-token` flow that:
  - reports whether setup is pending or complete,
  - locates the token using metadata rather than guessed paths,
  - enforces file permissions,
  - redacts the token from ordinary diagnostics,
  - explains how to regenerate it.
- Print a clear post-install readiness message containing the local URL, active
  health target, and next setup action for native and mono installs.
- Align frontend validation and docs for upload limits, TLS requirements, OAuth
  callback configuration, and vault-key backup.
- Add a recovery page or CLI guidance for a lost setup token and incomplete
  first-run state without weakening one-time token semantics.

**Acceptance:** restarting before account creation leaves setup available and
  does not require deleting a marker or manually editing the data volume.

### Phase 5 - Simplify documentation and support workflows

- Rewrite the installation index around the supported operating model rather
  than listing every artifact equally.
- Give each first-class mode one copy-paste install, verify, diagnose, update,
  backup, restore, and uninstall path.
- Move package/archive/AppImage details into an advanced section if retained.
- Remove contradictory statements about Docker, Compose defaults, CLI
  availability, paths, and OOBE limits.
- Generate path/service examples from the support matrix where feasible.
- Add a troubleshooting decision tree keyed by `cb doctor` result codes.
- Document air-gap/offline behavior explicitly, including expected failures and
  how to use locally available artifacts.

### Phase 6 - Validate complete operator journeys

Add artifact-level tests for:

1. Fresh native installation and identity generation.
2. Fresh mono/Compose installation and identity generation.
3. Fresh package installation if retained as first-class.
4. Proxmox wrapper installation and identity propagation.
5. `cb info`, `cb status`, and `cb doctor` in each mode.
6. Deliberate database, Redis, NATS, worker, storage, TLS, and proxy failures.
7. OOBE interruption before account creation, followed by restart and retry.
8. Setup-token regeneration and redaction.
9. Upgrade with pre-upgrade backup.
10. Backup, restore, restart, and health recovery.
11. Missing or corrupt identity metadata.
12. JSON diagnosis output stability and secret redaction.

The tests should validate user-visible exit codes, remediation text, and
documented commands, not only internal helper functions.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Existing scripts and operators depend on old paths or service names | Keep a compatibility reader/wrapper during one release and emit migration guidance. |
| Identity metadata becomes stale after manual changes | Include schema/version fields, validate referenced paths, and report stale fields as warnings rather than silently using guesses. |
| A unified doctor leaks secrets | Define an allowlisted evidence policy, redact environment/config output, cap logs, and add secret-scanning tests. |
| Detailed health endpoints become an attack surface | Require authentication for internal diagnostics and keep public liveness/readiness minimal. |
| CLI consolidation breaks mode-specific behavior | Use explicit adapters and retain contract tests for exit status and destructive-operation guards. |
| OOBE marker removal causes repeated setup work | Make the backend bootstrap state authoritative and test restart/resume transitions. |
| Supporting every artifact keeps complexity high | Make a deliberate first-class/advanced support decision and align documentation with it. |
| Shell diagnosis remains brittle across distros | Isolate platform checks, validate command arguments, and report `unknown` when a probe is unavailable rather than claiming failure. |

## 6. Acceptance criteria

This plan is complete when:

1. Every first-class installation writes a valid, secret-free identity record.
2. One CLI implementation provides mode-aware status and diagnosis.
3. No supported path depends on guessed container names, ports, or config
   directories.
4. `cb doctor` can combine application health, deployment checks, worker
   heartbeats, and bounded remediation evidence in human and JSON forms.
5. Liveness probes remain process-only while readiness and detailed diagnosis
   remain dependency-aware.
6. Interrupted OOBE resumes from backend state without manual marker cleanup.
7. Fresh-install, failure-recovery, update, backup/restore, and restart journeys
   are covered by artifact-level tests.
8. Installation documentation has one consistent command path per first-class
   mode and accurately describes advanced artifacts and offline limitations.
