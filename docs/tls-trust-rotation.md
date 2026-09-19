# Agent TLS Trust Rotation

The TLS pin is how every `cb-agent` verifies the certificate this server
presents. Changing the certificate an install serves is therefore a fleet-wide
operation, and doing it in the wrong order is the one mistake that cannot be
repaired remotely.

**Where:** `POST`/`GET /api/v1/agents/tls-pin/*`. Admin only.

This is a *different* rotation from [Agent Server-Key
Rotation](agent-key-rotation.md), and the two are independent: rotating the
Noise identity key does not rotate TLS trust, and rotating TLS trust does not
rotate the identity key. A change of both is two procedures, not one.

## Why the order matters

`tls_pin` is written into `/etc/circuit-breaker/agent.toml` once, by the
installer, and the agent never rewrites it — the file is root-owned and read-only
to the agent process. That single value gates **all four** of the agent's
connections:

- enrollment,
- the `/link` websocket,
- its reconnect,
- **the update binary download.**

The last one is what makes this severe rather than annoying. An agent stranded
by a certificate change cannot be repaired by pushing it a new binary, because
the download that would carry the fix is verified against the same pin that just
stopped matching. The only recovery is physical: re-run the installer on each
host.

So the certificate is not activated first and reconciled afterwards. The fleet
is told about the new trust policy over the already-authenticated link, the
server waits until every agent confirms it holds it, and only then does the
certificate change. The ordering is enforced, not advised:
`POST /certificates/{id}/activate` **refuses with 409** when activating would
change the trust policy agents verify against and the fleet has not been
prepared for that specific change.

Three things are safe and never refused, because none of them changes what an
agent verifies:

- an install with **no active agents** — there is nobody to strand;
- activating a certificate whose trust policy **matches what is already
  served** (a Let's Encrypt renewal, or re-activating the current
  certificate);
- an install that **serves no certificate yet**, so nothing has been pinned.

Everything else needs a converged rotation *for that certificate*. Rotating to
one certificate and then activating another is refused too — it strands the
fleet exactly as thoroughly as doing nothing would.

## The procedure

1. **Create or import the new certificate.** It is staged, not served: nothing
   changes for the fleet yet.

   ```
   POST /api/v1/certificates
   {"domain": "cb.example.com", "type": "selfsigned", "auto_renew": false}
   ```

2. **Advertise its trust policy as the successor**, using the id from step 1.

   ```
   POST /api/v1/agents/tls-pin/rotate
   {"certificate_id": 42}
   ```

   The successor is pushed immediately to every currently connected agent, and
   re-sent to every agent that reconnects for as long as the rotation is
   running (a **7-day overlap**, matching the server-key rotation's window).
   Only one rotation may be in flight; a second is rejected with 409.

3. **Watch convergence** until nothing is outstanding.

   ```
   GET /api/v1/agents/tls-pin/status
   → {"active": true, "successor_mode": "self_signed",
      "converged": 9, "unconverged": 1, ...}
   ```

   `converged` counts agents that have **confirmed they hold** the successor
   policy — not agents that have used it. Nothing can have used it yet; the old
   certificate is still the one being served. Holding it is what matters,
   because that is what lets an agent accept either leaf across the cutover.

   The status endpoint returns a *fingerprint* of the successor pin, never the
   pin itself, matching the server-key endpoints beside it.

4. **Activate**, once `unconverged` is 0.

   ```
   POST /api/v1/certificates/42/activate
   ```

   Agents reconnect against the new leaf, promote it to their effective
   policy, and the rotation closes automatically.

## Reading the pending list

`GET /api/v1/agents/tls-pin/pending` lists every active agent that has not
confirmed, most recently seen first, so stragglers can be chased by name.

| Bucket | Meaning |
|---|---|
| `current` | Has dialed since the rotation began, but matched the outgoing policy and did not report holding the successor |
| `unseen` | Has not reported a policy at all — either it has not dialed since the rotation began, or it predates this mechanism entirely |

Both buckets block activation, because both describe an agent the cutover would
strand. An agent too old to report readiness cannot be distinguished from one
that never received the advertisement, and treating "did not say" as "is fine"
is exactly the assumption that strands a fleet.

## The Let's Encrypt case

A **renewal** needs no rotation at all. The pin is empty on both sides of a
Let's Encrypt renewal — the agent does ordinary public-CA verification — so
nothing about the agent's trust policy changes when the leaf does.

**Switching between** self-signed and Let's Encrypt does need a rotation, in
either direction, and this is what the `mode` field carries. The two directions
strand a fleet for mirror-image reasons:

- `self_signed` → `public`: the agent holds a pin no publicly-trusted leaf can
  ever match.
- `public` → `self_signed`: the agent holds no pin and does standard
  verification, which a self-signed leaf can never pass.

In both cases the agent's current policy provably cannot verify the successor,
so the advertisement is the only thing that gets it across. A pin-only
advertisement could not express "stop pinning", which is why the rotated unit is
a policy `(mode, pin)` rather than a digest.

## Forcing

```
POST /api/v1/certificates/42/activate?force=true
```

`force=true` activates regardless of convergence. It exists so an operator can
knowingly abandon an agent — a decommissioned host that will never reconnect
should not hold a certificate change hostage — and **not** so the gate can be
skipped when it is inconvenient.

Every forced activation writes a separate audit entry, action
`certificate_activated_forced`, recording how many agents it stranded. It is
audited separately from the activation itself so that "someone knowingly
stranded agents" is findable without reading every activation record.

Agents stranded by a forced activation are not recoverable remotely. See below.

## Recovery

An agent whose pin no longer matches the served certificate must be repaired on
the host. Re-run the installer, which writes a fresh `agent.toml` with the
current pin:

```
curl -fsSL https://cb.example.com/install-agent.sh | sudo sh
```

Fetch the exact command, with this install's current pin and server key
embedded, from **Agents → Add agent** (`GET /api/v1/agents/install-command`).
The existing enrollment survives — the device key in
`/var/lib/cb-agent` is untouched by a reinstall, so the agent reconnects as
itself rather than arriving as a new pending agent.

There is no "cancel rotation" operation. If a rotation was started in error,
simply do not activate: both policies are accepted throughout the overlap, so
the rotation alone locks nobody out. Activating the *currently served*
certificate closes the rotation with no change to what agents trust.
