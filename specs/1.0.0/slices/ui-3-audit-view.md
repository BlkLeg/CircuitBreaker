# UI-3 — Audit View and Chain Integrity

**Supports:** INC-12
**Depends on:** UI-2 (`HighRiskConfirmDialog`)
**Spec:** [Missing UIs](../10-missing-uis.md) §5

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the tamper-evident audit log a dedicated view, and give its hash-chain verification and repair a UI.

**Architecture:** `/logs/audit` renders the existing `LogsPage` in an `auditMode` that pins `category=audit`, with a new chain-integrity panel above the table. `LogsPage`'s ~850 lines of row rendering, diffing, filtering and virtualisation are reused rather than rebuilt.

**Tech Stack:** React 18, vitest + @testing-library/react; FastAPI, pytest.

## Global Constraints

- **Every new surface is its own file. Host files gain a registration line, not a feature.** `LogsPage.jsx` is 1437 lines; `auditMode` must be a narrow, mechanical addition, not a second page inlined into the first.
- **Repair's dialog enforces the server's contract rather than restating it:** the phrase is `REPAIR_AUTHORIZATION` (`core/audit_chain.py:19` = `"REPAIR_AUDIT_CHAIN"`) and the reason minimum is the `Field(min_length=12)` on `AuditChainRepairRequest`.
- **A broken chain must never be reported quietly.** Intact is one line; broken is escalated, names the first failing entry, and states that repair relinks the chain but does not recover altered entries.
- **No fetch failure may render as an empty table**, and a verification that could not run must not look like a verification that passed.
- **Admin only** — `GET /logs`, `/admin/audit-log/verify-chain`, and `/admin/audit-log/repair-chain` are all `require_role("admin")`.

---

## Two findings that shape this slice

**1. `GET /logs/audit` is redundant, not missing.** Spec §5.1 records this and it holds up: `GET /logs` (`api/logs.py:120`) already accepts `category` and its parameter list is a strict superset of `/logs/audit`'s — the latter adds nothing and drops `entity_type`, `entity_id`, `entity_name`, `level`, `severity`, and `search`. This slice therefore builds the **view** against `GET /logs?category=audit` and gives the **endpoint** a disposition (Task 5), rather than inventing a caller to justify it.

**2. `LogsPage` already calls itself "Audit Log" and is not one.** `LogsPage.jsx:1120` renders `<h2>Audit Log</h2>` and `:1054` exports `circuit-breaker-audit-<date>.csv`, but `fetchLogs` (`:952-963`) sends **no `category` param** — it shows every log category. The page named "Audit Log" is not the audit log.

That is the same mislabelling class this register exists to catalogue, and shipping `/logs/audit` beside a `/logs` that claims the same title would make it worse: two pages, one title, different contents. Task 3 therefore retitles `/logs` to **"Logs"** and its export to `circuit-breaker-logs-<date>.csv`, and gives the audit title to the page that earns it.

**3. Deviation from spec §5.2:** the spec said auditMode would hide "the filters that don't apply". On reading them, every filter applies to audit entries — `entity_type`, `action`, `actor`, `severity`, `search`, and the time presets are all meaningful for `category=audit` rows. Hiding any of them would remove working functionality for no reason. **auditMode changes the category, the title, and the export filename. It hides nothing.** This is a smaller and safer change than the spec anticipated.

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `apps/frontend/src/api/audit.js` | `verifyChain`, `repairChain`. |
| `apps/frontend/src/components/logs/AuditChainPanel.jsx` | Verify status, broken-state escalation, guarded repair. |
| `apps/frontend/src/__tests__/audit-api.test.js` | Pins URLs and the repair payload. |
| `apps/frontend/src/__tests__/audit-chain-panel.test.jsx` | Panel states, repair flow, refetch. |
| `apps/frontend/src/__tests__/logs-page-audit-mode.test.jsx` | auditMode pins the category and retitles. |

**Modify**

| File | Change |
|---|---|
| `apps/frontend/src/pages/LogsPage.jsx` | `auditMode` prop: category, title, export name, panel slot. |
| `apps/frontend/src/App.jsx` | One lazy import, one route. |
| `apps/frontend/src/data/navigation.js` | One `NAV_ITEMS` entry (not the dock). |
| `docs/audit-log.md` | Correct the page description. |
| `docs/1.0.0-incomplete-features.md` | INC-12 resolution note + `/logs/audit` disposition. |

