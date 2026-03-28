# Status Pages

Status Pages let you publish a public-facing status board for the services you run, backed by your Circuit Breaker monitor data.

> **Note:** Status Pages is in active development. Expanded dashboard controls and publishing features are coming in future releases.

---

## Concepts

| Concept | Description |
|---|---|
| **Status Page** | A named, URL-accessible board with an overall health summary and one or more monitor groups |
| **Group** | A labeled section within a page that contains monitors (e.g. `Core Services`, `Storage`, `Network`) |
| **Monitor** | An individual service or endpoint tracked for uptime and availability |
| **Public / Private** | A page can be public (accessible without login) or private (login required) |

---

## Creating a Status Page

1. Open **Status Pages**.
2. Click **+ New Page**.
3. Enter:
   - **Page Name** — displayed as the title of the status board
   - **Slug** — URL-safe identifier; the page will be accessible at `/status/<slug>`
4. Save.

---

## Managing Groups

After selecting a page from the left sidebar:

1. The right panel shows the **Group Builder**.
2. Add a group by clicking **+ Add Group** and giving it a name.
3. Assign monitors to a group.
4. Delete a group by clicking the delete control next to it.

Groups are displayed as sections on the public status page.

---

## Making a Page Public

By default, new pages are private.

To share a page publicly:

1. Select the page in the left sidebar.
2. Toggle the **Public** switch in the share bar at the top.
3. Copy the URL displayed in the share bar and share it with your audience.

The public URL format is:

```
https://<your-circuit-breaker-host>/status/<slug>
```

Private pages return a 403 to unauthenticated visitors.

---

## Public Status Page Layout

The public page shows:

- **Overall status banner** — `All Systems Operational`, `Partial Outage`, or `Major Outage`
- **Monitor groups** — each group lists its monitors with current status, 7-day uptime, 30-day uptime, and last-checked time
- **Recent Incidents** — status-change events from the past 30 days

---

## Status Values

| Status | Meaning |
|---|---|
| **UP** | Monitor is responding normally |
| **DOWN** | Monitor is not responding |
| **MAINTENANCE** | Monitor is in a scheduled maintenance window |
| **PENDING** | No check has run yet |

---

## Deleting a Status Page

Click **Delete** next to the page name in the left sidebar. Deleting a page also removes all its groups.

---

## Related Guides

- [Webhooks & Notifications](integrations-webhooks-notifications.md) — route status-change events to Slack, Discord, and more
- [Settings](settings.md) — system configuration
- [Deployment & Security](deployment-security.md) — securing your Circuit Breaker installation
