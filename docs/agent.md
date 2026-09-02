# cb-agent

`cb-agent` is a small Go daemon you install on a machine you want Circuit Breaker to see from
the inside. It gives the server a vantage point on a network the server itself cannot reach —
a remote site, a separate VLAN, a segment behind NAT.

> **Linux only today.** The installer the server hands out is a POSIX shell script built around
> `useradd` and `sha256sum`, and only `linux/amd64` and `linux/arm64` binaries are built. The
> add-agent panel shows macOS and Windows tabs disabled rather than omitting them, so the answer
> to "is this coming?" is visible rather than implied.

> **Known issue — the shipped systemd unit blocks `AF_NETLINK`.** The unit the installer writes
> sets `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, which the kernel enforces on every
> `socket()` call. The agent needs `AF_NETLINK` both to read the neighbour cache and — less
> obviously — to enumerate its own interfaces, so on a native systemd install **local discovery
> and remote probing do not work at all** until the unit is corrected. Host telemetry,
> enrollment, the link, and self-update are unaffected. Symptom, workaround and fix are in
> [Known issues](#known-issues); everything below describes the design as written, so read that
> section before relying on the discovery and probe sections.

---

## What it is

The agent makes **outbound connections only**. It opens a WebSocket to your Circuit Breaker
server, completes a Noise IK handshake over it, and keeps that one connection alive. Everything
after that — telemetry, capability grants, probe assignments, discovery requests, update
instructions — travels inside that single encrypted session.

**You do not need an inbound firewall rule.** The agent binds no listening socket at all; there
is nothing on the host for anything to connect *to*. If the connection drops, the agent
reconnects on exponential backoff with jitter, starting at 1 second and capping at 5 minutes.

What it does while connected:

- **Host telemetry** — CPU, memory, filesystems, disks, network and temperatures. Docker
  containers are collected too, but only when an administrator turns `include_docker` on in the
  `host_telemetry` grant; it is **off by default**, and a reachable Docker socket alone does not
  enable it.
- **Remote probes** — server-assigned monitor checks (ICMP, TCP connect, HTTP, DNS) run from the
  agent's position rather than the server's.
- **Local discovery** — bounded sweeps of the segments the agent is attached to: neighbour cache
  reads, ICMP, TCP connect, reverse DNS. See [Known issues](#known-issues) — neither discovery
  nor probing runs under the systemd unit as currently shipped.

All three are capability grants the server issues. None of them can be turned on from the host.

---

## Install

### Get the command

Go to **Agents → Add agent**. The panel generates the install command for you and shows two
things you are meant to check before running it: which TLS mode it was built for, and the
SHA-256 of the script it pipes.

The command comes in one of two forms depending on your server's certificate.

**Publicly trusted certificate (e.g. Let's Encrypt):**

```sh
curl -fsSL https://your-server/install-agent.sh | sudo sh
```

**Self-signed certificate** — the command downloads first, verifies the digest, and only then
runs it, because `-k` skips certificate verification for the download:

```sh
curl -fsSLk https://your-server/install-agent.sh -o /tmp/cb-agent-install.sh && \
  echo "<script_sha256>  /tmp/cb-agent-install.sh" | sha256sum -c && \
  sudo sh /tmp/cb-agent-install.sh
```

The `<script_sha256>` is filled in by the panel. Compare it against what the panel shows before
you run the script. `GET /install-agent.sh` is unauthenticated by design — it embeds only the
server's *public* identity key and TLS pin, never a secret — so the digest is what makes it
trustworthy, not the transport.

### Architecture

The script maps `uname -m` itself:

| `uname -m` | Binary fetched |
|---|---|
| `x86_64` | `linux/amd64` |
| `aarch64` or `arm64` | `linux/arm64` |
| anything else | exits with `unsupported architecture` |

### What the installer does

Running as root, in order:

1. Creates the service user if it does not exist:
   `useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent`.
2. Downloads the binary from `${SERVER_URL}/api/v1/agents/binary/<version>/linux/<arch>` and
   verifies it against a SHA-256 digest embedded in the script itself (`sha256sum -c`).
3. Installs it to `/var/lib/cb-agent/versions/<version>/cb-agent`, points
   `/var/lib/cb-agent/current` at it, and points `/usr/local/bin/cb-agent` at *that*. The
   two-level symlink is what makes self-update and rollback atomic.
4. Writes `/etc/circuit-breaker/agent.toml`:

   ```toml
   server_url = "https://your-server"
   server_static_pk = "<64 hex chars — the server's X25519 identity public key>"
   tls_pin = "<base64 SHA-256 SPKI pin, empty for publicly trusted certs>"
   log_level = "info"
   spool_cap_bytes = 67108864
   ```

5. Adds `cb-agent` to the `docker` group **only if** `docker` is already on the host.
6. Appends `net.ipv4.ping_group_range = 0 2147483647` to `/etc/sysctl.conf` if that setting is
   not already there, and applies it. This is what lets the agent send ICMP without
   `CAP_NET_RAW`.
7. Writes `/etc/systemd/system/cb-agent.service` and runs `systemctl daemon-reload`.
8. Runs `sudo -u cb-agent /usr/local/bin/cb-agent enroll`, which prints the device fingerprint
   and pairing code and waits for you to approve.
9. Runs `systemctl enable --now cb-agent`.

---

## Enrollment

Enrollment is a mutual check. The agent proves it holds a private key; you prove the machine in
front of you is the one that just appeared in the UI.

### The sequence

1. The agent generates an X25519 keypair on first run and stores the private half at
   `/var/lib/cb-agent/device.key`, mode `0600`. That key — not the hostname, not the machine ID
   — is the agent's identity for its whole life.
2. It dials `wss://your-server/api/v1/agents/enroll` and completes a Noise IK handshake against
   the `server_static_pk` from `agent.toml`. If the server's identity key is not the one the
   config pins, the handshake simply fails.
