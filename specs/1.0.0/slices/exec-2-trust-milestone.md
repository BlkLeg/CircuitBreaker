# EXEC-2 — Trust Milestone

**Requirement:** EXEC-02
**Depends on:** EXEC-1; SEC-1 decision

## Implementation sequence

1. Schedule security slices in dependency order: tenant decision; exactly one tenant path; endpoint
   inventory/monitor auth; bootstrap/auth; outbound/dependency safety; content/audit/destructive/scans.
2. Require threat model and security-owner design review before migrations, auth/session changes,
   public allowlist, egress resolver, shared limit storage, audit repair, or destructive APIs merge.
3. Require test-first adversarial cases and a migration/rollout/rollback section in every security PR.
4. Run tenant/database policy tests with production role, endpoint identity matrix, proxy/auth/browser
   tests, real DNS rebinding/shared Redis tests, upload/audit/destructive tests, and complete scanners.
5. Reconcile findings/suppressions with RC-08; user-visible unsupported claims must be removed before
   treating a control as deferred.
6. Freeze a trust candidate and rerun the full security gate after its last relevant change.

## Exit review and done

Security presents SEC-01 through SEC-18 evidence, not aggregate counts. Product confirms tenant/exposure
claims. Done requires all SEC requirements against the trust candidate with no implicit P0 exception;
otherwise later milestones cannot compensate and the release remains NO-GO.
