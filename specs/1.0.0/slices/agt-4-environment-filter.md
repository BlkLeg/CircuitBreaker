# AGT-4 — Environment-Filter Request Correctness

**Requirement:** AGT-12
**Priority:** P0
**Issue:** #101

## Primary files

- `apps/frontend/src/pages/MapPage.jsx`
- `apps/frontend/src/hooks/useMapDataLoad.js`
- Environment settings/API hooks and `apps/backend/src/app/api/environments.py`
- Map/settings frontend tests and backend schema tests

## Build sequence

1. Write failing tests proving a saved name such as `staging` is not sent as integer
   `environment_id` during the interval before environments load.
2. Represent selection internally with an unambiguous state: unresolved saved name, numeric selected
   ID, or unfiltered. Do not coerce arbitrary strings with `Number()` at the request boundary.
3. After environments load, resolve saved names to one numeric ID. Clear or ignore missing/deleted
   names according to the UI contract and prevent a transient malformed fetch.
4. Validate API client parameters before serialization and keep backend integer validation as defense.
5. Cover valid name, deleted name, stale storage, numeric selection, slow/error loading, duplicate
   display names if possible, and unfiltered state in unit and browser tests.

## Verification

```bash
cd apps/frontend && npm test -- --run && npm run lint
```

Browser network assertions must show no string `environment_id` request at any lifecycle point.
Done includes a stable visible filter state and no unnecessary double fetch with malformed input.
