# Audit Log

The audit log shows a history of important actions in Circuit Breaker so you can answer three questions quickly:

- What changed?
- Who changed it?
- When did it happen?

---

## What Is Tracked

Common examples include:

- Creating, editing, or deleting inventory items
- Saving topology map layout changes
- Login activity (successful and failed)
- Settings changes
- Category and environment changes

Read-only browsing actions are not logged.

---

## What Each Entry Shows

Each entry records:

| Field | Description |
| --- | --- |
| **Timestamp** | When the action happened (shown in your selected timezone) |
| **Action** | The type of operation — `create`, `update`, `delete`, `login`, etc. |
| **Entity** | The type and name of the affected object (e.g., `Hardware / pve-node-01`) |
| **Actor** | The user or API token that performed the action |
| **Source IP** | The IP address the request originated from |
| **Severity** | `info`, `warn`, or `error` |

---

## Before/After View

For update actions, you can expand entries to compare previous and current values side by side.

---

## The audit view

**Where:** Administration → Audit Log (`/logs/audit`). Admin only.

The audit view shows entries in the `audit` category only. The filters at the
 top of the page — time range, action, actor, entity type, severity, and free
text — all apply to it, and are the same controls the general Logs view uses.

The general **Logs** view at `/logs` shows every category, audit entries
included.

- **Time range** (Last 1h / 24h / 7d / 30d / All time)
- **Actor** (a specific user, or all users)
- **Entity type**
- **Action**
- **Severity**
- **Search by name**

**Export CSV** writes the currently listed entries to a file. The export includes each entry's `log_hash`
alongside the timestamp, severity, action, entity, actor, role at the time, and source IP.

---

## Chain integrity

Audit entries are hash-chained: each entry's stored hash covers the previous
entry's, so altering or deleting an entry breaks every link after it.

The panel above the audit table reports the chain's state on load. When intact
it is a single line naming how many entries were verified. When broken it names
the first failing entry and offers **Repair chain**.

Repair relinks the chain from the first failure onward and appends a repair
record naming the operator and their stated reason. **It does not recover
altered or deleted entries** — a broken chain is evidence, and repairing it
removes the signal without restoring the data. Investigate before repairing.

Because repair is deliberately hard to trigger by accident, it requires typing
`REPAIR_AUDIT_CHAIN` exactly and giving a reason of at least twelve characters.
Both are recorded.

On PostgreSQL, appends are serialised by an advisory lock, so two concurrent writers cannot fork the chain.

If the chain is broken, `POST /api/v1/admin/audit-log/repair-chain` (admin-only) relinks the hashes from the
first failing row onward. It is deliberately awkward to call: the body must carry `authorization` equal to
exactly `REPAIR_AUDIT_CHAIN` plus a `reason` of 12–500 characters. Repair does not restore the original row
content and does not hide the break — it reports every hash it changed and appends a repair event to the log.

Append-only guarantees depend on your database and backup policy; verification only attests that stored entries are consistent with the hash chain.

---

## Retention and Clearing

Individual log entries cannot be edited.

Entries older than the retention period set under **Settings → Security → Audit Log → Retention Period (days)**
are purged automatically each day. The default is 90 days; set it to 0 to disable purging.

Administrators can clear log history when needed. Use this carefully, especially if your environment depends on long-term activity history for audits.
