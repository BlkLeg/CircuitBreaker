# UI-2 — Agent Server-Key Rotation

**Supports:** INC-13
**Depends on:** nothing — introduces `HighRiskConfirmDialog`, consumed later by UI-3 and UI-5
**Spec:** [Missing UIs](../10-missing-uis.md) §6 (§3.2 defines the dialog)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the admin a screen for rotating the key that authenticates the entire agent fleet, including whether the fleet has caught up before the overlap window closes.

**Architecture:** A self-contained panel on the Agents page, backed by the existing `GET /agents/server-key/status` extended with fleet-adoption counts derived from columns that already exist for this purpose, plus a drill-down endpoint listing the agents not yet on the successor key. The rotation action goes through a new shared type-to-confirm dialog.

**Tech Stack:** React 18, vitest + @testing-library/react; FastAPI, SQLAlchemy, pytest.

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include these.

- **Every new surface is its own file. Host files gain a registration line, not a feature.**
- **Wording is a constraint, not polish.** `models.py:432-450` states that the server sees only which key an agent's *handshakes have used*, never whether the agent holds the successor. Copy therefore says **"authenticated with successor key"**, never "has the successor key", and **"not seen since rotation"**, never anything predicting failure.
- **Adoption counts must be one aggregate query.** `agents.py:284`'s `_latest_samples` exists because query count must not scale with fleet size, and a test pins that count. This follows that precedent.
- **Rotate must not offer an action the server will refuse.** `POST /agents/server-key/rotate` returns 409 while an overlap is active; the button is disabled with its reason stated, and a racing 409 refetches rather than erroring.
- **No fetch failure may render as an empty or idle-looking panel.** An error state is required and is distinct from "no rotation in progress" — the two must never look alike, because one means *safe* and the other means *unknown*.
- **Never render key material.** The endpoints return fingerprints only; the panel must not acquire or display anything else.

---

## Design change from the spec: per-agent key state

**Spec §6.3 says:** *"During an overlap, `AgentsPage`'s table gains a key-state column carrying the same three values."*

**This plan does not do that**, for a reason found while reading the code. `FleetTable.jsx:18-21` documents its column list as a contract:

> *Column order is a contract with FleetRow: its collapsed variants (offline, telemetry-off, pending) span these columns by count, so a column added here needs FleetRow's spans moved in step.*

Those spans are hand-counted integers — `METRIC_COLUMN_SPAN = 5` and `PENDING_DETAIL_SPAN = 8` (`FleetRow.jsx:39-40`). A **conditional** twelfth column would make both dynamic, in the app's densest and most carefully tuned table, and would reflow the whole fleet view the moment a rotation starts.

Instead, per-agent key state is a **drill-down inside the rotation panel** (Task 3 and Task 6): the counts are clickable, and "not yet on the successor" expands to the agents that need attention. Same information, zero risk to the fleet table, and better placed — you reason about key state while looking at the rotation, not while scanning CPU and memory.

If you would rather have the column, say so before Task 6 and it becomes its own slice; do not attempt both.

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `apps/frontend/src/components/common/HighRiskConfirmDialog.jsx` | Type-to-confirm dialog with optional reason. Shared primitive; UI-3 and UI-5 consume it. |
| `apps/frontend/src/components/agents/ServerKeyRotationPanel.jsx` | The panel: status, adoption, drill-down, rotate. |
| `apps/frontend/src/__tests__/high-risk-confirm-dialog.test.jsx` | Dialog behaviour. |
| `apps/frontend/src/__tests__/server-key-rotation-panel.test.jsx` | Panel states and the 409 path. |
| `docs/agent-key-rotation.md` | Operator runbook. |

**Modify**

| File | Change |
|---|---|
| `apps/backend/src/app/schemas/agents.py:273` | `ServerKeyRotationStatus` gains a `fleet` block. |
| `apps/backend/src/app/api/agents.py:233-281` | `_rotation_status` takes a db session and computes counts; new pending-agents route. |
| `apps/frontend/src/api/agents.js` | `getServerKeyStatus`, `rotateServerKey`, `getServerKeyPendingAgents`. |
| `apps/frontend/src/pages/AgentsPage.jsx` | One import, one `isAdmin` line, one render line. |
| `apps/backend/tests/api/test_agents_api.py` | Adoption-count tests incl. the query-count pin. |
| `docs/1.0.0-incomplete-features.md` | INC-13 resolution note. |
| `mkdocs.yml` | Nav entry. |

---

## Task 1: HighRiskConfirmDialog

The shared primitive from spec §3.2. Built here because UI-2 is its first consumer; UI-3 and UI-5 reuse it unchanged.

**Files:**
- Create: `apps/frontend/src/components/common/HighRiskConfirmDialog.jsx`
- Test: `apps/frontend/src/__tests__/high-risk-confirm-dialog.test.jsx`

**Interfaces:**
- Consumes: nothing
- Produces: default export `HighRiskConfirmDialog`, props:
  - `open: bool`
  - `title: string`
  - `body: node`
  - `confirmPhrase: string` — must be typed exactly to enable Confirm
  - `reason: {required: bool, minLength: number, label: string} | null`
  - `confirmLabel: string` (default `'Confirm'`)
  - `busy: bool`
  - `error: string | null`
  - `onConfirm: ({reason: string}) => void`
  - `onCancel: () => void`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/high-risk-confirm-dialog.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import HighRiskConfirmDialog from '../components/common/HighRiskConfirmDialog.jsx';