3. It prints its **device fingerprint** — the first 16 bytes of SHA-256 over its public key,
   rendered as eight 4-character groups:

   ```
   device fingerprint: 3f2a-91c4-08de-77b1-5a3e-c210-6d94-ff08
   compare this fingerprint against the one shown on the approval screen
   ```

4. The server creates a `pending` row and mints a **pairing code**: 60 bits of randomness in
   Crockford base32, printed as `XXXX-XXXX-XXXX`. The agent prints it along with a magic link
   (`https://your-server/agents/enroll?c=<code>`).
5. In the UI, an **administrator** enters the code (or follows the link), compares the
   fingerprint, and approves.

### The pairing code is a selector, not a credential

Both approval routes require an authenticated session with the `admin` role. A leaked pairing
code on its own buys an attacker nothing — it identifies a pending row, it does not authorise
anything. The **fingerprint comparison** is the check that actually matters.

### Code expiry

| Property | Value |
|---|---|
| Lifetime | 15 minutes |
| Uses | Single-use (consumed atomically on lookup) |
| Storage | Redis, keyed by SHA-256 of the normalised code |

While the agent's `enroll` connection is still open, it re-mints and prints a fresh code
automatically once the previous one's 15 minutes lapse — so a code going stale while you find
an admin is not a problem. If the enroll process has exited, see
[Runbook 5](#5-expired-pairing-code).

### TLS pinning

Two modes, chosen by the server from the certificate nginx actually serves:

- **`public`** — the certificate is publicly trusted, `tls_pin` is empty, and the agent uses the
  system CA trust store normally.
- **`self_signed`** — `tls_pin` holds the base64 SHA-256 digest of the leaf certificate's
  SubjectPublicKeyInfo. Standard chain and hostname verification is replaced entirely by an
  exact match against that digest, because self-signed LAN certificates commonly carry only a
  legacy CN with no SAN, which Go's verifier rejects outright regardless of trust.

The pin is computed from `${CB_DATA_DIR:-/data}/tls/fullchain.pem` — the file nginx actually
presents — falling back to the certificate record in the database. It applies to the enrollment
socket, the link socket, **and** binary downloads.

### Limits an enrolling agent runs into

| Limit | Value | What you see |
|---|---|---|
| Handshake timeout | 10 s | Connection closed |
| Clock skew tolerance | ±60 s | `clock_skew` error, then close |
| Connection attempts per IP | 20 per 60 s | WebSocket close `1013` |
| Connection attempts globally | 200 per 60 s | WebSocket close `1013` |
| Wrong pairing codes per IP | 10 per 15 min | HTTP 429 on lookup |
| Wrong pairing codes globally | 50 per 15 min | HTTP 429 on lookup |
| Concurrent pending agents | 100 | WebSocket close `1013` |
| Pending row lifetime | 7 days, then auto-rejected | Agent shows `rejected` |

An agent whose device key is already on a `revoked` or `rejected` row is refused at `/enroll`
outright. There is no silent re-enrollment.

---

## What it can see

### Scope is derived, not declared

The agent does not choose what it may reach, and neither does the host. Scope is computed from
two inputs:

- **Directly connected private networks** — the RFC 1918 (`10/8`, `172.16/12`, `192.168/16`) and
  IPv6 ULA (`fc00::/7`) prefixes the agent reports as attached to a non-loopback,
  non-point-to-point interface. This is the `direct_private` scope mode, and it is the only mode
  v1 defines.
- **Grant configuration** — `additional_cidrs` an admin explicitly approved, minus
  `excluded_cidrs` an admin explicitly denied.

### Enforcement runs on both sides

The backend evaluator (`app/core/agent_scope.py`) and the agent evaluator
(`internal/netscope`) are deliberate mirrors of each other, pinned against a shared corpus so
they cannot drift. A destination has to pass **both**. The server refuses to dispatch what is
out of scope; the agent refuses to execute what is out of scope even when the server dispatched
it.

The rule order carries the security weight, and it is identical on both sides:

1. **Prefix width first.** A discovery target wider than `/16` (IPv4) or `/48` (IPv6) is
   refused, whatever the grant says — anything wider is a routing mistake being read as a scope.
2. **Special-use denial, on overlap.** Never reachable, regardless of grant:
   `0.0.0.0/8`, `127.0.0.0/8`, `169.254.0.0/16`, `224.0.0.0/4`, `240.0.0.0/4`, `::/128`,
   `::1/128`, `fe80::/10`, `ff00::/8`, `fd00:ec2::254/128`. Overlap, not containment — a request
   covering both a usable segment *and* link-local is still a request for link-local.
3. **Exclusions, also on overlap** — an excluded `/25` cannot be walked around by asking for the
   enclosing `/24`.
4. **Containment** — and only full containment inside a single allow-list network.
5. **Agent-side only:** the agent additionally refuses anything it is not *currently* directly
   attached to (reason `not_directly_connected`), which the server cannot express because only
   the agent knows its live interfaces.

Hostnames are judged by every resolved address independently — one bad answer refuses the whole
name, which is what makes a rebinding resolver useless here.

### The AGT-08 guarantee

**Disallowed scope is never scanned or probed.** The refusal happens before anything touches the
network — before a socket is dialled, before a name is resolved. A probe assignment or discovery
request naming an out-of-scope destination is rejected at validation and reported back with the
evaluator's own machine-readable reason (`out_of_scope`, `special_use`, `excluded_cidr`,
`prefix_too_wide`, `not_directly_connected`, …), never with a fabricated "nothing found".

