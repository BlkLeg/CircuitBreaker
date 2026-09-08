# 02 · Inventory transfer and recovery clarity

Status: approved. Depends on plan 00, inventory selector/error contracts in 07, and verified relationship serialization.

## Outcome and location

Settings → System → Data Management distinguishes **Inventory export**, **Inventory import**, and **Full-state backup / offline restore**. Import proceeds through file selection, validation, conflict resolution, preview, explicit confirmation, application, and an honest result. Existing Clear Lab/reset confirmations are not weakened or combined with import.

Existing integration points: frontend `pages/settings/SystemSection.jsx`, `components/settings/BackupSettings.jsx`, `api/client.jsx`; backend `api/admin.py` (`export_backup`, `_insert_rows`, `_restore_entities`, `import_backup`); `docs/backup-restore.md`. Paths under frontend/backend refer to their respective `src/` and `src/app/` roots.

## Minimal contract

- A versioned portable document declares entity/relationship kinds, format version, export timestamp, and explicit exclusions. Include hardware connections and every relationship the format promises to round-trip; exclude secrets unless an existing authorized backup format intentionally covers them.
- Validation returns safe file/schema errors, entity/relationship counts, unresolved references, collisions, and allowed resolution actions. Invalid files do not change inventory.
- **Merge** uses source-to-target ID remapping and explicit identity/conflict decisions, never primary-key equality as proof of identity. The first shipped mode should be the smallest safe supported operation; do not expose restore/replace modes until their distinct semantics and safety tests exist.
- A preview describes create/update/skip operations and relationship changes. Any deletion/replacement requires explicit scope, preview, backup requirements, and confirmation; it must never be implied by “Import.”
- Apply must match the validated file, mode, resolutions, and relevant inventory revision. Use a revalidation/digest or equivalent existing mechanism to reject stale previews; protect retries/double-clicks from duplicate application.
- Prefer one database transaction for supported portable inventory application. Define rollback and terminal outcomes precisely. Do not show partial success if the operation is atomic; do not promise atomicity over external side effects.
- A result reports actual counts, skipped/resolved items, rollback/failure state, and safe diagnostics. Do not invent percentage progress if the backend supplies only validation/apply stages.

No online full-database restore endpoint is part of this plan. The existing offline recovery process stays documented and separate.

## UI boundaries and work packages

Proposed: `components/settings/InventoryTransferPanel.jsx`, focused validation/preview/result children, and a feature-local `useInventoryTransfer.js` state hook. Keep file validation/state separate from rendering; extend existing admin services rather than building another backup subsystem.

- [ ] **T1:** Write round-trip fixtures covering all declared entity/relationship kinds and a foreign inventory with colliding primary keys. Decide supported merge semantics and explicit format compatibility.
- [ ] **T2:** Build the approved step flow with size/type checks, loading/validation failures, editable conflict decisions, preview, confirmation, and result states. Preserve choices when returning to prior steps.
- [ ] **T3:** Implement server-side bounded parsing/schema validation and preview using the same rules as apply. Frontend validation is advisory, not a security boundary.
- [ ] **T4:** Implement source ID remapping, referential validation, authoritative preview recheck, transaction/rollback behavior, and duplicate-submit protection.
- [ ] **T5:** Correct export naming and serialization; display included/excluded data. Link full-state backup and offline recovery instructions.
- [ ] **T6:** Wire real authorized API calls, refresh affected inventory/map query state after success, and show recoverable failures without dropping the chosen file unnecessarily.
- [ ] **T7:** Update portability/backup documentation and migration notes; retain any needed legacy export reader or explicitly reject unsupported versions before mutation.

## Acceptance and tests

- Supported export/import round trips preserve declared fields and relationships; imported IDs cannot overwrite unrelated local records silently.
- Invalid JSON/schema, unsupported versions, oversized files, missing references, ambiguous identity, and unauthorized requests change nothing.
- A preview becomes invalid if relevant inventory changes; the user gets a re-review path.
- Retrying or double-clicking Apply does not duplicate entities. A forced mid-apply failure rolls back according to the stated contract.
- Full-state backup is not mislabeled as portable inventory, and online import is not represented as full restore.
- Destructive controls retain accurate confirmation and backup safeguards. Cancel before application makes no changes.
- End-to-end tests use disposable inventory only. Include theme, keyboard, mobile, and structured error coverage from plans 00/07.

Release only the modes that meet these checks; approval of a mode selector is not permission to ship unsafe choices.