const baseProps = {
  open: true,
  title: 'Rotate the agent server key',
  body: 'This starts a 7-day overlap.',
  confirmPhrase: 'ROTATE',
  reason: null,
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

beforeEach(() => vi.clearAllMocks());

describe('HighRiskConfirmDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<HighRiskConfirmDialog {...baseProps} open={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('disables confirm until the phrase is typed exactly', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    const confirm = screen.getByRole('button', { name: /^confirm$/i });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    expect(confirm).toBeEnabled();
  });

  it('rejects a near-miss phrase, including wrong case', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    const input = screen.getByLabelText(/type rotate to confirm/i);

    fireEvent.change(input, { target: { value: 'rotate' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(input, { target: { value: 'ROTATE ' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();
  });

  it('requires the reason to meet its minimum length when one is configured', () => {
    render(
      <HighRiskConfirmDialog
        {...baseProps}
        confirmPhrase="REPAIR_AUDIT_CHAIN"
        reason={{ required: true, minLength: 12, label: 'Reason' }}
      />
    );
    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'too short' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Reason'), {
      target: { value: 'chain broken after restore' },
    });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeEnabled();
  });

  it('passes the reason to onConfirm', () => {
    render(
      <HighRiskConfirmDialog
        {...baseProps}
        reason={{ required: true, minLength: 12, label: 'Reason' }}
      />
    );
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.change(screen.getByLabelText('Reason'), {
      target: { value: 'planned quarterly rotation' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    expect(baseProps.onConfirm).toHaveBeenCalledWith({ reason: 'planned quarterly rotation' });
  });

  it('passes an empty reason when none is configured', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(baseProps.onConfirm).toHaveBeenCalledWith({ reason: '' });
  });

  it('surfaces a server error without closing', () => {
    render(<HighRiskConfirmDialog {...baseProps} error="A rotation is already active" />);
    expect(screen.getByRole('alert')).toHaveTextContent('A rotation is already active');
  });

  it('disables both buttons while busy', () => {
    render(<HighRiskConfirmDialog {...baseProps} busy />);
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  it('cancels on the cancel button', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(baseProps.onCancel).toHaveBeenCalled();
  });

  it('clears typed input when reopened', () => {
    const { rerender } = render(<HighRiskConfirmDialog {...baseProps} />);
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    rerender(<HighRiskConfirmDialog {...baseProps} open={false} />);
    rerender(<HighRiskConfirmDialog {...baseProps} open />);

    expect(screen.getByLabelText(/type rotate to confirm/i)).toHaveValue('');
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/high-risk-confirm-dialog.test.jsx`
Expected: FAIL — cannot resolve `../components/common/HighRiskConfirmDialog.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/common/HighRiskConfirmDialog.jsx`:

```jsx
import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';

/**
 * Confirmation for actions whose consequences are hard or impossible to undo.
 *
 * The typed phrase is always the thing you would get wrong: the audit chain's
 * own REPAIR_AUDIT_CHAIN authorization string, a token's label, the word
 * ROTATE. Where the server already states a contract — the repair endpoint
 * requires that exact string and a reason of at least 12 characters — this
 * dialog ENFORCES that contract rather than restating it, so the two cannot
 * drift. Client validation makes the 4xx unreachable in normal use; it does not
 * assume it away, and `error` renders whatever the server said.
 */
function HighRiskConfirmDialog({
  open,
  title,
  body,
  confirmPhrase,
  reason = null,
  confirmLabel = 'Confirm',
  busy = false,
  error = null,
  onConfirm,
  onCancel,
}) {
  const [typed, setTyped] = useState('');
  const [reasonText, setReasonText] = useState('');

  // A reopened dialog must never inherit the previous attempt's typing —
  // that would let a second, unintended confirm start already-armed.
  useEffect(() => {
    if (!open) {
      setTyped('');
      setReasonText('');
    }
  }, [open]);

  if (!open) return null;

  const phraseOk = typed === confirmPhrase;
  const reasonOk =
    !reason || !reason.required || reasonText.trim().length >= (reason.minLength || 0);
  const canConfirm = phraseOk && reasonOk && !busy;

  const phraseLabel = `Type ${confirmPhrase} to confirm`;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.55)',
      }}
      onClick={busy ? undefined : onCancel}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border, rgba(255,255,255,0.12))',
          borderRadius: 10,
          padding: '24px 28px',
          maxWidth: 520,
          width: '92%',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginTop: 0, fontSize: 16 }}>{title}</h2>
        <div style={{ fontSize: 13, opacity: 0.85, marginBottom: 16 }}>{body}</div>

        {error && (
          <div role="alert" style={{ marginBottom: 12, color: 'var(--color-danger, #f85149)' }}>
            {error}
          </div>
        )}

        <label htmlFor="high-risk-phrase" style={{ display: 'block', fontSize: 12 }}>
          {phraseLabel}
        </label>
        <input
          id="high-risk-phrase"
          value={typed}
          disabled={busy}
          autoComplete="off"
          onChange={(e) => setTyped(e.target.value)}
          style={{ width: '100%', marginBottom: 12 }}
        />

        {reason && (
          <>
            <label htmlFor="high-risk-reason" style={{ display: 'block', fontSize: 12 }}>
              {reason.label}
            </label>
            <textarea
              id="high-risk-reason"
              value={reasonText}
              disabled={busy}
              rows={3}
              onChange={(e) => setReasonText(e.target.value)}
              style={{ width: '100%', marginBottom: 4 }}
            />
            <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 12 }}>
              At least {reason.minLength} characters. Recorded in the audit log.
            </div>
          </>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            disabled={!canConfirm}
            onClick={() => onConfirm({ reason: reasonText.trim() })}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

HighRiskConfirmDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string.isRequired,
  body: PropTypes.node,
  confirmPhrase: PropTypes.string.isRequired,
  reason: PropTypes.shape({
    required: PropTypes.bool,
    minLength: PropTypes.number,
    label: PropTypes.string,
  }),
  confirmLabel: PropTypes.string,
  busy: PropTypes.bool,
  error: PropTypes.string,
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default HighRiskConfirmDialog;
```

Note: `confirmLabel` defaults to `'Confirm'`, and the tests match on `/^confirm$/i`. If a later consumer passes a custom label, its own tests must match that label.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/high-risk-confirm-dialog.test.jsx`
Expected: PASS — 10 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/common/HighRiskConfirmDialog.jsx apps/frontend/src/__tests__/high-risk-confirm-dialog.test.jsx
git commit -m "feat(ui): add HighRiskConfirmDialog shared primitive (INC-12, INC-13, INC-14)"
```

---

## Task 2: Fleet adoption counts on the rotation status

**Files:**
- Modify: `apps/backend/src/app/schemas/agents.py:273-282`
- Modify: `apps/backend/src/app/api/agents.py:233-281`
- Test: `apps/backend/tests/api/test_agents_api.py`

**Interfaces:**
- Consumes: `Agent.server_pk_current_pinned_at`, `Agent.server_pk_successor_pinned_at` (`models.py:446-450`)
- Produces: `ServerKeyRotationStatus.fleet: ServerKeyFleetAdoption | None` where
  ```python
  class ServerKeyFleetAdoption(BaseModel):
      total: int
      successor: int          # handshaked against the successor since rotation start
      current: int            # handshaked since rotation start, still on current
      unseen: int             # no handshake since rotation start
  ```
  `fleet` is `None` when no rotation is active.

**Bucketing rule (stated once, implemented once):** an agent counts as `successor` when `server_pk_successor_pinned_at >= started_at`; otherwise as `current` when `server_pk_current_pinned_at >= started_at`; otherwise `unseen`. Revoked agents are excluded — a revoked agent will never handshake again and would inflate `unseen` forever.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/api/test_agents_api.py`:

```python
# ── server-key rotation: fleet adoption (INC-13) ──────────────────────────────


@pytest.mark.asyncio
async def test_rotation_status_omits_fleet_when_no_rotation_active(client, auth_headers):
    resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["fleet"] is None


@pytest.mark.asyncio
async def test_rotation_status_buckets_the_fleet_by_key_last_handshaked(
    client, auth_headers, factories, db_session
):
    """The three buckets the panel shows, and the boundary that separates them.

    `started_at` is the divider: a pin recorded BEFORE this rotation began says
    nothing about this rotation, so such an agent is `unseen`, not `current`.
    """
    from datetime import timedelta

    from app.core.time import utcnow

    on_successor = factories.agent(status="active")
    on_current = factories.agent(status="active")
    never_seen = factories.agent(status="active")
    stale_pin = factories.agent(status="active")
    revoked = factories.agent(status="revoked")

    rotate = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert rotate.status_code == 201
    started_at = utcnow()

    on_successor.server_pk_successor_pinned_at = started_at + timedelta(minutes=1)
    on_current.server_pk_current_pinned_at = started_at + timedelta(minutes=1)
    # Pinned long before this rotation started — tells us nothing about it.
    stale_pin.server_pk_current_pinned_at = started_at - timedelta(days=30)
    revoked.server_pk_successor_pinned_at = started_at + timedelta(minutes=1)
    db_session.flush()

    resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    assert resp.status_code == 200
    fleet = resp.json()["fleet"]

    assert fleet["successor"] == 1
    assert fleet["current"] == 1
    assert fleet["unseen"] == 2, "never-handshaked and stale-pin both count as unseen"
    assert fleet["total"] == 4, "revoked agents are excluded from every bucket"


@pytest.mark.asyncio
async def test_rotation_status_adoption_is_one_query_regardless_of_fleet_size(
    client, auth_headers, factories
):
    """Same contract as test_presence_issues_single_query_regardless_of_fleet_size:
    the panel must not cost one query per agent. See _latest_samples' docstring
    at api/agents.py:284 for why this is pinned rather than merely intended."""
    for _ in range(20):
        factories.agent(status="active")

    rotate = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert rotate.status_code == 201

    with _capture_sql() as statements:
        resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["fleet"]["total"] == 20
    agent_selects = [
        s
        for s in statements
        if " agents" in s.lower() and s.lstrip().upper().startswith("SELECT")
    ]
    assert len(agent_selects) == 1, agent_selects


@pytest.mark.asyncio
async def test_rotation_status_never_returns_key_material(client, auth_headers):
    rotate = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert rotate.status_code == 201
    body = rotate.json()
    serialized = json.dumps(body)
    assert "priv" not in serialized.lower()
    assert set(body) <= {
        "active",
        "current_key_fingerprint",
        "successor_key_fingerprint",
        "started_at",
        "overlap_expires_at",
        "fleet",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_agents_api.py -k "rotation_status" -v`
Expected: FAIL — `KeyError: 'fleet'` / the response has no `fleet` key.

- [ ] **Step 3: Add the schema**

In `apps/backend/src/app/schemas/agents.py`, immediately above `ServerKeyRotationStatus` (line 273):

```python
class ServerKeyFleetAdoption(BaseModel):
    """How much of the fleet has switched, for an in-progress rotation.

    Derived from `Agent.server_pk_current_pinned_at` /
    `server_pk_successor_pinned_at`, which exist for exactly this (see the
    comment at db/models.py:432-450). Those columns record which key an
    agent's handshakes have USED — the server has no visibility into whether
    an agent's local state directory holds the successor key. Field names and
    all UI copy must preserve that distinction.
    """

    total: int
    successor: int
    current: int
    unseen: int
```

Then add to `ServerKeyRotationStatus`:

```python
    fleet: ServerKeyFleetAdoption | None = None
```

- [ ] **Step 4: Compute the counts in one query**

In `apps/backend/src/app/api/agents.py`, replace `_rotation_status` (line 233) with:

```python
def _fleet_adoption(db: Session, started_at: datetime) -> ServerKeyFleetAdoption:
    """Bucket the fleet by which server key each agent last handshaked against.

    ONE aggregate query, not one per agent — same contract as _latest_samples
    above, pinned by test_rotation_status_adoption_is_one_query_regardless_of_
    fleet_size. Counting in SQL rather than loading rows keeps it independent
    of fleet size in memory as well as in round trips.

    A pin recorded before `started_at` belongs to a previous rotation and says
    nothing about this one, so it falls through to `unseen`. Revoked agents are
    excluded: they will never handshake again and would inflate `unseen`
    permanently, making a finished rollout look stuck.
    """
    successor_pinned = and_(
        Agent.server_pk_successor_pinned_at.isnot(None),
        Agent.server_pk_successor_pinned_at >= started_at,
    )
    current_pinned = and_(
        Agent.server_pk_current_pinned_at.isnot(None),
        Agent.server_pk_current_pinned_at >= started_at,
    )
    row = db.execute(
        select(
            func.count().label("total"),
            func.count().filter(successor_pinned).label("successor"),
            func.count().filter(and_(~successor_pinned, current_pinned)).label("current"),
            func.count()
            .filter(and_(~successor_pinned, ~current_pinned))
            .label("unseen"),
        ).where(Agent.status != "revoked")
    ).one()
    return ServerKeyFleetAdoption(
        total=row.total,
        successor=row.successor,
        current=row.current,
        unseen=row.unseen,
    )


def _rotation_status(
    state: agent_crypto.ServerKeyRotationState,
    db: Session | None = None,
) -> ServerKeyRotationStatus:
    fleet = None
    if state.rotation_active and state.started_at is not None and db is not None:
        fleet = _fleet_adoption(db, state.started_at)
    return ServerKeyRotationStatus(
        active=state.rotation_active,
        current_key_fingerprint=hashlib.sha256(state.current_pub).hexdigest()[:32],
        successor_key_fingerprint=(
            hashlib.sha256(state.successor_pub).hexdigest()[:32]
            if state.successor_pub is not None
            else None
        ),
        started_at=state.started_at,
        overlap_expires_at=state.overlap_expires_at,
        fleet=fleet,
    )
```

Update both call sites to pass `db`:

- `get_server_key_rotation_status` (line 255): `return _rotation_status(agent_crypto.load_server_key_rotation_state(db), db)`
- `post_server_key_rotate` (line 281): `return _rotation_status(state, db)`

Add to the imports at the top of `apps/backend/src/app/api/agents.py`:

```python
from sqlalchemy import and_, func, select   # `select` is already imported — add and_, func
```

and add `ServerKeyFleetAdoption` to the existing `from app.schemas.agents import (...)` block at line 53.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_agents_api.py -k "rotation" -v`
Expected: PASS — the four new tests plus the pre-existing rotation tests at line 1182 onward, which must not regress.

If `func.count().filter(...)` raises on your SQLAlchemy version, the equivalent is `func.sum(case((cond, 1), else_=0))`. Keep it one query either way — that is the point of the test.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/schemas/agents.py apps/backend/src/app/api/agents.py apps/backend/tests/api/test_agents_api.py
git commit -m "feat(agents): report fleet key-rotation adoption counts (INC-13)"
```

---

## Task 3: Pending-agents drill-down endpoint

The actionable half: *which* agents have not switched, so an admin can chase them before the window closes.

**Files:**
- Modify: `apps/backend/src/app/api/agents.py`, `apps/backend/src/app/schemas/agents.py`
- Test: `apps/backend/tests/api/test_agents_api.py`

**Interfaces:**
- Produces: `GET /agents/server-key/pending` → `list[ServerKeyPendingAgent]`, admin-only, capped at 200 rows
  ```python
  class ServerKeyPendingAgent(BaseModel):
      id: int
      hostname: str | None
      name: str | None
      last_seen_at: datetime | None
      bucket: str   # "current" | "unseen"
  ```
  Returns `[]` when no rotation is active — an empty list, never a 409, because "nothing pending" and "no rotation" both mean *nothing to chase*.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/api/test_agents_api.py`:

```python
@pytest.mark.asyncio
async def test_pending_agents_is_empty_without_an_active_rotation(
    client, auth_headers, factories
):
    factories.agent(status="active")
    resp = await client.get("/api/v1/agents/server-key/pending", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_pending_agents_lists_only_agents_not_on_the_successor(
    client, auth_headers, factories, db_session
):
    from datetime import timedelta

    from app.core.time import utcnow

    switched = factories.agent(status="active", hostname="switched-01")
    lagging = factories.agent(status="active", hostname="lagging-01")
    factories.agent(status="active", hostname="never-01")

    assert (
        await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    ).status_code == 201
    started_at = utcnow()

    switched.server_pk_successor_pinned_at = started_at + timedelta(minutes=1)
    lagging.server_pk_current_pinned_at = started_at + timedelta(minutes=1)
    db_session.flush()

    resp = await client.get("/api/v1/agents/server-key/pending", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()

    by_host = {r["hostname"]: r for r in rows}
    assert set(by_host) == {"lagging-01", "never-01"}
    assert by_host["lagging-01"]["bucket"] == "current"
    assert by_host["never-01"]["bucket"] == "unseen"


@pytest.mark.asyncio
async def test_pending_agents_requires_admin(client, viewer_headers):
    resp = await client.get("/api/v1/agents/server-key/pending", headers=viewer_headers)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_agents_api.py -k "pending_agents" -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the schema**

In `apps/backend/src/app/schemas/agents.py`, after `ServerKeyFleetAdoption`:

```python
class ServerKeyPendingAgent(BaseModel):
    """One agent that has not yet handshaked against the successor key.

    `bucket` mirrors ServerKeyFleetAdoption's naming: "current" means it has
    handshaked since the rotation began but against the outgoing key; "unseen"
    means it has not handshaked at all since the rotation began. Neither states
    anything about what the agent holds locally.
    """

    id: int
    hostname: str | None
    name: str | None
    last_seen_at: datetime | None
    bucket: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Add the route**

In `apps/backend/src/app/api/agents.py`, directly after `post_server_key_rotate`:

```python
# Cap borrowed from the fleet-listing routes: a drill-down exists to be acted
# on, and a list longer than this is a rollout problem, not a UI problem.
_PENDING_AGENT_LIMIT = 200


@router.get("/server-key/pending", response_model=list[ServerKeyPendingAgent])
def get_server_key_pending_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Agents that have not yet authenticated with the successor server key.

    The actionable half of `/server-key/status`'s counts: an admin deciding
    whether to let an overlap window close needs the names, not just the
    number. Empty (not an error) when no rotation is in progress — "nothing to
    chase" is the same answer either way.
    """
    state = agent_crypto.load_server_key_rotation_state(db)
    if not state.rotation_active or state.started_at is None:
        return []

    started_at = state.started_at
    successor_pinned = and_(
        Agent.server_pk_successor_pinned_at.isnot(None),
        Agent.server_pk_successor_pinned_at >= started_at,
    )
    current_pinned = and_(
        Agent.server_pk_current_pinned_at.isnot(None),
        Agent.server_pk_current_pinned_at >= started_at,
    )
    rows = (
        db.execute(
            select(
                Agent.id,
                Agent.hostname,
                Agent.name,
                Agent.last_seen_at,
                case((current_pinned, "current"), else_="unseen").label("bucket"),
            )
            .where(Agent.status != "revoked", ~successor_pinned)
            .order_by(Agent.last_seen_at.desc().nulls_last())
            .limit(_PENDING_AGENT_LIMIT)
        )
        .all()
    )
    return [
        ServerKeyPendingAgent(
            id=r.id,
            hostname=r.hostname,
            name=r.name,
            last_seen_at=r.last_seen_at,
            bucket=r.bucket,
        )
        for r in rows
    ]
```

Add `case` to the SQLAlchemy import line and `ServerKeyPendingAgent` to the schema import block.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_agents_api.py -k "pending_agents" -v`
Expected: PASS — 3 tests.

- [ ] **Step 6: Run the whole agents suite**

Run: `pytest apps/backend/tests/api/test_agents_api.py -v`
Expected: PASS — no regressions.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/api/agents.py apps/backend/src/app/schemas/agents.py apps/backend/tests/api/test_agents_api.py
git commit -m "feat(agents): add server-key pending-agents drill-down (INC-13)"
```

---

## Task 4: Frontend API bindings

**Files:**
- Modify: `apps/frontend/src/api/agents.js`
- Test: `apps/frontend/src/__tests__/agents-server-key-api.test.js`

**Interfaces:**
- Produces: `getServerKeyStatus()`, `rotateServerKey()`, `getServerKeyPendingAgents()`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agents-server-key-api.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

import client from '../api/client.jsx';
import { getServerKeyStatus, rotateServerKey, getServerKeyPendingAgents } from '../api/agents';

beforeEach(() => vi.clearAllMocks());

describe('server-key API bindings', () => {
  it('reads the rotation status', () => {
    getServerKeyStatus();
    expect(client.get).toHaveBeenCalledWith('/agents/server-key/status');
  });

  it('starts a rotation with POST and no body', () => {
    rotateServerKey();
    expect(client.post).toHaveBeenCalledWith('/agents/server-key/rotate');
  });

  it('reads the pending-agent drill-down', () => {
    getServerKeyPendingAgents();
    expect(client.get).toHaveBeenCalledWith('/agents/server-key/pending');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/agents-server-key-api.test.js`
Expected: FAIL — `getServerKeyStatus is not a function`.

- [ ] **Step 3: Write minimal implementation**

Append to `apps/frontend/src/api/agents.js`:

```javascript
// INC-13: server identity-key rotation. `status` and `rotate` both return
// ServerKeyRotationStatus — fingerprints and timing only, never key material,
// plus a `fleet` adoption block while a rotation is active. `pending` is the
// actionable drill-down behind those counts.
export const getServerKeyStatus = () => client.get('/agents/server-key/status');
// 201 on success; 409 while a prior rotation's overlap is still running — the
// server allows exactly one rotation in flight.
export const rotateServerKey = () => client.post('/agents/server-key/rotate');
export const getServerKeyPendingAgents = () => client.get('/agents/server-key/pending');
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/agents-server-key-api.test.js`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/agents.js apps/frontend/src/__tests__/agents-server-key-api.test.js
git commit -m "feat(agents): add server-key rotation API bindings (INC-13)"
```

---

## Task 5: ServerKeyRotationPanel

**Files:**
- Create: `apps/frontend/src/components/agents/ServerKeyRotationPanel.jsx`
- Test: `apps/frontend/src/__tests__/server-key-rotation-panel.test.jsx`

**Interfaces:**
- Consumes: Task 1's dialog, Task 4's bindings, `useToast`
- Produces: default export `ServerKeyRotationPanel` — no props; owns its own fetching

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/server-key-rotation-panel.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../api/agents', () => ({
  getServerKeyStatus: vi.fn(),
  rotateServerKey: vi.fn(),
  getServerKeyPendingAgents: vi.fn(),
}));

import {
  getServerKeyStatus,
  rotateServerKey,
  getServerKeyPendingAgents,
} from '../api/agents';
import ServerKeyRotationPanel from '../components/agents/ServerKeyRotationPanel.jsx';

const IDLE = {
  active: false,
  current_key_fingerprint: 'a3f9c1e27b40d5a3f9c1e27b40d5a3f9',
  successor_key_fingerprint: null,
  started_at: null,
  overlap_expires_at: null,
  fleet: null,
};

const ACTIVE = {
  active: true,
  current_key_fingerprint: 'a3f9c1e27b40d5a3f9c1e27b40d5a3f9',
  successor_key_fingerprint: 'e77b0a941c2f8ee77b0a941c2f8ee77b',
  started_at: '2026-08-20T02:00:00Z',
  overlap_expires_at: '2026-08-27T02:00:00Z',
  fleet: { total: 38, successor: 27, current: 6, unseen: 5 },
};

beforeEach(() => {
  vi.clearAllMocks();
  getServerKeyPendingAgents.mockResolvedValue({ data: [] });
});

describe('ServerKeyRotationPanel', () => {
  it('shows the current fingerprint and an enabled Rotate when idle', async () => {
    getServerKeyStatus.mockResolvedValue({ data: IDLE });

    render(<ServerKeyRotationPanel />);

    await waitFor(() => expect(screen.getByText(/no rotation in progress/i)).toBeInTheDocument());
    expect(screen.getByText(/a3f9c1e2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /rotate key/i })).toBeEnabled();
  });

  it('disables Rotate during an overlap and says why', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);

    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /rotate key/i })).toBeDisabled();
    expect(screen.getByText(/one rotation in flight/i)).toBeInTheDocument();
  });

  it('reports adoption without claiming an agent holds the successor key', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);

    await waitFor(() =>
      expect(screen.getByText(/27 authenticated with successor/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/6 still on current/i)).toBeInTheDocument();
    expect(screen.getByText(/5 not seen since rotation/i)).toBeInTheDocument();
    expect(screen.queryByText(/has the successor/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/will fail/i)).not.toBeInTheDocument();
  });

  it('expands the drill-down of agents not yet on the successor', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });
    getServerKeyPendingAgents.mockResolvedValue({
      data: [
        { id: 1, hostname: 'lagging-01', name: null, last_seen_at: null, bucket: 'current' },
        { id: 2, hostname: 'never-01', name: null, last_seen_at: null, bucket: 'unseen' },
      ],
    });

    render(<ServerKeyRotationPanel />);
    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /show agents/i }));

    await waitFor(() => expect(screen.getByText('lagging-01')).toBeInTheDocument());
    expect(screen.getByText('never-01')).toBeInTheDocument();
  });

  it('rotates only after the phrase is typed, then refetches', async () => {
    getServerKeyStatus.mockResolvedValueOnce({ data: IDLE }).mockResolvedValue({ data: ACTIVE });
    rotateServerKey.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);
    await waitFor(() => expect(screen.getByText(/no rotation in progress/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /rotate key/i }));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(rotateServerKey).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(rotateServerKey).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());
  });

  it('treats a racing 409 as state, not as an error', async () => {
    getServerKeyStatus.mockResolvedValueOnce({ data: IDLE }).mockResolvedValue({ data: ACTIVE });
    rotateServerKey.mockRejectedValue({ response: { status: 409 } });

    render(<ServerKeyRotationPanel />);
    await waitFor(() => expect(screen.getByText(/no rotation in progress/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /rotate key/i }));
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('renders an error distinct from the idle state when status cannot be read', async () => {
    getServerKeyStatus.mockRejectedValue(new Error('boom'));

    render(<ServerKeyRotationPanel />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    // "unknown" must never be mistaken for "no rotation in progress" — one is
    // safe and the other is not.
    expect(screen.queryByText(/no rotation in progress/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/server-key-rotation-panel.test.jsx`
Expected: FAIL — cannot resolve `../components/agents/ServerKeyRotationPanel.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/agents/ServerKeyRotationPanel.jsx`:

```jsx
import React, { useCallback, useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import {
  getServerKeyStatus,
  getServerKeyPendingAgents,
  rotateServerKey,
} from '../../api/agents';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import { useToast } from '../common/Toast';

const SHORT_FP = (fp) => (fp ? `${fp.slice(0, 8)}…${fp.slice(-6)}` : '—');

function formatWhen(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

function remaining(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms) || ms <= 0) return 'expired';
  const days = Math.floor(ms / 86400000);
  const hours = Math.floor((ms % 86400000) / 3600000);
  return days > 0 ? `${days}d ${hours}h` : `${hours}h`;
}

/**
 * Rotation of the key that authenticates the entire agent fleet (INC-13).
 *
 * Copy discipline, per db/models.py:432-450: the server knows only which key
 * each agent's HANDSHAKES have used, never whether the agent holds the
 * successor locally. Nothing here may say an agent "has" the key, and nothing
 * may predict failure for an agent that has not been seen.
 */
function ServerKeyRotationPanel() {
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotateError, setRotateError] = useState(null);
  const [pending, setPending] = useState(null);
  const [pendingOpen, setPendingOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getServerKeyStatus();
      setStatus(res.data);
    } catch (err) {
      // Distinct from the idle state on purpose: "no rotation in progress"
      // means safe, "cannot read status" means unknown.
      setError(err?.userMessage || 'Could not read the server-key rotation status.');
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRotate = useCallback(async () => {
    setRotating(true);
    setRotateError(null);
    try {
      await rotateServerKey();
      setConfirmOpen(false);
      toast.success('Rotation started. The successor key was pushed to connected agents.');
      await load();
    } catch (err) {
      // 409 means a rotation is already running — that is state, not failure.
      // Show the operator the rotation rather than an error about it.
      if (err?.response?.status === 409) {
        setConfirmOpen(false);
        await load();
        return;
      }
      setRotateError(err?.userMessage || 'Could not start the rotation.');
    } finally {
      setRotating(false);
    }
  }, [toast, load]);

  const showPending = useCallback(async () => {
    setPendingOpen(true);
    if (pending != null) return;
    try {
      const res = await getServerKeyPendingAgents();
      setPending(res.data || []);
    } catch (err) {
      toast.error(err?.userMessage || 'Could not list pending agents.');
      setPendingOpen(false);
    }
  }, [pending, toast]);

  if (loading) return null;

  if (error) {
    return (
      <section className="agents-page__key-panel" role="alert">
        <p>{error}</p>
        <button type="button" className="btn btn-sm" onClick={load}>
          Retry
        </button>
      </section>
    );
  }

  const active = !!status?.active;
  const fleet = status?.fleet;

  return (
    <section className="agents-page__key-panel">
      <header style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <KeyRound size={16} />
        <strong>Agent server key</strong>
        <span className="fleet-muted">
          {active ? 'rotation in progress' : 'no rotation in progress'}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          style={{ marginLeft: 'auto' }}
          disabled={active}
          onClick={() => {
            setRotateError(null);
            setConfirmOpen(true);
          }}
        >
          Rotate key…
        </button>
      </header>

      <dl style={{ display: 'flex', gap: 26, flexWrap: 'wrap', marginTop: 8 }}>
        <div>
          <dt className="fleet-muted">Current fingerprint</dt>
          <dd>{SHORT_FP(status?.current_key_fingerprint)}</dd>
        </div>
        {active && (
          <>
            <div>
              <dt className="fleet-muted">Successor fingerprint</dt>
              <dd>{SHORT_FP(status?.successor_key_fingerprint)}</dd>
            </div>
            <div>
              <dt className="fleet-muted">Started</dt>
              <dd>{formatWhen(status?.started_at)}</dd>
            </div>
            <div>
              <dt className="fleet-muted">Overlap ends</dt>
              <dd>
                {formatWhen(status?.overlap_expires_at)}
                {remaining(status?.overlap_expires_at)
                  ? ` (in ${remaining(status.overlap_expires_at)})`
                  : ''}
              </dd>
            </div>
          </>
        )}
      </dl>

      {active && fleet && (
        <div style={{ marginTop: 12 }}>
          <ul style={{ display: 'flex', gap: 20, listStyle: 'none', padding: 0, margin: 0 }}>
            <li>{fleet.successor} authenticated with successor</li>
            <li>{fleet.current} still on current</li>
            <li>{fleet.unseen} not seen since rotation</li>
          </ul>
          {fleet.current + fleet.unseen > 0 && (
            <button type="button" className="btn btn-sm" onClick={showPending}>
              Show agents
            </button>
          )}
          {pendingOpen && pending && (
            <ul style={{ marginTop: 8 }}>
              {pending.map((a) => (
                <li key={a.id}>
                  {a.hostname || a.name || `Agent ${a.id}`}{' '}
                  <span className="fleet-muted">
                    {a.bucket === 'current' ? 'still on current' : 'not seen since rotation'}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="fleet-muted" style={{ fontSize: 11, marginTop: 8 }}>
            Counts reflect which key each agent&apos;s handshakes have used. The server has no
            visibility into what an agent holds locally.
          </p>
        </div>
      )}

      {active && (
        <p className="fleet-muted" style={{ fontSize: 11, marginTop: 8 }}>
          Rotate is unavailable until the overlap ends — the server allows one rotation in flight.
        </p>
      )}

      <HighRiskConfirmDialog
        open={confirmOpen}
        title="Rotate the agent server key"
        body={
          <>
            <p>
              A fresh successor keypair is generated and pushed immediately to every connected
              agent. Both keys are accepted for a 7-day overlap, after which the current key is
              retired.
            </p>
            <p>
              An agent that stays offline for the entire overlap window will not authenticate once
              it ends, and will need re-enrolling.
            </p>
          </>
        }
        confirmPhrase="ROTATE"
        confirmLabel="Confirm"
        busy={rotating}
        error={rotateError}
        onConfirm={handleRotate}
        onCancel={() => setConfirmOpen(false)}
      />
    </section>
  );
}

export default ServerKeyRotationPanel;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/server-key-rotation-panel.test.jsx`
Expected: PASS — 7 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/agents/ServerKeyRotationPanel.jsx apps/frontend/src/__tests__/server-key-rotation-panel.test.jsx
git commit -m "feat(agents): add server-key rotation panel (INC-13)"
```

---

## Task 6: Mount the panel on the Agents page

**Files:**
- Modify: `apps/frontend/src/pages/AgentsPage.jsx`
- Modify: `apps/frontend/src/styles/agents.css`
- Test: `apps/frontend/src/__tests__/agents-page.test.jsx` (existing file — add cases)

`AgentsPage` is documented at its top as *"orchestration and nothing else"*. It gains three lines: an import, an `isAdmin` derivation, and one conditional render. Nothing else moves.

- [ ] **Step 1: Write the failing tests**

Append to `apps/frontend/src/__tests__/agents-page.test.jsx` (inside the existing top-level `describe`; if the file mocks `../api/agents`, add the three server-key functions to that mock as `vi.fn()` returning resolved empty data):

```jsx
  it('shows the server-key rotation panel to an admin', async () => {
    renderAgentsPage({ user: { role: 'admin' } });
    await waitFor(() =>
      expect(screen.getByTestId('server-key-rotation-panel')).toBeInTheDocument()
    );
  });

  it('hides the server-key rotation panel from a non-admin', async () => {
    renderAgentsPage({ user: { role: 'viewer' } });
    await waitFor(() => expect(screen.getByRole('heading', { name: /agents/i })).toBeInTheDocument());
    expect(screen.queryByTestId('server-key-rotation-panel')).not.toBeInTheDocument();
  });
```

Add this mock alongside the file's existing mocks:

```jsx
vi.mock('../components/agents/ServerKeyRotationPanel', () => ({
  default: () => <div data-testid="server-key-rotation-panel" />,
}));
```

If `agents-page.test.jsx` has no `renderAgentsPage` helper or auth mock, add one that wraps the page in the same `AuthContext` provider the file already uses for other tests; do not invent a second auth mocking style in a file that has one.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix apps/frontend test -- src/__tests__/agents-page.test.jsx`
Expected: FAIL — `server-key-rotation-panel` not found.

- [ ] **Step 3: Add the three lines**

In `apps/frontend/src/pages/AgentsPage.jsx`:

Imports:

```javascript
import { useAuth } from '../context/AuthContext';
import ServerKeyRotationPanel from '../components/agents/ServerKeyRotationPanel';
```

Inside the component, next to the other hook calls:

```javascript
  // Same derivation as SettingsPage.jsx:251 — role, is_admin and is_superuser
  // are three ways of saying admin in this codebase, and the panel's endpoints
  // are all require_role("admin").
  const { user } = useAuth();
  const isAdmin = !!(user?.role === 'admin' || user?.is_admin || user?.is_superuser);
```

In the returned JSX, immediately after the `</header>` closing tag and before `<AddAgentPanel …>`:

```jsx
      {isAdmin && <ServerKeyRotationPanel />}
```

- [ ] **Step 4: Add the panel's styles**

Append to `apps/frontend/src/styles/agents.css`:

```css
/* INC-13: server-key rotation panel. Sits between the page header and the
   add-agent panel; admin-only, and absent entirely when no admin is viewing. */
.agents-page__key-panel {
  border: 1px solid var(--color-border, rgba(255, 255, 255, 0.12));
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: var(--color-surface);
}

.agents-page__key-panel dl {
  margin: 0;
}

.agents-page__key-panel dt {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.agents-page__key-panel dd {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix apps/frontend test -- src/__tests__/agents-page.test.jsx`
Expected: PASS — including every pre-existing case in that file.

- [ ] **Step 6: Run the full frontend suite and lint**

Run: `npm --prefix apps/frontend test`
Run: `npm --prefix apps/frontend run lint`
Expected: PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/pages/AgentsPage.jsx apps/frontend/src/styles/agents.css apps/frontend/src/__tests__/agents-page.test.jsx
git commit -m "feat(agents): mount server-key rotation panel on the Agents page (INC-13)"
```

---

## Task 7: Runbook and register update

- [ ] **Step 1: Write the runbook**

Create `docs/agent-key-rotation.md`:

```markdown
# Agent Server-Key Rotation

The agent server key is the identity key every `cb-agent` authenticates the
server against. Rotating it is a fleet-wide operation with a timed window.

**Where:** Agents page, top panel. Admin only.

## What rotation does

1. The server generates a fresh successor keypair and stores it alongside the
   current one.
2. The successor is pushed immediately to every currently connected agent,
   rather than waiting for each agent's next handshake.
3. For a **7-day overlap**, the server accepts handshakes against either key.
4. When the overlap expires, the successor is promoted and the previous key is
   retired.

Only one rotation may be in flight. Starting a second while an overlap is
running is rejected, and the button is unavailable for the same reason.

## Reading the adoption counts

While a rotation is running the panel reports three numbers:

| Bucket | Meaning |
|---|---|
| Authenticated with successor | Has completed a handshake against the new key since the rotation began |
| Still on current | Has handshaked since the rotation began, but against the outgoing key |
| Not seen since rotation | Has not handshaked at all since the rotation began |

These describe **which key each agent's handshakes have used**. The server has
no visibility into whether an agent's local state directory holds the successor
key — that state is agent-side. An agent in the second bucket will normally pick
the successor up on a subsequent handshake.

**Show agents** lists everything not yet in the first bucket, most recently seen
first, so you can chase the stragglers by name.

## Before the overlap expires

An agent that never handshakes during the overlap window will fail to
authenticate once the previous key is retired and will need re-enrolling. If the
"not seen since rotation" count is non-zero as the window closes, identify those
agents through **Show agents** and either bring them online or plan to
re-enroll them.

## Recovery

There is no "cancel rotation" operation. If a rotation was started in error, the
safest course is to let the overlap run: both keys are accepted throughout, so
no agent is locked out by the rotation itself.
```

- [ ] **Step 2: Add the nav entry**

In `mkdocs.yml`, add below the `cb-agent` entry, with **six spaces** of indentation:

```yaml
      - cb-agent: agent.md
      - Agent Key Rotation: agent-key-rotation.md
```

- [ ] **Step 3: Verify**

```bash
grep -n "agent-key-rotation.md" mkdocs.yml
python3 -c "import yaml; yaml.safe_load(open('mkdocs.yml')); print('mkdocs.yml parses')"
```

Expected: one hit, and the YAML parses.

- [ ] **Step 4: Update the register**

In `docs/1.0.0-incomplete-features.md`: set INC-13's summary row to `Resolved`, update the `**Last updated:**` line, and replace the INC-13 body with:

```markdown
### INC-13. Agent server-key rotation has no UI

**Resolved.** `POST /agents/server-key/rotate` and `GET /agents/server-key/status`
were implemented, along with the overlap-window columns, with no frontend
caller — a high-consequence operation with a timed window and no status display.

- `components/agents/ServerKeyRotationPanel.jsx` — admin-only, mounted on the
  Agents page, which gained an import, an `isAdmin` line and one render line and
  is otherwise untouched. Rotate is disabled during an overlap because the
  endpoint 409s then; a racing 409 refetches and shows the rotation rather than
  raising an error about it. A status read that fails renders an error state
  distinct from the idle state — "no rotation in progress" means safe, "cannot
  read status" means unknown, and the two must not look alike.
- `components/common/HighRiskConfirmDialog.jsx` — new shared type-to-confirm
  primitive, introduced here and reused by INC-12 and INC-14. Rotation confirms
  on the phrase `ROTATE`.
- `schemas/agents.py` / `api/agents.py` — `ServerKeyRotationStatus` gained a
  `fleet` adoption block computed from `server_pk_current_pinned_at` /
  `server_pk_successor_pinned_at`, the columns `models.py:432-450` added for
  exactly this and which nothing read. It is one aggregate query, pinned by
  `test_rotation_status_adoption_is_one_query_regardless_of_fleet_size`
  following `_latest_samples`' precedent. Revoked agents are excluded — they
  never handshake again and would make a finished rollout look stuck forever.
- `GET /agents/server-key/pending` — new: the agents not yet on the successor,
  by name, so an admin can chase them before the window closes. Empty rather
  than an error when no rotation is active.
- `docs/agent-key-rotation.md` — runbook, added to the MkDocs nav.

**Deviation from the design:** spec §6.3 called for a per-agent key-state column
on the fleet table. `FleetTable.jsx:18-21` documents its column list as a
contract with `FleetRow`'s hand-counted `colSpan` values
(`METRIC_COLUMN_SPAN`, `PENDING_DETAIL_SPAN`), so a *conditional* twelfth column
would have made both dynamic in the densest table in the app and reflowed the
fleet view the moment a rotation started. The same information is a drill-down
inside the panel instead.

No migration: every column this reads already existed.
```

- [ ] **Step 5: Run both suites**

Run: `npm --prefix apps/frontend test`
Run: `pytest apps/backend/tests/api/test_agents_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/agent-key-rotation.md mkdocs.yml docs/1.0.0-incomplete-features.md
git commit -m "docs(agents): document server-key rotation and close INC-13"
```

---

## Self-Review

**Spec coverage (§6).** Panel on Agents page ✓ Tasks 5–6. Idle and active states ✓ Task 5. Both fingerprints, started_at, countdown ✓ Task 5. Rotate disabled during overlap, 409 refetches ✓ Task 5. `HighRiskConfirmDialog` phrase `ROTATE` with the stated body ✓ Tasks 1, 5. Adoption counts from the pinned-at columns, one aggregate query ✓ Task 2. Wording constraint ✓ Tasks 5, 7 and asserted negatively in the panel tests. Never renders key material ✓ Task 2 test. Error state distinct from idle (§9) ✓ Task 5. Runbook ✓ Task 7. **§6.3's per-agent column is deliberately not implemented** — see the design-change section and Task 7's register note.

**Placeholder scan.** None. Every code step carries its code; the two fallbacks (SQLAlchemy `filter()` support, `agents-page.test.jsx`'s existing helpers) name the concrete alternative rather than saying "adjust as needed".

**Type consistency.** `ServerKeyFleetAdoption` fields (`total`, `successor`, `current`, `unseen`) are identical in Tasks 2, 3, 5 and the tests. `ServerKeyPendingAgent.bucket` uses the same two strings (`"current"`, `"unseen"`) in Task 3's route, its tests, and Task 5's rendering. `_rotation_status(state, db)` has the same signature at both call sites. `HighRiskConfirmDialog`'s props in Task 1 match its use in Task 5 exactly, and `onConfirm` receives `{reason}` in both.

**Carried forward:** UI-3 and UI-5 consume `HighRiskConfirmDialog` unchanged. Neither should modify it; if one needs a behaviour it lacks, add a prop with a default that preserves the current behaviour, and extend `high-risk-confirm-dialog.test.jsx` rather than replacing its cases.