Scope carries a **version**, derived from the networks, direct networks, exclusions and
hostnames that produced it. A dispatch built against a version the agent no longer holds is
refused with `scope_version_mismatch` rather than run against the newer authorisation. When a
reconnecting agent's `hello` reports networks that moved its scope, the server closes the
discovery dispatches that scope no longer authorises, in the same transaction.

### Capability grants

Three capabilities, all enabled by default at approval, each individually opt-out in the
approval modal:

| Capability | Default configuration |
|---|---|
| `host_telemetry` | 30 s interval; filesystems, disks, network and temperatures on; virtual interfaces (`include_virtual`) and Docker containers (`include_docker`) **off** |
| `remote_probe` | 20 concurrent; `direct_private` scope |
| `local_discovery` | 1024 addresses/job, 64 concurrent hosts, 1500 ms host timeout, 300 s job timeout, TCP ports `22, 53, 80, 443, 445, 3389, 8000, 8080, 8443` |

Grants arrive over the encrypted link and are cached to `/var/lib/cb-agent/grants.json` **only**
so a restart while disconnected does not go dark. The server re-sends the authoritative set on
every connection and the cache is overwritten. Editing that file changes nothing.

---

## Outbound endpoints

Everything the agent dials, so you can build an allowlist. `your-server` and its port are
whatever `server_url` in `agent.toml` says; the tables below use the ports a default deployment
publishes.

### To the Circuit Breaker server

| Purpose | URL | Protocol |
|---|---|---|
| Enrollment | `wss://your-server/api/v1/agents/enroll` | WebSocket over TLS |
| Live link | `wss://your-server/api/v1/agents/link` | WebSocket over TLS |
| Self-update download | `https://your-server/api/v1/agents/binary/{version}/{os}/{arch}` | HTTPS GET |
| Installer fetch (once, by `curl`) | `https://your-server/install-agent.sh` | HTTPS GET |

If `server_url` uses `http://`, the WebSocket scheme becomes `ws://` — the agent rewrites only
the scheme, never the host or port.

**Ports.** A default Circuit Breaker deployment publishes **443** for HTTPS and **80** for HTTP.
If you changed `CB_PORT` / `CB_PORT_HTTPS`, or you front the server with something else, allow
whatever port is in `server_url` instead — the agent has no port of its own and never falls back
to a different one.

**Proxies.** `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY` (and their lowercase forms) are honoured
for all three destinations above, WebSocket dials included.

### To the monitored network

Only when the corresponding grant is enabled, and only within scope:

| Traffic | Destination | Notes |
|---|---|---|
| ICMP echo | In-scope addresses | Unprivileged datagram sockets, no `CAP_NET_RAW` |
| TCP connect | In-scope addresses, granted ports | Discovery default `22, 53, 80, 443, 445, 3389, 8000, 8080, 8443`; monitor probes use the port the check specifies |
| HTTP/HTTPS checks | As specified per monitor | Only for assigned HTTP monitors |
| DNS | The host's configured resolver, or a resolver named by the check | Reverse lookups during discovery; forward lookups for DNS monitors |
| Docker API | `unix:///var/run/docker.sock` | Local socket, not network; requires `include_docker` on the `host_telemetry` grant **and** `docker` group membership |

