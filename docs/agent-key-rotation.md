# Agent Server-Key Rotation

The agent server key is the identity key every `cb-agent` authenticates the
server against. Rotating it is a fleet-wide operation with a timed window.

**See also:** [Agent TLS Trust Rotation](tls-trust-rotation.md), for changing
the *certificate* this install serves. The two are independent — rotating the
identity key does not rotate TLS trust, and vice versa — and changing both is
two procedures, not one.

**Where:** Agents page, top panel. Admin only.

## What rotation does

1. The server generates a fresh successor keypair and stores it alongside the
   current one.
2. The successor is pushed immediately to every currently connected agent,
   rather than waiting for each agent's next handshake.
3. For a **7-day overlap**, the server accepts handshakes against either key.
4. When the overlap expires, the successor is promoted and the previous key is
   retired.

Only one rotation may be in flight. Starting a second while an overlap is
running is rejected, and the button is unavailable for the same reason.

## Reading the adoption counts

While a rotation is running the panel reports three numbers:

| Bucket | Meaning |
|---|---|
| Authenticated with successor | Has completed a handshake against the new key since the rotation began |
| Still on current | Has handshaked since the rotation began, but against the outgoing key |
| Not seen since rotation | Has not handshaked at all since the rotation began |

These describe **which key each agent's handshakes have used**. The server has
no visibility into whether an agent's local state directory holds the successor
key — that state is agent-side. An agent in the second bucket will normally pick
the successor up on a subsequent handshake.

**Show agents** lists everything not yet in the first bucket, most recently seen
first, so you can chase the stragglers by name.

## Before the overlap expires

An agent that never handshakes during the overlap window will fail to
authenticate once the previous key is retired and will need re-enrolling. If the
"not seen since rotation" count is non-zero as the window closes, identify those
agents through **Show agents** and either bring them online or plan to
re-enroll them.

## Recovery

There is no "cancel rotation" operation. If a rotation was started in error, the
safest course is to let the overlap run: both keys are accepted throughout, so
no agent is locked out by the rotation itself.
