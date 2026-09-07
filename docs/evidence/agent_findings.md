# cb-agent spool durability — findings across four review cycles

Working notes on the `data.ack` commit-on-ack work (`944fa37c` → `4d83558c`). Written
because four consecutive review rounds each found the *same* bug in a new place, and
the recurrence is a more useful finding than any of the four instances.

---

## 1. The one bug, four times

**Shape:** a mechanism whose input is perturbed by the very failure it exists to detect.

The spool has a byte cap and drops oldest-first when it fills. Under commit-on-ack an
unacknowledged frame stays at the spool head, so **at the cap, the in-flight window
*is* the eviction target**. Every version of the in-flight bookkeeping read some
property of that window, and eviction rewrote that property.

| Round | Commit | What the mechanism read | How eviction defeated it | Symptom |
|---|---|---|---|---|
| 1 | `944fa37c` | in-flight tracked as *"N frames past the head"* | eviction moved the head, so a count-based commit discarded never-sent frames | acknowledged commit → **silent data loss** |
| 2 | `51516e5b` | `dropEvicted` reset `ackWaitSince` to now | at the cap it runs every drain tick, so the 45s deadline never elapsed | stall detector **off entirely** |
| 3 | `167d37e8` | deadline = oldest **surviving** entry's `sentAt` | eviction walks all 64 entries in 64 enqueues, so no survivor is ever old | stall detector off above **~1.5 frames/s** |
| 4 | `4d83558c` | correct clock, but check guarded by `len(inflight) == 0` | `drainBurst` prunes *before* the check and refills *after*, so the window is empty at every check | stall detector off when eviction ≥ **drain budget (4/tick)** |

Closed in `38fbcade`: the check now asks `unackedSince` and nothing else.

Each fix moved the dependency one level further out — count → position → per-entry time
→ stretch time — but every version kept *some* dependency on state that eviction
touches. Round 4's clock was finally right and the **guard in front of it** was not.

**The invariant that ends it:** the detector may depend only on facts eviction cannot
change. That is the passage of time since an acknowledgement last released something —
and nothing about the window's contents: not its head, not its ages, not its emptiness.

```go
// The whole condition. Not "and are frames outstanding right now".
func (d *dataFrameSender) ackStallError() error {
	if d.unackedSince.IsZero() { return nil }
	if time.Since(d.unackedSince) < ackStallTimeout { return nil }
	...
}
```

Measured at each round, server reading and pinging but never acknowledging:

```
round 2 code:  deadline pushed out indefinitely at any rate
round 3 code:  1656 observations destroyed, no stall     (60ms deadline, 8 deadlines)
round 4 code:  evict/tick 1,2,3 → fires;  4,5,8,16,64 → never fires
               at evict/tick=64: 25,600 observations destroyed, no stall
round 5 code:  fires at every rate tested (1×, 1× budget, 4× budget)
```

---

## 2. Why it took four rounds

Worth more than the fix itself. Each of these is a process defect, not a knowledge gap.

