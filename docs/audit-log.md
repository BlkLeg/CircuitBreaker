# Audit Log

The audit log is an append-only record of every meaningful action taken in Circuit Breaker — by users, by the API, or by the system itself. It is the authoritative answer to *what changed, who changed it, and when*.

---

## What Gets Logged

Every significant mutation produces a log entry, including:

- Creating, editing, or deleting any entity (hardware, compute, service, storage, network, etc.)
- Saving a topology map layout
- Authentication events (successful logins, failed login attempts, token usage)
- Settings changes (timezone, branding, environment variables)
- Category and environment creation, rename, or deletion

Read-only operations (list and detail views) are not logged.

---

## Entry Structure

Each entry records:

| Field | Description |
| --- | --- |
| **Timestamp** | When the action occurred, shown in your local timezone (hover for exact UTC) |
| **Action** | The type of operation — `create`, `update`, `delete`, `login`, etc. |
| **Entity** | The type and name of the affected object (e.g., `Hardware / pve-node-01`) |
| **Actor** | The user or API token that performed the action |
| **Source IP** | The IP address the request originated from |
| **Severity** | `info`, `warning`, or `critical` |

---

## Before / After Diff View

For `update` actions, each entry includes a collapsible **diff view** showing exactly what changed. Expand any entry to see the field-level before and after values side by side. Nothing is summarized — every changed field is shown.

---

## Filtering & Search

Use the controls at the top of the Logs panel to narrow the view:

- **Entity type** — filter to a specific kind (e.g., show only `Service` entries)
- **Action** — filter by operation type (`create`, `update`, `delete`, etc.)
- **Severity** — filter to `warning` or `critical` entries only
- **Search** — search by entity name to trace the full history of a specific resource

---

## Immutability

The audit log is permanent and append-only. Log entries **cannot be edited or deleted** — not from the UI, and not via the API. This is by design. If you need to document a correction, create a new action (e.g., update the entity) and that update will itself be logged.
