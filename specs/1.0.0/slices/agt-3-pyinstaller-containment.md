# AGT-3 — PyInstaller Runtime Containment

**Requirement:** AGT-11
**Priority:** P0
**Issue:** #101

## Primary files

- `scripts/build_native_release.py`
- `deploy/systemd/circuitbreaker-backend.service`, worker units, `deploy/setup.sh`
- Native upgrade/uninstall and health-check scripts

## Build sequence

1. Reproduce normal exit and crash-loop `_MEI*` accumulation; measure ownership, lifetime, and disk use.
2. Select a dedicated application-owned runtime/extraction parent with restrictive permissions,
   filesystem requirements, cleanup ownership marker, and explicit capacity budget.
3. Configure the PyInstaller runtime directory in package build/service units. Prevent concurrent
   service instances from sharing or deleting active extraction state.
4. Implement bounded cleanup that matches Circuit Breaker ownership, age, and inactive PID/start
   identity. Never glob-delete shared `/tmp` or follow attacker-controlled symlinks.
5. Cover normal exit, SIGKILL loop, reboot, concurrent start, wrong ownership, symlink attack, disk
   full, read-only directory, update, rollback, and uninstall.

## Verification

Use the installed package under its production service account and sandbox. After repeated forced
crashes, disk growth remains within the approved bound, active state survives, stale owned state is
removed, and foreign files are untouched.

## Rollout

The installer creates the directory before service start and upgrades safely from old `/tmp` state.
Old state cleanup must be opt-in and narrowly identified. Done requires ARM64 and x86_64 evidence.
