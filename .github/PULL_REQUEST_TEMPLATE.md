## What this changes

<!-- One or two sentences. -->

## Why

<!-- The problem this solves. Link the issue if there is one. -->

## Release requirements touched

<!-- Any RC-/SEC-/AGT-/SRV-/ACC-/REL-/GOV-/NPM-/EXEC- IDs from specs/1.0.0/.
     Per the change-control rule in 09-release-execution.md, a change after a
     requirement passes must re-run its evidence or record why it still holds.
     Write "none" if this touches no tested surface. -->

## Verification

- [ ] Tests added or updated for the behaviour changed
- [ ] `make lint` passes (ruff + mypy on the backend, eslint on the frontend)
- [ ] `make verify` passes — **if this PR touches `apps/backend/src/app`, run
      `make verify-full` instead**: `make verify` runs with
      `CB_VERIFY_BACKEND=off`, so it skips the backend unit suite entirely
- [ ] Docs updated if user-facing behaviour changed
