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
| **Severity** | `info`, `warning`, or `critical` |

---

## Before/After View

For update actions, you can expand entries to compare previous and current values side by side.

---

## Filter and Search

Use filters at the top of the page to narrow results:

- **Entity type**
- **Action**
- **Severity**
- **Search by name**

---

## Hash chain and verification

Each audit log entry stores a hash of its content and the previous entry’s hash so entries form a chain. Tampering or reordering breaks the chain. Admins can verify the chain with:

- **API:** `GET /api/v1/admin/audit-log/verify-chain` (admin-only). Returns `valid`, `first_failure_id`, `message`, and `checked_count`. Use this for monitoring or compliance checks.

Append-only guarantees depend on your database and backup policy; verification only attests that stored entries are consistent with the hash chain.

---

## Retention and Clearing

Individual log entries cannot be edited.

Administrators can clear log history when needed. Use this carefully, especially if your environment depends on long-term activity history for audits.
