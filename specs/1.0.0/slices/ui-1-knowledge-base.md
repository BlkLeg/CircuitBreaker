# UI-1 — Knowledge Base UI

**Supports:** INC-11
**Depends on:** nothing — this slice adds no backend behaviour
**Spec:** [Missing UIs](../10-missing-uis.md) §4 (§3.1 and §3.3 constrain it)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator-editable OUI and hostname knowledge-base tables a UI and documentation, closing INC-11.

**Architecture:** A new admin-only page component embedded as a Settings tab. Both KB tables share one configurable table component driven by a pair of declarative descriptors, so adding or changing a column happens in data rather than JSX. All CRUD goes through the existing `/api/v1/kb` routes — no backend change in this plan.

**Tech Stack:** React 18, Vite, vitest + @testing-library/react (frontend); FastAPI, SQLAlchemy, pytest (backend, tests only).

**Spec:** `specs/1.0.0/10-missing-uis.md` (§4 is this plan; §3.1 and §3.3 constrain it)

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include these.

- **Every new surface is its own file. Host files gain a registration line, not a feature.** `SettingsPage.jsx` is 1876 lines; it may gain exactly one render line.
- **Editability is dictated by the API, not by taste.** `PUT /kb/oui/{prefix}` accepts only `vendor`, `device_type`, `os_family`. `PUT /kb/hostname/{entry_id}` accepts those plus `match_type`. Identity columns (`prefix`, `pattern`) and `source` are never editable — the API offers no rename.
- **`match_type` is edited via the row modal, never as an inline free-text cell** — it is an enum (`prefix` | `exact` | `contains`) and a free-text cell would let an operator write a value the matcher silently ignores.
- **Pagination is server-driven.** `EntityTable` paginates client-side; the KB routes paginate server-side at `limit ≤ 500`. Wiring them naively caps the table at 500 rows while looking complete.
- **No fetch failure may render as an empty table.** An error state is required and is distinct from "no entries".
- **All KB routes are `require_role("admin")`.** The tab is `adminOnly`.
- **Documentation is a deliverable of this plan, not a follow-up** — INC-11 names the docs gap as part of the finding.

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `apps/frontend/src/api/kb.js` | HTTP surface for `/kb/oui` and `/kb/hostname`. No React, no state. |
| `apps/frontend/src/components/kb/kbTabs.jsx` | The two tab descriptors: columns, editable set, form fields, API binding, identity key. Data, not behaviour. |
| `apps/frontend/src/components/kb/KbTable.jsx` | One tab's body: toolbar, table, load-more, add/edit modal, delete confirm. Configured entirely by a descriptor. |
| `apps/frontend/src/pages/KnowledgeBasePage.jsx` | Tab switcher + page chrome. Thin. |
| `apps/frontend/src/__tests__/kb-api.test.js` | Pins the API module's URLs and params. |
| `apps/frontend/src/__tests__/kb-tabs.test.js` | Pins the editable column sets against what the API accepts. |
| `apps/frontend/src/__tests__/kb-table.test.jsx` | `KbTable` behaviour: load, filter, edit, delete, error, load-more. |
| `apps/frontend/src/__tests__/knowledge-base-page.test.jsx` | Page-level: tab switching, admin gating. |
| `docs/knowledge-base.md` | The missing MkDocs page. |

**Modify**

| File | Change |
|---|---|
| `apps/frontend/src/utils/validation.js` | Add `normalizeMacPrefix` + `formatMacPrefix`. |
| `apps/frontend/src/components/settings/SettingsNav.jsx` | One `SETTINGS_TABS` entry. |
| `apps/frontend/src/pages/SettingsPage.jsx` | One render line, next to the `users` tab line at 1761. |
| `apps/backend/tests/api/test_kb.py` | Add the contract-pin test for what `PUT` accepts. |
| `docs/discovery.md` | Cross-reference the new page. |
| `mkdocs.yml` | Nav entry. |
| `docs/1.0.0-incomplete-features.md` | INC-11 resolution note. |

**Why a shared `KbTable` rather than two tab components:** the two tabs differ only in columns, form fields, identity key, and endpoints — every behaviour (paging, filtering, inline save, delete, export, error handling) is identical. Two copies would mean fixing the pagination constraint twice.

---

## Task 1: MAC prefix normalisation helpers

`KbOuiCreate.validate_prefix` (`apps/backend/src/app/schemas/kb.py:29`) requires **exactly 6 hexadecimal characters** — `001122`, not `00:11:22`. An operator pasting a MAC prefix in the conventional colon form gets a 422. Normalising on input is required, not cosmetic. Display formatting is the inverse.

**Files:**
- Modify: `apps/frontend/src/utils/validation.js`
- Test: `apps/frontend/src/__tests__/validation-mac-prefix.test.js`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `normalizeMacPrefix(input: string) => string` — uppercased, separators stripped, truncated to 6. Does **not** validate.
  - `isValidMacPrefix(input: string) => boolean` — true iff normalising yields exactly 6 hex chars.
  - `formatMacPrefix(prefix: string) => string` — `"001122"` → `"00:11:22"`; returns input unchanged if not 6 hex chars.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/validation-mac-prefix.test.js`:

```javascript
import { describe, expect, it } from 'vitest';
import { normalizeMacPrefix, isValidMacPrefix, formatMacPrefix } from '../utils/validation';

describe('normalizeMacPrefix', () => {
  it('strips colons and uppercases', () => {
    expect(normalizeMacPrefix('b8:27:eb')).toBe('B827EB');
  });

  it('strips hyphens and dots', () => {
    expect(normalizeMacPrefix('b8-27-eb')).toBe('B827EB');
    expect(normalizeMacPrefix('b827.eb')).toBe('B827EB');
  });

  it('truncates a full MAC to its OUI', () => {
    expect(normalizeMacPrefix('B8:27:EB:12:34:56')).toBe('B827EB');
  });

  it('trims surrounding whitespace', () => {
    expect(normalizeMacPrefix('  001122  ')).toBe('001122');
  });

  it('returns empty string for nullish input', () => {
    expect(normalizeMacPrefix('')).toBe('');
    expect(normalizeMacPrefix(null)).toBe('');
    expect(normalizeMacPrefix(undefined)).toBe('');
  });
});

