# Parked Messages

**Where:** Logs → Parked Messages (`/logs/parked`). Admin only.

Circuit Breaker moves work between its own components over a message bus
(NATS JetStream). Most of that work succeeds on the first attempt. A message
that *cannot* succeed — malformed, or describing something that no longer
exists — would otherwise be redelivered forever, burning cycles and filling
logs while nobody is told. That is a poison-message loop, and the product's
target for it is zero.

So delivery is bounded. When a message exhausts its attempts it is **parked**:
set aside in the `failed_messages` table with its payload, the error that
stopped it, and how many times it was tried. Parking rather than dropping is
the point — bounding delivery alone would trade an infinite loop for a silent
loss, which is worse, because the operator still learns nothing and now the
work is gone too.

## What the page shows

| Column | Meaning |
|---|---|
| Subject | The bus subject the message was published on, with its stream underneath |
| Consumer | Which consumer gave up on it |
| Error | The failure that stopped the last attempt |
| Attempts | How many deliveries were made before it was parked |
| Parked | When it was set aside, and its resolution once it has one |

**The payload is not shown.** It is kept, because that is what makes the work
recoverable, but it is arbitrary bytes from a message that often parked
*because* it was malformed — there is no way to render it that is both honest
and safe. Requeue is how the payload gets used.

## Requeue and discard

**Requeue** publishes the message back to its stream and stamps the row. Use it
once you have fixed whatever caused the failure. If the cause is still there the
message will park again, which is informative rather than harmful.

**Discard** abandons the message. The row stays, because *"this failed and was
retried"* is a different fact from *"this never happened"*, and the difference
matters when the same message parks again.

Neither action deletes the row. Resolved rows are hidden until you tick **Show
resolved**, and the analytics job prunes them after the retention window.

## When the bus is down

Requeue refuses outright if the message bus is disconnected, and says so: the
message stays parked and nothing is sent. This is deliberate. The bus client
*buffers* a publish rather than failing it, so a requeue issued during an outage
would otherwise report success, stamp the row as handled, and drop the message
on the floor. A refusal you can retry is better than a success that lied.

If you see that message, the problem is the bus, not the parked work. Check
that NATS is running and reachable, then requeue again.

## An empty queue is the healthy state

Nothing parks unless the bus has already retried it to exhaustion. An empty
page means no work has been abandoned — not that the feature is broken.
