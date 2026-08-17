# cb-agent — Reachability Address Model Design

**Date:** 2026-08-14
**Status:** Draft — revised 2026-08-14 after infrastructure-architecture review. Awaiting sign-off
**Related:** `specs/2026-07-26-cb-agent-design.md` (§2.2 Noise IK link, §2.3 install command, §2.4
approval ritual — the trust model this design leans on), `docs/remote-access.md` (the LAN/VPN
boundary this design is the first step away from),
`apps/backend/src/app/services/agent_install.py` (install command and script generation),
`apps/agent/internal/link/link.go` (`serverKeyCandidates` — the candidate-list precedent this
design mirrors; `dialAndHandshake` — the function that has to stop reading a global pin)

## Context

An agent's server address is currently an accident of the admin's browser history. Both
`build_install_command` (`api/agents.py:218`) and `get_install_agent_script` (`main.py:2091`)
derive `server_url` from `request.url.scheme` + `netloc` — whatever hostname the operator happened
to type. Whatever that was gets baked into `/etc/circuit-breaker/agent.toml` as the one address
the agent will ever dial.

Three problems follow, in increasing order of severity:

1. **The two routes can disagree.** They render the same script from different requests, so any
   difference in `Host` or `X-Forwarded-Proto` between them produces a script whose digest does not
   match the one the UI displayed. This shipped: `deploy/nginx/circuitbreaker-tls.conf` had no
   `location = /install-agent.sh` at all, so the SPA catch-all answered with `index.html` and a
   200, and the operator's `sha256sum -c` failed on HTML. Fixed structurally in
   `tests/build/test_nginx_install_agent_route.py`, but the underlying fragility — two routes, two
   derivations, one digest — remains.
2. **A private address is offered as though it were universal.** An operator browsing to
   `https://192.168.0.167` is handed an install command that cannot work on any host outside that
   subnet, with nothing anywhere saying so.
3. **One address is a single point of failure.** An agent enrolled on a LAN address is dead the
   moment it leaves that LAN, and an operator whose server has no inbound path — behind CGNAT, for
   instance — cannot enroll a remote agent at all.

A fourth problem surfaced during review of this design and is fixed here because this design is
what makes the reasoning about `CB_BINARY_URL` explicit: **the installer's binary fetch is
unverified on the default deployment.** `build_install_command` hands out `curl -fsSLk` for the
script under self-signed TLS (`agent_install.py:237`), but the script's own binary download is
`curl -fsSL` with no `-k` (`agent_install.py:42`) against that same self-signed certificate. The
release gate does not catch it: `test_agent_release_gate.py` reads the script's *text* and writes
`agent.toml` itself rather than executing the download. See §4.

This design fixes (1), (2) and (4) outright and builds the substrate for (3). It is the first of
four subsystems; see **Relationship to the other subsystems** below.

## Decisions

