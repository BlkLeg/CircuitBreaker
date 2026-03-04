# Auto-Discovery (Beta)

Auto-Discovery helps you find devices and services in your network, then add them to Circuit Breaker with review and control.

> **Beta status:** Discovery is available now and actively improving. Use it with care in sensitive environments.

---

## What Discovery Does

- Scans selected network ranges.
- Finds hosts and service signals.
- Places findings into a review queue.
- Lets you approve and merge only what you want.

Nothing is added automatically without your approval.

---

## Discovery Workflow

### 1) Create a scan profile

Use **Scan Profiles** when you want a repeatable scan target.

A profile typically includes:

- A name
- Target range (CIDR)
- Scan method settings
- Schedule options

### 2) Run an ad-hoc scan

Use **Ad-hoc Scan** for one-time checks.

This is useful after changes like:

- New subnet rollout
- Device migration
- Service move

### 3) Review findings

Open the **Review Queue** to inspect discovered items before import.

You can:

- Merge one result at a time
- Bulk merge selected results
- Skip items that are not needed

### 4) Track progress and history

Use **Scan History** to see completed, running, canceled, and failed jobs.

---

## Safety and Good Practice

- Start with a small range first.
- Run scans during low-traffic windows.
- Review every merge carefully.
- Keep recurring scans targeted instead of broad.

If your environment has strict network controls, coordinate scanning windows before first use.

---

## Troubleshooting Basics

- **No results:** verify target range and network reachability.
- **Too many results:** narrow CIDR scope and use more specific profiles.
- **Scan failed:** retry once, then check permissions and environment constraints.
- **Unexpected matches:** keep findings in queue and merge only confirmed assets.

---

## Related Guides

- [Settings](settings.md)
- [Topology Map](topology-map.md)
- [Audit Log](audit-log.md)
