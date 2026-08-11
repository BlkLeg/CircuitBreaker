# EXEC-8 — RC Soak and Regression Control

**Requirement:** EXEC-08
**Depends on:** EXEC-7

## Procedure

1. Deploy staged RC artifacts in the approved topology/profile with representative users, agents,
   monitoring, discovery, integrations, notifications, retention, and backups.
2. Run the declared soak duration with scheduled dependency/network/process faults and backup/restore
   verification without contaminating the primary measurements.
3. Monitor SLOs, latency/errors, worker/queue/DB, CPU/RAM/disk/WAL, descriptors/tasks, reconnect/spool,
   retention, RPO/RTO, alerts, logs, and support bundles.
4. Record every anomaly, warning, manual intervention, unexpected growth, and user inconsistency.
   Absence of alert is not proof when measurement failed.
5. Classify changes as blocker/regression, evidence-only correction, or forbidden new scope; identify
   invalidated requirements before approval.
6. Rebuild/retest affected artifacts and restart soak when policy or impact requires.

## Done

The final candidate passes duration/objectives with no unresolved regression, unexplained trend, hidden
manual repair, expired exception, or scope addition. Evidence identifies exact promotion digests.