| Question | Decision |
|---|---|
| How many addresses does an agent know? | An ordered list. It walks them top-down and connects on the first that works |
| Where does the list come from? | Operator-declared server setting, plus server-advertised additions persisted agent-side |
| Can the server remove an agent's addresses? | No config endpoint, ever. No advertised endpoint the agent is *currently connected on*, either — see §3 |
| What authenticates the server? | Noise IK against a config-rooted static key, exactly as today. The endpoint list is routing data, not trust |
| Per-endpoint TLS trust? | Yes — `pinned` (pin computed live from nginx's cert) or `public` (system CA). Per endpoint means per dial: `Config.TLSPin` becomes a normalization input, not a thing any dial path reads |
| Does `server_url` still work? | Yes. Normalized at load into a one-element list; existing installs are unaffected |
| Does the install command still use the request URL? | Only for `CB_BINARY_URL`, which is provably reachable — and it is now pin-verified rather than fetched with `-k` |
| Is an all-private endpoint list allowed? | Yes, with a warning. LAN-only is a legitimate deployment |
| Is path selection continuous? | No. It is per-connection, plus a bounded preference re-walk while connected below the top live endpoint — see §2 |

### Rejected alternatives

**A single operator-declared URL.** Smallest change, and it fixes the digest bug and the private-IP
dishonesty. Rejected because it leaves a roaming agent broken the moment it changes network, and
because retrofitting a list later means re-enrolling a fleet.

**Always route through the relay/overlay when one exists.** One uniform path, one thing to debug.
Rejected because LAN telemetry would take a round trip through a public VPS, and a relay outage
would take down agents that never needed it.

**Server assigns each agent its list.** Most centrally controllable. Rejected because it requires
the server to model each agent's reachability, and a wrong assignment strands an agent with no way
back — the exact failure the append-only rule exists to prevent.

**Continuous path re-selection (Tailscale-style).** Re-evaluate every endpoint on a timer and move
the live connection to the best one. Rejected as the default because it introduces hysteresis and
makes "which path is this agent on" a moving target during an incident. The bounded re-walk in §2
buys most of the benefit at none of that cost.

### The security argument this design rests on

The endpoint list is **routing information, not trust.** Whatever address an agent dials, it must
still complete a Noise IK handshake against a server static key that came from its own config (or
a persisted rotation successor — `config.ServerKeyRotation`). An attacker who could inject an
endpoint gains a TCP connection that fails at handshake: no impersonation, no telemetry, no
commands.

Two properties follow, and most of this design's cheapness comes from them:

- Server-advertised endpoints are safe to accept without a second trust mechanism.
- A fleet can therefore be handed a new path — a relay, an overlay address — over the live link,
  with no re-enrollment and no config edit.

**What the argument does not cover**, and is handled explicitly elsewhere in this document:

- **Availability, not confidentiality, is the attack surface.** Injection cannot impersonate, but
  removal can strand. That is what the never-remove rules in §3 exist for, and the roaming-agent
  case is where the naive version of them fails.
- **Dialing an attacker-controlled endpoint leaks presence.** The agent completes TCP and TLS and
  sends Noise msg1 before failing. msg1's payload is encrypted to the responder's static key, so a
  wrong responder learns nothing about the agent's identity — but it does learn that a Circuit
  Breaker agent exists at that source IP, and (for a `public` endpoint) sees the SNI. Accepted:
  the same is already true of the single-address model.
- **The install script now discloses topology.** See §3, *Disclosure surface*.

## 1. Endpoint model

An endpoint is a URL plus the trust needed to dial it. `agent.toml`:

```toml
[[endpoint]]
url = "https://192.168.0.167"
tls_pin = "b64-spki…"

[[endpoint]]
url = "https://cb.example.ts.net"
tls_pin = "b64-spki…"
```

`config.Config` gains `Endpoints []Endpoint`. `config.Load` normalizes both spellings into it: a
file with top-level `server_url`/`tls_pin` and no `[[endpoint]]` yields exactly one endpoint, so
every consumer sees one shape and existing installs keep working untouched.

An empty `tls_pin` means system CA trust, matching `tlsdial.NewDialer`'s existing contract for an
empty pin.

Each endpoint additionally carries a **`source`** — `operator`, `detected`, or `advertised`. It
changes no behavior in this design (the walk order is config-then-advertised regardless), and it
exists now so the overlay subsystem can offer, refresh, and withdraw a *detected* address without
a config-format migration and without the UI having to guess whether the operator typed an address
or the server found it.

**Two sources, mirroring `serverKeyCandidates`:**

- **Config endpoints** — written at install, owned by the operator.
- **Advertised endpoints** — pushed by the server over `/link`, persisted to `endpoints.json` in
  `config.StateDir()` with the same temp-file-then-rename durability and `0600` mode as
  `config.SaveServerKeyRotation`. `StateDir()` is `/var/lib/cb-agent`, already inside the unit's
  `ReadWritePaths=`, so `ProtectSystem=strict` needs no change. A missing file is not an error; an
  *unparseable* one is logged and treated as empty, so a corrupt advertised set degrades to
  config-only rather than preventing the agent from starting.

The walk is config endpoints in declared order, then advertised ones. **Advertised endpoints are
appended only.** They never remove, replace, or reorder a config endpoint. This is the property
that makes it impossible for a server-side mistake to strand a fleet: the path an agent was
installed with is always still in its list.

### `Config.TLSPin` becomes a normalization input

§1's per-endpoint trust is a lie unless every dial path stops reading the global pin.
`dialAndHandshake` currently calls `tlsdial.NewDialer(opts.Config.TLSPin)` (`link.go:434`), and
`update.Download` and `internal/enroll` read the same field. All three take the *endpoint* they
are dialing and derive the pin from it. After this change `Config.TLSPin` and `Config.ServerURL`
exist only to be folded into `Endpoints` by `config.Load`; a test asserts no other package reads
either field. Without that invariant the most likely bug is silently applying endpoint #1's pin to
endpoint #3 — a failure that looks like an unreachable relay, not like a trust bug.

## 2. Agent selection state machine

**One connection attempt is one walk of the list.** `runOnce` already loops key candidates;
endpoints become the outer loop and keys the inner. One walk remains one `runOnce`, so
`backoffState` and `stabilityWindow` keep their present meaning — the 1s→5m progression counts
walks, not endpoints.

**Per-endpoint dial deadline (~5s), and it is mandatory.** `handshakeTimeout` only bounds the read
after a socket exists. A routable-but-black-holed address — what a moved server leaves behind —
hangs in TCP connect for the OS default of roughly two minutes, and the walk never reaches the
working endpoint below it. Each endpoint gets its own dial context.

**Failure classification decides whether to continue the walk:**

| Failure | Action |
|---|---|
| Dial failure | Try next **endpoint**. Do not try the remaining keys — a key candidate cannot fix a socket that never opened, and trying would pay the dial timeout once per key |
| Handshake failure | Try the next key **on this endpoint** (a fresh dial: a websocket cannot be reused after a failed handshake). Once every candidate key has failed, next endpoint |
| Rejected `hello.ack` | **Stop.** A server answered and refused on policy; other addresses reach the same server |

The stop rule is safe precisely because `hello.ack` only arrives *after* Noise succeeded — anyone
who can send one already holds the server's static key. It must not be relaxed to trigger on any
earlier signal.

**Latency budget, stated because it is what "offline" means to an operator.** Worst case per walk
is `n_endpoints × n_keys × (5s dial + 10s handshake)`. With the cap below and a rotation in
progress that is 8 × 2 × 15s = 4 minutes before backoff even begins, which is unacceptable, so:
**the endpoint list is capped at 8 total** (validated server-side, §3) and the realistic
no-rotation case is 8 × 15s = 2 minutes. An operator-visible consequence worth documenting in
`docs/`: adding unreachable endpoints costs reconnect latency for every agent.

**Demotion with decay.** State tracks consecutive failures per endpoint. After `N = 3` consecutive
failures an endpoint is probed only every `K = 6`th walk. A permanently dead address then costs one
dial timeout occasionally instead of one on every reconnect; it self-heals the moment it answers;
and because it is never removed, an agent still cannot be stranded. `N` and `K` are constants, not
config — nobody can tune what they cannot observe.

**Order is always top-down, and selection is per-connection.** `last_good` is persisted and
reported but deliberately does not reorder the walk. LAN therefore wins over relay *at connect
time*; it does not win continuously, because the walk only runs inside `runOnce`. An agent that
failed over to the relay would otherwise sit there until the link happened to drop — possibly for
weeks.

**Bounded preference re-walk.** While connected on an endpoint that is not the highest-ranked one,
the agent probes the endpoints above it once an hour. On a successful handshake it closes the
current connection and lets `Run`'s normal reconnect land on the better path. Bounded on purpose:
one probe per hour, only upward, and only while a strictly better endpoint exists — so it cannot
flap, and a connected agent on its top endpoint does no extra work at all. This is what makes "LAN
stays preferred over relay" true rather than aspirational.

**Other consumers.** `enroll` walks the same list. `update.Download` takes the endpoint the link is
currently connected on rather than re-deriving from config — the binary comes from the path already
proven to work, with that endpoint's pin.

## 3. Server side

**New setting `agent_endpoints`** on `AppSettings`, ordered, each entry `{url, label, tls}` where
`tls` is `pinned` or `public`. A migration in `apps/backend/migrations/versions/` adds the column
with an empty default. The pin is never stored: it is computed at render time from the live nginx
certificate via `_live_nginx_cert_pem` (added in `220c141b`), so it cannot go stale against a
regenerated cert. Every `pinned` endpoint receives that same pin — correct for direct, overlay, and
SNI-passthrough relay addresses alike. `public` covers an endpoint fronted by a terminator holding
its own certificate. `label` is display-only and never reaches `agent.toml`.

**Validation at the settings boundary.** This is the one setting that reroutes the entire fleet's
control channel and is rendered into a shell script, so it is validated hard: scheme in
`{https, http}`; no userinfo, path, query or fragment; host is a hostname or IP literal, punycode
rejected in favor of an explicit ASCII form; per-URL length cap; duplicates rejected; **at most 8
entries** (see §2's latency budget). A change writes an **audit-log entry** naming the before and
after lists — the existing audit log has no record of fleet-wide routing changes today, and this is
the setting that most needs one.

**Both render paths stop using the request URL.** `build_install_command` and
`get_install_agent_script` render from the setting. Three consequences:

- The two routes become structurally incapable of disagreeing. The digest-mismatch failure mode is
  eliminated as a class rather than patched where it surfaced.
- The script no longer depends on which hostname the admin browsed to, so the digest is stable
  across admins and sessions — which is what makes "compare this digest" a real instruction rather
  than theater.
- An agent's persisted config stops being an accident of the operator's browser history.

**One deliberate exception:** the script's `CB_BINARY_URL` keeps the request-derived URL. That
address is proven reachable from the operator's shell — it is how they just fetched the script.
Request derivation is not wrong everywhere; it is wrong as a source of persistent config. Reachable
is not the same as *verified*, which is why §4 pins that fetch.

**Disclosure surface.** `/install-agent.sh` has no auth dependency (`main.py:2085`) and must not
gain one — it has to be `curl`-able by a host that has no credentials yet. Today it discloses one
address the requester already used to reach it. After this change it publishes the operator's whole
address topology: LAN ranges, overlay hostnames, and eventually relay endpoints, to any
unauthenticated client that can reach the server. On a LAN-only deployment that is close to
harmless; on anything exposed it is real. Recorded here as an accepted consequence, with the
mitigation deliberately deferred to the install-token subsystem (see **Relationship to the other
subsystems**), which makes the script token-scoped and 404s otherwise without adding auth.

**Seeding.** First run seeds from the detected LAN IP (`setup.sh` already computes
`CB_DETECTED_IP`) plus `cfg.fqdn` when set. While the setting is empty the old request-derived
behavior remains as a fallback, so nothing breaks before configuration. The fallback is removed one
minor release after this ships; until then a startup log line names any install still relying on it.

**Honesty warning.** The Add Agent panel warns when every endpoint is RFC1918 or loopback: this
install command cannot work off-LAN. A warning, not a block — LAN-only is legitimate, and hard
failure would be wrong.

**Live propagation.** An `endpoint.set` frame over `/link`, modeled directly on `key.rotate`,
pushed on settings change and again on every `hello.ack`. Offline agents pick it up on reconnect.

Three rules govern how an agent applies it:

1. **It is ignored before an accepted `hello.ack`.** Persisted state is never mutated by a frame
   arriving on a connection the server has not yet accepted.
2. **It replaces `endpoints.json` wholesale rather than merging**, so a retired relay address
   disappears from the fleet on the next connect instead of lingering forever.
3. **It never removes the endpoint the link is currently connected on.** That endpoint survives the
   replace and is dropped only after a later connection succeeds on a different one.

Rule 3 is the correction to the obvious version of this mechanism. The wholesale replace is safe
for a LAN agent because "the agent still has its install-time path" is true for it — but it is
false for exactly the population this subsystem exists to serve. A roaming or CGNAT agent's only
working path *is* an advertised endpoint; its config endpoint is a LAN address three networks ago.
One bad settings save, or an empty-set bug, would take those hosts permanently offline with no
remote recovery. With rule 3 the worst a malformed or hostile `endpoint.set` can do is discard
addresses the agent is not using and could only have learned from the server in the first place.

**Version skew is already safe.** `runOnce`'s inbound frame switch (`link.go:784–881`) has no
`default` arm, so a pre-endpoint agent silently ignores `endpoint.set` and stays connected. That is
currently true by accident; a test locks it, because pushing an unknown frame on every `hello.ack`
to a fleet that has not upgraded yet is otherwise a fleet-wide disconnect on deploy day.

## 4. Install script

`_INSTALL_SCRIPT_TEMPLATE`'s three scalars become a rendered `[[endpoint]]` array.

The config heredoc is currently unquoted (`<<EOF`), so every value passes through the target
shell's expansion on its way to disk. Rendering the TOML server-side and emitting it under a quoted
`<<'EOF'` removes that: no URL can be mangled or expanded by the target's shell.

**Pin the binary fetch.** *Landed ahead of the rest of this design — the bug in the context's
problem (4) is live on the default deployment.* Repairing it with `-k` would have made the
installer work and verify nothing. The script already holds the SPKI pin and curl has taken exactly
that format since 7.39, so every fetch routes through one helper instead:

```sh
if [ -n "${CB_TLS_PIN}" ] && ! curl --pinnedpubkey "sha256//" --version >/dev/null 2>&1; then
  echo "curl here cannot verify this server's certificate:" >&2
  echo "--pinnedpubkey needs curl 7.39 or newer." >&2
  exit 1
fi
cb_curl() {
  if [ -n "${CB_TLS_PIN}" ]; then
    curl -fsSL --insecure --pinnedpubkey "sha256//${CB_TLS_PIN}" "$@"
  else
    curl -fsSL "$@"
  fi
}
```

The command shown in the UI for self-signed mode gains the same flag. `--pinnedpubkey` pins the
leaf's SPKI — the identical check `tlsdial.pinnedTLSConfig` makes — and curl enforces it
independently of `--insecure`, so the pair means "skip the CA chain, require exactly this key"
rather than "trust anything": a mismatched certificate fails with exit 90. Verified against a real
self-signed origin rather than assumed; the tests in §6 are what verify it.

The version guard is there because the failure it replaces is worse than it looks: without it an
old curl aborts partway through with `option --pinnedpubkey: is unknown`, which reads as a broken
installer rather than as an environment the operator can fix.

Three consequences worth stating plainly:

- The default deployment stops shipping an unverified binary download — today it does not merely
  fail to verify, it fails outright with curl exit 60, because the fetch had no `-k` either.
- `sha256sum -c` stops being the *only* thing between `-k` and a MITM'd installer. It becomes a
  second, independent check rather than the sole control — which is what makes it reasonable to
  drop the digest clause from the copied command later (see §7).
- An empty pin keeps system CA trust. `public` installs must not inherit `--insecure` as a side
  effect of this fix, which is why the helper branches at runtime rather than the template
  branching at render time.

The `public` (Let's Encrypt) command form is unchanged: system CA trust already covers it and there
is no pin to give curl.

**Determinism.** The digest is meaningful only if identical settings produce identical bytes. The
setting is ordered, so endpoints render deterministically — but `binary_digest_cases` iterates
`per_arch.items()` in manifest order, which is not guaranteed stable across manifest rewrites.
Sorting it makes the whole script reproducible.

**Stale-digest failure.** The digest now moves whenever the endpoint setting changes, the
certificate is regenerated, the manifest advances, or a key rotation begins. A command pasted into
a runbook therefore fails later as a bare `sha256sum: WARNING: 1 computed checksum did NOT match`,
which reads as an attack rather than as staleness. `/install-agent.sh` accepts an optional
`?d=<expected-digest>` — emitted in the copied command — and answers `409` with an explicit "this
install command is stale, copy a fresh one from Agents → Add Agent" when the current render does
not match. Omitting the parameter keeps today's behavior.

**Reinstall semantics.** A re-run rewrites the config's endpoints — the operator's declared truth —
and leaves `endpoints.json` alone, so server-advertised additions survive an upgrade.

`apps/agent/e2e/test_agent_release_gate.py:821` asserts on the exact `agent.toml` the script writes
and `:836` cross-checks it against the harness's own config; both change in lockstep with the
template. Note that neither *executes* the script's downloads, which is why problem (4) survived
the gate — §6 adds the test that would have caught it.

## 5. Failure modes and observability

| Failure | Behavior |
|---|---|
| Every endpoint unreachable | Existing offline path — spool, backoff, UI offline with spool depth. Unchanged |
| Bad advertised endpoint | Inert. Appended, never replacing the config endpoint that still works |
| `endpoint.set` that drops the live path | Refused for the connected endpoint (§3 rule 3); the agent keeps the path it is on |
| Corrupt `endpoints.json` | Logged, treated as empty. Agent starts on its config endpoints |
| Typo'd setting | Cannot break connected agents (append-only + config root). Produces a bad install command, which is why URL/scheme validation lives at the settings boundary |
| Server TLS cert regenerated | **Not solved here.** See below |

**Named gap: pin rotation.** Regenerating the server's TLS certificate invalidates the pin every
already-installed agent holds. This is pre-existing, but the endpoint model makes it worse in one
specific way: more addresses now share the one pin, so there is no path that survives the
regeneration. A `key.rotate`-style pin rotation is the obvious eventual answer. Recorded, not
solved, and deliberately not assumed away.

What *is* done here, because it costs a line and converts a landmine into a warned-about operation:
the certificates page states how many agents currently pin the live certificate and that
regenerating it disconnects them permanently.

**Observability.** Reporting only the connected endpoint answers "where is this agent" but not "why
can't it reach the relay" — which is the question the relay subsystem will generate on day one. The
agent therefore reports the whole walk result in `hello` and heartbeat: per endpoint, its index in
the list, `last_ok_at`, and the last failure class (dial / handshake / rejected). Addresses are
reported by index rather than by URL, so the payload stays small and bounded by the §3 cap.

Two things this buys: the fleet table from `afbd382b` gains a column showing which path each agent
is on, and the settings page can say "3 of 12 agents can reach `cb.example.com`" next to an
endpoint the operator just added — which is the difference between a debuggable relay and a black
box.

## 6. Testing

**Go unit.** Config back-compat (scalar `server_url` normalizes to one endpoint); no package other
than `config` reads `Config.TLSPin`/`Config.ServerURL`; `endpoints.json` round-trip, atomic write,
`0600` mode, and corrupt-file fallback to config endpoints; walk order; the per-endpoint dial
deadline actually bounding a black-holed address; failure classification (dial skips remaining keys
and moves on, handshake retries keys on the same endpoint, rejected `hello.ack` stops); demotion
decay counters; the bounded preference re-walk fires upward only and not at all when already on the
top endpoint.

**Go unit — the `endpoint.set` invariants**, each named after the property it protects: a config
endpoint can never be removed, reordered, or overridden; the currently-connected endpoint survives
a replace; a frame arriving before an accepted `hello.ack` is ignored; an agent built without
endpoint support ignores the frame and stays connected.

**Python unit.** Byte-identical render from both server routes — the direct regression test for the
digest mismatch; render determinism across manifest orderings; settings validation (scheme,
userinfo, duplicates, the 8-entry cap); the audit-log entry on change; the all-private warning; the
`?d=` stale-digest 409.

**Install-path test for problem (4).** *Landed with the fix.* The gap that let the unverified
binary fetch ship is that nothing executes the script's downloads —
`test_agent_release_gate.py` reads the script's text, and `_write_agent_toml` stands in for the
heredoc. `tests/services/test_agent_install.py` now serves the script's own `cb_curl` helper a real
self-signed HTTPS origin and runs it three ways: the matching pin downloads, a non-matching pin is
refused, and an empty pin still refuses a self-signed certificate (so the fix cannot quietly
downgrade `public` installs). Text-level assertions cover the flags and the curl-version guard.

**E2E.** The existing agent harness extended with a dead first endpoint and a live second: the
agent must connect via the second and report it.

**Retained.** `tests/build/test_nginx_install_agent_route.py` stays as the structural guard that
`/install-agent.sh` reaches the backend with the same identity headers as `/api/`.

## 7. Seamlessness budget

Worth stating explicitly, because "how many steps" is the thing this subsystem is ultimately judged
on and this design deliberately does not change it.

| | Cloudflare Tunnel | Circuit Breaker after this design |
|---|---|---|
| Operator steps | 1 (`cloudflared service install <token>`) | ~5 |
| Context switches | 0 | 2 (shell → UI → shell) |
| Address configuration | none — anycast is baked into the connector | operator must declare a reachable address |
| Approval | none — the token *is* the authorization | pairing code, fingerprint compare, capability pick |

The structural difference is the direction of the dependency: Cloudflare ships a universally
reachable address, so the connector never needs to know where home is. Circuit Breaker asks the
operator to do the anycast edge's job by hand. The endpoint list narrows that honestly — the
address is no longer a coin flip — but only the relay subsystem closes it.

Two changes get the step count to one or two, and neither needs the relay to exist:

1. **`--pinnedpubkey` retires the digest ritual** (§4). Once curl enforces the pin itself, the
   three-clause `curl … && sha256sum -c && sudo sh` command can collapse to one clause with no loss
   of protection. One step and most of the cognitive load, gone.
2. **A single-use install token retires the approval round-trip.** The token is minted by an
   authenticated admin session, is short-lived and single-use, and binds one enrollment; the agent
   presenting it can be auto-approved with the default capability grant, because the admin already
   made the trust decision when they generated the command. §2.4's fingerprint comparison stays as
   the default for tokenless installs, so the paranoid path does not regress, and the anti-race
   control is preserved because a single-use token cannot be raced. The same token scopes
   `/install-agent.sh`, which closes the disclosure surface named in §3.

Both are out of scope here and listed as a subsystem below.

## Non-goals

- **No relay and no tunnel.** `cb-relay`, the SNI-passthrough design, and the server-side tunnel
  client are a separate subsystem. This design only guarantees a relay can be expressed as another
  endpoint and delivered to a live fleet.
- **No overlay detection.** Offering a Tailscale or WireGuard address as a candidate is its own
  subsystem; this one just makes an overlay address representable and reserves `source: detected`
  for it.
- **No changes to enrollment or approval.** The fingerprint-comparison ritual and its rate limiting
  are unchanged; reaching them over an untrusted path is a later subsystem, and so is the
  install-token flow in §7.
- **No pin rotation.** See the named gap in §5.
- **No continuous path re-selection.** The §2 re-walk is bounded and upward-only by design.
- **No NAT traversal of any kind.** Nothing here makes an unreachable server reachable.

## Relationship to the other subsystems

Agreed order: **this design → install-token / one-command install → overlay integration →
`cb-relay` → enrollment over an untrusted path.** The install-token work moves ahead of overlay
because it is small, it is the single largest reduction in operator steps available (§7), and it is
what makes `/install-agent.sh` safe to publish a full topology from.

Overlay comes before relay because it is far less work and independently covers many CGNAT
operators. Note what overlay costs the operator per host: the server joins the tailnet (once) and
every agent host joins it too (once each) — two steps, and the server-side one can be driven to
near zero by detecting `tailscale0` and offering the address as a one-click `source: detected`
endpoint. The agent-side one cannot be folded into the installer: **a tailnet auth key must never
be embedded in `/install-agent.sh`**, which is unauthenticated by construction.

Everything downstream depends on exactly two things from this document: that an endpoint is
expressible with per-endpoint trust, and that `endpoint.set` can deliver one to an already-enrolled
agent. Neither requires a relay to exist to be built or tested.