---

## Task 1: Audit API module

**Files:**
- Create: `apps/frontend/src/api/audit.js`
- Test: `apps/frontend/src/__tests__/audit-api.test.js`

**Interfaces:**
- Produces:
  - `verifyChain() => Promise<{data: {valid, first_failure_id, message, checked_count}}>`
  - `repairChain({reason}) => Promise<{data: {repaired, before, changed, after}}>` — supplies the fixed `authorization` string itself.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/audit-api.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

import client from '../api/client.jsx';
import { verifyChain, repairChain, REPAIR_AUTHORIZATION } from '../api/audit';

beforeEach(() => vi.clearAllMocks());

describe('audit api module', () => {
  it('verifies the chain', () => {
    verifyChain();
    expect(client.get).toHaveBeenCalledWith('/admin/audit-log/verify-chain');
  });

  it('sends the exact authorization string the server requires', () => {
    repairChain({ reason: 'chain broken after a restore' });
    expect(client.post).toHaveBeenCalledWith('/admin/audit-log/repair-chain', {
      authorization: 'REPAIR_AUDIT_CHAIN',
      reason: 'chain broken after a restore',
    });
  });

  it('exports the authorization constant so the dialog and the payload cannot disagree', () => {
    expect(REPAIR_AUTHORIZATION).toBe('REPAIR_AUDIT_CHAIN');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/audit-api.test.js`
Expected: FAIL — cannot resolve `../api/audit`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/api/audit.js`:

```javascript
import client from './client.jsx';

/**
 * Must equal REPAIR_AUTHORIZATION in apps/backend/src/app/core/audit_chain.py:19.
 * Exported so the confirmation dialog's typed phrase and the request body read
 * from ONE constant — two spellings of the same magic string is exactly the
 * kind of drift this register catalogues.
 */
export const REPAIR_AUTHORIZATION = 'REPAIR_AUDIT_CHAIN';

// Returns {valid, first_failure_id, message, checked_count}.
export const verifyChain = () => client.get('/admin/audit-log/verify-chain');

// Returns {repaired, before, changed, after}. The server requires `reason` to
// be at least 12 characters; the dialog enforces that before we get here.
export const repairChain = ({ reason }) =>
  client.post('/admin/audit-log/repair-chain', {
    authorization: REPAIR_AUTHORIZATION,
    reason,
  });
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/audit-api.test.js`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/audit.js apps/frontend/src/__tests__/audit-api.test.js
git commit -m "feat(audit): add audit-chain API module (INC-12)"
```

---

## Task 2: AuditChainPanel

**Files:**
- Create: `apps/frontend/src/components/logs/AuditChainPanel.jsx`
- Test: `apps/frontend/src/__tests__/audit-chain-panel.test.jsx`

**Interfaces:**
- Consumes: Task 1's module; `HighRiskConfirmDialog` (UI-2 Task 1); `useToast`
- Produces: `<AuditChainPanel onRepaired={() => {}} />` — `onRepaired` lets the host refetch the log list, since the repair writes an audit entry that should appear in the view

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/audit-chain-panel.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../api/audit', () => ({
  verifyChain: vi.fn(),
  repairChain: vi.fn(),
  REPAIR_AUTHORIZATION: 'REPAIR_AUDIT_CHAIN',
}));

import { verifyChain, repairChain } from '../api/audit';
import AuditChainPanel from '../components/logs/AuditChainPanel.jsx';

const INTACT = { valid: true, first_failure_id: null, message: 'ok', checked_count: 12481 };
const BROKEN = {
  valid: false,
  first_failure_id: 8214,
  message: 'Log id=8214: previous_hash mismatch (chain broken).',
  checked_count: 12481,
};

beforeEach(() => vi.clearAllMocks());

describe('AuditChainPanel', () => {
  it('reports an intact chain quietly, with the count checked', async () => {
    verifyChain.mockResolvedValue({ data: INTACT });

    render(<AuditChainPanel />);

    await waitFor(() => expect(screen.getByText(/chain intact/i)).toBeInTheDocument());
    expect(screen.getByText(/12,?481/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /repair/i })).not.toBeInTheDocument();
  });

  it('escalates a broken chain and names the first failing entry', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });

    render(<AuditChainPanel />);

    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    expect(screen.getByText(/8214/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /repair chain/i })).toBeInTheDocument();
  });

  it('says repair does not recover altered entries', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });

    render(<AuditChainPanel />);

    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    expect(screen.getByText(/does not recover/i)).toBeInTheDocument();
  });

  it('requires both the phrase and a long-enough reason before repairing', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });
    repairChain.mockResolvedValue({ data: { repaired: true } });

    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /repair chain/i }));

    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'too short' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'chain broken after database restore' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() =>
      expect(repairChain).toHaveBeenCalledWith({ reason: 'chain broken after database restore' })
    );
  });

  it('re-verifies and notifies the host after a repair, so the repair entry appears', async () => {
    verifyChain.mockResolvedValueOnce({ data: BROKEN }).mockResolvedValue({ data: INTACT });
    repairChain.mockResolvedValue({ data: { repaired: true } });
    const onRepaired = vi.fn();

    render(<AuditChainPanel onRepaired={onRepaired} />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /repair chain/i }));
    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'chain broken after database restore' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText(/chain intact/i)).toBeInTheDocument());
    expect(onRepaired).toHaveBeenCalled();
  });

  it('surfaces a repair rejection in the dialog without closing it', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });
    repairChain.mockRejectedValue({ userMessage: 'authorization must equal…' });

    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /repair chain/i }));
    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'chain broken after database restore' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('authorization must equal')
    );
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument();
  });

  it('never lets a failed verification look like a passed one', async () => {
    verifyChain.mockRejectedValue(new Error('boom'));

    render(<AuditChainPanel />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByText(/chain intact/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/audit-chain-panel.test.jsx`
Expected: FAIL — cannot resolve `../components/logs/AuditChainPanel.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/logs/AuditChainPanel.jsx`:

```jsx
import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { ShieldCheck, ShieldAlert } from 'lucide-react';
import { REPAIR_AUTHORIZATION, repairChain, verifyChain } from '../../api/audit';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import { useToast } from '../common/Toast';

/**
 * Hash-chain integrity for the audit log (INC-12).
 *
 * Intact is deliberately one quiet line: an operator should be able to glance
 * past it. Broken is escalated, because a break means entries were altered or
 * removed after being written, and the panel is the only place that says so.
 *
 * Repair is guarded by the server's own contract — the exact REPAIR_AUDIT_CHAIN
 * authorization string and a reason of at least 12 characters — rather than by
 * a confirmation invented here.
 */
function AuditChainPanel({ onRepaired = undefined }) {
  const toast = useToast();
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairError, setRepairError] = useState(null);

  const verify = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await verifyChain();
      setResult(res.data);
    } catch (err) {
      // A verification that could not run must never look like one that
      // passed — that would be a silent all-clear over an unknown chain.
      setError(err?.userMessage || 'Could not verify the audit chain.');
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    verify();
  }, [verify]);

  const handleRepair = useCallback(
    async ({ reason }) => {
      setRepairing(true);
      setRepairError(null);
      try {
        await repairChain({ reason });
        setConfirmOpen(false);
        toast.success('Chain repaired. A repair record was appended to the audit log.');
        await verify();
        // The repair writes an audit entry. Refetching the list the operator is
        // looking at is the confirmation that it happened.
        if (onRepaired) onRepaired();
      } catch (err) {
        setRepairError(err?.userMessage || 'Repair failed.');
      } finally {
        setRepairing(false);
      }
    },
    [toast, verify, onRepaired]
  );

  if (loading) return null;

  if (error) {
    return (
      <div role="alert" className="audit-chain-panel audit-chain-panel--error">
        <span>{error}</span>
        <button type="button" className="btn btn-sm" onClick={verify}>
          Retry
        </button>
      </div>
    );
  }

  if (!result) return null;

  if (result.valid) {
    return (
      <div className="audit-chain-panel audit-chain-panel--ok">
        <ShieldCheck size={14} />
        <span>chain intact</span>
        <span className="audit-chain-panel__detail">
          {result.checked_count.toLocaleString()} entries verified
        </span>
        <button type="button" className="btn btn-sm" onClick={verify}>
          Re-verify
        </button>
      </div>
    );
  }

  return (
    <div className="audit-chain-panel audit-chain-panel--bad">
      <div className="audit-chain-panel__row">
        <ShieldAlert size={14} />
        <span>chain broken</span>
        <span className="audit-chain-panel__detail">
          Verification failed at entry #{result.first_failure_id} ·{' '}
          {result.checked_count.toLocaleString()} checked
        </span>
        <button type="button" className="btn btn-sm" onClick={verify}>
          Re-verify
        </button>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          onClick={() => {
            setRepairError(null);
            setConfirmOpen(true);
          }}
        >
          Repair chain…
        </button>
      </div>
      <p className="audit-chain-panel__note">
        A break means entries were altered or removed after being written. Repair relinks the chain
        and appends a repair record; it does not recover the original entries.
      </p>

      <HighRiskConfirmDialog
        open={confirmOpen}
        title="Repair the audit hash chain"
        body={
          <>
            <p>
              This rewrites the hash links from entry #{result.first_failure_id} onward so the chain
              verifies again, and appends a repair record naming you and your reason.
            </p>
            <p>
              It does <strong>not</strong> recover altered or deleted entries. If you have not yet
              established why the chain broke, investigate before repairing — repairing first
              removes the signal.
            </p>
          </>
        }
        confirmPhrase={REPAIR_AUTHORIZATION}
        confirmLabel="Confirm"
        reason={{ required: true, minLength: 12, label: 'Reason' }}
        busy={repairing}
        error={repairError}
        onConfirm={handleRepair}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

AuditChainPanel.propTypes = {
  onRepaired: PropTypes.func,
};

export default AuditChainPanel;
```

- [ ] **Step 4: Add the panel's styles**

Append to `apps/frontend/src/index.css` (or the stylesheet `LogsPage` already uses — check its imports and follow it rather than introducing a second convention):

```css
/* INC-12: audit hash-chain integrity, above the audit log table. */
.audit-chain-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--color-border);
  border-left-width: 3px;
  border-radius: 8px;
  font-size: 13px;
}

.audit-chain-panel__row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.audit-chain-panel--ok {
  flex-direction: row;
  align-items: center;
  border-left-color: var(--color-success, #3fb950);
}

.audit-chain-panel--bad {
  border-left-color: var(--color-danger, #f85149);
}

.audit-chain-panel--error {
  flex-direction: row;
  align-items: center;
  border-left-color: var(--color-warning, #d29922);
}

.audit-chain-panel__detail {
  opacity: 0.75;
}

.audit-chain-panel--ok button,
.audit-chain-panel--error button,
.audit-chain-panel__row button:last-child {
  margin-left: auto;
}

.audit-chain-panel__note {
  margin: 0;
  font-size: 11px;
  opacity: 0.75;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/audit-chain-panel.test.jsx`
Expected: PASS — 7 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/logs/AuditChainPanel.jsx apps/frontend/src/index.css apps/frontend/src/__tests__/audit-chain-panel.test.jsx
git commit -m "feat(audit): add audit-chain integrity panel (INC-12)"
```

---

## Task 3: LogsPage auditMode, and correcting the Logs title

**Files:**
- Modify: `apps/frontend/src/pages/LogsPage.jsx`
- Test: `apps/frontend/src/__tests__/logs-page-audit-mode.test.jsx`

Four narrow changes. Nothing else in the file moves.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/logs-page-audit-mode.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual('../api/client');
  return {
    ...actual,
    logsApi: {
      list: vi.fn(() => Promise.resolve({ data: { logs: [], total_count: 0 } })),
      actions: vi.fn(() => Promise.resolve({ data: { actions: [] } })),
      clear: vi.fn(),
      stream: vi.fn(() => '/api/v1/logs/stream'),
    },
  };
});

vi.mock('../components/logs/AuditChainPanel', () => ({
  default: () => <div data-testid="audit-chain-panel" />,
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

import { logsApi } from '../api/client';
import LogsPage from '../pages/LogsPage.jsx';

const renderPage = (props = {}) =>
  render(
    <MemoryRouter>
      <LogsPage {...props} />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

describe('LogsPage auditMode', () => {
  it('does not filter by category in the default mode', async () => {
    renderPage();
    await waitFor(() => expect(logsApi.list).toHaveBeenCalled());
    expect(logsApi.list.mock.calls[0][0]).not.toHaveProperty('category');
  });

  it('pins category=audit in auditMode', async () => {
    renderPage({ auditMode: true });
    await waitFor(() => expect(logsApi.list).toHaveBeenCalled());
    expect(logsApi.list.mock.calls[0][0]).toMatchObject({ category: 'audit' });
  });

  it('titles the default page Logs, not Audit Log', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Logs' })).toBeInTheDocument());
    expect(screen.queryByRole('heading', { name: /audit log/i })).not.toBeInTheDocument();
  });

  it('titles the audit page Audit Log', async () => {
    renderPage({ auditMode: true });
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /audit log/i })).toBeInTheDocument()
    );
  });

  it('mounts the chain panel only in auditMode', async () => {
    const { unmount } = renderPage();
    await waitFor(() => expect(logsApi.list).toHaveBeenCalled());
    expect(screen.queryByTestId('audit-chain-panel')).not.toBeInTheDocument();
    unmount();

    renderPage({ auditMode: true });
    await waitFor(() => expect(screen.getByTestId('audit-chain-panel')).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/logs-page-audit-mode.test.jsx`
Expected: FAIL — the default page is titled "Audit Log" and `category` is never sent.

- [ ] **Step 3: Accept the prop and pin the category**

In `apps/frontend/src/pages/LogsPage.jsx`:

Change the signature at line 854:

```javascript
function LogsPage({ auditMode = false }) {
```

In `fetchLogs` (line ~956), add the category immediately after `const params = …`:

```javascript
      const params = { limit, offset, sort: timestampSort };
      // INC-12: the audit view is GET /logs?category=audit. The dedicated
      // GET /logs/audit route is a strict subset of this one — it drops
      // entity_type, level, severity and search — so it is not used.
      if (auditMode) params.category = 'audit';
```

Add `auditMode` to `fetchLogs`'s dependency array, alongside `limit` and `offset`.

- [ ] **Step 4: Correct the titles and the export filename**

At line ~1120, replace `<h2>Audit Log</h2>` with:

```jsx
        <h2>{auditMode ? 'Audit Log' : 'Logs'}</h2>
```

At line ~1054, replace the export filename so it names what it actually contains:

```javascript
    const scope = auditMode ? 'audit' : 'logs';
    a.download = `circuit-breaker-${scope}-${new Date().toISOString().slice(0, 10)}.csv`;
```

- [ ] **Step 5: Mount the chain panel**

Import at the top of the file:

```javascript
import AuditChainPanel from '../components/logs/AuditChainPanel';
```

Immediately after the closing tag of the `page-header` block, add:

```jsx
      {auditMode && <AuditChainPanel onRepaired={fetchLogs} />}
```

Add the propTypes block directly above `export default LogsPage;`:

```javascript
LogsPage.propTypes = {
  // /logs/audit renders this same page pinned to category=audit. It hides no
  // filters: entity type, action, actor, severity, search and the time presets
  // are all meaningful for audit entries too.
  auditMode: PropTypes.bool,
};
```

If `PropTypes` is not already imported in this file, add `import PropTypes from 'prop-types';` with the other imports.

- [ ] **Step 6: Run tests to verify they pass**

Run: `npm --prefix apps/frontend test -- src/__tests__/logs-page-audit-mode.test.jsx`
Expected: PASS — 5 tests.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/pages/LogsPage.jsx apps/frontend/src/__tests__/logs-page-audit-mode.test.jsx
git commit -m "feat(logs): add auditMode and stop titling the all-category view Audit Log (INC-12)"
```

---

## Task 4: Route and navigation

**Files:**
- Modify: `apps/frontend/src/App.jsx`
- Modify: `apps/frontend/src/data/navigation.js`
- Test: `apps/frontend/src/__tests__/audit-nav.test.js`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/audit-nav.test.js`:

```javascript
import { describe, expect, it } from 'vitest';
import { NAV_ITEMS, NAV_MAP, DEFAULT_ORDER } from '../data/navigation';

const allItems = NAV_ITEMS.flatMap((g) => g.items);

describe('audit log navigation', () => {
  it('is listed under Administration', () => {
    const admin = NAV_ITEMS.find((g) => g.group === 'Administration');
    expect(admin.items.some((i) => i.path === '/logs/audit')).toBe(true);
  });

  it('is admin-only', () => {
    const item = allItems.find((i) => i.path === '/logs/audit');
    expect(item.requireAdmin).toBe(true);
  });

  it('stays out of the dock — it is a sub-view of Logs, not a peer of Map', () => {
    expect(NAV_MAP).not.toHaveProperty('/logs/audit');
    expect(DEFAULT_ORDER).not.toContain('/logs/audit');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/audit-nav.test.js`
Expected: FAIL — no `/logs/audit` item.

- [ ] **Step 3: Add the nav entry**

In `apps/frontend/src/data/navigation.js`, add `ShieldCheck` to the import if it is not already there (it is — it is used by `/privacy`), then insert into the `Administration` group's `items`, directly after the `/logs` entry:

```javascript
      {
        path: '/logs/audit',
        icon: ShieldCheck,
        label: 'Audit Log',
        labelKey: 'header.auditLog',
        requireAdmin: true,
      },
```

Do **not** add it to `NAV_MAP` or `DEFAULT_ORDER`.

- [ ] **Step 4: Add the route**

In `apps/frontend/src/App.jsx`, directly after the existing `/logs` route block:

```jsx
                  <Route
                    path="/logs/audit"
                    element={
                      <RequireAdmin>
                        <LogsPage auditMode />
                      </RequireAdmin>
                    }
                  />
```

No new lazy import is needed — `LogsPage` is already imported at line 53.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix apps/frontend test -- src/__tests__/audit-nav.test.js`
Expected: PASS — 3 tests.

- [ ] **Step 6: Run the full suite and lint**

Run: `npm --prefix apps/frontend test`
Run: `npm --prefix apps/frontend run lint`
Expected: PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/App.jsx apps/frontend/src/data/navigation.js apps/frontend/src/__tests__/audit-nav.test.js
git commit -m "feat(audit): route and navigation for /logs/audit (INC-12)"
```

---

## Task 5: Endpoint disposition, docs, and register

- [ ] **Step 1: Record the `GET /logs/audit` disposition**

`GET /logs/audit` (`api/logs.py:237`) is a strict subset of `GET /logs?category=audit` and now has no caller by design.

**Do not delete it in this slice.** Removing a route is an API-compatibility decision with its own blast radius, and INC-19 already exists as the place where orphaned routes get individual dispositions. Instead, mark it so the next reader does not mistake it for a gap. Add to its docstring in `apps/backend/src/app/api/logs.py`:

```python
    """Admin-only endpoint that returns entries with category='audit'.

    DISPOSITION (INC-12): superseded by `GET /logs?category=audit`, which
    accepts a strict superset of these parameters — this route drops
    entity_type, entity_id, entity_name, level, severity and search. The
    /logs/audit *view* in the frontend uses the general route; this one is kept
    only as an API convenience for existing clients. Tracked for removal under
    INC-19's orphaned-route dispositions; do not build new callers on it.
    """
```

- [ ] **Step 2: Correct the audit-log docs**

`docs/audit-log.md:48` describes *"filters at the top of the page"* for a dedicated audit view that did not exist. It does now. Replace that paragraph with:

```markdown
## The audit view

**Where:** Administration → Audit Log (`/logs/audit`). Admin only.

The audit view shows entries in the `audit` category only. The filters at the
top of the page — time range, action, actor, entity type, severity, and free
text — all apply to it, and are the same controls the general Logs view uses.

The general **Logs** view at `/logs` shows every category, audit entries
included.

## Chain integrity

Audit entries are hash-chained: each entry's stored hash covers the previous
entry's, so altering or deleting an entry breaks every link after it.

The panel above the audit table reports the chain's state on load. When intact
it is a single line naming how many entries were verified. When broken it names
the first failing entry and offers **Repair chain**.

Repair relinks the chain from the first failure onward and appends a repair
record naming the operator and their stated reason. **It does not recover
altered or deleted entries** — a broken chain is evidence, and repairing it
removes the signal without restoring the data. Investigate before repairing.

Because repair is deliberately hard to trigger by accident, it requires typing
`REPAIR_AUDIT_CHAIN` exactly and giving a reason of at least twelve characters.
Both are recorded.
```

- [ ] **Step 3: Update the register**

In `docs/1.0.0-incomplete-features.md`: set INC-12's summary row to `Resolved`, update `**Last updated:**`, and replace the INC-12 body with:

```markdown
### INC-12. Audit-chain verify/repair has no UI

**Resolved.** `GET /admin/audit-log/verify-chain` and
`POST /admin/audit-log/repair-chain` were the operator tooling for the
tamper-evident hash chain and had no frontend caller.

- `components/logs/AuditChainPanel.jsx` — verifies on mount. Intact is one
  quiet line; broken is escalated, names `first_failure_id`, and states that
  repair relinks the chain but does not recover the original entries. A
  verification that could not run renders an error, never a passing state —
  a silent all-clear over an unknown chain would be worse than no panel.
- Repair goes through `HighRiskConfirmDialog` (added by INC-13) with the phrase
  `REPAIR_AUDIT_CHAIN` and a ≥12-character reason. Both come from the server's
  own contract — `core/audit_chain.py:19` and `AuditChainRepairRequest`'s
  `Field(min_length=12)` — so the dialog enforces it rather than restating it.
  `api/audit.js` exports the authorization constant so the typed phrase and the
  request body read from one source.
- After a repair the panel re-verifies and refetches the log list. The repair
  entry appearing in the view is the confirmation.
- `/logs/audit` renders `LogsPage` with `auditMode`, pinning `category=audit`.
  It hides no filters: entity type, action, actor, severity, search and the
  time presets are all meaningful for audit entries, so the spec's expectation
  that some would be hidden turned out to be unnecessary.

**Two corrections found while implementing this:**

`GET /logs/audit` (`api/logs.py:237`) is **redundant, not missing** — the same
class as the `GET/PUT /hardware/{id}/ports` row already in INC-19.
`GET /logs` accepts `category` and a strict superset of its parameters; the
subset route drops `entity_type`, `entity_id`, `entity_name`, `level`,
`severity` and `search`. The view uses the general route; the subset route
carries a disposition comment and is tracked for removal under INC-19 rather
than being kept alive by an invented caller.

`LogsPage` was titled **"Audit Log"** while sending no `category` parameter —
it showed every category under the audit log's name, and exported CSVs named
`circuit-breaker-audit-*.csv` containing all of them. `/logs` is now titled
"Logs" and exports `circuit-breaker-logs-*.csv`; the audit title belongs to the
view that filters for it.

No migration and no schema change.
```

- [ ] **Step 4: Run both suites**

Run: `npm --prefix apps/frontend test`
Run: `pytest apps/backend/tests/api/ -k "logs or audit" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/api/logs.py docs/audit-log.md docs/1.0.0-incomplete-features.md
git commit -m "docs(audit): document the audit view and close INC-12"
```

---

## Self-Review

**Spec coverage (§5).** `/logs/audit` route reusing LogsPage ✓ Tasks 3–4. Category pinned ✓ Task 3. Title and empty state reworded ✓ Task 3. `AuditChainPanel` above the table ✓ Tasks 2–3. Intact quiet / broken escalated ✓ Task 2. Repair behind phrase + reason from the server contract ✓ Tasks 1–2. Refetch verify and list after repair ✓ Task 2. `GET /logs/audit` given a disposition rather than a caller ✓ Task 5. `docs/audit-log.md:48` corrected ✓ Task 5. Error never renders as a pass (§9) ✓ Task 2.

**Deviations, both recorded in the register note:** filters are not hidden in auditMode (all of them apply); and `/logs` is retitled, which the spec did not ask for but which becomes necessary the moment a second page claims the same name.

**Placeholder scan.** None. The two "follow the existing convention" notes (which stylesheet `LogsPage` imports; whether `PropTypes` is already imported) name the check to run rather than leaving a decision open.

**Type consistency.** `verifyChain`'s result fields (`valid`, `first_failure_id`, `message`, `checked_count`) match `core/audit_chain.py:139-160` exactly and are used identically in Task 2 and its tests. `repairChain({reason})` has one signature across Tasks 1 and 2. `REPAIR_AUTHORIZATION` is one exported constant used for both the dialog phrase and the payload. `HighRiskConfirmDialog`'s props match UI-2 Task 1's definition, including `reason: {required, minLength, label}` and `onConfirm({reason})`; nothing here modifies that component.