describe('isValidMacPrefix', () => {
  it('accepts six hex characters in any separator style', () => {
    expect(isValidMacPrefix('001122')).toBe(true);
    expect(isValidMacPrefix('b8:27:eb')).toBe(true);
  });

  it('rejects too few characters', () => {
    expect(isValidMacPrefix('0011')).toBe(false);
  });

  it('rejects non-hex characters', () => {
    expect(isValidMacPrefix('00zz22')).toBe(false);
  });

  it('rejects empty input', () => {
    expect(isValidMacPrefix('')).toBe(false);
  });
});

describe('formatMacPrefix', () => {
  it('inserts colons every two characters', () => {
    expect(formatMacPrefix('001122')).toBe('00:11:22');
  });

  it('returns the input unchanged when it is not six hex characters', () => {
    expect(formatMacPrefix('nonsense')).toBe('nonsense');
    expect(formatMacPrefix('')).toBe('');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/validation-mac-prefix.test.js`
Expected: FAIL — `normalizeMacPrefix is not a function` (the import resolves, the export does not exist).

- [ ] **Step 3: Write minimal implementation**

Append to `apps/frontend/src/utils/validation.js`:

```javascript
const MAC_PREFIX_SEPARATORS = /[:\-.\s]/g;
const SIX_HEX = /^[0-9A-F]{6}$/;

/**
 * Reduce any conventional MAC or OUI spelling to the six uppercase hex
 * characters the backend stores. `KbOuiCreate.validate_prefix` rejects
 * anything else with a 422, so operator input is normalised before it is sent.
 */
export function normalizeMacPrefix(input) {
  if (!input) return '';
  return String(input).replace(MAC_PREFIX_SEPARATORS, '').toUpperCase().slice(0, 6);
}

export function isValidMacPrefix(input) {
  return SIX_HEX.test(normalizeMacPrefix(input));
}

/** Display-only inverse of normalizeMacPrefix. Never sent to the API. */
export function formatMacPrefix(prefix) {
  const raw = String(prefix ?? '');
  if (!SIX_HEX.test(raw.toUpperCase())) return raw;
  return raw.toUpperCase().match(/.{2}/g).join(':');
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/validation-mac-prefix.test.js`
Expected: PASS — 12 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/utils/validation.js apps/frontend/src/__tests__/validation-mac-prefix.test.js
git commit -m "feat(kb): add MAC prefix normalisation helpers (INC-11)"
```

---

## Task 2: KB API module

**Files:**
- Create: `apps/frontend/src/api/kb.js`
- Test: `apps/frontend/src/__tests__/kb-api.test.js`

**Interfaces:**
- Consumes: the default axios instance from `apps/frontend/src/api/client.jsx`
- Produces:
  - `listOui(params)`, `createOui(body)`, `updateOui(prefix, body)`, `deleteOui(prefix)`, `exportOui()`
  - `listHostname(params)`, `createHostname(body)`, `updateHostname(id, body)`, `deleteHostname(id)`, `exportHostname()`
  - All return the axios promise; callers read `res.data`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/kb-api.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  },
}));

import client from '../api/client.jsx';
import * as kb from '../api/kb';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('kb api module', () => {
  it('lists OUI entries with params', () => {
    kb.listOui({ source: 'learned', offset: 0, limit: 100 });
    expect(client.get).toHaveBeenCalledWith('/kb/oui', {
      params: { source: 'learned', offset: 0, limit: 100 },
    });
  });

  it('updates an OUI entry by prefix, not by id', () => {
    kb.updateOui('001122', { vendor: 'Acme' });
    expect(client.put).toHaveBeenCalledWith('/kb/oui/001122', { vendor: 'Acme' });
  });

  it('deletes an OUI entry by prefix', () => {
    kb.deleteOui('001122');
    expect(client.delete).toHaveBeenCalledWith('/kb/oui/001122');
  });

  it('updates a hostname entry by numeric id', () => {
    kb.updateHostname(7, { match_type: 'exact' });
    expect(client.put).toHaveBeenCalledWith('/kb/hostname/7', { match_type: 'exact' });
  });

  it('exports each table from its own export route', () => {
    kb.exportOui();
    expect(client.get).toHaveBeenCalledWith('/kb/oui/export');
    kb.exportHostname();
    expect(client.get).toHaveBeenCalledWith('/kb/hostname/export');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-api.test.js`
Expected: FAIL — cannot resolve `../api/kb`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/api/kb.js`:

```javascript
import client from './client.jsx';

// Knowledge-base lookup tables that feed discovery naming (INC-11).
// Both tables are admin-only (`require_role("admin")` on every route in
// app/api/kb.py) and paginate server-side at limit <= 500.

// ── MAC OUI prefixes ─────────────────────────────────────────────────────────
// Keyed by `prefix` (String(6) primary key), NOT by a surrogate id — there is
// no `id` column on kb_oui.
export const listOui = (params = {}) => client.get('/kb/oui', { params });
export const createOui = (body) => client.post('/kb/oui', body);
export const updateOui = (prefix, body) => client.put(`/kb/oui/${prefix}`, body);
export const deleteOui = (prefix) => client.delete(`/kb/oui/${prefix}`);
export const exportOui = () => client.get('/kb/oui/export');

// ── Hostname patterns ────────────────────────────────────────────────────────
export const listHostname = (params = {}) => client.get('/kb/hostname', { params });
export const createHostname = (body) => client.post('/kb/hostname', body);
export const updateHostname = (id, body) => client.put(`/kb/hostname/${id}`, body);
export const deleteHostname = (id) => client.delete(`/kb/hostname/${id}`);
export const exportHostname = () => client.get('/kb/hostname/export');
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-api.test.js`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/kb.js apps/frontend/src/__tests__/kb-api.test.js
git commit -m "feat(kb): add KB API module (INC-11)"
```

---

## Task 3: Tab descriptors and the API contract pin

The spec requires a test asserting the editable column set matches what `PUT` accepts — "the two drifting apart is INC-17 in miniature". JavaScript and Python cannot share an assertion, so this is done as **two pins that name each other**: the frontend pins its editable set to a literal, and the backend pins `KbOuiUpdate` / `KbHostnameUpdate` field names to the same literal, with each test naming the other file. Either side drifting fails a test that says where to look.

**Files:**
- Create: `apps/frontend/src/components/kb/kbTabs.jsx`
- Test: `apps/frontend/src/__tests__/kb-tabs.test.js`
- Modify: `apps/backend/tests/api/test_kb.py`

**Interfaces:**
- Consumes: `api/kb.js` (Task 2), `normalizeMacPrefix` / `isValidMacPrefix` / `formatMacPrefix` (Task 1)
- Produces: `KB_TABS` — an array of two descriptors, each:
  ```
  {
    key: 'oui' | 'hostname',
    label: string,
    identityKey: 'prefix' | 'id',   // which field becomes EntityTable's row.id
    exportFilename: string,
    columns: Array<{key, label, render?}>,
    editableColumns: string[],       // inline-editable; must equal what PUT accepts
    formFields: Array<FormModal field>,
    validateCreate?: (values) => ({[field]: message}) | null,
    api: {list, create, update, remove, exportAll},
  }
  ```

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/kb-tabs.test.js`:

```javascript
import { describe, expect, it } from 'vitest';
import { KB_TABS } from '../components/kb/kbTabs.jsx';

const byKey = (k) => KB_TABS.find((t) => t.key === k);

describe('KB tab descriptors', () => {
  it('declares exactly the two KB tables', () => {
    expect(KB_TABS.map((t) => t.key)).toEqual(['oui', 'hostname']);
  });

  // CONTRACT PIN — the counterpart lives in
  // apps/backend/tests/api/test_kb.py::test_update_schemas_match_frontend_editable_columns
  // If PUT starts accepting a different set of fields, change BOTH.
  it('OUI inline-editable columns match what PUT /kb/oui/{prefix} accepts', () => {
    expect([...byKey('oui').editableColumns].sort()).toEqual([
      'device_type',
      'os_family',
      'vendor',
    ]);
  });

  it('hostname inline-editable columns exclude match_type', () => {
    // match_type IS accepted by PUT, but is an enum and must be edited through
    // the row modal — EntityTable's EditableCell is a bare text input.
    expect([...byKey('hostname').editableColumns].sort()).toEqual([
      'device_type',
      'os_family',
      'vendor',
    ]);
  });

  it('never marks identity or provenance columns editable', () => {
    for (const tab of KB_TABS) {
      expect(tab.editableColumns).not.toContain('prefix');
      expect(tab.editableColumns).not.toContain('pattern');
      expect(tab.editableColumns).not.toContain('source');
      expect(tab.editableColumns).not.toContain('seen_count');
    }
  });

  it('keys OUI rows by prefix and hostname rows by id', () => {
    expect(byKey('oui').identityKey).toBe('prefix');
    expect(byKey('hostname').identityKey).toBe('id');
  });

  it('rejects an invalid MAC prefix on create', () => {
    const errors = byKey('oui').validateCreate({ prefix: 'zz', vendor: 'Acme' });
    expect(errors).toHaveProperty('prefix');
  });

  it('accepts a colon-formatted MAC prefix on create', () => {
    expect(byKey('oui').validateCreate({ prefix: 'b8:27:eb', vendor: 'Acme' })).toBeNull();
  });

  it('offers exactly the three match types the backend allows', () => {
    const field = byKey('hostname').formFields.find((f) => f.name === 'match_type');
    expect(field.options.map((o) => o.value).sort()).toEqual(['contains', 'exact', 'prefix']);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-tabs.test.js`
Expected: FAIL — cannot resolve `../components/kb/kbTabs.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/kb/kbTabs.jsx`:

```jsx
import React from 'react';
import * as kbApi from '../../api/kb';
import { formatMacPrefix, isValidMacPrefix, normalizeMacPrefix } from '../../utils/validation';

// What the API actually accepts on PUT. Contract-pinned by
// src/__tests__/kb-tabs.test.js and apps/backend/tests/api/test_kb.py.
// `match_type` is accepted by PUT /kb/hostname/{id} but is deliberately absent
// here: it is an enum, and EntityTable's EditableCell is a bare text input, so
// inline editing it would let an operator store a value the matcher ignores.
// It is edited through the row modal instead.
const INLINE_EDITABLE = ['vendor', 'device_type', 'os_family'];

const MATCH_TYPES = [
  { value: 'prefix', label: 'Prefix' },
  { value: 'exact', label: 'Exact' },
  { value: 'contains', label: 'Contains' },
];

function SourceBadge({ source }) {
  const manual = source === 'manual';
  return (
    <span
      className="tw-inline-block tw-rounded-full tw-px-2 tw-py-0.5 tw-text-xs tw-border"
      style={{
        color: manual ? 'var(--color-success, #3fb950)' : 'var(--color-primary, #4493f8)',
        borderColor: 'var(--color-border, #2a323c)',
      }}
    >
      {source}
    </span>
  );
}

function formatTimestamp(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

const dash = (v) => (v == null || v === '' ? '—' : String(v));

export const KB_TABS = [
  {
    key: 'oui',
    label: 'MAC OUI Prefixes',
    identityKey: 'prefix',
    exportFilename: 'kb-oui.json',
    editableColumns: INLINE_EDITABLE,
    columns: [
      { key: 'prefix', label: 'Prefix', render: (v) => formatMacPrefix(v) },
      { key: 'vendor', label: 'Vendor' },
      { key: 'device_type', label: 'Device type', render: dash },
      { key: 'os_family', label: 'OS family', render: dash },
      { key: 'source', label: 'Source', render: (v) => <SourceBadge source={v} /> },
      { key: 'seen_count', label: 'Seen' },
      { key: 'last_seen_at', label: 'Last seen', render: formatTimestamp },
    ],
    formFields: [
      { name: 'prefix', label: 'MAC prefix (OUI)', required: true },
      { name: 'vendor', label: 'Vendor', required: true },
      { name: 'device_type', label: 'Device type' },
      { name: 'os_family', label: 'OS family' },
    ],
    validateCreate: (values) => {
      if (!isValidMacPrefix(values.prefix)) {
        return { prefix: 'Must be six hexadecimal characters, e.g. B8:27:EB or B827EB.' };
      }
      return null;
    },
    // The backend rejects anything but six bare hex characters, so normalise
    // before sending rather than surfacing a 422 for a conventional spelling.
    serializeCreate: (values) => ({
      ...values,
      prefix: normalizeMacPrefix(values.prefix),
    }),
    api: {
      list: kbApi.listOui,
      create: kbApi.createOui,
      update: kbApi.updateOui,
      remove: kbApi.deleteOui,
      exportAll: kbApi.exportOui,
    },
  },
  {
    key: 'hostname',
    label: 'Hostname Patterns',
    identityKey: 'id',
    exportFilename: 'kb-hostname.json',
    editableColumns: INLINE_EDITABLE,
    columns: [
      { key: 'pattern', label: 'Pattern' },
      { key: 'match_type', label: 'Match' },
      { key: 'vendor', label: 'Vendor', render: dash },
      { key: 'device_type', label: 'Device type', render: dash },
      { key: 'os_family', label: 'OS family', render: dash },
      { key: 'source', label: 'Source', render: (v) => <SourceBadge source={v} /> },
      { key: 'seen_count', label: 'Seen' },
      { key: 'last_seen_at', label: 'Last seen', render: formatTimestamp },
    ],
    formFields: [
      { name: 'pattern', label: 'Hostname pattern', required: true },
      { name: 'match_type', label: 'Match type', type: 'select', options: MATCH_TYPES },
      { name: 'vendor', label: 'Vendor' },
      { name: 'device_type', label: 'Device type' },
      { name: 'os_family', label: 'OS family' },
    ],
    validateCreate: (values) =>
      values.pattern && String(values.pattern).trim()
        ? null
        : { pattern: 'Pattern must not be empty.' },
    serializeCreate: (values) => ({ match_type: 'prefix', ...values }),
    api: {
      list: kbApi.listHostname,
      create: kbApi.createHostname,
      update: kbApi.updateHostname,
      remove: kbApi.deleteHostname,
      exportAll: kbApi.exportHostname,
    },
  },
];
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-tabs.test.js`
Expected: PASS — 8 tests.

- [ ] **Step 5: Write the backend half of the contract pin**

Append to `apps/backend/tests/api/test_kb.py`:

```python
# ── contract pin ──────────────────────────────────────────────────────────────


def test_update_schemas_match_frontend_editable_columns():
    """Pin what PUT accepts against the frontend's inline-editable column set.

    The counterpart is apps/frontend/src/__tests__/kb-tabs.test.js. INC-17 was
    exactly this drift — a schema accepting fields nothing stored — so if this
    fails, change BOTH files rather than only this expectation.

    `match_type` is accepted here but is intentionally NOT inline-editable in
    the UI: it is an enum, and the inline cell editor is a bare text input.
    """
    from app.schemas.kb import KbHostnameUpdate, KbOuiUpdate

    assert sorted(KbOuiUpdate.model_fields) == ["device_type", "os_family", "vendor"]
    assert sorted(KbHostnameUpdate.model_fields) == [
        "device_type",
        "match_type",
        "os_family",
        "vendor",
    ]


def test_oui_create_rejects_colon_formatted_prefix():
    """Why the frontend normalises before sending: the API takes bare hex only."""
    import pytest as _pytest
    from pydantic import ValidationError

    from app.schemas.kb import KbOuiCreate

    with _pytest.raises(ValidationError):
        KbOuiCreate(prefix="B8:27:EB", vendor="Raspberry Pi")

    assert KbOuiCreate(prefix="b827eb", vendor="Raspberry Pi").prefix == "B827EB"
```

- [ ] **Step 6: Run the backend tests**

Run: `pytest apps/backend/tests/api/test_kb.py -v`
Expected: PASS — the existing suite plus the two new tests.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/kb/kbTabs.jsx \
        apps/frontend/src/__tests__/kb-tabs.test.js \
        apps/backend/tests/api/test_kb.py
git commit -m "feat(kb): add tab descriptors with API contract pins (INC-11)"
```

---

## Task 4: KbTable component

The behavioural core. Server-driven paging, honest filtering, honest errors.

**Files:**
- Create: `apps/frontend/src/components/kb/KbTable.jsx`
- Test: `apps/frontend/src/__tests__/kb-table.test.jsx`

**Interfaces:**
- Consumes: a descriptor from `KB_TABS` (Task 3); `EntityTable`, `FormModal`, `ConfirmDialog`, `SkeletonTable`, `useToast` from existing components
- Produces: `<KbTable tab={descriptor} />` — default export

**Behaviour contract:**
- Fetches `limit: 100, offset: 0` on mount and whenever the source filter changes.
- "Load more" appends the next 100 and is hidden once a short page comes back.
- The text filter filters **loaded rows only**; when more rows exist unloaded, it says so.
- A failed fetch renders an error with Retry — never an empty table.
- Rows are normalised so `row.id = row[tab.identityKey]`, because `EntityTable` hard-codes `row.id` for React keys, inline-edit identity, and `onDelete(row.id)` — and `kb_oui` has no `id` column.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/kb-table.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../components/EntityTable', () => ({
  default: ({ data, onDelete, onCellSave, editableColumns }) => (
    <div data-testid="entity-table" data-editable={(editableColumns || []).join(',')}>
      {data.map((row) => (
        <div key={row.id} data-testid={`row-${row.id}`}>
          <span>{row.vendor}</span>
          <button onClick={() => onDelete(row.id)}>Delete {row.id}</button>
          <button onClick={() => onCellSave(row, 'vendor', 'Edited Vendor')}>Edit {row.id}</button>
        </div>
      ))}
    </div>
  ),
}));

import KbTable from '../components/kb/KbTable.jsx';

function makeTab(overrides = {}) {
  return {
    key: 'oui',
    label: 'MAC OUI Prefixes',
    identityKey: 'prefix',
    exportFilename: 'kb-oui.json',
    editableColumns: ['vendor', 'device_type', 'os_family'],
    columns: [{ key: 'vendor', label: 'Vendor' }],
    formFields: [{ name: 'prefix', label: 'Prefix', required: true }],
    validateCreate: () => null,
    serializeCreate: (v) => v,
    api: {
      list: vi.fn(),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      remove: vi.fn(() => Promise.resolve({ data: null })),
      exportAll: vi.fn(() => Promise.resolve({ data: {} })),
    },
    ...overrides,
  };
}

const row = (prefix, vendor) => ({
  prefix,
  vendor,
  device_type: null,
  os_family: null,
  source: 'learned',
  seen_count: 3,
  last_seen_at: '2026-08-24T10:00:00Z',
});

beforeEach(() => vi.clearAllMocks());

describe('KbTable', () => {
  it('keys rows by the descriptor identity key, not by a missing id', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);

    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());
  });

  it('requests the first server-side page on mount', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [] });

    render(<KbTable tab={tab} />);

    await waitFor(() =>
      expect(tab.api.list).toHaveBeenCalledWith({ offset: 0, limit: 100 })
    );
  });

  it('sends the source filter as a query param and refetches from offset 0', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(tab.api.list).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'manual' } });

    await waitFor(() =>
      expect(tab.api.list).toHaveBeenLastCalledWith({ offset: 0, limit: 100, source: 'manual' })
    );
  });

  it('loads the next server-side page and appends it', async () => {
    const tab = makeTab();
    const first = Array.from({ length: 100 }, (_, i) =>
      row(String(i).padStart(6, '0'), `Vendor ${i}`)
    );
    tab.api.list
      .mockResolvedValueOnce({ data: first })
      .mockResolvedValueOnce({ data: [row('FFFFFF', 'Last Vendor')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-000000')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /load more/i }));

    await waitFor(() =>
      expect(tab.api.list).toHaveBeenLastCalledWith({ offset: 100, limit: 100 })
    );
    await waitFor(() => expect(screen.getByTestId('row-FFFFFF')).toBeInTheDocument());
    expect(screen.getByTestId('row-000000')).toBeInTheDocument();
  });

  it('hides Load more once a short page comes back', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());

    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();
  });

  it('renders an error with retry instead of an empty table when the fetch fails', async () => {
    const tab = makeTab();
    tab.api.list.mockRejectedValue(new Error('boom'));

    render(<KbTable tab={tab} />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByTestId('entity-table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('says the text filter only covers loaded entries when more remain', async () => {
    const tab = makeTab();
    const first = Array.from({ length: 100 }, (_, i) =>
      row(String(i).padStart(6, '0'), `Vendor ${i}`)
    );
    tab.api.list.mockResolvedValue({ data: first });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-000000')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Filter loaded entries'), {
      target: { value: 'Vendor 1' },
    });

    expect(screen.getByText(/load more to search further/i)).toBeInTheDocument();
  });

  it('saves an inline edit through the descriptor update call', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Edit 001122' }));

    await waitFor(() =>
      expect(tab.api.update).toHaveBeenCalledWith('001122', { vendor: 'Edited Vendor' })
    );
  });

  it('deletes only after the confirmation is accepted', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);
    await waitFor(() => expect(screen.getByTestId('row-001122')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Delete 001122' }));
    expect(tab.api.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    await waitFor(() => expect(tab.api.remove).toHaveBeenCalledWith('001122'));
  });

  it('passes only the descriptor editable columns to the table', async () => {
    const tab = makeTab();
    tab.api.list.mockResolvedValue({ data: [row('001122', 'Acme')] });

    render(<KbTable tab={tab} />);

    await waitFor(() =>
      expect(screen.getByTestId('entity-table')).toHaveAttribute(
        'data-editable',
        'vendor,device_type,os_family'
      )
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-table.test.jsx`
Expected: FAIL — cannot resolve `../components/kb/KbTable.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/kb/KbTable.jsx`:

```jsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';
import { useToast } from '../common/Toast';

const PAGE_SIZE = 100;

/**
 * One KB table (OUI or hostname), driven entirely by a KB_TABS descriptor.
 *
 * Paging is server-side: the KB routes cap `limit` at 500, while EntityTable
 * paginates client-side over whatever it is handed. Handing it one unbounded
 * fetch would silently cap the view while looking complete, so pages are
 * fetched explicitly and EntityTable's own page size is set to the fetch size
 * so the two do not double-paginate.
 */
function KbTable({ tab }) {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [source, setSource] = useState('');
  const [query, setQuery] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formApiErrors, setFormApiErrors] = useState({});
  const [confirmTarget, setConfirmTarget] = useState(null);

  const buildParams = useCallback(
    (offset) => {
      const params = { offset, limit: PAGE_SIZE };
      if (source) params.source = source;
      return params;
    },
    [source]
  );

  // EntityTable hard-codes row.id for React keys, inline-edit identity and
  // onDelete(row.id). kb_oui has no id column — its primary key is `prefix` —
  // so identity is projected onto `id` here. For hostname rows this is a no-op.
  const withIdentity = useCallback(
    (list) => list.map((r) => ({ ...r, id: r[tab.identityKey] })),
    [tab.identityKey]
  );

  const fetchFirstPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await tab.api.list(buildParams(0));
      const data = res.data || [];
      setRows(withIdentity(data));
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      setError(err?.userMessage || err?.message || 'Failed to load entries.');
    } finally {
      setLoading(false);
    }
  }, [tab, buildParams, withIdentity]);

  useEffect(() => {
    fetchFirstPage();
  }, [fetchFirstPage]);

  const loadMore = useCallback(async () => {
    try {
      const res = await tab.api.list(buildParams(rows.length));
      const data = res.data || [];
      setRows((prev) => [...prev, ...withIdentity(data)]);
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      toast.error(err?.userMessage || 'Failed to load more entries.');
    }
  }, [tab, buildParams, rows.length, withIdentity, toast]);

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      tab.columns.some((c) => String(r[c.key] ?? '').toLowerCase().includes(q))
    );
  }, [rows, query, tab.columns]);

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      try {
        await tab.api.update(row[tab.identityKey], { [columnKey]: value });
        toast.success('Saved.');
        fetchFirstPage();
      } catch (err) {
        toast.error(err?.userMessage || 'Save failed.');
      }
    },
    [tab, toast, fetchFirstPage]
  );

  const handleCreate = useCallback(
    async (values) => {
      const validationErrors = tab.validateCreate ? tab.validateCreate(values) : null;
      if (validationErrors) {
        setFormApiErrors(validationErrors);
        return;
      }
      try {
        const body = tab.serializeCreate ? tab.serializeCreate(values) : values;
        await tab.api.create(body);
        toast.success('Entry added.');
        setShowForm(false);
        setFormApiErrors({});
        fetchFirstPage();
      } catch (err) {
        toast.error(err?.userMessage || 'Could not add entry.');
      }
    },
    [tab, toast, fetchFirstPage]
  );

  const handleDeleteConfirmed = useCallback(async () => {
    const target = confirmTarget;
    setConfirmTarget(null);
    if (target == null) return;
    try {
      await tab.api.remove(target);
      toast.success('Entry removed.');
      fetchFirstPage();
    } catch (err) {
      toast.error(err?.userMessage || 'Could not remove entry.');
    }
  }, [confirmTarget, tab, toast, fetchFirstPage]);

  const handleExport = useCallback(async () => {
    try {
      const res = await tab.api.exportAll();
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = tab.exportFilename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err?.userMessage || 'Export failed.');
    }
  }, [tab, toast]);

  const filtering = query.trim().length > 0;

  return (
    <div>
      <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-3 tw-mb-3">
        <label className="tw-text-sm" htmlFor={`kb-source-${tab.key}`}>
          Source
        </label>
        <select
          id={`kb-source-${tab.key}`}
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="btn btn-sm"
        >
          <option value="">All</option>
          <option value="learned">Learned</option>
          <option value="manual">Manual</option>
        </select>

        <label className="tw-sr-only" htmlFor={`kb-query-${tab.key}`}>
          Filter loaded entries
        </label>
        <input
          id={`kb-query-${tab.key}`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter loaded entries…"
          className="btn btn-sm"
        />

        <div className="tw-ml-auto tw-flex tw-gap-2">
          <button type="button" className="btn btn-sm" onClick={handleExport}>
            Export JSON
          </button>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowForm(true)}>
            + Add entry
          </button>
        </div>
      </div>

      {error ? (
        <div role="alert" className="tw-p-4 tw-border tw-rounded">
          <p>{error}</p>
          <button type="button" className="btn btn-sm" onClick={fetchFirstPage}>
            Retry
          </button>
        </div>
      ) : loading ? (
        <SkeletonTable />
      ) : (
        <>
          <EntityTable
            columns={tab.columns}
            data={visibleRows}
            editableColumns={tab.editableColumns}
            onCellSave={handleCellSave}
            onDelete={(id) => setConfirmTarget(id)}
            defaultPageSize={PAGE_SIZE}
          />
          <div className="tw-flex tw-items-center tw-gap-3 tw-mt-3 tw-text-sm">
            <span className="tw-opacity-70">
              {filtering
                ? `${visibleRows.length} of ${rows.length} loaded entries`
                : `${rows.length} loaded, highest seen-count first`}
            </span>
            {filtering && hasMore && (
              <span className="tw-opacity-70">Load more to search further.</span>
            )}
            {hasMore && (
              <button type="button" className="btn btn-sm tw-ml-auto" onClick={loadMore}>
                Load more
              </button>
            )}
          </div>
        </>
      )}

      <FormModal
        open={showForm}
        title={`Add ${tab.label.replace(/s$/, '')}`}
        fields={tab.formFields}
        initialValues={{}}
        apiErrors={formApiErrors}
        onSubmit={handleCreate}
        onClose={() => {
          setShowForm(false);
          setFormApiErrors({});
        }}
      />

      <ConfirmDialog
        open={confirmTarget != null}
        message="Remove this knowledge-base entry? Discovery will stop using it for naming."
        onConfirm={handleDeleteConfirmed}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}

KbTable.propTypes = {
  tab: PropTypes.object.isRequired,
};

export default KbTable;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-table.test.jsx`
Expected: PASS — 10 tests.

If the delete test fails on the button name, check `ConfirmDialog`'s confirm button label at `apps/frontend/src/components/common/ConfirmDialog.jsx:45-68` and align the test's `getByRole` name with it rather than changing the component.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/kb/KbTable.jsx apps/frontend/src/__tests__/kb-table.test.jsx
git commit -m "feat(kb): add KbTable with server-driven paging and honest errors (INC-11)"
```

---

## Task 5: KnowledgeBasePage

**Files:**
- Create: `apps/frontend/src/pages/KnowledgeBasePage.jsx`
- Test: `apps/frontend/src/__tests__/knowledge-base-page.test.jsx`

**Interfaces:**
- Consumes: `KB_TABS` (Task 3), `KbTable` (Task 4)
- Produces: `<KnowledgeBasePage embedded />` — default export. `embedded` suppresses the outer page heading, matching `AdminUsersPage`'s convention.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/knowledge-base-page.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../components/kb/KbTable.jsx', () => ({
  default: ({ tab }) => <div data-testid="kb-table">{tab.key}</div>,
}));

import KnowledgeBasePage from '../pages/KnowledgeBasePage.jsx';

describe('KnowledgeBasePage', () => {
  it('shows the OUI tab first', () => {
    render(<KnowledgeBasePage />);
    expect(screen.getByTestId('kb-table')).toHaveTextContent('oui');
  });

  it('switches to the hostname tab', () => {
    render(<KnowledgeBasePage />);
    fireEvent.click(screen.getByRole('tab', { name: /hostname patterns/i }));
    expect(screen.getByTestId('kb-table')).toHaveTextContent('hostname');
  });

  it('marks the active tab for assistive technology', () => {
    render(<KnowledgeBasePage />);
    expect(screen.getByRole('tab', { name: /mac oui prefixes/i })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  it('renders its own heading when not embedded', () => {
    render(<KnowledgeBasePage />);
    expect(screen.getByRole('heading', { name: /knowledge base/i })).toBeInTheDocument();
  });

  it('omits the heading when embedded in Settings', () => {
    render(<KnowledgeBasePage embedded />);
    expect(screen.queryByRole('heading', { name: /knowledge base/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/knowledge-base-page.test.jsx`
Expected: FAIL — cannot resolve `../pages/KnowledgeBasePage.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/pages/KnowledgeBasePage.jsx`:

```jsx
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { KB_TABS } from '../components/kb/kbTabs.jsx';
import KbTable from '../components/kb/KbTable.jsx';

/**
 * Operator-editable lookup tables that feed discovery naming (INC-11).
 *
 * Rendered as a Settings tab (`embedded`), following AdminUsersPage's
 * convention so SettingsPage gains one registration line rather than a feature.
 */
function KnowledgeBasePage({ embedded = false }) {
  const [activeKey, setActiveKey] = useState(KB_TABS[0].key);
  const activeTab = KB_TABS.find((t) => t.key === activeKey) || KB_TABS[0];

  return (
    <div>
      {!embedded && <h1 className="tw-text-xl tw-mb-1">Knowledge Base</h1>}
      <p className="tw-text-sm tw-opacity-70 tw-mb-4">
        Vendor and device-type hints that discovery applies when naming devices. Entries marked{' '}
        <em>learned</em> were inferred from scans; <em>manual</em> entries were added here. Highest
        seen-count first.
      </p>

      <div role="tablist" aria-label="Knowledge base tables" className="tw-flex tw-gap-2 tw-mb-4">
        {KB_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={tab.key === activeKey}
            className={`btn btn-sm ${tab.key === activeKey ? 'btn-primary' : ''}`}
            onClick={() => setActiveKey(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <KbTable key={activeTab.key} tab={activeTab} />
    </div>
  );
}

KnowledgeBasePage.propTypes = {
  embedded: PropTypes.bool,
};

export default KnowledgeBasePage;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/knowledge-base-page.test.jsx`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/pages/KnowledgeBasePage.jsx apps/frontend/src/__tests__/knowledge-base-page.test.jsx
git commit -m "feat(kb): add KnowledgeBasePage with OUI and hostname tabs (INC-11)"
```

---

## Task 6: Register the Settings tab

**Files:**
- Modify: `apps/frontend/src/components/settings/SettingsNav.jsx`
- Modify: `apps/frontend/src/pages/SettingsPage.jsx:1761`
- Test: `apps/frontend/src/__tests__/kb-settings-tab.test.js`

**Interfaces:**
- Consumes: `KnowledgeBasePage` (Task 5)
- Produces: a `SETTINGS_TABS` entry `{ id: 'kb', label: 'Knowledge Base', icon: BookOpen, description: …, adminOnly: true }`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/kb-settings-tab.test.js`:

```javascript
import { describe, expect, it } from 'vitest';
import { SETTINGS_TABS } from '../components/settings/SettingsNav.jsx';

describe('Knowledge Base settings tab', () => {
  it('is registered', () => {
    expect(SETTINGS_TABS.map((t) => t.id)).toContain('kb');
  });

  it('is admin-only, matching require_role("admin") on every /kb route', () => {
    const tab = SETTINGS_TABS.find((t) => t.id === 'kb');
    expect(tab.adminOnly).toBe(true);
  });

  it('sits next to the other discovery-adjacent configuration', () => {
    const ids = SETTINGS_TABS.map((t) => t.id);
    expect(ids.indexOf('kb')).toBeGreaterThan(ids.indexOf('connectivity'));
  });

  it('has a label and description', () => {
    const tab = SETTINGS_TABS.find((t) => t.id === 'kb');
    expect(tab.label).toBe('Knowledge Base');
    expect(typeof tab.description).toBe('string');
    expect(tab.description.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-settings-tab.test.js`
Expected: FAIL — `expect(ids).toContain('kb')` receives an array without `kb`.

- [ ] **Step 3: Add the tab entry**

In `apps/frontend/src/components/settings/SettingsNav.jsx`, add `BookOpen` to the `lucide-react` import list, then insert this entry into `SETTINGS_TABS` immediately after the `integrations` entry:

```javascript
  {
    id: 'kb',
    label: 'Knowledge Base',
    icon: BookOpen,
    description: 'Vendor and hostname hints that discovery uses for naming.',
    adminOnly: true,
  },
```

- [ ] **Step 4: Add the one render line**

In `apps/frontend/src/pages/SettingsPage.jsx`, add the lazy import next to the other page imports at the top:

```javascript
import KnowledgeBasePage from './KnowledgeBasePage.jsx';
```

Then add exactly one render line directly below the Users tab line at 1761:

```jsx
            {/* ── Knowledge Base Tab ─────────────────── */}
            {activeTab === 'kb' && isAdmin && <KnowledgeBasePage embedded />}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix apps/frontend test -- src/__tests__/kb-settings-tab.test.js`
Expected: PASS — 4 tests.

Run: `npm --prefix apps/frontend test`
Expected: PASS — the whole suite, including the pre-existing `settings-page.test.jsx`, which must not regress.

- [ ] **Step 6: Verify lint is clean**

Run: `npm --prefix apps/frontend run lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/settings/SettingsNav.jsx apps/frontend/src/pages/SettingsPage.jsx apps/frontend/src/__tests__/kb-settings-tab.test.js
git commit -m "feat(kb): register Knowledge Base settings tab (INC-11)"
```

---

## Task 7: Documentation and register update

INC-11 is *"has no UI **and no docs**"*, so this task closes the second half of the finding.

**Files:**
- Create: `docs/knowledge-base.md`
- Modify: `docs/discovery.md`, `mkdocs.yml`, `docs/1.0.0-incomplete-features.md`

- [ ] **Step 1: Write the docs page**

Create `docs/knowledge-base.md`:

```markdown
# Knowledge Base

The knowledge base holds two operator-editable lookup tables that discovery
consults when naming devices. They supplement the curated `device_kb.json`
shipped with Circuit Breaker.

**Where:** Settings → Knowledge Base. Admin only.

## The two tables

| Table | Keyed by | Feeds |
|---|---|---|
| MAC OUI Prefixes | The first six hex characters of a MAC address | Vendor, device type, and OS family for a discovered host |
| Hostname Patterns | A pattern plus a match type | The same three hints, from a host's reported name |

## Learned vs manual entries

Entries marked **learned** were inferred during scans; **manual** entries were
added here. `Seen` and `Last seen` are how you judge whether a learned entry is
worth trusting — a prefix seen hundreds of times across recent scans is
well-evidenced, one seen twice a month ago is not.

Source cannot be changed. Correcting a learned entry's vendor leaves it marked
learned; that is deliberate, so provenance survives the correction.

## Editing

Vendor, device type, and OS family are editable in place — click the cell.

The prefix and the pattern are identity and cannot be renamed: the API has no
rename operation, so an apparent rename would be a create plus a delete with
different provenance. Delete and re-add if you need to change one.

Match type on a hostname pattern is one of `prefix`, `exact`, or `contains`,
and is edited through the row's form rather than in place, because a free-text
value outside that set would be silently ignored by the matcher.

## Adding a MAC prefix

Enter the OUI in any conventional form — `B8:27:EB`, `b8-27-eb`, `B827EB`, or a
full MAC, from which the first six characters are taken. It is stored as six
uppercase hex characters.

## Export

**Export JSON** downloads the table in the same shape as `device_kb.json`'s
`mac_oui_prefixes` / `hostname_patterns` sections, suitable for review or for
copying into another install by hand.

There is no import in 1.0 — entries are added through this screen or learned
during discovery.

## See also

- [Discovery](discovery.md) — where these hints are applied
```

- [ ] **Step 2: Cross-reference from the discovery docs**

Append to `docs/discovery.md`:

```markdown
## Naming hints

Vendor and device-type identification draws on two operator-editable lookup
tables in addition to the curated device catalogue. See
[Knowledge Base](knowledge-base.md) for how learned entries accumulate and how
to correct them.
```

- [ ] **Step 3: Add the MkDocs nav entry**

In `mkdocs.yml`, the discovery page is listed at line 33 as `- Auto-Discovery (Beta): discovery.md` (the nav label is not "Discovery"). Insert the new entry on the following line with **six spaces** of indentation, matching its neighbours:

```yaml
      - Auto-Discovery (Beta): discovery.md
      - Knowledge Base: knowledge-base.md
      - cb-agent: agent.md
```

- [ ] **Step 4: Verify the nav entry and cross-links**

`mkdocs` is **not installed** in this repo — not on `PATH` and not in `.venv` — so `mkdocs build --strict` is unavailable. Verify by inspection instead:

```bash
grep -n "knowledge-base.md" mkdocs.yml docs/discovery.md
python3 -c "import yaml,sys; yaml.safe_load(open('mkdocs.yml')); print('mkdocs.yml parses')"
```

Expected: `mkdocs.yml` and `docs/discovery.md` each show one hit, and the YAML parses — which catches the indentation mistake this step exists to prevent.

If `mkdocs` is available in your environment, `mkdocs build --strict` is a stronger check and is worth running; do not add it as a dependency just for this.

- [ ] **Step 5: Update the finding register**

In `docs/1.0.0-incomplete-features.md`:

1. In the Summary table, change INC-11's severity cell from `P1` to `Resolved`.
2. Update the `**Last updated:**` line to `2026-08-24 — INC-11 closed; Knowledge Base has a UI and docs.`
3. Replace the body of the INC-11 section with:

```markdown
### INC-11. Knowledge Base (OUI / hostname) has no UI and no docs

**Resolved.** `api/kb.py` implemented full CRUD plus CSV export for two
operator-editable lookup tables that feed discovery naming, with no frontend
caller, no MkDocs page, and no mention in `docs/discovery.md`. The feature was
reachable only by hand-crafting HTTP requests.

Both halves are now closed:

- `pages/KnowledgeBasePage.jsx` — admin-only, embedded as the `kb` Settings tab
  following `AdminUsersPage`'s convention, so `SettingsPage.jsx` gained one
  render line rather than a feature.
- `components/kb/kbTabs.jsx` — the two tables as declarative descriptors. The
  inline-editable set is exactly what `PUT` accepts, pinned from both sides:
  `__tests__/kb-tabs.test.js` and `tests/api/test_kb.py::
  test_update_schemas_match_frontend_editable_columns` each name the other, so
  the drift that produced INC-17 fails a test that says where to look.
  `match_type` is accepted by the API but deliberately excluded from inline
  editing — it is an enum and the inline cell editor is a bare text input.
- `components/kb/KbTable.jsx` — paging is server-driven. `EntityTable`
  paginates client-side while the KB routes cap `limit` at 500, so handing it
  one unbounded fetch would have capped the view at 500 rows while looking
  complete. A failed fetch renders an error with retry, never an empty table.
  Rows are keyed by `prefix` for OUI, since `kb_oui` has no `id` column and
  `EntityTable` hard-codes `row.id`.
- `utils/validation.js` — `normalizeMacPrefix` folds any conventional MAC
  spelling to the six bare hex characters `KbOuiCreate` requires. Without it a
  pasted `B8:27:EB` is a 422 for what an operator reasonably typed.
- `docs/knowledge-base.md`, cross-referenced from `docs/discovery.md` and added
  to the MkDocs nav.

No backend change and no migration: every route this uses already existed.
```

- [ ] **Step 6: Run the full test suites**

Run: `npm --prefix apps/frontend test`
Expected: PASS.

Run: `pytest apps/backend/tests/api/test_kb.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/knowledge-base.md docs/discovery.md mkdocs.yml docs/1.0.0-incomplete-features.md
git commit -m "docs(kb): document the knowledge base and close INC-11"
```

---

## Self-Review

**Spec coverage (§4).** Page component with `embedded` ✓ Task 5. Two tabs ✓ Task 3/5. `EntityTable` over existing routes ✓ Task 4. `seen_count` / `last_seen_at` / source badge columns ✓ Task 3. Source filter passing the query param ✓ Task 4. Editable set dictated by the API, with the contract pin ✓ Task 3. `match_type` via modal ✓ Task 3. Server-driven pagination with Load more ✓ Task 4. `ConfirmDialog` for delete ✓ Task 4. Export from existing routes ✓ Task 4. No new endpoints ✓. Admin-only tab ✓ Task 6. Docs as a deliverable ✓ Task 7. Register update ✓ Task 7. Error state, never an empty table (§9) ✓ Task 4.

**Placeholder scan.** No TBDs, no "add error handling", no "similar to Task N". Every code step carries the code.

**Type consistency.** `KB_TABS` descriptor keys are identical across Tasks 3, 4, and 5 (`key`, `label`, `identityKey`, `exportFilename`, `columns`, `editableColumns`, `formFields`, `validateCreate`, `serializeCreate`, `api`). `api.remove` (not `delete` — a reserved word) is used consistently in Tasks 3 and 4. `onCellSave(row, columnKey, value)` matches `EntityTable.jsx:127`. `onDelete(row.id)` matches `EntityTable.jsx:323`. `FormModal` props match its propTypes at `FormModal.jsx:170-182`. `ConfirmDialog` props match `ConfirmDialog.jsx:14`.

**One deviation from the spec worth noting:** the spec's §4 mockup showed a plain text filter. This plan labels it "Filter loaded entries" and shows a "Load more to search further" hint when unloaded rows remain, because the KB routes have no server-side search — an unlabelled filter over a paged list would claim to search a table it can only see 100 rows of.

---

## Execution Handoff

**Plan complete and saved to `specs/1.0.0/slices/ui-1-knowledge-base.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