Neighbour-cache discovery reads the kernel's ARP/NDP table over a netlink socket and sends no
packets at all. That socket is `AF_NETLINK`, which the shipped systemd unit does not permit — see
[Known issues](#known-issues).

### Inbound

None. The agent binds no listening socket.

---

## Permissions

### Service user

The installer creates a dedicated system account: `cb-agent`, no home directory, shell
`/usr/sbin/nologin`. The daemon runs as `cb-agent:cb-agent`. Root is required for exactly two
things — running the installer, and running `cb-agent uninstall`.

### The systemd unit

`/etc/systemd/system/cb-agent.service`:

| Directive | Value | Why |
|---|---|---|
| `User` / `Group` | `cb-agent` | Never runs as root. The daemon aborts at startup if its state directory or any of `device.key`, `grants.json`, `status.json` is owned by a different uid/gid. |
| `ExecStart` | `/usr/local/bin/cb-agent` | The stable symlink, not a versioned path — self-update re-points what it resolves to. |
| `Restart` / `RestartSec` | `on-failure` / `5s` | A crash-looping build still reaches the rollback check, which runs before any network call. |
| `NoNewPrivileges` | `true` | No setuid binary the agent execs can gain privileges. It has none to gain. |
| `ProtectSystem` | `strict` | The entire filesystem is read-only except what `ReadWritePaths` opens. |
| `ProtectHome` | `true` | `/home`, `/root` and `/run/user` are inaccessible. |
| `PrivateTmp` | `true` | Private `/tmp` and `/var/tmp`, so update downloads cannot be swapped by another local user. |
| `RestrictAddressFamilies` | `AF_UNIX AF_INET AF_INET6` | TCP/UDP/ICMP-datagram and the Docker socket, nothing else — no `AF_PACKET`, so no raw frame capture. **It also omits `AF_NETLINK`, which the agent genuinely needs**; see [Known issues](#known-issues). |
| `SystemCallFilter` | `@system-service` | Kernel-level syscall allowlist. |
| `ReadWritePaths` | `/var/lib/cb-agent` | The single writable path: identity, grants, status, spool, and versioned binaries. |
| `After` / `Wants` | `network-online.target` | The first action is a network dial. |

### Elevated capabilities

There is exactly one, and it is not a Linux capability:

- **`net.ipv4.ping_group_range`**, set system-wide by the installer to `0 2147483647`. This lets
  unprivileged processes open ICMP *datagram* sockets. It is what avoids granting the agent
  `CAP_NET_RAW` — the agent has **no** `CAP_NET_RAW` and cannot craft or capture raw packets.
  Without this sysctl, ICMP probes report themselves as unavailable rather than failing
  silently.
- **`docker` group membership**, added only if Docker is already installed. It is what lets the
  host-telemetry collector read the Docker API socket. It is genuinely privileged — membership
  in `docker` is equivalent to root on that host.

  Group membership on its own collects nothing: container telemetry is **off by default** and
  only runs once an administrator sets `include_docker` on the `host_telemetry` grant. Turn it
  back off there — that is the supported control, and the collector then reports `host.docker` as
  `disabled`. Removing `cb-agent` from the `docker` group is a defence-in-depth measure against
  the privilege itself, not the way to turn the telemetry off; with the grant still enabled the
  collector reports `host.docker` as `unavailable` with a remediation string and marks the whole
  host sample `degraded`.

### File permissions

| Path | Mode | Owner |
|---|---|---|
| `/var/lib/cb-agent/` | created by the installer under its umask, then `chown`ed; the agent creates it `0700` if it is missing | `cb-agent` |
| `/var/lib/cb-agent/versions/<v>/` | `0755` | `cb-agent` |
| `/var/lib/cb-agent/device.key` | `0600` | `cb-agent` |
| `/var/lib/cb-agent/grants.json` | `0600` | `cb-agent` |
| `/var/lib/cb-agent/status.json` | `0600` | `cb-agent` |
| `/var/lib/cb-agent/queue.jsonl`, `queue.head` | `0600` | `cb-agent` |
| `/etc/circuit-breaker/agent.toml` | written by the installer as root under its umask — it holds no secret, only the server's public key and TLS pin | root |

At every daemon start the agent audits `device.key`, `grants.json` and `status.json` plus the
state directory itself: **ownership** drift aborts startup loudly, and **mode** drift on those
three files is corrected back to `0600` in place and logged.

---

## Update and rollback

### Dispatching an update

An administrator triggers an update from the agent's detail page (`POST
/api/v1/agents/{id}/update`). The server resolves the target version — the one you pinned, or
the latest in its manifest — looks up the SHA-256 for that agent's OS and architecture, and
refuses with a 404 if no binary exists for that combination.

The instruction (version, SHA-256, OS, arch) is pushed over the encrypted link immediately. If
that push is missed, the agent picks it up from a Redis-queued fallback the link polls every
5 seconds.

### What the agent does

1. Downloads from `https://your-server/api/v1/agents/binary/{version}/{os}/{arch}` through the
   same pinned-TLS transport the link uses. Responses larger than 256 MiB are rejected.
2. Verifies the SHA-256 against the digest that arrived over the encrypted channel, using a
   constant-time comparison.
3. Fetches the detached signature from the same URL with a `.sig` suffix and verifies it against
   a public key embedded in the agent at build time. See **Signed updates** below.
4. Writes a durable marker, `fsync`s the new binary into
   `/var/lib/cb-agent/versions/<version>/cb-agent`, atomically re-points
   `/var/lib/cb-agent/current`, and re-execs itself.
5. Reports `started`, then `succeeded` / `failed` / `rolled_back` back to the server as
   `update.status` frames, which appear in the agent's event log.

### Signed updates

The SHA-256 above proves the download matches what **the server said**. That is worth nothing
if the server itself is compromised: whoever controls it can serve any binary along with a
matching digest, and every agent in the fleet would install it. Agent binaries are therefore
signed with an Ed25519 key that lives only in the release pipeline.

The verifying public key is compiled into the agent with an `-ldflags -X` at build time. It is
deliberately **not** configurable at runtime, not delivered by the server, and not read from
disk — a key the server can influence would reproduce exactly the problem signing solves. The
private half never exists in the application runtime, in this repository, or in any container
image.

**This release verifies in warn mode.** A binary that fails verification is installed, and the
agent logs a warning naming the reason. That is the migration, not the destination: agents
running today have no embedded key and binaries built before this change carry no signature at
all, so defaulting to refusal would break every in-flight fleet. Enforcement becomes the
default in **0.6.0**.

To enforce now, set on the agent host:

```
CB_AGENT_UPDATE_ENFORCE_SIGNATURE=1
```

An update whose signature does not verify is then refused before anything is written: no
rollback marker, no swap, and an `update.status` of `failed` naming the reason.

**Agents you built yourself are unsigned by default.** `make build-from-source` has no access
to the release private key, so it produces a warn-mode binary with no embedded key — and a
binary with no embedded key stays in warn mode *even with the flag set*, because it has nothing
to verify against. Refusing there would strand every self-built agent the moment enforcement
defaults on. To sign your own builds:

```
make agent-signing-key                    # writes a private key, prints the public one
cd apps/agent && make build-all SIGNING_PUBKEY=<the printed key>
make verify-signing-key SIGNING_PUBKEY=<the printed key>   # proves the ldflag landed
```

Then set `AGENT_SIGNING_PRIVATE_KEY` when generating the manifest, and keep the private key in
your own secret store. `cb-agent signing-key` prints whichever key a given binary carries, or
nothing for a warn-mode build.

### Automatic rollback

The new binary must re-establish a link and reach an accepted `hello.ack` within **2 minutes**.
If it does not, the agent re-points `current` back at the previous version directory, records
the failure for the next connection to report, and re-execs.

Two independent paths enforce that, and they cover different failures:

- **Live watch** — the running process waits out the two-minute window and rolls back if the
  marker was never cleared.
- **Startup check** — the marker carries a durable deadline that is evaluated from disk *before
  any network call*. This is what saves an agent whose new binary crashes on startup or cannot
  reach the server at all: a crash loop converges on a rollback instead of looping forever.

If the crash landed *before* the binary swap actually happened, nothing is rolled back — the
marker is cleared and the abandoned attempt logged. Rolling back in that case would downgrade a
perfectly healthy binary to an unrelated older one.

### Deliberate rollback

Dispatch an update pinned to the older version. Previous versions stay on disk under
`/var/lib/cb-agent/versions/`, so the download is the only cost.

---

## Revoke and uninstall

These are two different actions with two different blast radii.

### Revoke (server-side)

`POST /api/v1/agents/{id}/revoke`, admin only, and a reason of at least 3 characters is
mandatory. It:

- Flips the agent's status to `revoked` and records who did it and why.
- Cancels every probe run the agent still holds and closes its open discovery dispatches.
- Writes an `agent_revoke_authorized` audit entry.
- Pushes a disconnect to the agent's live socket, if it has one.
- Refuses every subsequent `/link` handshake (the row is no longer `active`) and every
  subsequent `/enroll` attempt from that device key.

**Revoke removes nothing from the host.** The binary, the unit and the state directory stay
exactly where they are — it is the user's machine. The agent simply stops being able to connect.

### Uninstall (host-side)

```sh
sudo cb-agent uninstall
```

Root is required. In order, it:

1. Best-effort notifies the server, which revokes the row with reason *"uninstalled by agent"*
   and performs the same run cancellation the admin-initiated revoke does. A server that cannot
   be reached is reported and the uninstall continues.
2. Runs `systemctl disable --now cb-agent`.
3. Removes:
   - `/etc/systemd/system/cb-agent.service`
   - `/usr/local/bin/cb-agent`
   - `/etc/circuit-breaker/agent.toml`
   - `/var/lib/cb-agent/` in full — `device.key`, `grants.json`, `status.json`, the spool
     (`queue.jsonl` / `queue.head`), and every versioned binary under `versions/`
4. Removes `/etc/circuit-breaker/` **only if removing `agent.toml` left it empty**. On a host
   that also runs the Circuit Breaker server, that directory holds the server's own
   `config.toml` and `circuit-breaker.env` (which carries `CB_VAULT_KEY`) — removing it would
   leave the server's vault permanently undecryptable. Leaving it is silent and is not an error.
5. Runs `systemctl daemon-reload`.

Each phase is independent: a failed `systemctl disable` does not block file removal, and a
failed removal does not block the others. The command prints exactly what it did and exits
non-zero if anything failed.

### Deliberately left behind

- **The `cb-agent` user account** and its `docker` group membership. Removing a system account
  can orphan files elsewhere; deleting users is your call, not the uninstaller's.
- **The `net.ipv4.ping_group_range` line in `/etc/sysctl.conf`.** It is a system-wide setting
  that other software may now depend on.
- **`/etc/circuit-breaker/`** when it still holds the server's own files (see above).
- **The agent's row in the database.** It is left `revoked` so its history, events and audit
  trail survive. Delete it explicitly (`DELETE /api/v1/agents/{id}`) if you want it gone —
  which is refused with a 409 while monitors or discovery profiles are still assigned to it.

Because uninstall removes `device.key`, reinstalling on the same host generates a **new**
identity and appears as a **new** pending agent. That is intentional: it is the clean path back
in after a revoke, since a revoked device key is refused at `/enroll` forever.

---

## Troubleshooting

Start here:

```sh
cb-agent status      # link state, grants, readiness, spool depth
cb-agent version     # version and device fingerprint
journalctl -u cb-agent -f
```

`cb-agent status` reads `/var/lib/cb-agent/status.json`. If it says *"no status recorded yet"*,
the daemon has never run or has not reached its first link attempt — that is a service problem,
not a connection problem. Check `systemctl status cb-agent`.

### Agent shows offline in the UI

The server declares a link dead after **60 seconds** without an application heartbeat (the agent
sends one every 20 s, so that is three misses).

| `cb-agent status` says | Cause | Fix |
|---|---|---|
| No status file at all | Service not running | `systemctl status cb-agent`; check the journal for a startup abort |
| `last error:` names a dial failure | Network path to the server is blocked | Allow outbound to `server_url`'s host and port |
| `last error:` names a pin mismatch | Server certificate changed | See *TLS pin mismatch* below |
| `last error:` mentions the handshake | Server identity key changed, or `server_static_pk` is wrong | [Runbook 1](#1-lost-server-key) |
| `link: connected` but the UI disagrees | Presence is Redis-backed with a 60 s TTL | Check the server's Redis; presence recovers on its own |
| Startup aborts with an ownership error | `/var/lib/cb-agent` or a state file is owned by the wrong user | `chown -R cb-agent:cb-agent /var/lib/cb-agent` |

An agent whose row was **revoked** will dial successfully and then be closed immediately, on
every reconnect, forever. Check the agent's status in the UI before chasing the network.

### Enrollment fails

| Symptom | Cause | Fix |
|---|---|---|
| Connection closed immediately, no fingerprint printed | Attempt-rate limit (20/IP/min, 200 global/min) | Wait a minute and retry |
| Closed right after the fingerprint | Concurrent-pending cap (100) reached | Approve or reject pending agents in the UI |
| `clock_skew` error | Host clock more than 60 s from the server's | See *Clock skew* below |
| Closed immediately, agent shows `revoked`/`rejected` in the UI | That device key is barred | Delete the row, or reinstall to generate a new key |
| Pairing code rejected in the UI | Code expired (15 min) or already used | [Runbook 5](#5-expired-pairing-code) |
| HTTP 429 on the pairing lookup | 10 wrong codes from your IP, or 50 globally, in 15 minutes | Wait out the 15-minute window |
| Fingerprints do not match | **Stop.** Something else is enrolling. | Reject it and investigate |

### TLS pin mismatch

The journal names both digests:

```
tlsdial: certificate pin mismatch (got <base64>, want <base64>)
```

The `want` value is `tls_pin` in `/etc/circuit-breaker/agent.toml`; the `got` value is what the
server actually presented. Causes, in order of likelihood:

1. The server's self-signed certificate was regenerated (reinstall, restore, data directory
   rebuilt).
2. Something is terminating TLS between the agent and the server that was not there before.
3. Genuine interception.

Fix by re-running the installer from the add-agent panel, which fetches the current pin — or by
editing `tls_pin` in `agent.toml` and restarting. Never "fix" it by blanking `tls_pin`: an empty
pin means "use the system CA store", which a self-signed certificate will not satisfy anyway,
and you would have removed the check instead of updating it.

### Clock skew

Both `/enroll` and `/link` reject a handshake whose timestamp is more than **60 seconds** from
the server's clock, and the failure is reported as `clock_skew` rather than as a generic
handshake error. It is genuinely common on VMs resumed from a snapshot and on appliances with no
RTC.

```sh
timedatectl status                 # is NTP synchronised?
systemctl restart systemd-timesyncd
```

Fix the *agent's* clock first — but if several agents report skew at once, suspect the server's.

### Spool pressure

While disconnected, data frames are written to `/var/lib/cb-agent/queue.jsonl` (with
`/var/lib/cb-agent/queue.head` marking how much has already been delivered), capped at 64 MiB by
default (`spool_cap_bytes` in `agent.toml`, `67108864` as installed). When the cap is reached
the **oldest** frames are dropped. Control frames are never spooled — replaying a stale probe
assignment is worse than losing it.

`cb-agent status` ends with the depth:

```
spool: depth=1284 bytes=3947160
```

Depth is also reported to the server on every heartbeat, so the fleet view shows backlog
without waiting for a reconnect.

| Observation | Meaning |
|---|---|
| Depth grows while `link: connected` | The link is flapping — check for a reconnect loop in the journal |
| Depth stays flat at the cap | Frames are being evicted; the outage is longer than the buffer |
| Depth falls slowly after reconnect | Normal. Catch-up is deliberately paced at 4 frames (or 256 KiB) per 100 ms so a backlog cannot stall live telemetry |
| Depth never falls | The drain is failing — look for send errors in the journal |

Every spooled frame carries its original timestamp, so recovered data lands in the right time
bucket rather than bunching at the reconnect moment. Delivery is at-least-once by construction;
the server deduplicates on ingest.

### Duplicate agent after a host clone

Cloning a VM or golden image copies `/var/lib/cb-agent/device.key` and `/etc/machine-id`
together. What happens next depends on which one you copied:

| What was copied | Effect |
|---|---|
| `/etc/machine-id` only | Two distinct agents report the same `machine_id_hash`. The approval screen shows a **duplicate machine** warning. Both work; host linkage may propose the wrong hardware record. |
| `device.key` too | Two hosts hold the *same identity*. `device_pk` is unique, so they alternately claim the same agent row — telemetry from two machines lands on one entity and the link flaps between them. |

The second case is the one that corrupts data. See [Runbook 3](#3-duplicate-agent).

---

## Recovery runbooks

These are the six scenarios AGT-18 requires. Each is written to be followed as-is.

> **On evidence:** AGT-18 counts a runbook as evidence only once it has been exercised in a
> tabletop or automated scenario. This page is the prerequisite for that exercise, not a record
> that it happened.

### 1. Lost server key

**Symptom.** Every agent fails its handshake and is closed. Nothing enrolls. `cb-agent status`
shows a handshake error on every attempt.

The server's static X25519 private key lives vault-encrypted in the application settings row and
is decrypted with the instance's vault key. Losing that key — a lost `CB_VAULT_KEY`, a database
restored without it — means no agent's pinned `server_static_pk` can ever match again.

**If the key is recoverable:**

1. Restore `CB_VAULT_KEY` in `/etc/circuit-breaker/circuit-breaker.env` from your backup.
2. Restart the server.
3. Agents reconnect on their own backoff. No agent-side action.

**If the key is genuinely gone:**

1. The server generates a fresh identity key on first use. Confirm it is up.
2. Every existing agent must be re-pointed at the new key. There is no remote fix — the agents
   cannot authenticate the server well enough to be told anything.
3. On each agent host: `sudo cb-agent uninstall`, then re-run the current install command from
   **Agents → Add agent**, then approve.
4. Delete the stale agent rows once their replacements are approved.

**Prefer rotation over loss.** If you *plan* to change the key, rotate it instead of letting it
go. Rotation mints a successor keypair with a **7-day overlap window** during which both keys are
accepted, and pushes the successor to every connected agent immediately — each one persists it to
`/var/lib/cb-agent/server_key_rotation.json` and trusts both keys thereafter. New install commands
generated during the overlap embed the successor. Only one rotation may be in flight at a time; a
second attempt returns 409 until the overlap elapses.

There is no button for this and no `cb` subcommand — it is two admin API calls, deliberately, so
that a key rotation is something you do on purpose:

```sh
# Where does the key stand right now?
curl -fsS -H "Authorization: Bearer $CB_ADMIN_TOKEN" \
  https://cb.example.com/api/v1/agents/server-key/status | jq

# Start the 7-day overlap.
curl -fsS -X POST -H "Authorization: Bearer $CB_ADMIN_TOKEN" \
  https://cb.example.com/api/v1/agents/server-key/rotate | jq
```

`status` reports `active`, both key fingerprints and `overlap_expires_at`; neither endpoint ever
returns key material. Watch the fleet reconnect before the overlap elapses — an agent that stays
offline through the whole window still pins only the old key and will need its install command
re-run.

### 2. Cloned machine ID

**Symptom.** The approval screen warns *"this may be a cloned image or a re-enrollment of an
existing device"*, or two agents show the same machine identity.

The machine ID hash is derived from `/etc/machine-id`, falling back to
`/var/lib/dbus/machine-id`. It is **not** the agent's identity — it is a host-linkage hint, the
strongest of three descending-confidence signals (machine ID → MAC → hostname) used to propose
which hardware record an agent belongs to.

1. On the cloned host, stop the agent: `sudo systemctl stop cb-agent`.
2. Regenerate the machine ID:
   ```sh
   sudo rm -f /etc/machine-id /var/lib/dbus/machine-id
   sudo systemd-machine-id-setup
   sudo dbus-uuidgen --ensure
   ```
3. Start the agent: `sudo systemctl start cb-agent`. The new value is reported in the `hello` on
   the next connection — host metadata is collected fresh on every connect, so nothing else is
   needed.
4. In the UI, correct the host linkage on the agent's detail page if it was proposed against the
   wrong hardware record.
5. If `device.key` was cloned as well, do [Runbook 3](#3-duplicate-agent) too. Fixing the machine
   ID alone does not fix a shared identity.

An agent that can read *neither* machine-ID file reports readiness `agent.identity: degraded`
with remediation `systemd-machine-id-setup`, and can never be flagged as a duplicate.

### 3. Duplicate agent

**Symptom.** Two agent rows for one machine, or one row whose telemetry visibly comes from two
machines (flapping hostname, contradictory metrics, a link that connects and drops repeatedly).

**Case A — two rows, one machine** (usually: reinstalled without uninstalling, so a second
device key was generated).

1. Decide which row to keep — normally the one currently `active` and connected.
2. Revoke the other one, with a reason (**Agents → detail → Revoke**).
3. Delete it. If the delete returns 409, monitors or discovery profiles are still assigned to it;
   reassign them to the surviving agent first.

**Case B — two machines, one identity** (`device.key` was cloned).

1. Identify which host you want to keep. `cb-agent version` prints the fingerprint on each; they
   will be identical, which is the confirmation.
2. On **every other** host, stop the agent and destroy the copied identity:
   ```sh
   sudo systemctl stop cb-agent
   sudo rm -f /var/lib/cb-agent/device.key
   ```
3. Re-enroll each of them as a genuinely new agent:
   ```sh
   sudo -u cb-agent /usr/local/bin/cb-agent enroll
   ```
   A fresh keypair is generated, a new pending row appears, and a new pairing code and
   fingerprint are printed.
4. Approve each in the UI, comparing fingerprints.
5. `sudo systemctl start cb-agent` on each.
6. Clean up: the original row now belongs to exactly one host. Its history includes telemetry
   from the clones — annotate or discard as your retention policy requires.

**Prevention:** remove `/var/lib/cb-agent/device.key` before capturing any golden image, or
install the agent after cloning rather than before.

### 4. Hostname or IP change

**Symptom.** A host was renamed, re-addressed, or moved to a different segment.

**Identity is unaffected.** The agent is identified by `device.key`, not by hostname or address.
Hostname, OS version, MACs and networks are re-collected fresh and re-reported in the `hello` on
every single reconnect, so the UI catches up within one reconnect cycle with no action from you.

What *does* need attention:

1. **Scope moves with the interfaces.** Under `direct_private`, the agent's scope is derived from
   the private prefixes it is attached to. Moving segments changes it, which changes the scope
   version. Discovery dispatches the new scope no longer authorises are closed automatically by
   the server when the moved `hello` arrives.
2. **Re-check grant configuration.** Any `additional_cidrs` or `excluded_cidrs` you set for the
   old position are still in force and may now be wrong. Review them under the agent's
   capabilities.
3. **Confirm scope after the move:** `cb-agent status` lists the current grants; the agent's
   discovery page in the UI lists the effective scope entries.
4. **If the *server's* address or name changed**, edit `server_url` in
   `/etc/circuit-breaker/agent.toml` on each agent and `sudo systemctl restart cb-agent`. If the
   server's certificate changed with it, update `tls_pin` too — or simply re-run the installer,
   which rewrites both.
5. **If reverse DNS or hardware linkage looks wrong afterwards**, re-check the host link on the
   agent's detail page; the machine-ID match is unaffected by an address change.

### 5. Expired pairing code

**Symptom.** The code is rejected as *"Unknown or expired pairing code"*. Codes live 15 minutes
and are single-use.

**If the `enroll` process is still running** (the installer is still in the foreground, or you
started it by hand): do nothing. It re-mints and prints a fresh code automatically once the old
one lapses. Use the newest one printed.

**If the process has exited:**

1. Re-run enrollment on the host:
   ```sh
   sudo -u cb-agent /usr/local/bin/cb-agent enroll
   ```
   The same `device.key` is reused, so it attaches to the existing pending row rather than
   creating a second one. A fresh code and the same fingerprint are printed.
2. Approve in the UI within 15 minutes, comparing the fingerprint.

**If the agent has been pending for more than 7 days**, a nightly job (03:30 server time) has
auto-rejected it, and `/enroll` now refuses that device key outright.

1. Delete the rejected row: `DELETE /api/v1/agents/{id}`, or the delete action on its detail
   page.
2. Re-run `sudo -u cb-agent /usr/local/bin/cb-agent enroll`. With the row gone, the same device
   key enrolls cleanly as a new pending agent.

**If you are locked out** after wrong codes (10 from one IP, or 50 globally, within 15 minutes),
wait out the 15-minute window. The code itself is not invalidated by a failed lookup that never
matched.

### 6. Restored server

**Symptom.** The Circuit Breaker server was restored from backup, rebuilt, or migrated.

Work through these in order — each is independently able to break every agent:

1. **Vault key.** `CB_VAULT_KEY` in `/etc/circuit-breaker/circuit-breaker.env` must be the one
   the restored database was encrypted with. Without it the server's agent identity key cannot
   be decrypted and no agent can complete a handshake. If it is lost, go to
   [Runbook 1](#1-lost-server-key).
2. **Server identity key.** Restored with the database. If the database is intact and the vault
   key matches, agents reconnect with no changes. Verify at **Agents → server key status** that
   the fingerprint is the one your agents were installed against.
3. **TLS certificate.** This is the most common breakage. If the restore regenerated the
   self-signed certificate at `${CB_DATA_DIR:-/data}/tls/fullchain.pem`, every self-signed-mode
   agent now fails its pin check. Either restore the original certificate *and* its key, or
   update every agent — the fastest path is to re-run the current install command from **Agents
   → Add agent** on each host, which rewrites `tls_pin` from the live certificate. Agents on a
   publicly trusted certificate are unaffected.
4. **Redis state is not restored, and does not need to be.** Presence keys (60 s TTL), pairing
   codes, rate-limit counters and queued update instructions all live only in Redis. Agents show
   offline until each reconnects on its own backoff — up to 5 minutes for one that had been
   failing for a while. Any pairing code minted before the restore is gone; mint a new one.
5. **Server URL.** If the restored server is reachable at a different address, edit `server_url`
   in `/etc/circuit-breaker/agent.toml` on each agent and restart. Agents cannot be told this
   over the link — they have to reach the server to be told anything.
6. **Verify** once agents are back: presence green in the fleet view, `cb-agent status` showing
   `link: connected` with a recent `last connected`, and spool depths falling toward zero.

---

## Known issues

Defects are listed here rather than described away in the sections above, so that what those
sections say about the intended behaviour stays readable.

Both entries below are now **fixed**, and are kept because the fix does not reach an agent that is
already installed: the `AF_NETLINK` one needs the install command re-run on each host, or the
drop-in it documents. Once your fleet is on a unit written by the current installer, neither
applies.

### Fixed in this release — `AF_NETLINK` and the systemd unit

**Status: fixed.** Earlier agents were installed with a unit whose
`RestrictAddressFamilies` line omitted `AF_NETLINK`. systemd enforces that as a
seccomp filter on `socket()`, and two things the agent does need netlink: the
`RTM_GETNEIGH` neighbour-cache dump, and Go's `net.Interfaces()`, which has no
`/sys` fallback on Linux. An affected agent could not enumerate its own
interfaces, so its derived `direct_private` scope arrived empty and every
discovery target and probe destination was refused `empty_scope` before a
packet was sent. Telemetry, enrollment, the link, the spool and self-update
were unaffected — none of them touches netlink.

The installer now writes `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
AF_NETLINK`, and `apps/backend/tests/services/test_agent_install.py` pins the
whole directive so it cannot regress. This does not grant raw packet access:
`AF_PACKET` stays excluded, the agent holds no `CAP_NET_RAW`, and the only
netlink protocol it opens is `NETLINK_ROUTE` for a read-only dump.

**Hosts installed before the fix keep their old unit file.** Re-run the install
command from **Agents → Add agent** on each one — it rewrites the unit — or, as
a per-host stopgap, `sudo systemctl edit cb-agent` and add:

```ini
[Service]
RestrictAddressFamilies=AF_NETLINK
```

Repeated assignments are merged rather than replaced, so the drop-in only has
to name the missing family. Then `sudo systemctl restart cb-agent` and confirm
`cb-agent status` reports `discovery.neighbor: ready`.

### Fixed in this release — `log_level`

**Status: fixed.** `log_level` in `/etc/circuit-breaker/agent.toml` was decoded
into the agent's config struct and read by nothing, so setting it changed
neither what was logged nor how much, and a typo was accepted in silence.

It now takes `debug`, `info` (the default), `warn` or `error`, and an
unrecognised value stops the daemon at startup with a message naming it rather
than being ignored. Output is still a plain message line on standard error,
which systemd routes to the journal — `journalctl -u cb-agent` is unchanged.

Levels behave as follows. The agent's routine progress reporting is `info`, so
`warn` and `error` quieten it; failures the agent could not recover from — a
failed rollback, a failed re-exec after one — are logged at `error` and survive
even the quietest setting. `debug` adds detail on top of `info`.