**The regression tests encoded the previous instance, not the invariant.** Round 2's
test asserted "eviction may move the deadline, but not to now" — which *pinned the very
weakness* round 3 was found for. A test written against the mechanism ("eviction never
moves the deadline at all") would have failed round 3's code on the day it was written.

**The test fixtures drained as fast as they enqueued.** Round 3's fast-producer test
used one `perTick` constant for both the producer and `drainBurst`, so the window never
emptied and round 4's failure mode was unreachable by construction. Production's drain
is *paced* (`drainFramesPerTick = 4` per 100ms tick) and the producer is not. **Fixtures
that use the production constants find things fixtures that pick their own numbers
cannot.**

**Rate was never swept.** Rounds 2–4 each reasoned correctly about the state machine
and never asked "at what producer rate does this stop holding?" Every one of the three
had a rate threshold; each threshold was found only by someone sweeping it. Any fix
whose correctness depends on a rate must be *tested across* that rate, not at one
convenient point.

**Each round re-read the code it had just changed, not the whole path.** The four bugs
sit in four different places: the commit arithmetic, the eviction hook, the deadline
derivation, the guard. Round 4's diff touched the clock and left the guard unexamined
because the guard had not changed.

**Confident prose made the code look settled.** Every round shipped a comment
explaining, accurately and at length, why the *previous* version was wrong. That reads
as evidence the current one is right. It is not. A comment about a past bug says
nothing about the present one, and its fluency actively discourages the next reader
from re-deriving the invariant.

**What actually worked, every time:** an independent reviewer that (a) ported the new
regression test back to the pre-fix commit to confirm it fails there, and (b) wrote its
*own* probe from the invariant rather than trusting the shipped test. Both halves
mattered — the shipped tests were real regression tests and still missed the next
instance.

---

## 3. Checklist for the next mechanism like this

1. **Name the input the fault perturbs.** If a detector reads state the failure mode
   rewrites, remove the dependency; do not compensate for it. Write that sentence down
   in the code.
2. **Test the invariant first, the instance second.** One test that pins the rule
   ("eviction never moves the deadline"), then a behavioural test at production
   constants.
3. **Sweep the rate.** Never validate a rate-sensitive fix at a single rate. Run it at
   1×, at the production budget, and well above it.
4. **Use the production constants in fixtures.** A test that picks its own drain budget
   is testing a system that does not ship.
5. **Re-read the whole path each round, including the parts the diff did not touch.**
   The guard, the caller, the early returns.
6. **Never batch a durability write with its log line.** Rate-limit the line; write the
   record through. "Live surfaces read the in-memory copy so nothing is observable" is
   an argument about the running process and says nothing about a restart — and restart
   is exactly what the operator does after fixing the underlying fault.
7. **Never branch control flow on operator-facing prose.** Persist a machine code; keep
   the sentence as display copy.
8. **Verify rendered operator output against the docs**, by rendering it. Both were
   wrong in ways reading the format string did not reveal.

---

## 4. The other findings (reporting and durability)

Not the recurring bug, but the same theme: **a loss that is real but invisible, or
reported wrongly, is the failure this whole effort exists to end.**

- **Batched persist lost counts outright** (`167d37e8`). `RecordDestroyed` threw its
  `persistEvictionsLocked` in with its rate-limited log line. Measured: **1 of 25**
  destroyed observations survived a restart. Worse, the cumulative total then *decreased*,
  and `agent_registry.py` reads any decrease as the state directory having been
  recreated — writing a permanent audit event making a confidently wrong claim about
  data loss, on top of real data loss. Fixed in `4d83558c`.
- **Confidently wrong remedies.** `cb-agent status` and the fleet view told every
  operator to raise `spool_cap_bytes`. The same counter also records observations the
  spool could not *write* — a full disk, a read-only `/var` — where that advice cannot
  work. Both surfaces now name the cause that actually applied and withhold the remedy
  that cannot help.
- **The batched loss line named the wrong end of the hole.** It printed the triggering
  frame's timestamp — the *newest* of the batch — followed by `..`, which reads as
  "the gap starts here" when the gap *ends* there.
- **`t.Cleanup` is LIFO.** A spool close registered *after* `stopDaemonState` ran
  *before* it, so the goroutines still writing to the spool were stopped second — the
  opposite of what the comment claimed. Harmless only because `Spool.Close` was a no-op.

---

## 5. Carried forward

**Closed in `38fbcade`:**

- `persistEvictionsLocked` now fsyncs the file and its directory before and
  after the rename, as `appendLine` already did. The audit record is no longer
  less durable than the queue it audits.
- `agent_registry.py`'s counter-reset event now means "the record went
  backwards" rather than asserting a recreated state directory. An agent whose
  state directory is read-only cannot persist the record *because* that is what
  is destroying its observations, so its total legitimately goes backwards on
  restart with nothing having been recreated.
- `printSpoolLossCause` switches on `last_destroyed_cause`, a machine code.
  `CapEvictionReason` is display copy again and safe to reword.
- A persist failure is reported when the run of failures begins, not only when
  the next log window opens.

**Still open:**

- `TestOnCapabilitiesSet_DisablingLocalDiscoveryCancelsInFlightWorkAndStopsFutureWork`
  fails under 16-way CPU saturation. Pre-existing — reproduces at `167d37e8`
  and earlier — and unrelated to any of this. Untriaged.
- `make verify` runs with `CB_VERIFY_BACKEND=off`, so the pre-push gate does not
  cover the backend suite. `make verify-full` does, at roughly double the
  runtime. Worth knowing when a change touches both sides of the agent link.
