# Agent Console Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent detail page a real design layer — a tabbed console over shared layout primitives, composed from the agent's lifecycle state, that keeps activity visible on every tab — and fix the two defects remaining on the agent list page.

**Architecture:** Ten generic primitives land in `components/common/` over the existing Gruvbox tokens, with a new `styles/panels.css` supplying the spacing and type scale the app has never had. Two pure modules (`lib/agentFreshness.js`, `lib/agentComposition.js`) decide freshness and page composition so both are testable without rendering. `AgentDetailPage.jsx` drops from 975 lines to wiring, and `hooks/useAgentDetail.js` splits data loading into always-on subscriptions and tab-gated fetches.

**Tech Stack:** React 18 + Vite, JavaScript/JSX (not TypeScript), plain CSS over CSS custom properties, `lucide-react` icons, PropTypes, vitest + @testing-library/react + jsdom.

**Spec:** [specs/2026-09-05-agent-console-redesign-design.md](specs/2026-09-05-agent-console-redesign-design.md)

## Global Constraints

- **No new colour vocabulary.** Every tone comes from the existing `:root` in `styles/main.css`: `--color-bg` `#282828`, `--color-surface` `#3c3836`, `--color-border` `#504945`, `--color-primary` `#fe8019`, `--color-text` `#ebdbb2`, `--color-text-muted` `#c8bfb0`, `--color-success` `#b8bb26`, `--color-warning` `#d79921`, `--color-danger` `#fb4934`, `--color-info` `#83a598`. Do not edit `main.css`.
- **Tone names are `ok | warn | danger | info | default`** — the same vocabulary `AgentStateChip` passes to `data-tone`. Never invent a sixth.
- **Nothing in `components/common/` may import from `components/agents/`, `lib/agent*`, or `api/agents`.** These primitives must not know the word "agent".
- **Frontend is JavaScript, not TypeScript.** `.jsx` for components (PascalCase), `.js` for hooks and lib modules. Every component declares `PropTypes`.
- **All HTTP goes through the axios client** (`src/api/client.jsx`). No inline `fetch`.
- **The AGT-14/15/16 operator prose is relocated, never reworded.** Where this plan quotes a string, copy it byte-for-byte.
- **`prefers-reduced-motion: reduce` suppresses all animation** in every stylesheet this plan touches.
- **Never lower the coverage gate.** `make lint` and `make verify` must pass before the branch is done.
- **jsdom performs no layout.** Never assert on computed geometry. Layout is verified by eye against the running app.
- **Commit prefixes:** `feat:` / `fix:` / `chore:` / `docs:`.

## Working Directory

All paths are relative to the repo root unless a command says otherwise. Frontend commands run from `apps/frontend`:

```bash
cd apps/frontend
npx vitest run src/__tests__/<file> -t "<test name>"   # one test
npx vitest run src/__tests__/<file>                     # one file
npm run lint                                            # eslint
```

## File Structure

**New — `apps/frontend/src/components/common/` (generic, agent-agnostic):**

| File | Responsibility |
|---|---|
| `Panel.jsx` | A titled, bordered surface: header (label, optional summary, optional actions) + padded body |
| `PanelGrid.jsx` | Responsive auto-fit grid of Panels |
| `EmptyState.jsx` | Icon + message + optional hint, centred, for "nothing here" |
| `Banner.jsx` | Toned callout: title, short body, optional actions, optional `<details>` disclosure |
| `KeyValue.jsx` | `<dl>` with an aligned label column and tabular-numeral monospace values |
| `CopyField.jsx` | Monospace value, optionally truncated, with a copy-to-clipboard button |
| `StatTile.jsx` | Label + large tabular value + sparkline; renders `—` for null |
| `Toggle.jsx` | Accessible switch with label and optional note |
| `Tabs.jsx` | ARIA tablist with roving focus, arrow keys, and per-tab indicators |
| `DetailHeader.jsx` | Sticky page header: back link, title, chips, meta row, actions, optional strip slot |

**New — `apps/frontend/src/lib/`:**

| File | Responsibility |
|---|---|
| `agentFreshness.js` | The LIVE → LAGGING → STALE → OFFLINE ladder, pure |
| `agentComposition.js` | Lifecycle state → which tabs, panels, actions and strip the page shows, pure |

**New — `apps/frontend/src/components/agents/`:**

| File | Responsibility |
|---|---|
| `AgentIdentityHeader.jsx` | Wraps `DetailHeader` with agent identity, chips and actions |
| `AgentStateBanner.jsx` | Primary state as a `Banner` with the verbatim prose behind disclosure |
| `AgentLiveStrip.jsx` | Five micro-sparklines + freshness pill, sticky in the header |
| `AgentCapabilitiesPanel.jsx` | The three capability toggles + host-telemetry cadence settings |
| `AgentHardwarePanel.jsx` | Linked hardware, or an `EmptyState` |
| `AgentEventsPanel.jsx` | The `describeAgentEvent` feed as a live tail |
| `AgentTelemetryTab.jsx` | Stat tiles, `HistoryChart` ×5, `DeviceTable` ×4, Docker block, readiness alerts |
| `AgentOverviewTab.jsx` | Condensed panels, each linking into its own tab |

**New — `apps/frontend/src/hooks/useAgentDetail.js`:** always-on subscriptions vs tab-gated fetches.

**New — `apps/frontend/src/styles/panels.css`:** spacing ramp, type scale, `--color-surface-raised`, and every primitive's rules.

**Modified:**

| File | Change |
|---|---|
| `pages/AgentDetailPage.jsx` | 975 → ~250 lines; wiring only |
| `pages/AgentsPage.jsx` | `FleetSummary` wording; chrome onto `Panel` |
| `components/agents/FleetRow.jsx` | `PendingCells` separator |
| `components/agents/AssignedProbesSection.jsx` | Re-skinned onto `Panel`; logic unchanged |
| `components/agents/DiscoveryScopeSection.jsx` | Re-skinned onto `Panel`; logic unchanged |
| `lib/fleetFilters.js` | **Unmodified.** The count arithmetic is correct; Task 8 fixes the sentence in `FleetSummary` |
| `styles/agents.css` | Detail-page rules; `.fleet-*` untouched |

**Unmodified:** every backend file, `lib/agentState.js`, `lib/agentErrors.js`, `lib/agentLabel.js`, `api/agents.js`, `App.jsx`, `styles/main.css`.

## Task Dependency Order

```
Tasks 1-6  (primitives)      ── independent of each other, do in order
Tasks 7-8  (list defects)    ── independent of everything; shippable alone
Tasks 9-10 (pure modules)    ── independent of 1-8
Task  11   (useAgentDetail)  ── needs 9, 10
Tasks 12-13 (header pieces)  ── needs 1-6, 9, 10
Task  14   (page shell)      ── needs 5, 6, 11, 12, 13
Tasks 15-18 (tab contents)   ── needs 14
Task  19   (indicators)      ── needs 14, 11
Task  20   (list alignment)  ── needs 1-4, 7, 8
```

---

### Task 1: Panel, PanelGrid, and the token scale

**Files:**
- Create: `apps/frontend/src/styles/panels.css`
- Create: `apps/frontend/src/components/common/Panel.jsx`
- Create: `apps/frontend/src/components/common/PanelGrid.jsx`
- Test: `apps/frontend/src/__tests__/common-panel.test.jsx`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `<Panel title={string} summary={node?} tone={'default'|'ok'|'warn'|'danger'|'info'} actions={node?} bodyless={bool?}>children</Panel>` — renders `<section class="cb-panel" data-tone>` with `aria-label={title}`. Header is `<h3 class="cb-panel__title">`. Omits the body wrapper when `bodyless`.
  - `<PanelGrid min={number=232}>children</PanelGrid>` — `<div class="cb-panel-grid">` with `--cb-grid-min` set inline from `min`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/common-panel.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import Panel from '../components/common/Panel';
import PanelGrid from '../components/common/PanelGrid';

describe('Panel', () => {
  it('labels itself with its title so a screen reader can find the region', () => {
    render(<Panel title="Capabilities">body text</Panel>);
    const region = screen.getByRole('region', { name: 'Capabilities' });
    expect(region).toBeTruthy();
    expect(region.textContent).toContain('body text');
  });

  it('renders a summary and actions in the header', () => {
    render(
      <Panel title="Probes" summary="0 of 8 in use" actions={<button type="button">Add</button>}>
        body
      </Panel>
    );
    expect(screen.getByText('0 of 8 in use')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add' })).toBeTruthy();
  });

  it('carries its tone as a data attribute rather than a colour class', () => {
    const { container } = render(<Panel title="Scope" tone="warn">x</Panel>);
    expect(container.querySelector('.cb-panel').getAttribute('data-tone')).toBe('warn');
  });

  it('defaults to the neutral tone', () => {
    const { container } = render(<Panel title="Scope">x</Panel>);
    expect(container.querySelector('.cb-panel').getAttribute('data-tone')).toBe('default');
  });

  it('omits the padded body when bodyless, so a table can reach the panel edge', () => {
    const { container } = render(<Panel title="Jobs" bodyless><table /></Panel>);
    expect(container.querySelector('.cb-panel__body')).toBeNull();
    expect(container.querySelector('table')).toBeTruthy();
  });
});

describe('PanelGrid', () => {
  it('passes its minimum column width through as a custom property', () => {
    const { container } = render(
      <PanelGrid min={300}>
        <Panel title="A">a</Panel>
      </PanelGrid>
    );
    const grid = container.querySelector('.cb-panel-grid');
    expect(grid.style.getPropertyValue('--cb-grid-min')).toBe('300px');
  });

  it('defaults to a 232px minimum', () => {
    const { container } = render(<PanelGrid><Panel title="A">a</Panel></PanelGrid>);
    expect(container.querySelector('.cb-panel-grid').style.getPropertyValue('--cb-grid-min')).toBe(
      '232px'
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-panel.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/common/Panel"`.

- [ ] **Step 3: Create the token scale and panel rules**

Create `apps/frontend/src/styles/panels.css`:

```css
/* ── Shared layout primitives ───────────────────────────────────────────────
   The spacing and type scale main.css never had. Colour is NOT redefined here
   — every tone below resolves to a --color-* already declared in main.css, so
   a theme change lands in one place and this file follows it.

   Nothing in components/common/ knows the word "agent". These rules are named
   cb-* rather than agent-* for the same reason: the next detail page adopts
   them without renaming anything. */

:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;

  --panel-pad: var(--space-3);
  --panel-gap: var(--space-3);

  /* A type ramp, not a set of one-off font-sizes. --fs-micro is the uppercase
     label size and is deliberately paired with letter-spacing everywhere it is
     used; below 9.5px the tracking stops compensating for the size. */
  --fs-micro: 9.5px;
  --fs-xs: 11px;
  --fs-sm: 12.5px;
  --fs-md: 13px;
  --fs-lg: 19px;
  --fs-xl: 21px;

  /* Panels sit *above* the page. --color-surface (#3c3836) is the same value
     the page chrome uses, so a panel painted with it reads as flat. */
  --color-surface-raised: #32302f;

  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* ── Panel ──────────────────────────────────────────────────────────────── */

.cb-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  overflow: hidden;
}

/* Tone is a left edge, never a fill: a panel whose whole background changes
   colour stops reading as the same kind of object as its neighbours. */
.cb-panel[data-tone='ok'] { border-left: 3px solid var(--color-success); }
.cb-panel[data-tone='warn'] { border-left: 3px solid var(--color-warning); }
.cb-panel[data-tone='danger'] { border-left: 3px solid var(--color-danger); }
.cb-panel[data-tone='info'] { border-left: 3px solid var(--color-info); }

.cb-panel__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--panel-pad);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}

.cb-panel__title {
  margin: 0;
  font-size: var(--fs-micro);
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

/* The summary is a reading of the panel's contents, so it is quiet and it is
   tabular — these values change in place as polls land. */
.cb-panel__summary {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.cb-panel__actions { margin-left: auto; display: flex; gap: var(--space-2); }
.cb-panel__summary + .cb-panel__actions { margin-left: var(--space-2); }

.cb-panel__body { padding: var(--panel-pad); }

/* ── PanelGrid ──────────────────────────────────────────────────────────── */

.cb-panel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--cb-grid-min, 232px), 1fr));
  gap: var(--panel-gap);
}

@media (prefers-reduced-motion: reduce) {
  .cb-panel,
  .cb-panel * {
    animation: none !important;
    transition: none !important;
  }
}
```

- [ ] **Step 4: Write Panel**

Create `apps/frontend/src/components/common/Panel.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const TONES = ['default', 'ok', 'warn', 'danger', 'info'];

/**
 * A titled, bordered surface.
 *
 * The title is both the visible label and the region's accessible name, so a
 * screen reader walking the page hears the same headings a sighted operator
 * scans. `summary` is for a reading of the panel's own contents ("0 of 8 in
 * use") — it is not a place for prose.
 *
 * `bodyless` exists for panels whose content is a full-bleed table: the padded
 * body would inset the table away from the border it should meet.
 */
export default function Panel({
  title,
  summary = null,
  tone = 'default',
  actions = null,
  bodyless = false,
  children,
}) {
  return (
    <section className="cb-panel" data-tone={tone} aria-label={title}>
      <div className="cb-panel__head">
        <h3 className="cb-panel__title">{title}</h3>
        {summary === null ? null : <span className="cb-panel__summary">{summary}</span>}
        {actions === null ? null : <div className="cb-panel__actions">{actions}</div>}
      </div>
      {bodyless ? children : <div className="cb-panel__body">{children}</div>}
    </section>
  );
}

Panel.propTypes = {
  title: PropTypes.string.isRequired,
  summary: PropTypes.node,
  tone: PropTypes.oneOf(TONES),
  actions: PropTypes.node,
  bodyless: PropTypes.bool,
  children: PropTypes.node,
};
```

- [ ] **Step 5: Write PanelGrid**

Create `apps/frontend/src/components/common/PanelGrid.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/**
 * Auto-fit grid of Panels. `min` is the narrowest a column may get before the
 * grid drops one — it is passed as a custom property rather than an inline
 * grid-template so the responsive behaviour stays in CSS where it can be read.
 */
export default function PanelGrid({ min = 232, children }) {
  return (
    <div className="cb-panel-grid" style={{ '--cb-grid-min': `${min}px` }}>
      {children}
    </div>
  );
}

PanelGrid.propTypes = {
  min: PropTypes.number,
  children: PropTypes.node,
};
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-panel.test.jsx
```

Expected: PASS — 7 tests.

- [ ] **Step 7: Lint**

```bash
cd apps/frontend && npm run lint
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/src/styles/panels.css \
        apps/frontend/src/components/common/Panel.jsx \
        apps/frontend/src/components/common/PanelGrid.jsx \
        apps/frontend/src/__tests__/common-panel.test.jsx
git commit -m "feat(ui): add Panel, PanelGrid and the shared spacing scale

styles/main.css defines colour, one radius and one font size. It has no
spacing ramp, no type scale and no raised-surface colour, which is why nine
sections were added to the agent detail page with no framing at all — there
was no vocabulary to add them in.

panels.css supplies that vocabulary and redefines no colour: every tone
resolves to a --color-* already in main.css.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: EmptyState and Banner

**Files:**
- Create: `apps/frontend/src/components/common/EmptyState.jsx`
- Create: `apps/frontend/src/components/common/Banner.jsx`
- Modify: `apps/frontend/src/styles/panels.css` (append)
- Test: `apps/frontend/src/__tests__/common-banner.test.jsx`

**Interfaces:**
- Consumes: `panels.css` from Task 1.
- Produces:
  - `<EmptyState icon={node?} message={string} hint={node?} />` — `<div class="cb-empty">`.
  - `<Banner tone={'ok'|'warn'|'danger'|'info'} title={string} body={node} detail={node?} actions={node?} />` — `<div class="cb-banner" role="status">`. When `detail` is given, renders a `<details><summary>Why?</summary>` containing it. **`detail` is where verbatim AGT-14/15/16 prose goes.**

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/common-banner.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Banner from '../components/common/Banner';
import EmptyState from '../components/common/EmptyState';

const VERBATIM =
  'The machine has enrolled but nobody has approved it yet. It collects nothing. ' +
  'What to do: Compare the fingerprint against the one the agent printed, then approve or reject it.';

describe('Banner', () => {
  it('shows the short body without requiring any interaction', () => {
    render(<Banner tone="warn" title="Awaiting approval" body="Compare the fingerprint, then approve." />);
    expect(screen.getByText('Awaiting approval')).toBeTruthy();
    expect(screen.getByText('Compare the fingerprint, then approve.')).toBeTruthy();
  });

  it('keeps the full operator prose in the DOM behind a disclosure', async () => {
    render(
      <Banner tone="warn" title="Awaiting approval" body="Compare the fingerprint." detail={VERBATIM} />
    );
    // In the DOM from the start — searchable, and reachable by a screen reader
    // walking the document — but visually collapsed until asked for.
    expect(screen.getByText(VERBATIM)).toBeTruthy();
    const disclosure = screen.getByText('Why?').closest('details');
    expect(disclosure.open).toBe(false);
    await userEvent.click(screen.getByText('Why?'));
    expect(disclosure.open).toBe(true);
  });

  it('renders no disclosure when there is no extra detail', () => {
    const { container } = render(<Banner tone="ok" title="Online" body="Reporting normally." />);
    expect(container.querySelector('details')).toBeNull();
  });

  it('announces itself as a status region', () => {
    render(<Banner tone="danger" title="Revoked" body="Its credential no longer works." />);
    expect(screen.getByRole('status').textContent).toContain('Revoked');
  });

  it('carries its tone as a data attribute', () => {
    const { container } = render(<Banner tone="danger" title="Revoked" body="x" />);
    expect(container.querySelector('.cb-banner').getAttribute('data-tone')).toBe('danger');
  });

  it('renders actions when given', () => {
    render(
      <Banner
        tone="warn"
        title="Awaiting approval"
        body="x"
        actions={<button type="button">Approve</button>}
      />
    );
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });
});

describe('EmptyState', () => {
  it('states what is absent and what to do about it', () => {
    render(
      <EmptyState
        message="No monitors run from this agent"
        hint="Assign one with “Run from” on a monitor’s form."
      />
    );
    expect(screen.getByText('No monitors run from this agent')).toBeTruthy();
    expect(screen.getByText('Assign one with “Run from” on a monitor’s form.')).toBeTruthy();
  });

  it('hides a decorative icon from assistive technology', () => {
    const { container } = render(<EmptyState icon="◎" message="Nothing here" />);
    expect(container.querySelector('.cb-empty__icon').getAttribute('aria-hidden')).toBe('true');
  });

  it('renders without a hint', () => {
    const { container } = render(<EmptyState message="No hardware linked" />);
    expect(container.querySelector('.cb-empty__hint')).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-banner.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/common/Banner"`.

- [ ] **Step 3: Append the styles**

Append to `apps/frontend/src/styles/panels.css`:

```css
/* ── EmptyState ─────────────────────────────────────────────────────────── */

/* "No X yet" was five bare <p> elements on the agent detail page, each phrased
   and placed differently. One treatment, and it always has room to say what to
   do next — an empty state that only reports absence wastes the moment the
   operator is most likely to act. */
.cb-empty {
  text-align: center;
  padding: var(--space-5) var(--space-3);
  color: var(--color-text-muted);
  font-size: var(--fs-sm);
}

.cb-empty__icon {
  display: block;
  font-size: var(--fs-lg);
  opacity: 0.5;
  margin-bottom: var(--space-2);
}

.cb-empty__hint {
  font-size: var(--fs-xs);
  opacity: 0.85;
  margin-top: var(--space-1);
}

/* ── Banner ─────────────────────────────────────────────────────────────── */

/* The tone is carried by a left edge and a tinted ground, both derived from
   the same --color-*: a banner must survive being read in greyscale, so the
   title also carries the icon and the wording states the condition. */
.cb-banner {
  border: 1px solid var(--color-border);
  border-left-width: 3px;
  border-radius: var(--radius);
  padding: var(--space-3);
  margin-bottom: var(--panel-gap);
}

.cb-banner[data-tone='ok'] { border-color: var(--color-success); }
.cb-banner[data-tone='warn'] { border-color: var(--color-warning); }
.cb-banner[data-tone='danger'] { border-color: var(--color-danger); }
.cb-banner[data-tone='info'] { border-color: var(--color-info); }

.cb-banner__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.cb-banner[data-tone='ok'] .cb-banner__title { color: var(--color-success); }
.cb-banner[data-tone='warn'] .cb-banner__title { color: var(--color-warning); }
.cb-banner[data-tone='danger'] .cb-banner__title { color: var(--color-danger); }
.cb-banner[data-tone='info'] .cb-banner__title { color: var(--color-info); }

.cb-banner__body {
  margin: var(--space-1) 0 0;
  color: var(--color-text-muted);
  font-size: var(--fs-sm);
  max-width: 74ch;
}

/* The disclosure holds the full operator prose verbatim. It stays in the DOM
   collapsed rather than being mounted on demand, so the page is searchable and
   a screen reader walking the document still reaches it. */
.cb-banner__why {
  margin-top: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--color-text-muted);
}

.cb-banner__why summary {
  cursor: pointer;
  list-style: none;
  width: max-content;
}

.cb-banner__why summary::-webkit-details-marker { display: none; }
.cb-banner__why summary::after { content: ' ⌄'; }
.cb-banner__why[open] summary::after { content: ' ⌃'; }
.cb-banner__why summary:hover { color: var(--color-primary); }

.cb-banner__why-body {
  margin-top: var(--space-2);
  padding-left: var(--space-3);
  border-left: 2px solid var(--color-border);
  font-size: var(--fs-sm);
  max-width: 74ch;
}

.cb-banner__actions {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
```

- [ ] **Step 4: Write EmptyState**

Create `apps/frontend/src/components/common/EmptyState.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/**
 * One treatment for "there is nothing here".
 *
 * `hint` is not decoration: the moment an operator reads an empty state is the
 * moment they are most likely to act, and an empty state that only reports
 * absence wastes it. Where the reason for the emptiness is a blocked
 * precondition, say the precondition.
 */
export default function EmptyState({ icon = null, message, hint = null }) {
  return (
    <div className="cb-empty">
      {icon === null ? null : (
        <span className="cb-empty__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <div className="cb-empty__message">{message}</div>
      {hint === null ? null : <div className="cb-empty__hint">{hint}</div>}
    </div>
  );
}

EmptyState.propTypes = {
  icon: PropTypes.node,
  message: PropTypes.string.isRequired,
  hint: PropTypes.node,
};
```

- [ ] **Step 5: Write Banner**

Create `apps/frontend/src/components/common/Banner.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const TONES = ['ok', 'warn', 'danger', 'info'];

/**
 * A toned callout carrying a condition and what to do about it.
 *
 * `body` is the short imperative an operator acts on. `detail` is the full
 * explanation — on the agent pages that is the AGT-14/15/16 prose, reproduced
 * verbatim. It is rendered inside a collapsed <details> rather than mounted on
 * demand so that the text stays in the DOM: searchable with the browser's own
 * find, and reachable by a screen reader walking the document.
 *
 * role="status" and not role="alert": these conditions are already true when
 * the page loads, and an alert would interrupt on every navigation.
 */
export default function Banner({ tone, title, body, detail = null, actions = null, icon = null }) {
  return (
    <div className="cb-banner" data-tone={tone} role="status">
      <p className="cb-banner__title">
        {icon === null ? null : <span aria-hidden="true">{icon}</span>}
        {title}
      </p>
      <p className="cb-banner__body">{body}</p>
      {detail === null ? null : (
        <details className="cb-banner__why">
          <summary>Why?</summary>
          <div className="cb-banner__why-body">{detail}</div>
        </details>
      )}
      {actions === null ? null : <div className="cb-banner__actions">{actions}</div>}
    </div>
  );
}

Banner.propTypes = {
  tone: PropTypes.oneOf(TONES).isRequired,
  title: PropTypes.string.isRequired,
  body: PropTypes.node.isRequired,
  detail: PropTypes.node,
  actions: PropTypes.node,
  icon: PropTypes.node,
};
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-banner.test.jsx
```

Expected: PASS — 9 tests.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/common/EmptyState.jsx \
        apps/frontend/src/components/common/Banner.jsx \
        apps/frontend/src/styles/panels.css \
        apps/frontend/src/__tests__/common-banner.test.jsx
git commit -m "feat(ui): add EmptyState and Banner primitives

Banner's disclosure is where the AGT-14/15/16 operator prose goes. It stays
in the DOM collapsed rather than mounted on demand, so the wording is still
searchable and still reachable by a screen reader walking the document — the
prose is relocated, not withdrawn.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: KeyValue and CopyField

**Files:**
- Create: `apps/frontend/src/components/common/KeyValue.jsx`
- Create: `apps/frontend/src/components/common/CopyField.jsx`
- Modify: `apps/frontend/src/styles/panels.css` (append)
- Test: `apps/frontend/src/__tests__/common-keyvalue.test.jsx`

**Interfaces:**
- Consumes: `panels.css`.
- Produces:
  - `<KeyValue rows={[[label, value], …]} />` — a `<dl class="cb-kv">`. `value` may be any node; `null`/`undefined` renders `—`.
  - `<CopyField value={string} label={string} head={number?} tail={number?} />` — monospace `<code>` plus a copy button named `Copy ${label}`. When `head` is given, displays `value.slice(0, head)…value.slice(-tail)`; the **full** value is always what gets copied and always what `title` carries.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/common-keyvalue.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import KeyValue from '../components/common/KeyValue';
import CopyField from '../components/common/CopyField';

describe('KeyValue', () => {
  it('pairs every label with its value', () => {
    render(
      <KeyValue
        rows={[
          ['Scope mode', 'direct_private'],
          ['Concurrent hosts', 64],
        ]}
      />
    );
    expect(screen.getByText('Scope mode')).toBeTruthy();
    expect(screen.getByText('direct_private')).toBeTruthy();
    expect(screen.getByText('64')).toBeTruthy();
  });

  it('renders an em dash for a missing value rather than an empty cell', () => {
    // A blank cell is indistinguishable from a rendering bug. An em dash says
    // "this was asked for and there is no answer".
    render(<KeyValue rows={[['Host timeout', null]]} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('renders zero as zero, not as missing', () => {
    render(<KeyValue rows={[['Assigned', 0]]} />);
    expect(screen.getByText('0')).toBeTruthy();
  });
});

describe('CopyField', () => {
  beforeEach(() => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('copies the full value even when the display is truncated', async () => {
    const full = 'b030b0aa1cde5b3e9f77c2a10d4e6b81';
    render(<CopyField value={full} label="scope version" head={8} tail={4} />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy scope version' }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(full);
  });

  it('shows head and tail around an ellipsis so both ends stay comparable', () => {
    // Operators compare fingerprints character by character against what the
    // agent printed on the host. Truncating only the tail hides half of what
    // they are checking.
    render(<CopyField value="b030b0aa1cde5b3e9f77c2a10d4e6b81" label="fp" head={8} tail={4} />);
    expect(screen.getByText('b030b0aa…6b81')).toBeTruthy();
  });

  it('keeps the untruncated value available as a title', () => {
    const full = 'b030b0aa1cde5b3e9f77c2a10d4e6b81';
    const { container } = render(<CopyField value={full} label="fp" head={8} tail={4} />);
    expect(container.querySelector('code').getAttribute('title')).toBe(full);
  });

  it('shows the whole value when no truncation is asked for', () => {
    render(<CopyField value="direct_private" label="mode" />);
    expect(screen.getByText('direct_private')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-keyvalue.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/common/KeyValue"`.

- [ ] **Step 3: Append the styles**

Append to `apps/frontend/src/styles/panels.css`:

```css
/* ── KeyValue ───────────────────────────────────────────────────────────── */

/* Two columns, labels sized to their content, so values line up as a column an
   eye can run down. Values are monospace and tabular because most of them are
   numbers or identifiers that get compared against something else. */
.cb-kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-4);
  margin: 0;
  font-size: var(--fs-sm);
}

.cb-kv dt { color: var(--color-text-muted); }

.cb-kv dd {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}

/* ── CopyField ──────────────────────────────────────────────────────────── */

.cb-copy { display: inline-flex; align-items: center; gap: var(--space-1); }

.cb-copy code {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  background: rgba(60, 56, 54, 0.5);
  padding: 1px var(--space-1);
  border-radius: 3px;
  color: var(--color-text);
}

.cb-copy__btn {
  background: none;
  border: 0;
  padding: 0 2px;
  cursor: pointer;
  color: var(--color-text-muted);
  font: inherit;
  line-height: 1;
}

.cb-copy__btn:hover { color: var(--color-primary); }
.cb-copy__btn:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
```

- [ ] **Step 4: Write KeyValue**

Create `apps/frontend/src/components/common/KeyValue.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/** Missing means missing. A blank cell is indistinguishable from a bug. */
const ABSENT = '—';

/**
 * An aligned label/value list.
 *
 * `rows` is an array of `[label, value]` pairs rather than an object so the
 * caller controls the order — these lists are read top to bottom and the order
 * is part of the meaning.
 */
export default function KeyValue({ rows }) {
  return (
    <dl className="cb-kv">
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt>{label}</dt>
          {/* `== null` and not falsy: 0 and '' are answers, not absences. */}
          <dd>{value == null ? ABSENT : value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

KeyValue.propTypes = {
  rows: PropTypes.arrayOf(
    PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.node]))
  ).isRequired,
};
```

- [ ] **Step 5: Write CopyField**

Create `apps/frontend/src/components/common/CopyField.jsx`:

```jsx
import React, { useCallback, useState } from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const COPIED_MS = 1200;

/**
 * A monospace value with a copy button.
 *
 * Truncation shows head AND tail. These values — agent fingerprints, scope
 * versions — exist to be compared character by character against something
 * printed elsewhere, and truncating only the tail hides half of what is being
 * checked. The full value is always what gets copied and always what `title`
 * carries, so nothing is lost to the abbreviation.
 */
export default function CopyField({ value, label, head = null, tail = 4 }) {
  const [copied, setCopied] = useState(false);

  const display = head === null || value.length <= head + tail
    ? value
    : `${value.slice(0, head)}…${value.slice(-tail)}`;

  const onCopy = useCallback(() => {
    // Clipboard access is denied outright in some embedded browsers. The copy
    // is a convenience over a value that is already on screen and selectable,
    // so a failure is silent rather than a toast the operator cannot act on.
    Promise.resolve(navigator.clipboard?.writeText(value))
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), COPIED_MS);
      })
      .catch(() => {});
  }, [value]);

  return (
    <span className="cb-copy">
      <code title={value}>{display}</code>
      <button
        type="button"
        className="cb-copy__btn"
        onClick={onCopy}
        aria-label={`Copy ${label}`}
      >
        {copied ? '✓' : '⧉'}
      </button>
    </span>
  );
}

CopyField.propTypes = {
  value: PropTypes.string.isRequired,
  label: PropTypes.string.isRequired,
  head: PropTypes.number,
  tail: PropTypes.number,
};
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-keyvalue.test.jsx
```

Expected: PASS — 8 tests.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/common/KeyValue.jsx \
        apps/frontend/src/components/common/CopyField.jsx \
        apps/frontend/src/styles/panels.css \
        apps/frontend/src/__tests__/common-keyvalue.test.jsx
git commit -m "feat(ui): add KeyValue and CopyField primitives

CopyField truncates head and tail rather than just the tail: fingerprints and
scope versions exist to be compared character by character against a value
printed on the host, and hiding one end defeats that. The full value is what
gets copied and what title carries.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: StatTile and Toggle

**Files:**
- Create: `apps/frontend/src/components/common/StatTile.jsx`
- Create: `apps/frontend/src/components/common/Toggle.jsx`
- Modify: `apps/frontend/src/styles/panels.css` (append)
- Test: `apps/frontend/src/__tests__/common-stattile.test.jsx`

**Interfaces:**
- Consumes: `panels.css`.
- Produces:
  - `<StatTile label={string} value={string|null} points={number[]?} hot={bool=false} flash={bool=false} />` — `<div class="cb-tile" data-hot data-flash>`. `value` of `null` renders `—`. `points` under two entries renders no sparkline.
  - `<Toggle checked={bool} onChange={fn(bool)} label={string} note={node?} disabled={bool=false} />` — a `<button role="switch" aria-checked>`.

**Note on `value`:** the caller formats. `StatTile` never formats a number, because the unit and precision rules already live in `formatMetric` on the detail page and must not be duplicated here.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/common-stattile.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StatTile from '../components/common/StatTile';
import Toggle from '../components/common/Toggle';

describe('StatTile', () => {
  it('renders the value the caller formatted', () => {
    render(<StatTile label="CPU" value="12%" />);
    expect(screen.getByText('CPU')).toBeTruthy();
    expect(screen.getByText('12%')).toBeTruthy();
  });

  it('renders an em dash when there is no value', () => {
    // The fleet table left these cells blank, which reads as a rendering
    // failure rather than as "this agent has never reported".
    render(<StatTile label="CPU" value={null} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('draws a sparkline once there are at least two points', () => {
    const { container } = render(<StatTile label="CPU" value="12%" points={[1, 4, 2, 8]} />);
    expect(container.querySelector('polyline').getAttribute('points')).toBeTruthy();
  });

  it('draws no sparkline for a single point, which has no shape', () => {
    const { container } = render(<StatTile label="CPU" value="12%" points={[4]} />);
    expect(container.querySelector('polyline')).toBeNull();
  });

  it('marks a threshold crossing with data-hot rather than a colour class', () => {
    const { container } = render(<StatTile label="CPU" value="93%" points={[90, 93]} hot />);
    expect(container.querySelector('.cb-tile').getAttribute('data-hot')).toBe('true');
  });

  it('hides the sparkline from assistive technology, since the value is text', () => {
    const { container } = render(<StatTile label="CPU" value="12%" points={[1, 2]} />);
    expect(container.querySelector('svg').getAttribute('aria-hidden')).toBe('true');
  });
});

describe('Toggle', () => {
  it('exposes itself as a switch with its checked state', () => {
    render(<Toggle checked label="Host telemetry" onChange={() => {}} />);
    const el = screen.getByRole('switch', { name: /Host telemetry/ });
    expect(el.getAttribute('aria-checked')).toBe('true');
  });

  it('reports the flipped value, not the current one', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} label="Remote probe" onChange={onChange} />);
    await userEvent.click(screen.getByRole('switch', { name: /Remote probe/ }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('does not fire when disabled', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} label="Local discovery" onChange={onChange} disabled />);
    await userEvent.click(screen.getByRole('switch', { name: /Local discovery/ }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('puts the note in the accessible name, so the reason is not colour-only', () => {
    // A capability locked until approval must say so to a screen reader, not
    // only to an eye reading dimmed text beside it.
    render(
      <Toggle checked={false} label="Host telemetry" note="locked until approved" disabled onChange={() => {}} />
    );
    expect(screen.getByRole('switch', { name: 'Host telemetry — locked until approved' })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-stattile.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/common/StatTile"`.

- [ ] **Step 3: Append the styles**

Append to `apps/frontend/src/styles/panels.css`:

```css
/* ── StatTile ───────────────────────────────────────────────────────────── */

.cb-tile {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  padding: var(--space-2) var(--space-3) var(--space-1);
  transition: border-color 0.5s ease, box-shadow 0.5s ease;
}

.cb-tile__label {
  font-size: var(--fs-micro);
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

/* Tabular numerals are load-bearing: without them a value stepping 9 -> 11
   shifts every digit beside it and the column appears to twitch. */
.cb-tile__value {
  font-family: var(--font-mono);
  font-size: var(--fs-xl);
  font-variant-numeric: tabular-nums;
  margin: 2px 0 1px;
}

.cb-tile svg { width: 100%; height: 30px; display: block; }

.cb-tile polyline {
  fill: none;
  stroke: var(--color-info);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}

/* A flash marks a threshold crossing or a state change — never the arrival of
   an ordinary sample. At a 10s cadence a per-sample flash reads as fidgeting
   rather than as signal, and a page that flashes constantly trains the
   operator to stop looking at it. */
.cb-tile[data-flash='true'] {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 1px rgba(var(--color-primary-rgb), 0.35);
}

.cb-tile[data-hot='true'] {
  border-color: var(--color-danger);
  box-shadow: 0 0 0 1px rgba(251, 73, 52, 0.4);
}

.cb-tile[data-hot='true'] .cb-tile__value { color: var(--color-danger); }
.cb-tile[data-hot='true'] polyline { stroke: var(--color-danger); }

.cb-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(154px, 1fr));
  gap: var(--space-2);
}

/* ── Toggle ─────────────────────────────────────────────────────────────── */

.cb-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  font-size: var(--fs-sm);
  background: none;
  border: 0;
  color: var(--color-text);
  font-family: inherit;
  width: 100%;
  text-align: left;
  cursor: pointer;
}

.cb-toggle:disabled { cursor: not-allowed; opacity: 0.65; }
.cb-toggle:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.cb-toggle + .cb-toggle { border-top: 1px solid rgba(80, 73, 69, 0.5); }

.cb-toggle__track {
  width: 30px;
  height: 17px;
  border-radius: 999px;
  background: var(--color-border);
  position: relative;
  flex: none;
  transition: background 0.15s ease;
}

.cb-toggle__track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: var(--color-text-muted);
  transition: transform 0.15s ease, background 0.15s ease;
}

.cb-toggle[aria-checked='true'] .cb-toggle__track { background: rgba(184, 187, 38, 0.35); }

.cb-toggle[aria-checked='true'] .cb-toggle__track::after {
  transform: translateX(13px);
  background: var(--color-success);
}

.cb-toggle__note { margin-left: auto; font-size: var(--fs-xs); color: var(--color-text-muted); }

@media (prefers-reduced-motion: reduce) {
  .cb-tile,
  .cb-toggle__track,
  .cb-toggle__track::after {
    transition: none !important;
  }
}
```

- [ ] **Step 4: Write StatTile**

Create `apps/frontend/src/components/common/StatTile.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const ABSENT = '—';
const VIEW_W = 120;
const VIEW_H = 26;
const MIN_POINTS = 2;

/**
 * Normalise a series into a polyline over a fixed 120x26 viewBox.
 *
 * The scale runs from 0, not from the series minimum: a rescaled floor makes a
 * flat line look like a mountain range, and these sparklines exist to answer
 * "is this quiet or is it spiking" at a glance.
 */
function polylinePoints(points) {
  const max = Math.max(...points) * 1.12 || 1;
  return points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * VIEW_W;
      const y = VIEW_H - (value / max) * (VIEW_H - 2);
      return `${x.toFixed(1)},${Math.max(1, Math.min(VIEW_H - 1, y)).toFixed(1)}`;
    })
    .join(' ');
}

/**
 * Label, value, and a sparkline.
 *
 * `value` arrives pre-formatted. Unit and precision rules already live in the
 * caller (formatMetric on the agent pages) and a second copy here is exactly
 * the drift this primitive would otherwise introduce.
 */
export default function StatTile({ label, value, points = [], hot = false, flash = false }) {
  const hasSeries = points.length >= MIN_POINTS;
  return (
    <div className="cb-tile" data-hot={String(hot)} data-flash={String(flash)}>
      <div className="cb-tile__label">{label}</div>
      <div className="cb-tile__value">{value == null ? ABSENT : value}</div>
      {hasSeries ? (
        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="none" aria-hidden="true">
          <polyline points={polylinePoints(points)} />
        </svg>
      ) : null}
    </div>
  );
}

StatTile.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string,
  points: PropTypes.arrayOf(PropTypes.number),
  hot: PropTypes.bool,
  flash: PropTypes.bool,
};
```

- [ ] **Step 5: Write Toggle**

Create `apps/frontend/src/components/common/Toggle.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/**
 * An accessible switch.
 *
 * `note` is folded into the accessible name rather than left as adjacent
 * text: the note is usually the *reason* a toggle cannot be used ("locked
 * until approved"), and a reason a screen reader has to go hunting for is a
 * reason that does not reach half the operators who need it.
 */
export default function Toggle({ checked, onChange, label, note = null, disabled = false }) {
  const accessibleName = note ? `${label} — ${note}` : label;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={accessibleName}
      className="cb-toggle"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="cb-toggle__track" aria-hidden="true" />
      <span aria-hidden="true">{label}</span>
      {note === null ? null : (
        <span className="cb-toggle__note" aria-hidden="true">
          {note}
        </span>
      )}
    </button>
  );
}

Toggle.propTypes = {
  checked: PropTypes.bool.isRequired,
  onChange: PropTypes.func.isRequired,
  label: PropTypes.string.isRequired,
  note: PropTypes.node,
  disabled: PropTypes.bool,
};
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-stattile.test.jsx
```

Expected: PASS — 10 tests.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/common/StatTile.jsx \
        apps/frontend/src/components/common/Toggle.jsx \
        apps/frontend/src/styles/panels.css \
        apps/frontend/src/__tests__/common-stattile.test.jsx
git commit -m "feat(ui): add StatTile and Toggle primitives

StatTile renders an em dash for a null value. The fleet table left those
cells blank, which reads as a rendering failure rather than as 'this agent
has never reported'.

Toggle folds its note into the accessible name, because the note is usually
the reason the control cannot be used.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Tabs

**Files:**
- Create: `apps/frontend/src/components/common/Tabs.jsx`
- Modify: `apps/frontend/src/styles/panels.css` (append)
- Test: `apps/frontend/src/__tests__/common-tabs.test.jsx`

**Interfaces:**
- Consumes: `panels.css`.
- Produces:
  - `<Tabs tabs={[{ key, label, indicator }]} active={string} onChange={fn(key)} label={string} />` — `<div role="tablist" aria-label={label}>` of `<button role="tab" id={`cb-tab-${key}`} aria-controls={`cb-panel-${key}`}>`.
  - `indicator` is `null` (nothing), `true` (a dot), or a number (a count). It is announced as ` — new activity` / ` — N new` in the tab's accessible name, never by colour alone.
  - Named export `panelPropsFor(key)` returning `{ id, role: 'tabpanel', 'aria-labelledby', tabIndex: 0 }` so consumers wire the panel side correctly without repeating the id convention.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/common-tabs.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Tabs, { panelPropsFor } from '../components/common/Tabs';

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'telemetry', label: 'Telemetry' },
  { key: 'events', label: 'Events' },
];

function renderTabs(props = {}) {
  const onChange = props.onChange ?? vi.fn();
  const utils = render(
    <Tabs tabs={TABS} active={props.active ?? 'overview'} onChange={onChange} label="Agent sections" />
  );
  return { ...utils, onChange };
}

describe('Tabs', () => {
  it('marks only the active tab as selected', () => {
    renderTabs({ active: 'telemetry' });
    expect(screen.getByRole('tab', { name: 'Telemetry' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('false');
  });

  it('reports the key of the tab that was clicked', async () => {
    const { onChange } = renderTabs();
    await userEvent.click(screen.getByRole('tab', { name: 'Events' }));
    expect(onChange).toHaveBeenCalledWith('events');
  });

  it('keeps only the active tab in the tab order', () => {
    // Roving tabindex: one Tab keystroke enters the tablist, then arrow keys
    // move within it. Without this, a five-tab bar costs five Tab presses to
    // step over.
    renderTabs({ active: 'overview' });
    expect(screen.getByRole('tab', { name: 'Overview' }).tabIndex).toBe(0);
    expect(screen.getByRole('tab', { name: 'Telemetry' }).tabIndex).toBe(-1);
  });

  it('moves to the next tab on ArrowRight', async () => {
    const { onChange } = renderTabs({ active: 'overview' });
    screen.getByRole('tab', { name: 'Overview' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onChange).toHaveBeenCalledWith('telemetry');
  });

  it('wraps from the last tab to the first on ArrowRight', async () => {
    const { onChange } = renderTabs({ active: 'events' });
    screen.getByRole('tab', { name: 'Events' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onChange).toHaveBeenCalledWith('overview');
  });

  it('wraps backwards from the first tab on ArrowLeft', async () => {
    const { onChange } = renderTabs({ active: 'overview' });
    screen.getByRole('tab', { name: 'Overview' }).focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(onChange).toHaveBeenCalledWith('events');
  });

  it('jumps to the first and last tab on Home and End', async () => {
    const { onChange } = renderTabs({ active: 'telemetry' });
    screen.getByRole('tab', { name: 'Telemetry' }).focus();
    await userEvent.keyboard('{Home}');
    expect(onChange).toHaveBeenCalledWith('overview');
    await userEvent.keyboard('{End}');
    expect(onChange).toHaveBeenCalledWith('events');
  });

  it('announces a boolean indicator in the accessible name, not by colour alone', () => {
    render(
      <Tabs
        tabs={[{ key: 'telemetry', label: 'Telemetry', indicator: true }]}
        active="overview"
        onChange={() => {}}
        label="Agent sections"
      />
    );
    expect(screen.getByRole('tab', { name: 'Telemetry — new activity' })).toBeTruthy();
  });

  it('announces a numeric indicator as a count', () => {
    render(
      <Tabs
        tabs={[{ key: 'events', label: 'Events', indicator: 3 }]}
        active="overview"
        onChange={() => {}}
        label="Agent sections"
      />
    );
    expect(screen.getByRole('tab', { name: 'Events — 3 new' })).toBeTruthy();
  });

  it('links each tab to the panel it controls', () => {
    renderTabs({ active: 'overview' });
    const tab = screen.getByRole('tab', { name: 'Overview' });
    expect(tab.getAttribute('aria-controls')).toBe('cb-panel-overview');
    expect(tab.id).toBe('cb-tab-overview');
  });
});

describe('panelPropsFor', () => {
  it('produces panel attributes matching the tab id convention', () => {
    expect(panelPropsFor('telemetry')).toEqual({
      id: 'cb-panel-telemetry',
      role: 'tabpanel',
      'aria-labelledby': 'cb-tab-telemetry',
      tabIndex: 0,
    });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-tabs.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/common/Tabs"`.

- [ ] **Step 3: Append the styles**

Append to `apps/frontend/src/styles/panels.css`:

```css
/* ── Tabs ───────────────────────────────────────────────────────────────── */

.cb-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--color-border);
  overflow-x: auto;
}

.cb-tab {
  position: relative;
  font: inherit;
  font-size: var(--fs-sm);
  padding: var(--space-2) var(--space-3);
  background: none;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  white-space: nowrap;
}

.cb-tab:hover { color: var(--color-text); }
.cb-tab:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }

.cb-tab[aria-selected='true'] {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  font-weight: 600;
}

/* The indicator is the tabbed shape's one real cost: content on a hidden tab
   cannot announce itself. It is duplicated into the tab's accessible name in
   Tabs.jsx, so this dot is reinforcement and never the only channel. */
.cb-tab__indicator {
  position: absolute;
  top: 5px;
  right: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
}

.cb-tab__indicator--count {
  width: auto;
  height: auto;
  border-radius: 999px;
  padding: 0 5px;
  font-size: var(--fs-micro);
  font-style: normal;
  font-weight: 700;
  color: var(--color-bg);
  line-height: 13px;
}
```

- [ ] **Step 4: Write Tabs**

Create `apps/frontend/src/components/common/Tabs.jsx`:

```jsx
import React, { useCallback } from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const tabId = (key) => `cb-tab-${key}`;
const panelId = (key) => `cb-panel-${key}`;

/**
 * The attributes a tab's panel must carry. Exported so consumers do not
 * re-derive the id convention and drift out of agreement with the tablist.
 */
export function panelPropsFor(key) {
  return {
    id: panelId(key),
    role: 'tabpanel',
    'aria-labelledby': tabId(key),
    tabIndex: 0,
  };
}

/** The indicator, stated in words, for the tab's accessible name. */
function indicatorSuffix(indicator) {
  if (indicator === null || indicator === undefined || indicator === false) return '';
  if (indicator === true) return ' — new activity';
  return ` — ${indicator} new`;
}

/**
 * An ARIA tablist with roving focus.
 *
 * Selection follows focus (arrow keys change the active tab, not merely the
 * focused one), which is the correct pattern when panels are cheap to render.
 * Every panel here is already-fetched state, so there is no cost to landing on
 * one while arrowing past.
 */
export default function Tabs({ tabs, active, onChange, label }) {
  const onKeyDown = useCallback(
    (event) => {
      const index = tabs.findIndex((tab) => tab.key === active);
      let next = null;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      if (next === null) return;
      event.preventDefault();
      onChange(tabs[next].key);
    },
    [tabs, active, onChange]
  );

  return (
    <div className="cb-tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab) => {
        const selected = tab.key === active;
        const indicator = tab.indicator ?? null;
        const isCount = typeof indicator === 'number';
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={tabId(tab.key)}
            aria-controls={panelId(tab.key)}
            aria-selected={selected}
            aria-label={`${tab.label}${indicatorSuffix(indicator)}`}
            tabIndex={selected ? 0 : -1}
            className="cb-tab"
            onClick={() => onChange(tab.key)}
          >
            <span aria-hidden="true">{tab.label}</span>
            {indicator === null || indicator === false ? null : (
              <i
                aria-hidden="true"
                className={`cb-tab__indicator${isCount ? ' cb-tab__indicator--count' : ''}`}
              >
                {isCount ? indicator : ''}
              </i>
            )}
          </button>
        );
      })}
    </div>
  );
}

Tabs.propTypes = {
  tabs: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      indicator: PropTypes.oneOfType([PropTypes.bool, PropTypes.number]),
    })
  ).isRequired,
  active: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  label: PropTypes.string.isRequired,
};
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-tabs.test.jsx
```

Expected: PASS — 11 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/common/Tabs.jsx \
        apps/frontend/src/styles/panels.css \
        apps/frontend/src/__tests__/common-tabs.test.jsx
git commit -m "feat(ui): add the Tabs primitive

The indicator is stated in the tab's accessible name as well as drawn as a
dot. A tabbed shape hides content by design, and an activity signal that only
exists as a coloured dot does not reach an operator using a screen reader.

panelPropsFor() is exported so consumers wire the panel side from the same id
convention the tablist uses rather than re-deriving it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: DetailHeader

**Files:**
- Create: `apps/frontend/src/components/common/DetailHeader.jsx`
- Modify: `apps/frontend/src/styles/panels.css` (append)
- Test: `apps/frontend/src/__tests__/common-detail-header.test.jsx`

**Interfaces:**
- Consumes: `panels.css`; `react-router-dom`'s `Link` (generic, allowed).
- Produces:
  - `<DetailHeader backTo={string} backLabel={string} title={string} chips={node?} meta={node[]?} actions={node?} strip={node?} />` — `<header class="cb-detail-head">`, title as `<h1>`.
  - **`meta` is an array of nodes and each entry is wrapped in its own `<span class="cb-meta__item">` by this component.** Callers pass content, never separators.

**Why `meta` wraps rather than trusting callers:** `FleetRow`'s `PendingCells` renders a bare text node next to a `.fleet-muted` span, and the separator rule at `agents.css:614` is `.fleet-muted + .fleet-muted::before` — an adjacent-*sibling* selector that a text node cannot satisfy. That is the "Waiting for approvallinux / amd64" defect Task 7 fixes. `DetailHeader` makes the bug unreachable by owning the wrapper.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/common-detail-header.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DetailHeader from '../components/common/DetailHeader';

function renderHeader(props = {}) {
  return render(
    <MemoryRouter>
      <DetailHeader backTo="/agents" backLabel="Agents" title="73235d37c4a3" {...props} />
    </MemoryRouter>
  );
}

describe('DetailHeader', () => {
  it('renders the title as the page heading', () => {
    renderHeader();
    expect(screen.getByRole('heading', { level: 1, name: '73235d37c4a3' })).toBeTruthy();
  });

  it('links back to the list it came from', () => {
    renderHeader();
    expect(screen.getByRole('link', { name: /Agents/ }).getAttribute('href')).toBe('/agents');
  });

  it('wraps every meta entry in its own element so separators can apply', () => {
    // The list page's PendingCells emitted a bare text node beside a span, and
    // the CSS separator is an adjacent-sibling rule that a text node cannot
    // satisfy — the fields ran together on screen. This component owns the
    // wrapper so a caller cannot reintroduce that.
    const { container } = renderHeader({ meta: ['pending', 'linux / amd64', 'v0.0.0-dev'] });
    const items = container.querySelectorAll('.cb-meta__item');
    expect(items).toHaveLength(3);
    expect(items[1].textContent).toBe('linux / amd64');
  });

  it('renders no meta row when there is nothing to put in it', () => {
    const { container } = renderHeader({ meta: [] });
    expect(container.querySelector('.cb-meta')).toBeNull();
  });

  it('renders chips, actions and the strip slot', () => {
    renderHeader({
      chips: <span>Online</span>,
      actions: <button type="button">Revoke</button>,
      strip: <div data-testid="strip">sparklines</div>,
    });
    expect(screen.getByText('Online')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeTruthy();
    expect(screen.getByTestId('strip')).toBeTruthy();
  });

  it('omits the strip slot entirely when there is nothing live to show', () => {
    // A pending agent has no telemetry. Reserving empty space for a strip that
    // will never fill reads as something failing to load.
    const { container } = renderHeader({ strip: null });
    expect(container.querySelector('.cb-detail-head__strip')).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-detail-header.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/common/DetailHeader"`.

- [ ] **Step 3: Append the styles**

Append to `apps/frontend/src/styles/panels.css`:

```css
/* ── DetailHeader ───────────────────────────────────────────────────────── */

/* Sticky, because the identity of the thing being looked at must not scroll
   away from the numbers describing it. --header-height is the app chrome this
   sits beneath; see main.css. */
.cb-detail-head {
  position: sticky;
  top: var(--header-height);
  z-index: 5;
  padding: var(--space-4) var(--space-4) 0;
  background: var(--color-surface-raised);
  border-bottom: 1px solid var(--color-border);
}

.cb-detail-head__back {
  font-size: var(--fs-xs);
  color: var(--color-text-muted);
  text-decoration: none;
}

.cb-detail-head__back:hover { color: var(--color-primary); }

.cb-detail-head__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.cb-detail-head__title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 650;
  font-family: var(--font-mono);
  letter-spacing: 0.2px;
}

.cb-detail-head__chips { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.cb-detail-head__actions { margin-left: auto; display: flex; gap: var(--space-2); }

/* Each item is its own element, so the separator is a real adjacent-sibling
   rule rather than a hyphen baked into a string. */
.cb-meta {
  display: flex;
  flex-wrap: wrap;
  margin: var(--space-2) 0 var(--space-3);
  font-size: var(--fs-sm);
  color: var(--color-text-muted);
}

.cb-meta__item { padding-right: var(--space-2); }

.cb-meta__item + .cb-meta__item {
  margin-left: var(--space-2);
  border-left: 1px solid var(--color-border);
  padding-left: var(--space-2);
}

.cb-detail-head__strip {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) 0 var(--space-3);
  border-top: 1px solid rgba(80, 73, 69, 0.4);
  overflow-x: auto;
}
```

- [ ] **Step 4: Write DetailHeader**

Create `apps/frontend/src/components/common/DetailHeader.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import '../../styles/panels.css';

/**
 * The sticky header of a detail page.
 *
 * `meta` entries are wrapped here, not by the caller. The separator between
 * them is an adjacent-sibling CSS rule, and a caller passing a bare string
 * would produce a text node that no sibling selector can match — which is
 * exactly how the fleet table's pending row came to render its fields run
 * together. Owning the wrapper makes that unreachable.
 *
 * `strip` is a slot for content that must stay visible on every tab. It is
 * omitted entirely when null rather than rendered empty: reserved space that
 * never fills reads as something failing to load.
 */
export default function DetailHeader({
  backTo,
  backLabel,
  title,
  chips = null,
  meta = [],
  actions = null,
  strip = null,
}) {
  return (
    <header className="cb-detail-head">
      <Link className="cb-detail-head__back" to={backTo}>
        ← {backLabel}
      </Link>
      <div className="cb-detail-head__row">
        <h1 className="cb-detail-head__title">{title}</h1>
        {chips === null ? null : <div className="cb-detail-head__chips">{chips}</div>}
        {actions === null ? null : <div className="cb-detail-head__actions">{actions}</div>}
      </div>
      {meta.length === 0 ? null : (
        <div className="cb-meta">
          {meta.map((item, index) => (
            // eslint-disable-next-line react/no-array-index-key -- meta entries
            // are positional fields of one record (status, platform, version);
            // they have no identity of their own and the list never reorders.
            <span className="cb-meta__item" key={index}>
              {item}
            </span>
          ))}
        </div>
      )}
      {strip === null ? null : <div className="cb-detail-head__strip">{strip}</div>}
    </header>
  );
}

DetailHeader.propTypes = {
  backTo: PropTypes.string.isRequired,
  backLabel: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  chips: PropTypes.node,
  meta: PropTypes.arrayOf(PropTypes.node),
  actions: PropTypes.node,
  strip: PropTypes.node,
};
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-detail-header.test.jsx
```

Expected: PASS — 6 tests.

- [ ] **Step 6: Run every primitive test together and lint**

```bash
cd apps/frontend && npx vitest run src/__tests__/common-*.test.jsx && npm run lint
```

Expected: PASS — 51 tests across 6 files; no lint errors.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/common/DetailHeader.jsx \
        apps/frontend/src/styles/panels.css \
        apps/frontend/src/__tests__/common-detail-header.test.jsx
git commit -m "feat(ui): add the DetailHeader primitive

meta entries are wrapped by the component, not the caller. The separator is
an adjacent-sibling rule, and a caller passing a bare string yields a text
node no sibling selector can match — which is precisely how the fleet table's
pending row came to render 'Waiting for approvallinux / amd64'. Owning the
wrapper makes that class of bug unreachable here.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Fix the pending row's run-together fields

**Files:**
- Modify: `apps/frontend/src/components/agents/FleetRow.jsx:386-399`
- Modify: `apps/frontend/src/styles/agents.css` (append)
- Test: `apps/frontend/src/__tests__/fleet-pending-row.test.jsx`

**Interfaces:**
- Consumes: nothing. Independent of Tasks 1–6.
- Produces: no new exports. `PendingCells` keeps its signature `({ agent })`.

**The defect:** `PendingCells` emits the bare text node `Waiting for approval` followed immediately by `<span className="fleet-muted">{agent.os} / {agent.arch}</span>`. The separator rule is `.fleet-muted + .fleet-muted::before` (`agents.css:614`). A text node is not an element, so the adjacent-sibling selector never matches and the cell renders `Waiting for approvallinux / amd64` — visible in the screenshots that prompted this work.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/fleet-pending-row.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetRow from '../components/agents/FleetRow';

const PENDING = {
  id: 7,
  status: 'pending',
  hostname: '73235d37c4a3',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.0.0-dev',
  fingerprint: '5a8253d7b7af678c4fcd7872631139d8',
  last_seen_at: null,
  online: false,
  capabilities: {},
};

function renderRow(agent = PENDING) {
  return render(
    <MemoryRouter>
      <table>
        <tbody>
          <FleetRow agent={agent} />
        </tbody>
      </table>
    </MemoryRouter>
  );
}

describe('FleetRow pending cells', () => {
  it('keeps every field in its own element so the separator rule applies', () => {
    // The separator is `.fleet-muted + .fleet-muted::before` — an adjacent
    // SIBLING selector. A bare text node cannot satisfy it, which is why the
    // cell rendered "Waiting for approvallinux / amd64".
    const { container } = renderRow();
    const cell = container.querySelector('.fleet-pending');
    const items = cell.querySelectorAll('.fleet-pending__item');
    expect(items.length).toBeGreaterThanOrEqual(2);
    items.forEach((item) => {
      expect(item.tagName).toBe('SPAN');
    });
  });

  it('no longer concatenates the status with the platform', () => {
    renderRow();
    expect(screen.queryByText(/approvallinux/)).toBeNull();
    expect(screen.getByText('Waiting for approval')).toBeTruthy();
    expect(screen.getByText('linux / amd64')).toBeTruthy();
  });

  it('still abbreviates the fingerprint while keeping the full value reachable', () => {
    renderRow();
    const chip = screen.getByTitle(PENDING.fingerprint);
    expect(chip.textContent).toContain('…');
    expect(chip.textContent.length).toBeLessThan(PENDING.fingerprint.length);
  });

  it('omits the fingerprint field entirely when the agent has not reported one', () => {
    renderRow({ ...PENDING, fingerprint: null });
    expect(screen.getByText('Waiting for approval')).toBeTruthy();
    expect(screen.queryByText(/…/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/fleet-pending-row.test.jsx
```

Expected: FAIL — `container.querySelector('.fleet-pending')` is null.

- [ ] **Step 3: Rewrite PendingCells**

In `apps/frontend/src/components/agents/FleetRow.jsx`, replace the whole `PendingCells` function:

```jsx
function PendingCells({ agent }) {
  return (
    <td className="fleet-cell fleet-muted fleet-pending" colSpan={PENDING_DETAIL_SPAN}>
      {/* Every field is its own element. The separator between them is an
          adjacent-sibling rule, and the leading label used to be a bare text
          node — which no sibling selector can match, so the status ran
          straight into the platform: "Waiting for approvallinux / amd64". */}
      <span className="fleet-pending__item">Waiting for approval</span>
      <span className="fleet-pending__item">
        {agent.os} / {agent.arch}
      </span>
      {agent.fingerprint && (
        <span className="fleet-pending__item">
          {/* Full label text, abbreviated visually rather than by slicing it
              here — a truncated string is unreachable to a screen reader.
              `title` restores it on hover. */}
          <span className="fleet-chip" data-tone="warn" title={agent.fingerprint}>
            {agent.fingerprint.slice(0, FINGERPRINT_PREVIEW_CHARS)}…
          </span>
        </span>
      )}
    </td>
  );
}
```

- [ ] **Step 4: Append the styles**

Append to `apps/frontend/src/styles/agents.css`:

```css
/* AGT: the pending row's detail cell. Each field is its own element and the
   separator is an adjacent-sibling rule, so adding a field cannot reintroduce
   the run-together defect — a bare text node simply will not match. */
.fleet-pending {
  display: flex;
  align-items: center;
  gap: 0;
}

.fleet-pending__item + .fleet-pending__item::before {
  content: '·';
  margin: 0 6px;
  color: var(--color-border);
}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/fleet-pending-row.test.jsx
```

Expected: PASS — 4 tests.

- [ ] **Step 6: Run the existing fleet suites to confirm nothing regressed**

```bash
cd apps/frontend && npx vitest run src/__tests__/agents-page.test.jsx src/__tests__/agent-state-rendering.test.jsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/agents/FleetRow.jsx \
        apps/frontend/src/styles/agents.css \
        apps/frontend/src/__tests__/fleet-pending-row.test.jsx
git commit -m "fix(agents): separate the pending row's fields

PendingCells emitted the bare text node 'Waiting for approval' immediately
followed by a .fleet-muted span. The separator is
\`.fleet-muted + .fleet-muted::before\` (agents.css) — an adjacent-sibling
selector, which a text node cannot satisfy. The rule never fired and the cell
rendered 'Waiting for approvallinux / amd64'.

Every field is now its own element under .fleet-pending, so adding a field
cannot reintroduce this.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Stop reporting a fleet of one as empty

**Files:**
- Modify: `apps/frontend/src/pages/AgentsPage.jsx:246-258` (`FleetSummary`)
- Test: `apps/frontend/src/__tests__/fleet-summary-counts.test.jsx`

**Interfaces:**
- Consumes: `summarizeFleet` from `lib/fleetFilters.js`, **unchanged**.
- Produces: no new exports.

**The defect:** `summarizeFleet` (`fleetFilters.js:152`) filters pending agents out before counting and returns `total: fleet.length`. That exclusion is correct — the filter predicates genuinely do not apply to an unapproved agent — but `FleetSummary` renders `${summary.matching} of ${summary.total} agents` unconditionally, so a deployment whose only agent is pending reads `0 of 0 agents · 1 awaiting approval` directly above a visible row. **`lib/fleetFilters.js` is not modified;** the sentence is what is wrong, not the arithmetic.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/fleet-summary-counts.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { summarizeFleet, readFleetFilters } from '../lib/fleetFilters';
import { FleetSummary } from '../pages/AgentsPage';

const FILTERS = readFleetFilters(new URLSearchParams());

function summaryFor(rows) {
  return summarizeFleet(rows, FILTERS, {});
}

describe('FleetSummary', () => {
  it('does not claim a fleet of zero when the only agent is pending', () => {
    // The row is visible directly beneath this sentence. Saying "0 of 0
    // agents" contradicts what the operator can see.
    const summary = summaryFor([{ id: 1, status: 'pending', online: false }]);
    render(<FleetSummary summary={summary} />);
    const text = screen.getByRole('status').textContent;
    expect(text).toBe('1 awaiting approval');
    expect(text).not.toContain('0 of 0');
  });

  it('reports the fleet count once there is an approved agent', () => {
    const summary = summaryFor([
      { id: 1, status: 'pending', online: false },
      { id: 2, status: 'active', online: true, capabilities: { host_telemetry: { enabled: true } } },
    ]);
    render(<FleetSummary summary={summary} />);
    const text = screen.getByRole('status').textContent;
    expect(text).toContain('1 of 1 agents');
    expect(text).toContain('1 awaiting approval');
  });

  it('still reports an empty deployment as empty', () => {
    render(<FleetSummary summary={summaryFor([])} />);
    expect(screen.getByRole('status').textContent).toBe('0 of 0 agents');
  });

  it('keeps announcing changes as a status region', () => {
    render(<FleetSummary summary={summaryFor([{ id: 1, status: 'pending', online: false }])} />);
    expect(screen.getByRole('status')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/fleet-summary-counts.test.jsx
```

Expected: FAIL — two failures. `FleetSummary` is not exported (`does not provide an export named 'FleetSummary'`), and once exported the first case returns `'0 of 0 agents · 1 awaiting approval'`.

- [ ] **Step 3: Export FleetSummary and suppress the empty clause**

In `apps/frontend/src/pages/AgentsPage.jsx`, change the declaration to a named export and add the guard:

```jsx
export function FleetSummary({ summary }) {
  const parts = [];
  // summarizeFleet excludes pending agents from `total` on purpose — the
  // filter predicates do not apply to an agent nobody has approved. But a
  // deployment whose only agent is pending then read "0 of 0 agents" directly
  // above a visible row. The arithmetic was right and the sentence was wrong.
  if (summary.total > 0 || summary.pending === 0) {
    parts.push(`${summary.matching} of ${summary.total} agents`);
  }
  if (summary.pending > 0) parts.push(`${summary.pending} awaiting approval`);
  if (summary.offline > 0) parts.push(`${summary.offline} offline`);
  if (summary.attention > 0) parts.push(`${summary.attention} need attention`);
  if (summary.behind > 0) parts.push(`${summary.behind} behind newest`);
  if (summary.spool > 0) parts.push(`${summary.spool} with a spool backlog`);
  return (
    <p className="agents-page__summary" role="status">
      {parts.join(' · ')}
    </p>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/fleet-summary-counts.test.jsx
```

Expected: PASS — 4 tests.

- [ ] **Step 5: Run the agents page suite and lint**

```bash
cd apps/frontend && npx vitest run src/__tests__/agents-page.test.jsx && npm run lint
```

Expected: PASS; no lint errors.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/pages/AgentsPage.jsx \
        apps/frontend/src/__tests__/fleet-summary-counts.test.jsx
git commit -m "fix(agents): stop reporting a fleet of one as empty

summarizeFleet excludes pending agents from \`total\` deliberately — the
filter predicates do not apply to an agent nobody has approved. FleetSummary
then rendered that count unconditionally, so a deployment whose only agent is
pending read '0 of 0 agents · 1 awaiting approval' directly above the row it
was describing.

The arithmetic was right and the sentence was wrong, so fleetFilters.js is
unchanged and the clause is suppressed where it is written.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The freshness ladder

**Files:**
- Create: `apps/frontend/src/lib/agentFreshness.js`
- Test: `apps/frontend/src/__tests__/agent-freshness.test.js`

**Interfaces:**
- Consumes: `secondsSince`, `staleSampleWindowSeconds`, `LAST_SEEN_FRESH_SECONDS`, `LAST_SEEN_LAGGING_SECONDS` — all already exported from `lib/agentState.js`. **Do not redeclare these thresholds.**
- Produces:
  - `FRESHNESS = { LIVE: 'live', LAGGING: 'lagging', STALE: 'stale', OFFLINE: 'offline' }`
  - `telemetryFreshness({ online, lastSeenAt, latestSampleAt, telemetryIntervalSeconds, now })` → `{ level, label, ageSeconds, animate }`

**Why this is a module and not a component:** spec §5.2 says motion must only ever mean live data. That is a rule about the *data*, and putting it in a pure function makes it assertable at every boundary without rendering an animation and trying to observe it.

| Condition | Level | Label | `animate` |
|---|---|---|---|
| `online === false` | `offline` | `OFFLINE` | `false` |
| Nothing ever heard (`lastSeenAt` and `latestSampleAt` both absent) | `offline` | `OFFLINE` | `false` |
| Last seen older than `LAST_SEEN_LAGGING_SECONDS` (900) | `offline` | `OFFLINE` | `false` |
| Last seen older than `LAST_SEEN_FRESH_SECONDS` (90) | `lagging` | `LAGGING` | `false` |
| No sample yet, or sample older than `staleSampleWindowSeconds(interval)` | `stale` | `STALE` | `false` |
| Otherwise | `live` | `LIVE` | `true` |

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-freshness.test.js`:

```js
import { describe, expect, it } from 'vitest';
import { FRESHNESS, telemetryFreshness } from '../lib/agentFreshness';
import { LAST_SEEN_FRESH_SECONDS, LAST_SEEN_LAGGING_SECONDS } from '../lib/agentState';

const NOW = Date.parse('2026-09-05T12:00:00.000Z');
const agoIso = (seconds) => new Date(NOW - seconds * 1000).toISOString();

const live = (overrides = {}) => ({
  online: true,
  lastSeenAt: agoIso(5),
  latestSampleAt: agoIso(5),
  telemetryIntervalSeconds: 30,
  now: NOW,
  ...overrides,
});

describe('telemetryFreshness', () => {
  it('is live when the link is up and a recent sample has arrived', () => {
    const result = telemetryFreshness(live());
    expect(result.level).toBe(FRESHNESS.LIVE);
    expect(result.label).toBe('LIVE');
    expect(result.animate).toBe(true);
  });

  it('is offline when presence says the link is down', () => {
    const result = telemetryFreshness(live({ online: false }));
    expect(result.level).toBe(FRESHNESS.OFFLINE);
    expect(result.animate).toBe(false);
  });

  it('is offline when nothing has ever been heard', () => {
    // The pending agent in the screenshots: enrolled, never connected.
    const result = telemetryFreshness({
      online: null,
      lastSeenAt: null,
      latestSampleAt: null,
      now: NOW,
    });
    expect(result.level).toBe(FRESHNESS.OFFLINE);
    expect(result.ageSeconds).toBeNull();
  });

  it('degrades to lagging past the fresh window', () => {
    const result = telemetryFreshness(live({ lastSeenAt: agoIso(LAST_SEEN_FRESH_SECONDS + 10) }));
    expect(result.level).toBe(FRESHNESS.LAGGING);
    expect(result.label).toBe('LAGGING');
    expect(result.animate).toBe(false);
  });

  it('falls to offline past the lagging window even while presence claims online', () => {
    // A socket that is open but silent is not a live agent. Trusting the flag
    // over the clock is how a dead host keeps a pulsing green light.
    const result = telemetryFreshness(live({ lastSeenAt: agoIso(LAST_SEEN_LAGGING_SECONDS + 10) }));
    expect(result.level).toBe(FRESHNESS.OFFLINE);
    expect(result.animate).toBe(false);
  });

  it('is stale when the link is fresh but samples have stopped', () => {
    // staleSampleWindowSeconds(30) is max(30*3, 90) = 90s.
    const result = telemetryFreshness(live({ latestSampleAt: agoIso(200) }));
    expect(result.level).toBe(FRESHNESS.STALE);
    expect(result.label).toBe('STALE');
    expect(result.animate).toBe(false);
  });

  it('is stale when no sample has ever arrived but the link is up', () => {
    const result = telemetryFreshness(live({ latestSampleAt: null }));
    expect(result.level).toBe(FRESHNESS.STALE);
    expect(result.animate).toBe(false);
  });

  it('scales the stale window with the configured cadence', () => {
    // A 300s cadence allows 900s between samples; 200s old is still live.
    const result = telemetryFreshness(
      live({ latestSampleAt: agoIso(200), telemetryIntervalSeconds: 300 })
    );
    expect(result.level).toBe(FRESHNESS.LIVE);
  });

  it('falls back to the floor window when the cadence is not known yet', () => {
    // capability-defaults has not resolved. 120s > the 90s floor.
    const result = telemetryFreshness(
      live({ latestSampleAt: agoIso(120), telemetryIntervalSeconds: undefined })
    );
    expect(result.level).toBe(FRESHNESS.STALE);
  });

  it('reports the age of the newest sample so a caller can render it', () => {
    expect(telemetryFreshness(live({ latestSampleAt: agoIso(42) })).ageSeconds).toBe(42);
  });

  it('never animates on anything but live', () => {
    const levels = [
      telemetryFreshness(live({ online: false })),
      telemetryFreshness(live({ lastSeenAt: agoIso(LAST_SEEN_FRESH_SECONDS + 10) })),
      telemetryFreshness(live({ latestSampleAt: agoIso(500) })),
    ];
    levels.forEach((result) => expect(result.animate).toBe(false));
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-freshness.test.js
```

Expected: FAIL — `Failed to resolve import "../lib/agentFreshness"`.

- [ ] **Step 3: Write the module**

Create `apps/frontend/src/lib/agentFreshness.js`:

```js
/**
 * The freshness ladder behind the header's live pill.
 *
 * The rule this encodes is that motion must only ever mean live data. A chart
 * that keeps animating over a dead agent is worse than no chart: it reports
 * health the server has no evidence for, and it is exactly the failure an
 * operator is least likely to catch, because nothing looks wrong.
 *
 * Every threshold is imported from lib/agentState rather than redeclared. Two
 * copies of "how old is too old" is how a page comes to disagree with the
 * fleet table about the same agent.
 */

import {
  LAST_SEEN_FRESH_SECONDS,
  LAST_SEEN_LAGGING_SECONDS,
  secondsSince,
  staleSampleWindowSeconds,
} from './agentState';

export const FRESHNESS = {
  LIVE: 'live',
  LAGGING: 'lagging',
  STALE: 'stale',
  OFFLINE: 'offline',
};

const LABELS = {
  [FRESHNESS.LIVE]: 'LIVE',
  [FRESHNESS.LAGGING]: 'LAGGING',
  [FRESHNESS.STALE]: 'STALE',
  [FRESHNESS.OFFLINE]: 'OFFLINE',
};

function result(level, ageSeconds) {
  return {
    level,
    label: LABELS[level],
    ageSeconds,
    // Only the top rung animates. This is the whole point of the module.
    animate: level === FRESHNESS.LIVE,
  };
}

/**
 * @param {object} input
 * @param {boolean|null} [input.online] Presence; null = not known.
 * @param {string|null} [input.lastSeenAt] ISO, server-produced.
 * @param {string|null} [input.latestSampleAt] ISO of the newest host sample.
 * @param {number} [input.telemetryIntervalSeconds] Configured host cadence.
 * @param {number} [input.now] Client epoch ms; injectable for tests.
 * @returns {{level: string, label: string, ageSeconds: number|null, animate: boolean}}
 */
export function telemetryFreshness({
  online,
  lastSeenAt,
  latestSampleAt,
  telemetryIntervalSeconds,
  now = Date.now(),
} = {}) {
  const sampleAge = latestSampleAt ? secondsSince(latestSampleAt, now) : null;

  if (online === false) return result(FRESHNESS.OFFLINE, sampleAge);
  if (!lastSeenAt && !latestSampleAt) return result(FRESHNESS.OFFLINE, null);

  const seenAge = lastSeenAt ? secondsSince(lastSeenAt, now) : null;

  // A socket the server still believes is open, over which nothing has arrived
  // for fifteen minutes, is not a live agent. The clock outranks the flag.
  if (seenAge !== null && seenAge > LAST_SEEN_LAGGING_SECONDS) {
    return result(FRESHNESS.OFFLINE, sampleAge);
  }
  if (seenAge !== null && seenAge > LAST_SEEN_FRESH_SECONDS) {
    return result(FRESHNESS.LAGGING, sampleAge);
  }

  // The link is fresh. Whether telemetry is fresh is a separate question, and
  // an agent checking in while its collector is wedged is a real state.
  const window = staleSampleWindowSeconds(telemetryIntervalSeconds);
  if (sampleAge === null || sampleAge > window) return result(FRESHNESS.STALE, sampleAge);

  return result(FRESHNESS.LIVE, sampleAge);
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-freshness.test.js
```

Expected: PASS — 11 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/lib/agentFreshness.js \
        apps/frontend/src/__tests__/agent-freshness.test.js
git commit -m "feat(agents): add the telemetry freshness ladder

Motion on the detail page must only ever mean live data, so the rule lives in
a pure function that can be asserted directly rather than inferred by trying
to observe an animation.

Every threshold is imported from lib/agentState. A second copy of 'how old is
too old' is how a page comes to disagree with the fleet table about the same
agent.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Lifecycle-driven page composition

**Files:**
- Create: `apps/frontend/src/lib/agentComposition.js`
- Test: `apps/frontend/src/__tests__/agent-composition.test.js`

**Interfaces:**
- Consumes: `deriveAgentStates` output — an ordered array of state descriptors, each `{ code, label, tone, summary, action, detail }`. `lib/agentState.js` is **not modified**.
- Produces:
  - `TAB_KEYS = ['overview', 'telemetry', 'probes', 'discovery', 'events']`
  - `composeAgentPage(states)` → `{ primary, secondary, showLiveStrip, liveStripDimmed, tabs, overviewPanels, capabilitiesLocked, blockedReason }`

`overviewPanels` values are `'capabilities' | 'discovery' | 'probes' | 'hardware' | 'events'`.
`blockedReason` is `'approval' | 'revocation' | null`.

**This is spec §6 as a table lookup.** Keeping it out of JSX is what makes it possible to assert all fifteen `STATE_ORDER` codes without mounting a page.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-composition.test.js`:

```js
import { describe, expect, it } from 'vitest';
import { composeAgentPage, TAB_KEYS } from '../lib/agentComposition';
import { STATE_ORDER, agentStateDefinition } from '../lib/agentState';

const state = (code) => ({ code, ...agentStateDefinition(code) });
const statesFor = (...codes) => codes.map(state);

describe('composeAgentPage', () => {
  it('promotes the first state as primary and keeps the rest as secondary', () => {
    // deriveAgentStates already returns STATE_ORDER order. Composition must
    // not re-sort it: severity ordering is that module's decision.
    const page = composeAgentPage(statesFor('pending_approval', 'offline'));
    expect(page.primary.code).toBe('pending_approval');
    expect(page.secondary.map((s) => s.code)).toEqual(['offline']);
  });

  it('hides the live strip for an agent that has never been approved', () => {
    // Reserving space for sparklines that cannot fill reads as a load failure.
    const page = composeAgentPage(statesFor('pending_approval', 'offline'));
    expect(page.showLiveStrip).toBe(false);
  });

  it('locks the capability toggles and names approval as the blocker', () => {
    const page = composeAgentPage(statesFor('pending_approval'));
    expect(page.capabilitiesLocked).toBe(true);
    expect(page.blockedReason).toBe('approval');
  });

  it('reduces a revoked agent to overview and events', () => {
    const page = composeAgentPage(statesFor('revoked'));
    expect(page.tabs).toEqual(['overview', 'events']);
    expect(page.overviewPanels).toEqual(['events']);
    expect(page.blockedReason).toBe('revocation');
    expect(page.showLiveStrip).toBe(false);
  });

  it('reduces a rejected agent the same way', () => {
    expect(composeAgentPage(statesFor('rejected')).tabs).toEqual(['overview', 'events']);
  });

  it('shows every tab and a live strip for an online agent', () => {
    const page = composeAgentPage(statesFor('online'));
    expect(page.tabs).toEqual(TAB_KEYS);
    expect(page.showLiveStrip).toBe(true);
    expect(page.liveStripDimmed).toBe(false);
    expect(page.capabilitiesLocked).toBe(false);
    expect(page.blockedReason).toBeNull();
  });

  it('keeps the strip for an offline agent but dims it', () => {
    // Last known values are still information. Presenting them as current is
    // the failure; withholding them is an over-correction.
    const page = composeAgentPage(statesFor('offline'));
    expect(page.showLiveStrip).toBe(true);
    expect(page.liveStripDimmed).toBe(true);
  });

  it('dims the strip when presence is merely unknown', () => {
    expect(composeAgentPage(statesFor('presence_unknown')).liveStripDimmed).toBe(true);
  });

  it('raises capabilities to the front when the agent has none enabled', () => {
    const page = composeAgentPage(statesFor('no_capabilities'));
    expect(page.overviewPanels[0]).toBe('capabilities');
  });

  it('orders an online overview with capabilities before the rest', () => {
    expect(composeAgentPage(statesFor('online')).overviewPanels).toEqual([
      'capabilities',
      'discovery',
      'probes',
      'hardware',
      'events',
    ]);
  });

  it('gives a pending agent a three-panel overview', () => {
    expect(composeAgentPage(statesFor('pending_approval')).overviewPanels).toEqual([
      'capabilities',
      'hardware',
      'events',
    ]);
  });

  it('returns a usable page for every state the app can derive', () => {
    // No STATE_ORDER entry may produce a page with no tabs — that would be a
    // blank screen for a state nobody thought about.
    STATE_ORDER.forEach((code) => {
      const page = composeAgentPage(statesFor(code));
      expect(page.tabs.length).toBeGreaterThan(0);
      expect(page.tabs).toContain('overview');
      expect(page.primary.code).toBe(code);
    });
  });

  it('survives an empty state list rather than throwing', () => {
    const page = composeAgentPage([]);
    expect(page.primary).toBeNull();
    expect(page.tabs).toEqual(TAB_KEYS);
    expect(page.secondary).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-composition.test.js
```

Expected: FAIL — `Failed to resolve import "../lib/agentComposition"`.

- [ ] **Step 3: Write the module**

Create `apps/frontend/src/lib/agentComposition.js`:

```js
/**
 * Spec §6: which page an agent gets, decided by its lifecycle state.
 *
 * The detail page used to render the same eight sections for every agent. For
 * a pending machine that meant eight sections of nothing surrounding the one
 * thing available to do — compare a fingerprint and approve. Composition is a
 * table lookup here rather than conditionals in JSX so that every STATE_ORDER
 * code can be asserted without mounting anything.
 */

export const TAB_KEYS = ['overview', 'telemetry', 'probes', 'discovery', 'events'];

const TERMINAL_TABS = ['overview', 'events'];

const DEFAULT_OVERVIEW = ['capabilities', 'discovery', 'probes', 'hardware', 'events'];
const PENDING_OVERVIEW = ['capabilities', 'hardware', 'events'];
const TERMINAL_OVERVIEW = ['events'];

/**
 * Per-code overrides. A code absent from this map takes the defaults, which is
 * why a new state added to STATE_ORDER degrades to a full, working page rather
 * than to a blank one.
 */
const OVERRIDES = {
  pending_approval: {
    showLiveStrip: false,
    tabs: TAB_KEYS,
    overviewPanels: PENDING_OVERVIEW,
    capabilitiesLocked: true,
    blockedReason: 'approval',
  },
  revoked: {
    showLiveStrip: false,
    tabs: TERMINAL_TABS,
    overviewPanels: TERMINAL_OVERVIEW,
    capabilitiesLocked: true,
    blockedReason: 'revocation',
  },
  rejected: {
    showLiveStrip: false,
    tabs: TERMINAL_TABS,
    overviewPanels: TERMINAL_OVERVIEW,
    capabilitiesLocked: true,
    blockedReason: 'revocation',
  },
  // Last known values are still information. Presenting them as current is the
  // failure; withholding them is an over-correction — so the strip stays and
  // dims, and lib/agentFreshness is what says the pill reads OFFLINE.
  offline: { liveStripDimmed: true },
  presence_unknown: { liveStripDimmed: true },
  // Nothing is enabled, so the only useful panel is the one that enables it.
  no_capabilities: {
    overviewPanels: ['capabilities', 'hardware', 'events'],
  },
};

const BASE = {
  showLiveStrip: true,
  liveStripDimmed: false,
  tabs: TAB_KEYS,
  overviewPanels: DEFAULT_OVERVIEW,
  capabilitiesLocked: false,
  blockedReason: null,
};

/**
 * @param {Array<object>} states Ordered descriptors from deriveAgentStates.
 * @returns {object} The page's shape for this agent.
 */
export function composeAgentPage(states = []) {
  const [primary = null, ...secondary] = states;
  // The order deriveAgentStates produced is the severity order declared in
  // STATE_ORDER. Re-sorting here would put two modules in charge of it.
  const overrides = primary === null ? {} : (OVERRIDES[primary.code] ?? {});
  return { ...BASE, ...overrides, primary, secondary };
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-composition.test.js
```

Expected: PASS — 13 tests.

- [ ] **Step 5: Lint and commit**

```bash
cd apps/frontend && npm run lint
cd ../.. && git add apps/frontend/src/lib/agentComposition.js \
        apps/frontend/src/__tests__/agent-composition.test.js
git commit -m "feat(agents): compose the detail page from lifecycle state

The page rendered the same eight sections for every agent. For a pending
machine that meant eight sections of nothing around the one available action.

Composition is a table lookup rather than conditionals in JSX, so every
STATE_ORDER code is assertable without mounting a page, and a state added
later falls through to a full working page instead of a blank one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: useAgentDetail — always-on subscriptions, tab-gated fetches

**Files:**
- Create: `apps/frontend/src/hooks/useAgentDetail.js`
- Test: `apps/frontend/src/__tests__/agent-detail-hook.test.jsx`

**Interfaces:**
- Consumes: `api/agents` (`getAgent`, `getAgentEvents`, `getAgentsPresence`, `getAgentTelemetry`, `getAgentTelemetryHistory`, `getAgentProbes`, `getAgentDiscovery`, `getCapabilityDefaults`, `normalizeCapability`); `useAgentLive`; `useTelemetryStream`; `deriveAgentStates` and `updateStateFromEvents` from `lib/agentState`; `telemetryFreshness` from Task 9; `composeAgentPage` from Task 10; `serverClockOffsetMs` from `utils/serverClock`.
- Produces:
  - `POLL_ACTIVE_MS = 30000`, `POLL_BACKOFF_MS = 120000` — named exports so the test asserts the real values rather than a copy.
  - `useAgentDetail(id, { activeTab })` → `{ agent, presence, events, telemetry, history, probes, discovery, capabilityDefaults, loading, states, page, freshness, online, historyRange, setHistoryRange, reload, reloadTelemetry, reloadProbes, reloadDiscovery }`

**Gating (spec §5.4):**

| Source | When | Why |
|---|---|---|
| `getAgent` + `getAgentEvents`, `getAgentsPresence`, `getCapabilityDefaults` | Always | Identity and state feed the header on every tab |
| `useAgentLive`, `useTelemetryStream` | Always | One WebSocket each; they are what make an off-tab spike visible |
| `getAgentTelemetry` (latest sample, readiness, spool) | Always, polled | Feeds the header live strip, which is on every tab |
| `getAgentTelemetryHistory` | `activeTab === 'telemetry'` | Range queries over a series nothing else renders |
| `getAgentProbes` | `activeTab` in `overview`, `probes` | Overview shows a condensed summary |
| `getAgentDiscovery` | `activeTab` in `overview`, `discovery` | Overview shows a condensed summary |

**Poll backoff:** the telemetry poll runs at `POLL_ACTIVE_MS` and drops to `POLL_BACKOFF_MS` while the live stream is delivering. It is a reconciliation fallback, not the primary path — the page it replaces ran it unconditionally beside a stream already carrying the same data.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-detail-hook.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const api = {
  getAgent: vi.fn(),
  getAgentEvents: vi.fn(),
  getAgentsPresence: vi.fn(),
  getAgentTelemetry: vi.fn(),
  getAgentTelemetryHistory: vi.fn(),
  getAgentProbes: vi.fn(),
  getAgentDiscovery: vi.fn(),
  getCapabilityDefaults: vi.fn(),
};

vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return { ...api, normalizeCapability: actual.normalizeCapability };
});
vi.mock('../hooks/useAgentLive', () => ({
  useAgentLive: () => ({ statuses: new Map(), connected: true }),
}));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => ({ data: new Map(), connected: true }),
}));
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}));

import { useAgentDetail, POLL_ACTIVE_MS } from '../hooks/useAgentDetail';

const AGENT = {
  id: 7,
  status: 'active',
  hostname: 'edge-01',
  agent_version: '0.4.0',
  fingerprint: 'a'.repeat(32),
  last_seen_at: new Date().toISOString(),
  capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
};

const wrapper = ({ children }) => <MemoryRouter>{children}</MemoryRouter>;

function mount(activeTab = 'overview') {
  return renderHook(({ tab }) => useAgentDetail('7', { activeTab: tab }), {
    wrapper,
    initialProps: { tab: activeTab },
  });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getAgent.mockResolvedValue({ data: AGENT });
  api.getAgentEvents.mockResolvedValue({ data: [] });
  api.getAgentsPresence.mockResolvedValue({ data: [{ online: true, hardware: null }] });
  api.getAgentTelemetry.mockResolvedValue({ data: { latest: null, readiness: [], spool: null } });
  api.getAgentTelemetryHistory.mockResolvedValue({ data: { points: [] } });
  api.getAgentProbes.mockResolvedValue({ data: [] });
  api.getAgentDiscovery.mockResolvedValue({ data: { subnets: [] } });
  api.getCapabilityDefaults.mockResolvedValue({
    data: { host_telemetry: { config: { interval_s: 30 } } },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useAgentDetail', () => {
  it('loads identity, presence and the latest sample regardless of tab', async () => {
    mount('events');
    await waitFor(() => expect(api.getAgent).toHaveBeenCalled());
    expect(api.getAgentsPresence).toHaveBeenCalled();
    // The header live strip is on every tab, so its source must be too.
    expect(api.getAgentTelemetry).toHaveBeenCalled();
  });

  it('does not fetch telemetry history until the telemetry tab is open', async () => {
    const { rerender } = mount('overview');
    await waitFor(() => expect(api.getAgent).toHaveBeenCalled());
    expect(api.getAgentTelemetryHistory).not.toHaveBeenCalled();

    rerender({ tab: 'telemetry' });
    await waitFor(() => expect(api.getAgentTelemetryHistory).toHaveBeenCalled());
  });

  it('does not fetch discovery on the telemetry tab', async () => {
    mount('telemetry');
    await waitFor(() => expect(api.getAgent).toHaveBeenCalled());
    expect(api.getAgentDiscovery).not.toHaveBeenCalled();
  });

  it('fetches probes and discovery on overview, which summarises both', async () => {
    mount('overview');
    await waitFor(() => expect(api.getAgentProbes).toHaveBeenCalled());
    expect(api.getAgentDiscovery).toHaveBeenCalled();
  });

  it('polls the latest sample on the active interval', async () => {
    mount('overview');
    await waitFor(() => expect(api.getAgentTelemetry).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(POLL_ACTIVE_MS + 100);
    await waitFor(() => expect(api.getAgentTelemetry.mock.calls.length).toBeGreaterThan(1));
  });

  it('derives states and a page composition from what it loaded', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(Array.isArray(result.current.states)).toBe(true);
    expect(result.current.page.tabs).toContain('overview');
  });

  it('exposes a freshness reading for the header pill', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.freshness.label).toMatch(/LIVE|LAGGING|STALE|OFFLINE/);
  });

  it('keeps the page usable when presence fails', async () => {
    // Presence is additive. A hiccup there must not blank identity.
    api.getAgentsPresence.mockRejectedValue(new Error('boom'));
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.presence).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('keeps the page usable when discovery fails', async () => {
    api.getAgentDiscovery.mockRejectedValue(new Error('boom'));
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.discovery).toBeNull();
  });

  it('refetches history when the range changes', async () => {
    const { result } = mount('telemetry');
    await waitFor(() => expect(api.getAgentTelemetryHistory).toHaveBeenCalledTimes(1));
    result.current.setHistoryRange('7d');
    await waitFor(() => expect(api.getAgentTelemetryHistory).toHaveBeenCalledTimes(2));
    expect(api.getAgentTelemetryHistory).toHaveBeenLastCalledWith('7', '7d');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-detail-hook.test.jsx
```

Expected: FAIL — `Failed to resolve import "../hooks/useAgentDetail"`.

- [ ] **Step 3: Write the hook**

Create `apps/frontend/src/hooks/useAgentDetail.js`:

```js
/**
 * All of the agent detail page's data, split by what the page actually needs
 * on the tab it is showing.
 *
 * The page this replaces fired everything at once — identity, presence, a 30s
 * telemetry poll, a history range, probes, discovery, events and two live
 * streams — on every mount, whether or not anything rendered the result.
 *
 * The split is deliberately NOT "gate everything not visible". An activity
 * spike must be visible from a tab that is not showing it, so the cheap
 * always-on sources stay always-on: both WebSockets and the latest-sample
 * poll, which is what feeds the header's live strip. Only the expensive
 * per-tab queries are gated.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getAgent,
  getAgentDiscovery,
  getAgentEvents,
  getAgentProbes,
  getAgentTelemetry,
  getAgentTelemetryHistory,
  getAgentsPresence,
  getCapabilityDefaults,
} from '../api/agents';
import { useAgentLive } from './useAgentLive';
import { useTelemetryStream } from './useTelemetryStream';
import { useToast } from '../components/common/Toast';
import { deriveAgentStates, updateStateFromEvents } from '../lib/agentState';
import { telemetryFreshness } from '../lib/agentFreshness';
import { composeAgentPage } from '../lib/agentComposition';
import { serverClockOffsetMs } from '../utils/serverClock';

/** The reconciliation poll while the stream is quiet. */
export const POLL_ACTIVE_MS = 30000;
/** …and while it is delivering, where the poll is only a safety net. */
export const POLL_BACKOFF_MS = 120000;

const DEFAULT_RANGE = '1h';

/** Which tabs need which of the expensive fetches. */
const NEEDS_HISTORY = new Set(['telemetry']);
const NEEDS_PROBES = new Set(['overview', 'probes']);
const NEEDS_DISCOVERY = new Set(['overview', 'discovery']);

export function useAgentDetail(id, { activeTab = 'overview' } = {}) {
  const toast = useToast();

  const [agent, setAgent] = useState(null);
  const [events, setEvents] = useState([]);
  const [presence, setPresence] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [history, setHistory] = useState([]);
  const [probes, setProbes] = useState(null);
  const [discovery, setDiscovery] = useState(null);
  const [capabilityDefaults, setCapabilityDefaults] = useState(null);
  const [historyRange, setHistoryRange] = useState(DEFAULT_RANGE);
  const [loading, setLoading] = useState(true);

  const { statuses } = useAgentLive();
  const telemetryEntities = useMemo(
    () => [{ entity_type: 'agent', entity_id: Number(id) }],
    [id]
  );
  const { data: liveTelemetry } = useTelemetryStream({ entities: telemetryEntities });

  // ── Always on ───────────────────────────────────────────────────────────

  const reload = useCallback(() => {
    Promise.all([getAgent(id), getAgentEvents(id)])
      .then(([agentRes, eventsRes]) => {
        setAgent(agentRes.data);
        setEvents(eventsRes.data);
      })
      .catch(() => toast.error('Could not load agent'))
      .finally(() => setLoading(false));

    // Own catch: online state, connected_since and the linked-hardware summary
    // are not on AgentRead, so this is their only source — but a presence
    // hiccup must not blank the identity the whole page is built around.
    getAgentsPresence({ ids: [id] })
      .then(({ data }) => setPresence(data[0] ?? null))
      .catch(() => setPresence(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    getCapabilityDefaults()
      .then(({ data }) => {
        if (!cancelled) setCapabilityDefaults(data ?? {});
      })
      .catch(() => {
        if (!cancelled) toast.error('Could not load capability defaults');
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadTelemetry = useCallback(() => {
    getAgentTelemetry(id)
      .then(({ data }) => setTelemetry(data))
      .catch(() => {});
  }, [id]);

  // The live stream is the primary path for new samples. This poll reconciles
  // what the stream may have missed across a reconnect, so it backs off rather
  // than running at full rate beside a healthy socket.
  const streamIsDelivering = liveTelemetry.size > 0;

  useEffect(() => {
    reloadTelemetry();
    const period = streamIsDelivering ? POLL_BACKOFF_MS : POLL_ACTIVE_MS;
    const timer = setInterval(reloadTelemetry, period);
    return () => clearInterval(timer);
  }, [reloadTelemetry, streamIsDelivering]);

  // ── Gated on the active tab ─────────────────────────────────────────────

  const wantsHistory = NEEDS_HISTORY.has(activeTab);
  useEffect(() => {
    if (!wantsHistory) return undefined;
    let cancelled = false;
    getAgentTelemetryHistory(id, historyRange)
      .then(({ data }) => {
        if (!cancelled) setHistory(data.points ?? []);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id, historyRange, wantsHistory]);

  const reloadProbes = useCallback(() => {
    getAgentProbes(id)
      .then(({ data }) => setProbes(data))
      .catch(() => setProbes(null));
  }, [id]);

  const wantsProbes = NEEDS_PROBES.has(activeTab);
  useEffect(() => {
    if (wantsProbes) reloadProbes();
  }, [wantsProbes, reloadProbes]);

  const reloadDiscovery = useCallback(() => {
    getAgentDiscovery(id)
      .then(({ data }) => setDiscovery(data))
      .catch(() => setDiscovery(null));
  }, [id]);

  const wantsDiscovery = NEEDS_DISCOVERY.has(activeTab);
  useEffect(() => {
    if (wantsDiscovery) reloadDiscovery();
  }, [wantsDiscovery, reloadDiscovery]);

  // ── Derived ─────────────────────────────────────────────────────────────

  const online = presence?.online ?? null;
  const interval =
    telemetry?.capability?.config?.interval_s ??
    capabilityDefaults?.host_telemetry?.config?.interval_s;

  const states = useMemo(() => {
    if (agent === null) return [];
    const offsetMs = serverClockOffsetMs();
    return deriveAgentStates({
      status: agent.status,
      online,
      lastSeenAt: agent.last_seen_at,
      capabilities: agent.capabilities,
      latestSampleAt: telemetry?.latest?.collected_at ?? null,
      hasTelemetryHistory: Boolean(telemetry?.latest),
      telemetryIntervalSeconds: interval,
      readiness: telemetry?.readiness,
      update: updateStateFromEvents(events),
      spoolDepth: telemetry?.spool?.depth ?? null,
      clockSkewSeconds: offsetMs == null ? null : offsetMs / 1000,
    });
  }, [agent, online, telemetry, interval, events]);

  const page = useMemo(() => composeAgentPage(states), [states]);

  const freshness = useMemo(
    () =>
      telemetryFreshness({
        online,
        lastSeenAt: agent?.last_seen_at ?? null,
        latestSampleAt: telemetry?.latest?.collected_at ?? null,
        telemetryIntervalSeconds: interval,
      }),
    [online, agent, telemetry, interval]
  );

  return {
    agent,
    presence,
    events,
    telemetry,
    history,
    probes,
    discovery,
    capabilityDefaults,
    loading,
    states,
    page,
    freshness,
    online,
    historyRange,
    setHistoryRange,
    reload,
    reloadTelemetry,
    reloadProbes,
    reloadDiscovery,
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-detail-hook.test.jsx
```

Expected: PASS — 10 tests.

- [ ] **Step 5: Lint**

```bash
cd apps/frontend && npm run lint
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/hooks/useAgentDetail.js \
        apps/frontend/src/__tests__/agent-detail-hook.test.jsx
git commit -m "feat(agents): split detail-page loading by active tab

The page fired identity, presence, a 30s telemetry poll, a history range,
probes, discovery, events and two WebSockets on every mount regardless of
what rendered the result.

The split is deliberately not 'gate everything not visible'. A spike must be
visible from a tab that is not showing it, so both sockets and the
latest-sample poll stay always-on — they feed the header strip. Only history
ranges, probe assignments and the discovery tables are gated, and the poll
backs off while the stream is delivering rather than racing it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: AgentStateBanner and AgentIdentityHeader

**Files:**
- Create: `apps/frontend/src/components/agents/AgentStateBanner.jsx`
- Create: `apps/frontend/src/components/agents/AgentIdentityHeader.jsx`
- Test: `apps/frontend/src/__tests__/agent-identity-header.test.jsx`

**Interfaces:**
- Consumes: `Banner` (Task 2), `CopyField` (Task 3), `DetailHeader` (Task 6), `AgentStateChip` and `stateDetailText` from `components/agents/AgentStateChip` (**unmodified**), `agentDisplayName` from `lib/agentLabel`.
- Produces:
  - `<AgentStateBanner state={stateDescriptor} actions={node?} />` → a `Banner`, or `null` when `state` is null or `state.code === 'online'`.
  - `<AgentIdentityHeader agent={} online={} freshness={} chips={node} actions={node} strip={node?} />` → a `DetailHeader`.

**The D3 split, exactly:**

| Banner slot | Content |
|---|---|
| `title` | `state.label` — e.g. `Awaiting approval` |
| `body` | `state.action` — the short imperative, e.g. *Compare the fingerprint against the one the agent printed, then approve or reject it.* |
| `detail` | `${state.summary} ${stateDetailText(state) ?? ''} What to do: ${state.action}` — the composite the old `<dl>` rendered, **byte for byte** |

Nothing is reworded. The imperative is promoted out of the paragraph; the paragraph stays, in full, one click away.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-identity-header.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentStateBanner from '../components/agents/AgentStateBanner';
import AgentIdentityHeader from '../components/agents/AgentIdentityHeader';
import { agentStateDefinition } from '../lib/agentState';
import { FRESHNESS } from '../lib/agentFreshness';

const pending = { code: 'pending_approval', ...agentStateDefinition('pending_approval') };
const online = { code: 'online', ...agentStateDefinition('online') };

const AGENT = {
  id: 7,
  status: 'pending',
  hostname: '73235d37c4a3',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.0.0-dev',
  fingerprint: '5a8253d7b7af678c4fcd7872631139d8',
  last_seen_at: null,
};

const FRESH = { level: FRESHNESS.OFFLINE, label: 'OFFLINE', ageSeconds: null, animate: false };

describe('AgentStateBanner', () => {
  it('leads with the imperative, not the explanation', () => {
    render(<AgentStateBanner state={pending} />);
    expect(screen.getByText(pending.label)).toBeTruthy();
    expect(screen.getByText(pending.action)).toBeTruthy();
  });

  it('keeps the full original wording verbatim behind the disclosure', () => {
    // The AGT-14 prose is relocated, never reworded. This assertion is what
    // makes a future "tidy-up" of that string fail loudly.
    render(<AgentStateBanner state={pending} />);
    const expected = `${pending.summary}  What to do: ${pending.action}`.replace(/\s+/g, ' ');
    const body = document.querySelector('.cb-banner__why-body');
    expect(body.textContent.replace(/\s+/g, ' ').trim()).toBe(expected.trim());
  });

  it('takes its tone from the state rather than deciding one', () => {
    const { container } = render(<AgentStateBanner state={pending} />);
    expect(container.querySelector('.cb-banner').getAttribute('data-tone')).toBe(pending.tone);
  });

  it('renders nothing for a healthy agent', () => {
    // "Online" is not news. A banner that is always present is chrome.
    const { container } = render(<AgentStateBanner state={online} />);
    expect(container.querySelector('.cb-banner')).toBeNull();
  });

  it('renders nothing when there is no state at all', () => {
    const { container } = render(<AgentStateBanner state={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('places actions inside the banner where the decision is being read', () => {
    render(<AgentStateBanner state={pending} actions={<button type="button">Approve</button>} />);
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });
});

describe('AgentIdentityHeader', () => {
  function renderHeader(props = {}) {
    return render(
      <MemoryRouter>
        <AgentIdentityHeader agent={AGENT} online={false} freshness={FRESH} {...props} />
      </MemoryRouter>
    );
  }

  it('titles the page with the agent display name', () => {
    renderHeader();
    expect(screen.getByRole('heading', { level: 1, name: '73235d37c4a3' })).toBeTruthy();
  });

  it('puts status, platform and version in separate meta elements', () => {
    const { container } = renderHeader();
    const items = [...container.querySelectorAll('.cb-meta__item')].map((el) => el.textContent);
    expect(items).toContain('pending');
    expect(items).toContain('linux / amd64');
    expect(items).toContain('v0.0.0-dev');
  });

  it('offers the fingerprint as a copyable field, abbreviated at both ends', () => {
    renderHeader();
    expect(screen.getByRole('button', { name: 'Copy fingerprint' })).toBeTruthy();
    expect(screen.getByTitle(AGENT.fingerprint)).toBeTruthy();
  });

  it('says an agent has never connected rather than showing an empty last-seen', () => {
    const { container } = renderHeader();
    const items = [...container.querySelectorAll('.cb-meta__item')].map((el) => el.textContent);
    expect(items).toContain('never connected');
  });

  it('omits the strip slot when there is nothing live to show', () => {
    const { container } = renderHeader({ strip: null });
    expect(container.querySelector('.cb-detail-head__strip')).toBeNull();
  });

  it('renders chips and actions passed by the page', () => {
    renderHeader({
      chips: <span>Awaiting approval</span>,
      actions: <button type="button">Approve</button>,
    });
    expect(screen.getByText('Awaiting approval')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-identity-header.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/agents/AgentStateBanner"`.

- [ ] **Step 3: Write AgentStateBanner**

Create `apps/frontend/src/components/agents/AgentStateBanner.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import Banner from '../common/Banner';
import { stateDetailText } from './AgentStateChip';

/**
 * The primary agent state, as a banner.
 *
 * The page this replaces rendered every holding state as a <dl> of label,
 * summary and "What to do: …" — correct, complete, and eight paragraphs deep
 * on an agent that had done nothing yet.
 *
 * The split here is positional only. The imperative (state.action) is promoted
 * to the always-visible body; the composite the <dl> used to render is
 * reproduced byte for byte in the disclosure. No wording in lib/agentState is
 * edited by this component or by anything downstream of it.
 */
export default function AgentStateBanner({ state, actions = null }) {
  // "Online" is not news. A banner present on every healthy page is chrome,
  // and chrome is what an operator learns to stop reading.
  if (!state || state.code === 'online') return null;

  const detailText = stateDetailText(state);
  const verbatim = [state.summary, detailText, `What to do: ${state.action}`]
    .filter(Boolean)
    .join(' ');

  return (
    <Banner
      tone={state.tone}
      title={state.label}
      body={state.action}
      detail={verbatim}
      actions={actions}
    />
  );
}

AgentStateBanner.propTypes = {
  state: PropTypes.shape({
    code: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    tone: PropTypes.string,
    summary: PropTypes.string,
    action: PropTypes.string,
    detail: PropTypes.object,
  }),
  actions: PropTypes.node,
};
```

- [ ] **Step 4: Write AgentIdentityHeader**

Create `apps/frontend/src/components/agents/AgentIdentityHeader.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import DetailHeader from '../common/DetailHeader';
import CopyField from '../common/CopyField';
import { agentDisplayName } from '../../lib/agentLabel';
import { formatTimestamp } from '../../lib/time';

const FP_HEAD = 8;
const FP_TAIL = 5;

/**
 * Identity for one agent, in the sticky header.
 *
 * Every meta field is passed as a separate array entry, because DetailHeader
 * wraps each one — the run-together defect on the fleet's pending row came
 * from concatenating fields into a single node.
 */
export default function AgentIdentityHeader({
  agent,
  online,
  freshness,
  chips = null,
  actions = null,
  strip = null,
}) {
  const meta = [
    agent.status,
    agent.os && agent.arch ? `${agent.os} / ${agent.arch}` : null,
    agent.agent_version ? `v${agent.agent_version}` : null,
    agent.fingerprint ? (
      <CopyField value={agent.fingerprint} label="fingerprint" head={FP_HEAD} tail={FP_TAIL} />
    ) : null,
    // "never connected" and not a blank cell: the difference between an agent
    // that has gone quiet and one that has never spoken is the whole question
    // an operator is asking on a pending page.
    agent.last_seen_at ? formatTimestamp(agent.last_seen_at) : 'never connected',
    online === false && freshness?.label ? freshness.label.toLowerCase() : null,
  ].filter(Boolean);

  return (
    <DetailHeader
      backTo="/agents"
      backLabel="Agents"
      title={agentDisplayName(agent, agent.id)}
      chips={chips}
      meta={meta}
      actions={actions}
      strip={strip}
    />
  );
}

AgentIdentityHeader.propTypes = {
  agent: PropTypes.object.isRequired,
  online: PropTypes.bool,
  freshness: PropTypes.shape({ label: PropTypes.string }),
  chips: PropTypes.node,
  actions: PropTypes.node,
  strip: PropTypes.node,
};
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-identity-header.test.jsx
```

Expected: PASS — 12 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/agents/AgentStateBanner.jsx \
        apps/frontend/src/components/agents/AgentIdentityHeader.jsx \
        apps/frontend/src/__tests__/agent-identity-header.test.jsx
git commit -m "feat(agents): promote the imperative, keep the paragraph

The detail page rendered every holding state as label, summary and 'What to
do: …' — correct, complete, and eight paragraphs deep on an agent that had
done nothing yet.

The action is now the always-visible line and the composite the old <dl>
rendered is reproduced byte for byte in the disclosure. A test asserts that
equality, so a later tidy-up of the AGT-14 wording fails loudly instead of
quietly losing it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: AgentLiveStrip

**Files:**
- Create: `apps/frontend/src/components/agents/AgentLiveStrip.jsx`
- Modify: `apps/frontend/src/styles/agents.css` (append)
- Test: `apps/frontend/src/__tests__/agent-live-strip.test.jsx`

**Interfaces:**
- Consumes: `FRESHNESS` from `lib/agentFreshness` (Task 9).
- Produces:
  - `<AgentLiveStrip freshness={{ level, label, animate }} metrics={[{ key, label, value, points, hot }]} dimmed={bool} />`
  - `metrics[].value` is a **pre-formatted string or null**; `points` is a number array.

**This is spec §5.1 — the glass pane.** It renders inside `DetailHeader`'s `strip` slot, so it is on screen on every tab, including Discovery and Events which have no telemetry of their own.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-live-strip.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import AgentLiveStrip from '../components/agents/AgentLiveStrip';
import { FRESHNESS } from '../lib/agentFreshness';

const METRICS = [
  { key: 'cpu', label: 'CPU', value: '12%', points: [10, 12, 11, 12] },
  { key: 'mem', label: 'MEM', value: '38%', points: [37, 38] },
  { key: 'disk', label: 'DISK', value: null, points: [] },
];

const live = { level: FRESHNESS.LIVE, label: 'LIVE', animate: true };
const offline = { level: FRESHNESS.OFFLINE, label: 'OFFLINE', animate: false };

describe('AgentLiveStrip', () => {
  it('states the freshness in words, not only as a colour', () => {
    render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    expect(screen.getByText('LIVE')).toBeTruthy();
  });

  it('animates only while data is actually arriving', () => {
    // The rule this component exists to hold: a pulsing indicator over a dead
    // agent reports health the server has no evidence for.
    const { container, rerender } = render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    expect(container.querySelector('.agent-strip__pill').getAttribute('data-animate')).toBe('true');
    rerender(<AgentLiveStrip freshness={offline} metrics={METRICS} />);
    expect(container.querySelector('.agent-strip__pill').getAttribute('data-animate')).toBe('false');
  });

  it('carries the freshness level as data rather than as a class name', () => {
    const { container } = render(<AgentLiveStrip freshness={offline} metrics={METRICS} />);
    expect(container.querySelector('.agent-strip').getAttribute('data-level')).toBe('offline');
  });

  it('renders an em dash for a metric that has never reported', () => {
    render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('marks a metric over its threshold', () => {
    const { container } = render(
      <AgentLiveStrip
        freshness={live}
        metrics={[{ key: 'cpu', label: 'CPU', value: '93%', points: [90, 93], hot: true }]}
      />
    );
    expect(container.querySelector('[data-metric="cpu"]').getAttribute('data-hot')).toBe('true');
  });

  it('hides the sparklines from assistive technology', () => {
    // The numbers beside them are text, and the Telemetry tab carries the same
    // values. Asking a screen reader to track an animating polyline is asking
    // it to narrate noise.
    const { container } = render(<AgentLiveStrip freshness={live} metrics={METRICS} />);
    container.querySelectorAll('svg').forEach((svg) => {
      expect(svg.getAttribute('aria-hidden')).toBe('true');
    });
  });

  it('dims when the agent is not reporting but last known values remain', () => {
    const { container } = render(<AgentLiveStrip freshness={offline} metrics={METRICS} dimmed />);
    expect(container.querySelector('.agent-strip').getAttribute('data-dimmed')).toBe('true');
  });

  it('draws no sparkline for a series with fewer than two points', () => {
    const { container } = render(
      <AgentLiveStrip freshness={live} metrics={[{ key: 'net', label: 'NET', value: '0', points: [1] }]} />
    );
    expect(container.querySelector('polyline')).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-live-strip.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/agents/AgentLiveStrip"`.

- [ ] **Step 3: Append the styles**

Append to `apps/frontend/src/styles/agents.css`:

```css
/* ── Detail-page live strip ─────────────────────────────────────────────────
   Spec §5.1. This sits in DetailHeader's sticky strip slot, so it is on screen
   on every tab — including Discovery and Events, which carry no telemetry of
   their own. Hiding detail behind tabs is only safe if the pulse never hides
   with it. */

.agent-strip {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  width: 100%;
}

.agent-strip[data-dimmed='true'] .agent-strip__spark polyline { opacity: 0.35; }

.agent-strip__pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-micro);
  letter-spacing: 0.09em;
  font-weight: 700;
  flex: none;
  color: var(--color-success);
}

.agent-strip__pill::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.agent-strip__pill[data-animate='true']::before {
  animation: agent-strip-pulse 1.6s ease-in-out infinite;
}

.agent-strip[data-level='lagging'] .agent-strip__pill,
.agent-strip[data-level='stale'] .agent-strip__pill { color: var(--color-warning); }
.agent-strip[data-level='offline'] .agent-strip__pill { color: var(--color-text-muted); }

@keyframes agent-strip-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.8); }
}

.agent-strip__metric { display: flex; align-items: center; gap: 7px; flex: none; }

.agent-strip__label {
  font-size: var(--fs-micro);
  letter-spacing: 0.09em;
  color: var(--color-text-muted);
  font-weight: 700;
  width: 32px;
}

.agent-strip__spark { width: 78px; height: 22px; display: block; }

.agent-strip__spark polyline {
  fill: none;
  stroke: var(--color-info);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}

.agent-strip__value {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  min-width: 46px;
}

.agent-strip__metric[data-hot='true'] .agent-strip__spark polyline { stroke: var(--color-danger); }
.agent-strip__metric[data-hot='true'] .agent-strip__value { color: var(--color-danger); }

@media (prefers-reduced-motion: reduce) {
  .agent-strip__pill[data-animate='true']::before { animation: none; }
}
```

- [ ] **Step 4: Write the component**

Create `apps/frontend/src/components/agents/AgentLiveStrip.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/agents.css';

const ABSENT = '—';
const VIEW_W = 120;
const VIEW_H = 26;
const MIN_POINTS = 2;

/**
 * Normalise a series over a fixed viewBox, scaled from zero.
 *
 * Rescaling to the series minimum would turn a flat line into a mountain
 * range, which is the opposite of what a strip meant to answer "quiet or
 * spiking?" at a glance should do.
 */
function sparkPoints(points) {
  const max = Math.max(...points) * 1.12 || 1;
  return points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * VIEW_W;
      const y = VIEW_H - (value / max) * (VIEW_H - 2);
      return `${x.toFixed(1)},${Math.max(1, Math.min(VIEW_H - 1, y)).toFixed(1)}`;
    })
    .join(' ');
}

/**
 * The pulse of one machine, pinned to the sticky header.
 *
 * Two rules hold this component together. The freshness label is rendered as
 * text and not only as colour, so what it says survives greyscale and reaches
 * a screen reader. And the pulse animates only when `freshness.animate` is
 * true — lib/agentFreshness owns that decision, and it is false for everything
 * but genuinely arriving data.
 */
export default function AgentLiveStrip({ freshness, metrics, dimmed = false }) {
  return (
    <div className="agent-strip" data-level={freshness.level} data-dimmed={String(dimmed)}>
      <span className="agent-strip__pill" data-animate={String(freshness.animate)}>
        {freshness.label}
      </span>
      {metrics.map((metric) => {
        const points = metric.points ?? [];
        return (
          <div
            className="agent-strip__metric"
            key={metric.key}
            data-metric={metric.key}
            data-hot={String(Boolean(metric.hot))}
          >
            <span className="agent-strip__label">{metric.label}</span>
            {points.length >= MIN_POINTS ? (
              <svg
                className="agent-strip__spark"
                viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <polyline points={sparkPoints(points)} />
              </svg>
            ) : null}
            <b className="agent-strip__value">{metric.value ?? ABSENT}</b>
          </div>
        );
      })}
    </div>
  );
}

AgentLiveStrip.propTypes = {
  freshness: PropTypes.shape({
    level: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    animate: PropTypes.bool.isRequired,
  }).isRequired,
  metrics: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      value: PropTypes.string,
      points: PropTypes.arrayOf(PropTypes.number),
      hot: PropTypes.bool,
    })
  ).isRequired,
  dimmed: PropTypes.bool,
};
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-live-strip.test.jsx
```

Expected: PASS — 8 tests.

- [ ] **Step 6: Lint and commit**

```bash
cd apps/frontend && npm run lint
```

```bash
git add apps/frontend/src/components/agents/AgentLiveStrip.jsx \
        apps/frontend/src/styles/agents.css \
        apps/frontend/src/__tests__/agent-live-strip.test.jsx
git commit -m "feat(agents): pin the machine's pulse to the header

Spec 5.1. The strip renders in DetailHeader's sticky slot, so it stays on
screen on every tab — including Discovery and Events, which carry no
telemetry of their own. Hiding detail behind tabs is only safe if the pulse
does not hide with it.

The pulse animates only when agentFreshness says data is genuinely arriving,
and the freshness label is text rather than colour alone.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: The page shell — tabs, `?tab=`, and composition

**Files:**
- Modify: `apps/frontend/src/pages/AgentDetailPage.jsx` (whole file)
- Test: `apps/frontend/src/__tests__/agent-tabs.test.jsx`
- Test (update): `apps/frontend/src/__tests__/agent-detail-page.test.jsx`

**Interfaces:**
- Consumes: `useAgentDetail` (Task 11), `Tabs` + `panelPropsFor` (Task 5), `AgentIdentityHeader` + `AgentStateBanner` (Task 12), `AgentLiveStrip` (Task 13), `AgentStateChip` (unmodified), `TAB_KEYS` (Task 10).
- Produces: no exports beyond the default page component.

**What moves and what stays.** These blocks in the current file are **cut verbatim** into `AgentTelemetryTab.jsx` in Task 16 — do not rewrite them here, and do not delete them until Task 16 lands:

| Block | Current lines |
|---|---|
| `SUMMARY_LABELS`, `formatMetric`, `formatBytes` | 58–92 |
| `DeviceTable` | 94–122 |
| `HistoryChart` | 124–157 |

These blocks **stay in the page**, unchanged, because they own mutations and confirmation copy that spec §11 puts out of scope:

| Block | Current lines |
|---|---|
| `capabilityConfirmation` | 414–455 |
| `handleToggleCapability`, `handleConfirmCapability` | 457–474 |
| `updateHostConfig`, `updateProbeConfig` | 476–549 |
| `handleRevoke`, `handleUpdate` | 551–576 |
| The three `ConfirmDialog`s | end of the render |

**In this task the page still renders the existing section components inline inside the new shell.** Tabs 15–18 replace them one at a time. That keeps every step shippable.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-tabs.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

const hookResult = {
  agent: {
    id: 7,
    status: 'active',
    hostname: 'edge-01',
    os: 'linux',
    arch: 'amd64',
    agent_version: '0.4.0',
    fingerprint: 'a'.repeat(32),
    last_seen_at: new Date().toISOString(),
    capabilities: {},
  },
  presence: { online: true, hardware: null },
  events: [],
  telemetry: null,
  history: [],
  probes: [],
  discovery: null,
  capabilityDefaults: {},
  loading: false,
  states: [{ code: 'online', label: 'Online', tone: 'ok', summary: 's', action: 'a' }],
  page: {
    primary: { code: 'online', label: 'Online', tone: 'ok', summary: 's', action: 'a' },
    secondary: [],
    showLiveStrip: true,
    liveStripDimmed: false,
    tabs: ['overview', 'telemetry', 'probes', 'discovery', 'events'],
    overviewPanels: ['capabilities', 'discovery', 'probes', 'hardware', 'events'],
    capabilitiesLocked: false,
    blockedReason: null,
  },
  freshness: { level: 'live', label: 'LIVE', ageSeconds: 3, animate: true },
  online: true,
  historyRange: '1h',
  setHistoryRange: vi.fn(),
  reload: vi.fn(),
  reloadTelemetry: vi.fn(),
  reloadProbes: vi.fn(),
  reloadDiscovery: vi.fn(),
};

vi.mock('../hooks/useAgentDetail', () => ({
  useAgentDetail: (...args) => {
    hookResult.calls.push(args);
    return hookResult;
  },
  POLL_ACTIVE_MS: 30000,
  POLL_BACKOFF_MS: 120000,
}));
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}));

import AgentDetailPage from '../pages/AgentDetailPage';

function renderAt(url) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  hookResult.calls = [];
});

describe('agent detail tabs', () => {
  it('opens on overview when no tab is named', async () => {
    renderAt('/agents/7');
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Overview' })).toBeTruthy());
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true');
  });

  it('opens on the tab named in the URL', async () => {
    renderAt('/agents/7?tab=discovery');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Discovery' }).getAttribute('aria-selected')).toBe('true')
    );
  });

  it('falls back to overview for a tab name it does not know', async () => {
    // A stale bookmark or a hand-edited URL must not produce a blank page.
    renderAt('/agents/7?tab=nonsense');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true')
    );
  });

  it('writes the tab into the URL when one is clicked', async () => {
    renderAt('/agents/7');
    await userEvent.click(await screen.findByRole('tab', { name: 'Events' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Events' }).getAttribute('aria-selected')).toBe('true')
    );
  });

  it('tells the data hook which tab is active, so gating can work', async () => {
    renderAt('/agents/7?tab=telemetry');
    await waitFor(() => expect(hookResult.calls.length).toBeGreaterThan(0));
    const [, options] = hookResult.calls.at(-1);
    expect(options.activeTab).toBe('telemetry');
  });

  it('renders one tabpanel, labelled by its tab', async () => {
    renderAt('/agents/7?tab=events');
    const panel = await screen.findByRole('tabpanel');
    expect(panel.id).toBe('cb-panel-events');
    expect(panel.getAttribute('aria-labelledby')).toBe('cb-tab-events');
  });

  it('keeps the live strip on a tab that has no telemetry of its own', async () => {
    // Spec 5.1: the pulse must not hide with the detail.
    const { container } = renderAt('/agents/7?tab=events');
    await waitFor(() => expect(container.querySelector('.agent-strip')).toBeTruthy());
    expect(screen.getByText('LIVE')).toBeTruthy();
  });

  it('renders only the tabs the composition allows', async () => {
    hookResult.page = { ...hookResult.page, tabs: ['overview', 'events'] };
    renderAt('/agents/7');
    await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(2));
    hookResult.page = { ...hookResult.page, tabs: ['overview', 'telemetry', 'probes', 'discovery', 'events'] };
  });

  it('shows no live strip when the composition withholds it', async () => {
    hookResult.page = { ...hookResult.page, showLiveStrip: false };
    const { container } = renderAt('/agents/7');
    await waitFor(() => expect(screen.getByRole('tablist')).toBeTruthy());
    expect(container.querySelector('.agent-strip')).toBeNull();
    hookResult.page = { ...hookResult.page, showLiveStrip: true };
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-tabs.test.jsx
```

Expected: FAIL — no `tablist` role in the document.

- [ ] **Step 3: Replace the page's imports, tab state, and render body**

In `apps/frontend/src/pages/AgentDetailPage.jsx`:

**(a)** Add these imports beside the existing ones:

```jsx
import { useSearchParams } from 'react-router-dom';
import Tabs, { panelPropsFor } from '../components/common/Tabs';
import AgentIdentityHeader from '../components/agents/AgentIdentityHeader';
import AgentStateBanner from '../components/agents/AgentStateBanner';
import AgentLiveStrip from '../components/agents/AgentLiveStrip';
import { useAgentDetail } from '../hooks/useAgentDetail';
import { TAB_KEYS } from '../lib/agentComposition';
```

**(b)** Add the tab constants above the component:

```jsx
const TAB_LABELS = {
  overview: 'Overview',
  telemetry: 'Telemetry',
  probes: 'Probes',
  discovery: 'Discovery',
  events: 'Events',
};

const DEFAULT_TAB = 'overview';

/** Which strip metrics come from which summary key, in reading order. */
const STRIP_METRICS = [
  { key: 'cpu_pct', label: 'CPU' },
  { key: 'mem_pct', label: 'MEM' },
  { key: 'root_disk_pct', label: 'DISK' },
  { key: 'net_rx_bps', label: 'NET' },
  { key: 'max_temp_c', label: 'TEMP' },
];
```

**(c)** Replace every `useState`/`useEffect`/loader block between the component's opening line and `capabilityConfirmation` with the hook plus tab state. The confirmation and mutation handlers below it are untouched:

```jsx
export default function AgentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  const [revokeOpen, setRevokeOpen] = useState(false);
  const [updateConfirmOpen, setUpdateConfirmOpen] = useState(false);
  const [pendingCapability, setPendingCapability] = useState(null);

  const requestedTab = searchParams.get('tab');
  // A stale bookmark or a hand-edited URL must land somewhere, not on a blank
  // page — and the composition, not the URL, decides which tabs exist at all.
  const activeTab = TAB_KEYS.includes(requestedTab) ? requestedTab : DEFAULT_TAB;

  const detail = useAgentDetail(id, { activeTab });
  const {
    agent,
    presence,
    events,
    telemetry,
    history,
    probes,
    discovery,
    capabilityDefaults,
    loading,
    page,
    freshness,
    online,
    historyRange,
    setHistoryRange,
    reload,
    reloadProbes,
    reloadDiscovery,
  } = detail;

  const hostDefaults = capabilityDefaults?.host_telemetry?.config ?? {};
  const probeDefaults = capabilityDefaults?.remote_probe?.config ?? {};
  const discoveryDefaults = capabilityDefaults?.local_discovery?.config ?? {};

  const selectTab = useCallback(
    (key) => {
      // `replace` so a five-tab page does not bury the previous page under five
      // history entries the back button has to walk out of.
      setSearchParams((params) => {
        const next = new URLSearchParams(params);
        next.set('tab', key);
        return next;
      });
    },
    [setSearchParams]
  );

  const tabs = useMemo(
    () => page.tabs.map((key) => ({ key, label: TAB_LABELS[key] })),
    [page.tabs]
  );

  const stripMetrics = useMemo(
    () =>
      STRIP_METRICS.map(({ key, label }) => ({
        key,
        label,
        value:
          telemetry?.latest?.summary?.[key] == null
            ? null
            : formatMetric(key, telemetry.latest.summary[key]),
        points: history.map((point) => point[key]).filter((value) => typeof value === 'number'),
      })),
    [telemetry, history]
  );

  // …capabilityConfirmation and every handler below stay exactly as they are…
```

**(d)** Replace the whole `return (…)` with the shell. `renderTab` grows in Tasks 15–18; for now it renders the same components the old page did:

```jsx
  if (loading) return <div className="agent-detail-page">Loading…</div>;
  if (!agent) return <div className="agent-detail-page">Agent not found</div>;

  const agentLabel = agentDisplayName(agent, id);

  const headerActions = (
    <>
      <button type="button" onClick={() => setUpdateConfirmOpen(true)}>
        Update
      </button>
      {agent.status === 'active' && (
        <button type="button" onClick={() => setRevokeOpen(true)}>
          Revoke
        </button>
      )}
    </>
  );

  const renderTab = () => {
    if (activeTab === 'probes') {
      return (
        <AssignedProbesSection
          agentId={Number(id)}
          probes={probes}
          granted={normalizeCapability(agent.capabilities?.remote_probe).enabled}
          onChanged={reloadProbes}
        >
          {normalizeCapability(agent.capabilities?.remote_probe).enabled &&
            (capabilityDefaults === null ? (
              <p>Loading remote probe settings…</p>
            ) : (
              <RemoteProbeConfigEditor
                config={normalizeCapability(agent.capabilities.remote_probe).config}
                defaults={probeDefaults}
                onChange={updateProbeConfig}
              />
            ))}
        </AssignedProbesSection>
      );
    }
    if (activeTab === 'discovery') {
      return (
        <DiscoveryScopeSection
          agentId={id}
          agentName={agentLabel}
          discovery={discovery}
          granted={normalizeCapability(agent.capabilities?.local_discovery).enabled}
          config={normalizeCapability(agent.capabilities.local_discovery).config}
          defaults={capabilityDefaults === null ? null : discoveryDefaults}
          onDiscovery={() => {}}
          onChanged={() => {
            reload();
            reloadDiscovery();
          }}
        />
      );
    }
    if (activeTab === 'events') {
      return <AgentEventsPanel events={events} />;
    }
    if (activeTab === 'telemetry') {
      return (
        <AgentTelemetryTab
          telemetry={telemetry}
          history={history}
          historyRange={historyRange}
          onHistoryRange={setHistoryRange}
          hostDefaults={hostDefaults}
          hasHardware={Boolean(presence?.hardware)}
        />
      );
    }
    return (
      <AgentOverviewTab
        panels={page.overviewPanels}
        agent={agent}
        presence={presence}
        events={events}
        probes={probes}
        discovery={discovery}
        capabilitiesLocked={page.capabilitiesLocked}
        blockedReason={page.blockedReason}
        stripMetrics={stripMetrics}
        onToggleCapability={handleToggleCapability}
        onSelectTab={selectTab}
      />
    );
  };

  return (
    <div className="agent-detail-page">
      <AgentIdentityHeader
        agent={agent}
        online={online}
        freshness={freshness}
        chips={page.secondary
          .concat(page.primary && page.primary.code === 'online' ? [page.primary] : [])
          .map((state) => (
            <AgentStateChip key={state.code} state={state} showAction={false} />
          ))}
        actions={headerActions}
        strip={
          page.showLiveStrip ? (
            <AgentLiveStrip
              freshness={freshness}
              metrics={stripMetrics}
              dimmed={page.liveStripDimmed}
            />
          ) : null
        }
      />

      <AgentStateBanner state={page.primary} />

      <Tabs tabs={tabs} active={activeTab} onChange={selectTab} label="Agent sections" />

      <div className="agent-detail-page__panel" {...panelPropsFor(activeTab)}>
        {renderTab()}
      </div>

      {/* AGT-16: names the machine and states what revocation actually does. */}
      <ConfirmDialog
        open={revokeOpen}
        message={
          `Revoke ${agentLabel}? Its credential stops working immediately: it disconnects, ` +
          'stops reporting telemetry, and every monitor assigned to it stops running from that ' +
          'vantage. It cannot reconnect without being enrolled and approved again.'
        }
        onConfirm={handleRevoke}
        onCancel={() => setRevokeOpen(false)}
      />

      {/* AGT-16: dispatching an update replaces the running binary on a remote
          machine, and a failed swap is recovered by the agent's own rollback. */}
      <ConfirmDialog
        open={updateConfirmOpen}
        message={
          `Update ${agentLabel} from version ${agent.agent_version ?? 'unknown'} to the newest ` +
          'published agent build? It downloads the binary, verifies its digest and restarts ' +
          'itself, so it drops off briefly. If the swap fails it rolls back to the version it ' +
          'is on now and reports the failure here.'
        }
        onConfirm={handleUpdate}
        onCancel={() => setUpdateConfirmOpen(false)}
      />

      <ConfirmDialog
        open={pendingCapability !== null}
        message={pendingCapability?.message ?? ''}
        onConfirm={handleConfirmCapability}
        onCancel={() => setPendingCapability(null)}
      />
    </div>
  );
}
```

**(e)** Add the panel rule to `apps/frontend/src/styles/agents.css`:

```css
.agent-detail-page__panel { padding: var(--space-4); }
.agent-detail-page__panel:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
```

**(f)** Tasks 15–17 create `AgentEventsPanel`, `AgentTelemetryTab` and `AgentOverviewTab`. Until they exist, add three temporary local definitions at the bottom of the page file so this task is independently runnable, and delete each one as its real component lands:

```jsx
// Replaced by AgentEventsPanel in Task 15.
function AgentEventsPanel({ events }) {
  return (
    <ul>
      {events.map((event) => {
        const described = describeAgentEvent(event);
        return (
          <li key={event.id}>
            <span>{formatTimestamp(event.created_at)}</span> — <strong>{described.label}</strong>
            {described.detail && <span> — {described.detail}</span>}
          </li>
        );
      })}
    </ul>
  );
}
AgentEventsPanel.propTypes = { events: PropTypes.array.isRequired };

// Replaced by AgentTelemetryTab in Task 16.
function AgentTelemetryTab() {
  return <p>No host samples received yet.</p>;
}

// Replaced by AgentOverviewTab in Task 17.
function AgentOverviewTab() {
  return <p>Overview</p>;
}
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-tabs.test.jsx
```

Expected: PASS — 9 tests.

- [ ] **Step 5: Re-point the existing detail-page suite**

`src/__tests__/agent-detail-page.test.jsx` (1,434 lines) asserts against markup that no longer exists on one page. Content on a non-active tab is not in the DOM, so each assertion must first select its tab. Add this helper near the top of the file and call it before any assertion about probes, discovery, telemetry or events:

```jsx
import userEvent from '@testing-library/user-event';

/**
 * Tabs mean a section is only in the DOM while its tab is selected. Every
 * assertion about a section must first ask for that section.
 */
async function openTab(name) {
  await userEvent.click(await screen.findByRole('tab', { name }));
  return screen.findByRole('tabpanel');
}
```

Work through the file failure by failure:

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-detail-page.test.jsx
```

Expected on first run: many failures, all of the form "Unable to find an element". For each, add `await openTab('Probes' | 'Discovery' | 'Telemetry' | 'Events')` before the assertion. **Do not delete an assertion to make it pass** — if a behaviour genuinely no longer exists, stop and raise it rather than removing its test.

- [ ] **Step 6: Run the whole agent suite**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-*.test.jsx src/__tests__/agents-*.test.jsx src/__tests__/fleet-*.test.jsx src/__tests__/monitor-from-agent.test.jsx
```

Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd apps/frontend && npm run lint
```

```bash
git add apps/frontend/src/pages/AgentDetailPage.jsx \
        apps/frontend/src/styles/agents.css \
        apps/frontend/src/__tests__/agent-tabs.test.jsx \
        apps/frontend/src/__tests__/agent-detail-page.test.jsx
git commit -m "feat(agents): give the detail page a shell

Identity, state and the live strip are now sticky and constant; everything
below them is a tab, backed by ?tab= so deep links and the back button work
without a router change.

Which tabs exist is decided by lib/agentComposition from the agent's
lifecycle state, not by the URL — a revoked agent has no telemetry tab to
link to, and an unknown tab name falls back to overview rather than
rendering a blank page.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: Capabilities, Hardware and Events panels

**Files:**
- Create: `apps/frontend/src/components/agents/AgentCapabilitiesPanel.jsx`
- Create: `apps/frontend/src/components/agents/AgentHardwarePanel.jsx`
- Create: `apps/frontend/src/components/agents/AgentEventsPanel.jsx`
- Modify: `apps/frontend/src/pages/AgentDetailPage.jsx` (delete the temporary `AgentEventsPanel` from Task 14 step (f); import the real one)
- Test: `apps/frontend/src/__tests__/agent-panels.test.jsx`

**Interfaces:**
- Consumes: `Panel` (Task 1), `EmptyState` (Task 2), `KeyValue` (Task 3), `Toggle` (Task 4); `describeAgentEvent` from `lib/agentErrors` (**unmodified** — AGT-15 redaction is not touched); `formatTimestamp` from `lib/time`; `normalizeCapability` from `api/agents`.
- Produces:
  - `<AgentCapabilitiesPanel capabilities={} locked={bool} blockedReason={string|null} onToggle={fn(key, enabled)} children={node?} />`
  - `<AgentHardwarePanel hardware={object|null} />`
  - `<AgentEventsPanel events={array} />`

`CAPABILITY_LABELS` moves out of `AgentDetailPage.jsx:44-56` into `AgentCapabilitiesPanel.jsx` and is re-exported from there; the page imports it from its new home.

**Blocked-reason copy** — the note beside each locked toggle:

| `blockedReason` | Note |
|---|---|
| `'approval'` | `locked until approved` |
| `'revocation'` | `credential revoked` |
| `null` | none |

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-panels.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentCapabilitiesPanel from '../components/agents/AgentCapabilitiesPanel';
import AgentHardwarePanel from '../components/agents/AgentHardwarePanel';
import AgentEventsPanel from '../components/agents/AgentEventsPanel';

const CAPS = {
  host_telemetry: { enabled: true, config: { interval_s: 30 } },
  remote_probe: { enabled: false, config: {} },
  local_discovery: { enabled: false, config: {} },
};

describe('AgentCapabilitiesPanel', () => {
  it('renders one switch per capability with its current state', () => {
    render(<AgentCapabilitiesPanel capabilities={CAPS} onToggle={() => {}} />);
    expect(screen.getByRole('switch', { name: /Host telemetry/ }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('switch', { name: /Remote probe/ }).getAttribute('aria-checked')).toBe('false');
  });

  it('reports the capability key and the requested state', async () => {
    const onToggle = vi.fn();
    render(<AgentCapabilitiesPanel capabilities={CAPS} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole('switch', { name: /Remote probe/ }));
    expect(onToggle).toHaveBeenCalledWith('remote_probe', true);
  });

  it('disables every switch and names the blocker when locked', async () => {
    // A toggle that silently does nothing is worse than one that says why.
    const onToggle = vi.fn();
    render(
      <AgentCapabilitiesPanel capabilities={CAPS} locked blockedReason="approval" onToggle={onToggle} />
    );
    const control = screen.getByRole('switch', { name: 'Host telemetry — locked until approved' });
    expect(control.disabled).toBe(true);
    await userEvent.click(control);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('names revocation as the blocker when that is the reason', () => {
    render(
      <AgentCapabilitiesPanel capabilities={CAPS} locked blockedReason="revocation" onToggle={() => {}} />
    );
    expect(screen.getByRole('switch', { name: 'Remote probe — credential revoked' })).toBeTruthy();
  });

  it('summarises how many capabilities are on', () => {
    render(<AgentCapabilitiesPanel capabilities={CAPS} onToggle={() => {}} />);
    expect(screen.getByText('1 of 3 on')).toBeTruthy();
  });

  it('renders capability settings passed as children', () => {
    render(
      <AgentCapabilitiesPanel capabilities={CAPS} onToggle={() => {}}>
        <p>Cadence settings</p>
      </AgentCapabilitiesPanel>
    );
    expect(screen.getByText('Cadence settings')).toBeTruthy();
  });
});

describe('AgentHardwarePanel', () => {
  it('names the linked hardware and its hostname', () => {
    render(<AgentHardwarePanel hardware={{ name: 'rack-01-node3', hostname: 'node3.lan' }} />);
    expect(screen.getByText('rack-01-node3')).toBeTruthy();
    expect(screen.getByText('node3.lan')).toBeTruthy();
  });

  it('says what linking would buy when nothing is linked', () => {
    render(<AgentHardwarePanel hardware={null} />);
    expect(screen.getByText('No hardware linked')).toBeTruthy();
    expect(
      screen.getByText('Link this agent to Hardware to add topology, analytics, and Hardware telemetry views.')
    ).toBeTruthy();
  });

  it('renders without a hostname', () => {
    render(<AgentHardwarePanel hardware={{ name: 'rack-01-node3', hostname: null }} />);
    expect(screen.getByText('rack-01-node3')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
  });
});

describe('AgentEventsPanel', () => {
  const EVENTS = [
    { id: 1, created_at: '2026-09-05T11:52:00Z', event_type: 'enrolled', detail: {} },
    { id: 2, created_at: '2026-09-05T11:58:00Z', event_type: 'approved', detail: {} },
  ];

  it('renders one row per event', () => {
    render(<AgentEventsPanel events={EVENTS} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('goes through describeAgentEvent rather than stringifying the payload', () => {
    // AGT-15. This list once rendered JSON.stringify(e.detail), putting frame
    // types and raw validation text off the wire in front of an operator.
    render(<AgentEventsPanel events={EVENTS} />);
    expect(screen.queryByText(/\{/)).toBeNull();
  });

  it('says so rather than rendering an empty list', () => {
    render(<AgentEventsPanel events={[]} />);
    expect(screen.getByText('No events recorded yet')).toBeTruthy();
  });

  it('summarises the count in the panel header', () => {
    render(<AgentEventsPanel events={EVENTS} />);
    expect(screen.getByText('2')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-panels.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/agents/AgentCapabilitiesPanel"`.

- [ ] **Step 3: Write AgentCapabilitiesPanel**

Create `apps/frontend/src/components/agents/AgentCapabilitiesPanel.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import Toggle from '../common/Toggle';
import { normalizeCapability } from '../../api/agents';

/** Moved here from AgentDetailPage; this is the only component that needs it. */
export const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

/** Why a toggle cannot be used, in the operator's terms. */
const BLOCKED_NOTES = {
  approval: 'locked until approved',
  revocation: 'credential revoked',
};

/**
 * The three capability switches.
 *
 * When the agent's lifecycle state makes these unusable, each switch says why
 * rather than simply appearing dim. A control that silently does nothing is a
 * worse answer than one that names its precondition — and the note is folded
 * into the accessible name by Toggle, so the reason is not colour-only.
 */
export default function AgentCapabilitiesPanel({
  capabilities,
  locked = false,
  blockedReason = null,
  onToggle,
  children = null,
}) {
  const keys = Object.keys(CAPABILITY_LABELS);
  const enabled = keys.filter((key) => normalizeCapability(capabilities?.[key]).enabled).length;
  const note = locked ? (BLOCKED_NOTES[blockedReason] ?? null) : null;

  return (
    <Panel title="Capabilities" summary={`${enabled} of ${keys.length} on`}>
      {keys.map((key) => (
        <Toggle
          key={key}
          label={CAPABILITY_LABELS[key]}
          note={note}
          disabled={locked}
          checked={normalizeCapability(capabilities?.[key]).enabled}
          onChange={(next) => onToggle(key, next)}
        />
      ))}
      {children}
    </Panel>
  );
}

AgentCapabilitiesPanel.propTypes = {
  capabilities: PropTypes.object,
  locked: PropTypes.bool,
  blockedReason: PropTypes.oneOf(['approval', 'revocation', null]),
  onToggle: PropTypes.func.isRequired,
  children: PropTypes.node,
};
```

- [ ] **Step 4: Write AgentHardwarePanel**

Create `apps/frontend/src/components/agents/AgentHardwarePanel.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import KeyValue from '../common/KeyValue';
import EmptyState from '../common/EmptyState';

export default function AgentHardwarePanel({ hardware }) {
  return (
    <Panel title="Linked hardware">
      {hardware ? (
        <KeyValue
          rows={[
            ['Name', hardware.name],
            ['Hostname', hardware.hostname],
          ]}
        />
      ) : (
        <EmptyState
          icon="▤"
          message="No hardware linked"
          hint="Link this agent to Hardware to add topology, analytics, and Hardware telemetry views."
        />
      )}
    </Panel>
  );
}

AgentHardwarePanel.propTypes = {
  hardware: PropTypes.shape({ name: PropTypes.string, hostname: PropTypes.string }),
};
```

- [ ] **Step 5: Write AgentEventsPanel**

Create `apps/frontend/src/components/agents/AgentEventsPanel.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import EmptyState from '../common/EmptyState';
import { describeAgentEvent } from '../../lib/agentErrors';
import { formatTimestamp } from '../../lib/time';
import '../../styles/agents.css';

/**
 * The agent's event history.
 *
 * AGT-15: every row goes through describeAgentEvent, which allow-lists the
 * keys it will show per event type and redacts what it does show. This list
 * once rendered JSON.stringify(event.detail), which put frame types, sequence
 * numbers and raw validation text straight off the wire in front of an
 * operator — and would have carried whatever a future payload added with it.
 * Nothing here may reach into `event.detail` directly.
 */
export default function AgentEventsPanel({ events }) {
  return (
    <Panel title="Events" summary={String(events.length)}>
      {events.length === 0 ? (
        <EmptyState icon="≡" message="No events recorded yet" />
      ) : (
        <ul className="agent-events">
          {events.map((event) => {
            const described = describeAgentEvent(event);
            return (
              <li key={event.id}>
                <time>{formatTimestamp(event.created_at)}</time>
                <strong>{described.label}</strong>
                {described.detail ? <span>{described.detail}</span> : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

AgentEventsPanel.propTypes = { events: PropTypes.array.isRequired };
```

- [ ] **Step 6: Append the events styles**

Append to `apps/frontend/src/styles/agents.css`:

```css
.agent-events { list-style: none; margin: 0; padding: 0; font-size: var(--fs-sm); }

.agent-events li {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-1) 0;
  border-bottom: 1px solid rgba(80, 73, 69, 0.35);
}

.agent-events li:last-child { border-bottom: 0; }

.agent-events time {
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  flex: none;
  width: 132px;
}
```

- [ ] **Step 7: Wire the real component into the page**

In `apps/frontend/src/pages/AgentDetailPage.jsx`, delete the temporary `AgentEventsPanel` added in Task 14 step (f), delete the local `CAPABILITY_LABELS` at lines 44–56, and add:

```jsx
import AgentEventsPanel from '../components/agents/AgentEventsPanel';
import AgentCapabilitiesPanel, { CAPABILITY_LABELS } from '../components/agents/AgentCapabilitiesPanel';
import AgentHardwarePanel from '../components/agents/AgentHardwarePanel';
```

`CAPABILITY_LABELS` is still referenced by `capabilityConfirmation`, so the import keeps that block working unchanged.

- [ ] **Step 8: Run the tests**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-panels.test.jsx src/__tests__/agent-tabs.test.jsx
```

Expected: PASS — 12 + 9 tests.

- [ ] **Step 9: Commit**

```bash
git add apps/frontend/src/components/agents/AgentCapabilitiesPanel.jsx \
        apps/frontend/src/components/agents/AgentHardwarePanel.jsx \
        apps/frontend/src/components/agents/AgentEventsPanel.jsx \
        apps/frontend/src/pages/AgentDetailPage.jsx \
        apps/frontend/src/styles/agents.css \
        apps/frontend/src/__tests__/agent-panels.test.jsx
git commit -m "feat(agents): panel the capabilities, hardware and events sections

A locked capability now names its precondition — 'locked until approved',
'credential revoked' — in the switch's accessible name rather than only
appearing dim. A control that silently does nothing is a worse answer than
one that says why.

AGT-15 redaction is untouched: AgentEventsPanel still routes every row
through describeAgentEvent and reaches into event.detail nowhere.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: AgentTelemetryTab

**Files:**
- Create: `apps/frontend/src/components/agents/AgentTelemetryTab.jsx`
- Modify: `apps/frontend/src/pages/AgentDetailPage.jsx` (cut lines 58–157 out; delete the temporary stub)
- Test: `apps/frontend/src/__tests__/agent-telemetry-tab.test.jsx`

**Interfaces:**
- Consumes: `Panel` (Task 1), `EmptyState` + `Banner` (Task 2), `StatTile` (Task 4).
- Produces:
  - `<AgentTelemetryTab telemetry={} history={} historyRange={} onHistoryRange={fn} hostDefaults={} hasHardware={bool} />`
  - Re-exports `formatMetric` and `SUMMARY_LABELS`, which `AgentDetailPage` still needs for the header strip.

**Move these verbatim from `AgentDetailPage.jsx`** — do not rewrite them, they carry decisions this task is not revisiting:

| Block | Lines | Note |
|---|---|---|
| `SUMMARY_LABELS` | 58–68 | |
| `formatMetric` | 69–81 | |
| `formatBytes` | 82–92 | |
| `DeviceTable` | 94–122 | |
| `HistoryChart` | 124–157 | |

**Two behaviours that must survive the move**, both currently load-bearing comments in the page:

1. **The catch-up indicator renders outside the `latest` branch.** An agent that buffered samples but has never delivered one is exactly when the backlog is worth showing — nothing else on the section would explain the empty page. Depth `0` and a null spool both render nothing.
2. **Docker's payload is a dict, not a row array.** `telemetry.latest.payload.docker` is `{containers, total, running, truncated}`. Only `.containers` may reach `DeviceTable`; handing it the dict makes `Object.keys(rows[0])` a nonsense header.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-telemetry-tab.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AgentTelemetryTab from '../components/agents/AgentTelemetryTab';

const HOST_DEFAULTS = { interval_s: 30 };

const withLatest = (overrides = {}) => ({
  capability: { config: { interval_s: 30 } },
  latest: {
    collected_at: new Date().toISOString(),
    projected: false,
    summary: { cpu_pct: 12, mem_pct: 38, root_disk_pct: 61, net_rx_bps: 2400, max_temp_c: 44 },
    payload: {},
  },
  readiness: [],
  spool: { depth: 0 },
  ...overrides,
});

function renderTab(props = {}) {
  return render(
    <AgentTelemetryTab
      telemetry={null}
      history={[]}
      historyRange="1h"
      onHistoryRange={() => {}}
      hostDefaults={HOST_DEFAULTS}
      hasHardware={false}
      {...props}
    />
  );
}

describe('AgentTelemetryTab', () => {
  it('says no samples have arrived rather than rendering empty tiles', () => {
    renderTab();
    expect(screen.getByText('No host samples received yet.')).toBeTruthy();
  });

  it('shows the spool backlog even when no sample has ever been delivered', () => {
    // An agent that buffered samples but delivered none is exactly when the
    // backlog is worth showing — nothing else here would explain the blank.
    renderTab({ telemetry: { latest: null, readiness: [], spool: { depth: 42 } } });
    expect(screen.getByText(/42 samples buffered/)).toBeTruthy();
  });

  it('shows no backlog indicator for a drained spool', () => {
    renderTab({ telemetry: { latest: null, readiness: [], spool: { depth: 0 } } });
    expect(screen.queryByText(/samples buffered/)).toBeNull();
  });

  it('renders a tile per summary metric once a sample exists', () => {
    const { container } = renderTab({ telemetry: withLatest() });
    expect(container.querySelectorAll('.cb-tile')).toHaveLength(5);
  });

  it('raises a banner for a degraded collector', () => {
    const { container } = renderTab({
      telemetry: withLatest({
        readiness: [
          { collector: 'host.cpu', state: 'degraded', reason: 'cannot read /proc', remediation: 'check perms' },
        ],
      }),
    });
    expect(container.querySelector('.cb-banner')).toBeTruthy();
    expect(screen.getByText(/cannot read \/proc/)).toBeTruthy();
  });

  it('does not raise a banner for a collector that is merely switched off', () => {
    // A disabled collector is a choice, not a fault.
    const { container } = renderTab({
      telemetry: withLatest({ readiness: [{ collector: 'host.docker', state: 'disabled' }] }),
    });
    expect(container.querySelector('.cb-banner')).toBeNull();
  });

  it('passes only the container rows to the device table, never the docker dict', () => {
    // payload.docker is {containers, total, running, truncated}. Handing the
    // dict to DeviceTable makes Object.keys(rows[0]) a nonsense header.
    renderTab({
      telemetry: withLatest({
        latest: {
          ...withLatest().latest,
          payload: {
            docker: {
              total: 2,
              running: 1,
              truncated: false,
              containers: [{ id: 'abc', name: 'web', image: 'nginx', state: 'running' }],
            },
          },
        },
      }),
    });
    expect(screen.getByText('1 of 2 containers running')).toBeTruthy();
    expect(screen.getByText('web')).toBeTruthy();
  });

  it('reports the selected history range and reports a change', async () => {
    const onHistoryRange = vi.fn();
    renderTab({ telemetry: withLatest(), historyRange: '6h', onHistoryRange });
    const select = screen.getByLabelText(/History range/);
    expect(select.value).toBe('6h');
  });

  it('offers to link hardware when none is linked', () => {
    renderTab({ telemetry: withLatest(), hasHardware: false });
    expect(
      screen.getByText('Link this agent to Hardware to add topology, analytics, and Hardware telemetry views.')
    ).toBeTruthy();
  });

  it('says nothing about hardware when hardware is already linked', () => {
    renderTab({ telemetry: withLatest(), hasHardware: true });
    expect(screen.queryByText(/Link this agent to Hardware/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-telemetry-tab.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/agents/AgentTelemetryTab"`.

- [ ] **Step 3: Create the component with the moved helpers**

Create `apps/frontend/src/components/agents/AgentTelemetryTab.jsx`. Paste `SUMMARY_LABELS`, `formatMetric`, `formatBytes`, `DeviceTable` and `HistoryChart` from `AgentDetailPage.jsx:58-157` **unchanged**, then add:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import StatTile from '../common/StatTile';
import EmptyState from '../common/EmptyState';
import Banner from '../common/Banner';
import '../../styles/agents.css';

// ── moved verbatim from AgentDetailPage.jsx:58-157 ──────────────────────────
// SUMMARY_LABELS, formatMetric, formatBytes, DeviceTable, HistoryChart
// (paste here unchanged; formatMetric and SUMMARY_LABELS are re-exported below
//  because the page's header strip formats its values with them)
// ────────────────────────────────────────────────────────────────────────────

export { SUMMARY_LABELS, formatMetric };

const STALE_FLOOR_MS = 90000;
const STALE_MULTIPLIER = 3000;
const RANGES = ['1h', '6h', '24h', '7d', '30d'];

const CATCH_UP_LABEL =
  'The agent is replaying host samples it buffered while it could not reach ' +
  'the server. Displayed samples may lag until the backlog drains.';

/** Series for one metric, in the order history returned it. */
function seriesFor(history, key) {
  return history.map((point) => point[key]).filter((value) => typeof value === 'number');
}

export default function AgentTelemetryTab({
  telemetry,
  history,
  historyRange,
  onHistoryRange,
  hostDefaults,
  hasHardware,
}) {
  // hostDefaults, not a literal: the registry owns the cadence default, and a
  // second copy here is exactly the drift this avoids.
  const interval = telemetry?.capability?.config?.interval_s ?? hostDefaults.interval_s;

  // Deliberately outside the `latest` branch. Depth 0 ("reported, drained")
  // and a null spool ("this agent predates spool reporting") both render
  // nothing — but an agent that buffered samples and has never delivered one
  // is exactly when the backlog is worth showing, since nothing else on this
  // tab would explain the empty page.
  const spoolDepth = telemetry?.spool?.depth ?? 0;
  const catchUp =
    spoolDepth > 0 ? (
      <span className="agent-telemetry__catchup" title={CATCH_UP_LABEL} aria-label={CATCH_UP_LABEL}>
        Catching up · {spoolDepth} samples buffered
        {telemetry.spool?.bytes != null && ` (${formatBytes(telemetry.spool.bytes)})`}
      </span>
    ) : null;

  // `disabled` stays excluded: a switched-off collector is a choice, not a fault.
  const faults = (telemetry?.readiness ?? []).filter(
    (item) => item.state === 'degraded' || item.state === 'unavailable'
  );

  if (!telemetry?.latest) {
    return (
      <Panel title="System metrics">
        <EmptyState icon="◴" message="No host samples received yet." />
        {catchUp}
        {faults.map((item) => (
          <Banner
            key={item.collector}
            tone={item.state === 'unavailable' ? 'danger' : 'warn'}
            title={`${item.collector}: ${item.state}`}
            body={item.remediation ? `${item.reason} — ${item.remediation}` : item.reason}
          />
        ))}
      </Panel>
    );
  }

  const age = Date.now() - new Date(telemetry.latest.collected_at).getTime();
  // `interval` is undefined until GET /agents/capability-defaults resolves, so
  // the window falls back to the 90s floor and the cadence segment is omitted
  // rather than rendering a bare "Cadence s".
  const stale = age > Math.max((interval ?? 0) * STALE_MULTIPLIER, STALE_FLOOR_MS);
  const docker = telemetry.latest.payload?.docker;

  return (
    <>
      {faults.map((item) => (
        <Banner
          key={item.collector}
          tone={item.state === 'unavailable' ? 'danger' : 'warn'}
          title={`${item.collector}: ${item.state}`}
          body={item.remediation ? `${item.reason} — ${item.remediation}` : item.reason}
        />
      ))}

      <div className="cb-tiles">
        {Object.entries(SUMMARY_LABELS).map(([key, label]) => (
          <StatTile
            key={key}
            label={label}
            value={
              telemetry.latest.summary?.[key] == null
                ? null
                : formatMetric(key, telemetry.latest.summary[key])
            }
            points={seriesFor(history, key)}
          />
        ))}
      </div>

      <p className="agent-telemetry__status">
        {stale ? 'Stale' : 'Live'} · Last sample{' '}
        {new Date(telemetry.latest.collected_at).toLocaleString()} ·{' '}
        {interval != null && <>Cadence {interval}s · </>}
        {telemetry.latest.projected ? 'Projected to linked hardware' : 'Agent only'}
        {catchUp && (
          <>
            {' · '}
            {catchUp}
          </>
        )}
      </p>

      <Panel
        title="History"
        actions={
          <label>
            History range{' '}
            <select value={historyRange} onChange={(event) => onHistoryRange(event.target.value)}>
              {RANGES.map((range) => (
                <option key={range}>{range}</option>
              ))}
            </select>
          </label>
        }
      >
        <div className="agent-telemetry__charts">
          <HistoryChart label="CPU" metric="cpu_pct" points={history} />
          <HistoryChart label="Memory" metric="mem_pct" points={history} />
          <HistoryChart label="Disk" metric="root_disk_pct" points={history} />
          <HistoryChart label="Network receive" metric="net_rx_bps" points={history} />
          <HistoryChart label="Temperature" metric="max_temp_c" points={history} />
        </div>
      </Panel>

      <DeviceTable title="Filesystems" rows={telemetry.latest.payload?.filesystems} />
      <DeviceTable title="Disks" rows={telemetry.latest.payload?.disks} />
      <DeviceTable title="Interfaces" rows={telemetry.latest.payload?.interfaces} />
      <DeviceTable title="Temperatures" rows={telemetry.latest.payload?.temperatures} />

      {/* Docker is absent in the normal case — include_docker defaults to
          false — so the whole block disappears rather than rendering an empty
          table. `docker` is a dict, never a row array, so only `.containers`
          may reach DeviceTable. */}
      {docker && (
        <Panel title="Docker" summary={`${docker.running} of ${docker.total} running`}>
          <p>
            {docker.running} of {docker.total} containers running
          </p>
          {docker.truncated && (
            <Banner
              tone="warn"
              title="Container list truncated"
              body="This host reports more than 100 containers; only the first 100 are collected and the sample is marked degraded."
            />
          )}
          <DeviceTable title="Containers" rows={docker.containers} />
        </Panel>
      )}

      {!hasHardware && (
        <EmptyState message="Link this agent to Hardware to add topology, analytics, and Hardware telemetry views." />
      )}
    </>
  );
}

AgentTelemetryTab.propTypes = {
  telemetry: PropTypes.object,
  history: PropTypes.array.isRequired,
  historyRange: PropTypes.string.isRequired,
  onHistoryRange: PropTypes.func.isRequired,
  hostDefaults: PropTypes.object.isRequired,
  hasHardware: PropTypes.bool,
};
```

- [ ] **Step 4: Delete the moved code from the page**

In `apps/frontend/src/pages/AgentDetailPage.jsx`, delete lines 58–157 (`SUMMARY_LABELS` through `HistoryChart`) and the temporary `AgentTelemetryTab` stub, then import:

```jsx
import AgentTelemetryTab, { formatMetric } from '../components/agents/AgentTelemetryTab';
```

`formatMetric` is still used by `stripMetrics` in the page, which is why it is re-exported rather than left private.

- [ ] **Step 5: Run the tests**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-telemetry-tab.test.jsx src/__tests__/agent-tabs.test.jsx src/__tests__/agent-detail-page.test.jsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/agents/AgentTelemetryTab.jsx \
        apps/frontend/src/pages/AgentDetailPage.jsx \
        apps/frontend/src/__tests__/agent-telemetry-tab.test.jsx
git commit -m "feat(agents): move telemetry into its own tab

SUMMARY_LABELS, formatMetric, formatBytes, DeviceTable and HistoryChart move
out of the page unchanged. Two behaviours are pinned by tests during the
move: the spool catch-up indicator renders outside the 'latest' branch, since
an agent that buffered samples and delivered none is exactly when the backlog
explains the blank page; and only payload.docker.containers reaches
DeviceTable, because the dict itself would make the derived header nonsense.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 17: AgentOverviewTab

**Files:**
- Create: `apps/frontend/src/components/agents/AgentOverviewTab.jsx`
- Modify: `apps/frontend/src/pages/AgentDetailPage.jsx` (delete the temporary stub; import the real one)
- Test: `apps/frontend/src/__tests__/agent-overview-tab.test.jsx`

**Interfaces:**
- Consumes: `Panel`, `PanelGrid`, `KeyValue`, `EmptyState`, `StatTile`; `AgentCapabilitiesPanel`, `AgentHardwarePanel`, `AgentEventsPanel` (Task 15).
- Produces: `<AgentOverviewTab panels={string[]} agent={} presence={} events={} probes={} discovery={} capabilitiesLocked={bool} blockedReason={} stripMetrics={} onToggleCapability={fn} onSelectTab={fn} />`

**Rules.** Overview renders **only** the panels named in `panels`, **in that order** — that array is `composeAgentPage`'s decision (Task 10) and this component does not second-guess it. Overview **never contains a table**: each panel shows a condensed reading and a control that opens the owning tab.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-overview-tab.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentOverviewTab from '../components/agents/AgentOverviewTab';

const ALL = ['capabilities', 'discovery', 'probes', 'hardware', 'events'];

const AGENT = { id: 7, status: 'active', capabilities: {} };

function renderOverview(props = {}) {
  return render(
    <AgentOverviewTab
      panels={ALL}
      agent={AGENT}
      presence={{ hardware: null }}
      events={[]}
      probes={[]}
      discovery={{ scope_version: 'b030b0aa1cde5b3e', config: { mode: 'direct_private' }, subnets: [] }}
      capabilitiesLocked={false}
      blockedReason={null}
      stripMetrics={[]}
      onToggleCapability={() => {}}
      onSelectTab={() => {}}
      {...props}
    />
  );
}

describe('AgentOverviewTab', () => {
  it('renders exactly the panels the composition named', () => {
    renderOverview({ panels: ['capabilities', 'events'] });
    expect(screen.getByRole('region', { name: 'Capabilities' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Events' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Linked hardware' })).toBeNull();
  });

  it('renders them in the order the composition gave', () => {
    const { container } = renderOverview({ panels: ['events', 'capabilities'] });
    const titles = [...container.querySelectorAll('.cb-panel__title')].map((el) => el.textContent);
    expect(titles).toEqual(['Events', 'Capabilities']);
  });

  it('contains no table — depth belongs to the owning tab', () => {
    const { container } = renderOverview();
    expect(container.querySelector('table')).toBeNull();
  });

  it('opens the owning tab from a panel', async () => {
    const onSelectTab = vi.fn();
    renderOverview({ onSelectTab });
    await userEvent.click(screen.getByRole('button', { name: 'Open Discovery' }));
    expect(onSelectTab).toHaveBeenCalledWith('discovery');
  });

  it('summarises probes rather than listing them', () => {
    renderOverview({ probes: [{ id: 1, name: 'a' }, { id: 2, name: 'b' }] });
    expect(screen.getByRole('region', { name: 'Probes' }).textContent).toContain('2 assigned');
  });

  it('says probes are still loading rather than claiming none exist', () => {
    // `null` means the request has not resolved. Rendering "0 assigned" there
    // is a claim the server has not made — and it is exactly the claim that
    // decides whether disabling the capability needs a confirmation.
    renderOverview({ probes: null });
    expect(screen.getByRole('region', { name: 'Probes' }).textContent).toContain('Loading');
  });

  it('says discovery is still loading rather than rendering an empty scope', () => {
    renderOverview({ discovery: null });
    expect(screen.getByRole('region', { name: 'Discovery' }).textContent).toContain('Loading');
  });

  it('passes the lock and its reason through to the capabilities panel', () => {
    renderOverview({ capabilitiesLocked: true, blockedReason: 'approval' });
    expect(screen.getByRole('switch', { name: 'Host telemetry — locked until approved' })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-overview-tab.test.jsx
```

Expected: FAIL — `Failed to resolve import "../components/agents/AgentOverviewTab"`.

- [ ] **Step 3: Write the component**

Create `apps/frontend/src/components/agents/AgentOverviewTab.jsx`:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import PanelGrid from '../common/PanelGrid';
import KeyValue from '../common/KeyValue';
import EmptyState from '../common/EmptyState';
import AgentCapabilitiesPanel from './AgentCapabilitiesPanel';
import AgentHardwarePanel from './AgentHardwarePanel';
import AgentEventsPanel from './AgentEventsPanel';

/**
 * The landing tab.
 *
 * Two rules. It renders only the panels composeAgentPage named, in that order
 * — which panels matter is a lifecycle decision and belongs in one place, not
 * re-litigated in JSX. And it contains no table: overview is a reading, and
 * every panel offers a control that opens the tab owning the detail.
 */
export default function AgentOverviewTab({
  panels,
  agent,
  presence,
  events,
  probes,
  discovery,
  capabilitiesLocked,
  blockedReason,
  onToggleCapability,
  onSelectTab,
}) {
  const openButton = (tab, label) => (
    <button type="button" onClick={() => onSelectTab(tab)}>
      Open {label}
    </button>
  );

  const render = {
    capabilities: () => (
      <AgentCapabilitiesPanel
        key="capabilities"
        capabilities={agent.capabilities}
        locked={capabilitiesLocked}
        blockedReason={blockedReason}
        onToggle={onToggleCapability}
      />
    ),
    discovery: () => (
      <Panel key="discovery" title="Discovery" actions={openButton('discovery', 'Discovery')}>
        {/* null means the request has not resolved. Rendering an empty scope
            there would read as "this agent discovers nothing", which is the
            one thing this panel exists to distinguish. */}
        {discovery === null ? (
          <EmptyState message="Loading discovery scope…" />
        ) : (
          <KeyValue
            rows={[
              ['Scope mode', discovery.config?.mode],
              ['Subnets', discovery.subnets?.length ?? 0],
              ['Scope version', discovery.scope_version],
            ]}
          />
        )}
      </Panel>
    ),
    probes: () => (
      <Panel
        key="probes"
        title="Probes"
        summary={probes === null ? 'Loading…' : `${probes.length} assigned`}
        actions={openButton('probes', 'Probes')}
      >
        {probes === null ? (
          <EmptyState message="Loading assigned probes…" />
        ) : probes.length === 0 ? (
          <EmptyState icon="◎" message="No monitors run from this agent" hint="Assign one with “Run from” on a monitor’s form." />
        ) : (
          <KeyValue rows={[['Assigned', probes.length]]} />
        )}
      </Panel>
    ),
    hardware: () => <AgentHardwarePanel key="hardware" hardware={presence?.hardware ?? null} />,
    events: () => <AgentEventsPanel key="events" events={events} />,
  };

  return <PanelGrid>{panels.map((name) => render[name]?.() ?? null)}</PanelGrid>;
}

AgentOverviewTab.propTypes = {
  panels: PropTypes.arrayOf(PropTypes.string).isRequired,
  agent: PropTypes.object.isRequired,
  presence: PropTypes.object,
  events: PropTypes.array.isRequired,
  probes: PropTypes.array,
  discovery: PropTypes.object,
  capabilitiesLocked: PropTypes.bool,
  blockedReason: PropTypes.oneOf(['approval', 'revocation', null]),
  onToggleCapability: PropTypes.func.isRequired,
  onSelectTab: PropTypes.func.isRequired,
};
```

- [ ] **Step 4: Wire it into the page**

In `apps/frontend/src/pages/AgentDetailPage.jsx`, delete the temporary `AgentOverviewTab` stub and add:

```jsx
import AgentOverviewTab from '../components/agents/AgentOverviewTab';
```

- [ ] **Step 5: Run the tests and lint**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-overview-tab.test.jsx src/__tests__/agent-tabs.test.jsx && npm run lint
```

Expected: PASS — 8 + 9 tests; no lint errors.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/agents/AgentOverviewTab.jsx \
        apps/frontend/src/pages/AgentDetailPage.jsx \
        apps/frontend/src/__tests__/agent-overview-tab.test.jsx
git commit -m "feat(agents): add the overview tab

It renders only the panels composeAgentPage named, in that order — which
panels matter is a lifecycle decision and belongs in one module rather than
being re-litigated in JSX.

A null probes or discovery response renders 'Loading', not '0 assigned' or an
empty scope. Both are claims the server has not made, and 'this agent
discovers nothing' is the exact thing the discovery panel exists to
distinguish.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: Re-skin the probes and discovery sections

**Files:**
- Modify: `apps/frontend/src/components/agents/AssignedProbesSection.jsx`
- Modify: `apps/frontend/src/components/agents/DiscoveryScopeSection.jsx`
- Test (update): `apps/frontend/src/__tests__/agent-assigned-probes.test.jsx`, `apps/frontend/src/__tests__/agent-discovery-scope.test.jsx`

**Interfaces:**
- Consumes: `Panel`, `Banner`, `EmptyState`, `KeyValue`.
- Produces: **no signature changes.** Both components keep the exact props `AgentDetailPage` already passes.

**This task changes presentation only.** Every mutation, every confirmation, every fetch and every string stays as it is. Spec §11 puts rewording out of scope, and `DiscoveryScopeSection` is 779 lines of behaviour this redesign has no business touching.

The mechanical substitutions:

| Current | Becomes |
|---|---|
| `<section aria-label="Assigned probes"><h2>Assigned probes</h2>` (`AssignedProbesSection.jsx:139-140`) | `<Panel title="Assigned probes" summary={…}>` |
| `<section aria-label="Discovery scope"><h2>Discovery scope</h2>` (`DiscoveryScopeSection.jsx:395-396`) | `<Panel title="Discovery scope" summary={…}>` |
| Each `<h3>{group.title}</h3>` + `<table>` (`DiscoveryScopeSection.jsx:435`, `582`, `595`, `629`, `674`) | `<Panel title={group.title} bodyless>` wrapping the table |
| The "Remote probing is disabled for this agent…" paragraph | `<Banner tone="warn" title="Remote probing is disabled" body={…} />` — **the existing sentence becomes the `body`, unchanged** |
| The "Local discovery is disabled for this agent…" paragraph | Same treatment |
| The scope-mode `<dl>` | `<KeyValue rows={…} />` |
| "No monitors run from this agent." / "No discovery subnets are assigned to this agent yet." / "This agent has not reported any discovered devices yet." | `<EmptyState message={…} />` — **same strings** |

- [ ] **Step 1: Add the assertions that must survive**

Add to `apps/frontend/src/__tests__/agent-assigned-probes.test.jsx`:

```jsx
it('keeps the disabled-probing wording exactly as written', () => {
  renderSection({ granted: false });
  expect(
    screen.getByText(
      'Remote probing is disabled for this agent. Assigned monitors keep their last known target state and stay probe-unavailable until it is re-enabled.'
    )
  ).toBeTruthy();
});

it('is reachable as a region by its heading', () => {
  renderSection({ granted: true });
  expect(screen.getByRole('region', { name: 'Assigned probes' })).toBeTruthy();
});
```

Add to `apps/frontend/src/__tests__/agent-discovery-scope.test.jsx`:

```jsx
it('keeps the disabled-discovery wording exactly as written', () => {
  renderSection({ granted: false });
  expect(
    screen.getByText(
      'Local discovery is disabled for this agent. Its subnets stay configured and its results and job history are retained; nothing is scanned from here until it is re-enabled.'
    )
  ).toBeTruthy();
});

it('is reachable as a region by its heading', () => {
  renderSection({ granted: true });
  expect(screen.getByRole('region', { name: 'Discovery scope' })).toBeTruthy();
});
```

**Before editing either component**, run the two suites and copy the disabled-state strings out of the *current* source so the assertions above match byte for byte:

```bash
cd apps/frontend && grep -n "is disabled for this agent" src/components/agents/AssignedProbesSection.jsx src/components/agents/DiscoveryScopeSection.jsx
```

- [ ] **Step 2: Run the suites to verify the new assertions fail**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-assigned-probes.test.jsx src/__tests__/agent-discovery-scope.test.jsx
```

Expected: FAIL on the two `region` assertions (a bare `<section>` has no accessible region role without a name resolved from `aria-label`, and the `<h2>` is not that name once `Panel` owns it). The wording assertions should PASS immediately — if either fails, the string in the test is wrong, not the component.

- [ ] **Step 3: Apply the substitutions**

Work through the table above in both files. Do not touch any handler, any `useEffect`, any request, or any string.

- [ ] **Step 4: Run both suites**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-assigned-probes.test.jsx src/__tests__/agent-discovery-scope.test.jsx
```

Expected: PASS — the pre-existing tests plus 4 new ones. **If a pre-existing assertion fails, the re-skin changed behaviour it should not have.** Fix the component, not the test.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/agents/AssignedProbesSection.jsx \
        apps/frontend/src/components/agents/DiscoveryScopeSection.jsx \
        apps/frontend/src/__tests__/agent-assigned-probes.test.jsx \
        apps/frontend/src/__tests__/agent-discovery-scope.test.jsx
git commit -m "feat(agents): put probes and discovery in panels

Presentation only. Every mutation, confirmation, fetch and string is
untouched — DiscoveryScopeSection is 779 lines of behaviour this redesign has
no business rewriting.

New assertions pin the two 'is disabled for this agent' sentences byte for
byte, so a later tidy-up of that wording fails rather than drifting.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 19: Off-tab activity indicators

**Files:**
- Create: `apps/frontend/src/lib/agentThresholds.js`
- Create: `apps/frontend/src/hooks/useTabActivity.js`
- Modify: `apps/frontend/src/pages/AgentDetailPage.jsx` (feed `indicator` into `tabs`; mark hot strip metrics)
- Test: `apps/frontend/src/__tests__/agent-reactivity.test.jsx`

**Interfaces:**
- Produces:
  - `METRIC_THRESHOLDS = { cpu_pct: 90, mem_pct: 90, root_disk_pct: 90, max_temp_c: 80 }`
  - `hotMetrics(summary)` → `string[]` of keys at or over threshold, in `METRIC_THRESHOLDS` key order.
  - `useTabActivity({ activeTab, signals })` → `{ [tabKey]: true | number | null }`

**How a signal works.** `signals` is `{ [tabKey]: value }`. A non-numeric value that *changes* while its tab is inactive raises `true`. A numeric value that *grows* raises the delta since the tab was last seen. Selecting a tab clears its indicator and rebaselines it.

**Why telemetry's signal is the hot set, not the sample time:** a signal that changes on every sample would leave the dot permanently lit, which is the same as no dot. `hotMetrics(...).join(',')` changes only when something crosses a threshold — which is what spec §5.3 means by a spike, and it is the same rule §5.5 uses for the tile flash.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/agent-reactivity.test.jsx`:

```jsx
import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useTabActivity } from '../hooks/useTabActivity';
import { METRIC_THRESHOLDS, hotMetrics } from '../lib/agentThresholds';

describe('hotMetrics', () => {
  it('names nothing while every metric is under its threshold', () => {
    expect(hotMetrics({ cpu_pct: 12, mem_pct: 38, root_disk_pct: 61, max_temp_c: 44 })).toEqual([]);
  });

  it('names a metric at or over its threshold', () => {
    expect(hotMetrics({ cpu_pct: METRIC_THRESHOLDS.cpu_pct, mem_pct: 10 })).toEqual(['cpu_pct']);
  });

  it('names several, in a stable order', () => {
    expect(hotMetrics({ cpu_pct: 95, mem_pct: 5, root_disk_pct: 99, max_temp_c: 90 })).toEqual([
      'cpu_pct',
      'root_disk_pct',
      'max_temp_c',
    ]);
  });

  it('ignores metrics the sample did not carry', () => {
    expect(hotMetrics({ cpu_pct: null, mem_pct: undefined })).toEqual([]);
  });

  it('ignores a summary that has not arrived', () => {
    expect(hotMetrics(null)).toEqual([]);
  });
});

describe('useTabActivity', () => {
  const mount = (initial) =>
    renderHook(({ activeTab, signals }) => useTabActivity({ activeTab, signals }), {
      initialProps: initial,
    });

  it('raises nothing on first render', () => {
    // Everything is new on mount. Lighting every tab would say nothing.
    const { result } = mount({ activeTab: 'overview', signals: { telemetry: '', events: 3 } });
    expect(result.current.telemetry).toBeNull();
    expect(result.current.events).toBeNull();
  });

  it('raises a flag when a signal changes on an inactive tab', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { telemetry: '' } });
    rerender({ activeTab: 'overview', signals: { telemetry: 'cpu_pct' } });
    expect(result.current.telemetry).toBe(true);
  });

  it('raises nothing when the change is on the tab being watched', () => {
    const { result, rerender } = mount({ activeTab: 'telemetry', signals: { telemetry: '' } });
    rerender({ activeTab: 'telemetry', signals: { telemetry: 'cpu_pct' } });
    expect(result.current.telemetry).toBeNull();
  });

  it('counts how many arrived for a numeric signal', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: 3 } });
    rerender({ activeTab: 'overview', signals: { events: 6 } });
    expect(result.current.events).toBe(3);
  });

  it('does not count a numeric signal going down', () => {
    // A shrinking list is a reload, not new activity.
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: 6 } });
    rerender({ activeTab: 'overview', signals: { events: 2 } });
    expect(result.current.events).toBeNull();
  });

  it('clears and rebaselines when its tab is selected', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: 3 } });
    rerender({ activeTab: 'overview', signals: { events: 6 } });
    expect(result.current.events).toBe(3);

    rerender({ activeTab: 'events', signals: { events: 6 } });
    expect(result.current.events).toBeNull();

    // Rebaselined: the next arrival counts from 6, not from 3.
    rerender({ activeTab: 'overview', signals: { events: 7 } });
    expect(result.current.events).toBe(1);
  });

  it('tracks each tab independently', () => {
    const { result, rerender } = mount({
      activeTab: 'overview',
      signals: { telemetry: '', discovery: 'job-1' },
    });
    rerender({ activeTab: 'overview', signals: { telemetry: 'cpu_pct', discovery: 'job-1' } });
    expect(result.current.telemetry).toBe(true);
    expect(result.current.discovery).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-reactivity.test.jsx
```

Expected: FAIL — `Failed to resolve import "../hooks/useTabActivity"`.

- [ ] **Step 3: Write the thresholds module**

Create `apps/frontend/src/lib/agentThresholds.js`:

```js
/**
 * When a host metric stops being background and becomes news.
 *
 * These values drive two things and must stay one list: which tiles flash
 * (spec §5.5) and which tabs raise an indicator (spec §5.3). A metric that
 * flashed without raising an indicator would be invisible from another tab,
 * which is the failure the indicators exist to prevent.
 */
export const METRIC_THRESHOLDS = {
  cpu_pct: 90,
  mem_pct: 90,
  root_disk_pct: 90,
  max_temp_c: 80,
};

/**
 * @param {object|null} summary A sample's `summary` block.
 * @returns {string[]} Keys at or over threshold, in METRIC_THRESHOLDS order.
 */
export function hotMetrics(summary) {
  if (!summary) return [];
  return Object.keys(METRIC_THRESHOLDS).filter((key) => {
    const value = summary[key];
    return typeof value === 'number' && value >= METRIC_THRESHOLDS[key];
  });
}
```

- [ ] **Step 4: Write the hook**

Create `apps/frontend/src/hooks/useTabActivity.js`:

```js
/**
 * Spec §5.3 — what makes a tabbed console safe.
 *
 * Tabs hide content by design. Without this, a CPU spike or a finished
 * discovery job on a tab the operator is not looking at is simply invisible
 * until they happen to click over, which is the one genuine cost of the shape.
 *
 * A signal is a value per tab. Non-numeric values raise a flag when they
 * change; numeric values raise the delta when they grow. Selecting a tab
 * clears its indicator and rebaselines it, so the next arrival counts from
 * what the operator actually saw.
 */

import { useEffect, useRef, useState } from 'react';

export function useTabActivity({ activeTab, signals }) {
  // Baselines, not state: they change together with the indicators and a
  // render between the two would flash a stale count.
  const baseline = useRef(null);
  const [indicators, setIndicators] = useState({});

  useEffect(() => {
    // Everything is new on the first render. Lighting every tab at once says
    // nothing, so the first pass only records where we started.
    if (baseline.current === null) {
      baseline.current = { ...signals };
      return;
    }

    const next = {};
    Object.keys(signals).forEach((tab) => {
      const current = signals[tab];
      const previous = baseline.current[tab];

      if (tab === activeTab) {
        baseline.current[tab] = current;
        next[tab] = null;
        return;
      }

      if (typeof current === 'number' && typeof previous === 'number') {
        // A shrinking list is a reload, not new activity.
        next[tab] = current > previous ? current - previous : null;
        return;
      }

      next[tab] = current !== previous ? true : null;
    });

    setIndicators(next);
  }, [activeTab, signals]);

  return indicators;
}
```

- [ ] **Step 5: Feed the indicators into the page**

In `apps/frontend/src/pages/AgentDetailPage.jsx`:

```jsx
import { useTabActivity } from '../hooks/useTabActivity';
import { hotMetrics } from '../lib/agentThresholds';
```

```jsx
  const hot = useMemo(() => hotMetrics(telemetry?.latest?.summary), [telemetry]);

  // A signal that changed on every sample would leave the dot permanently lit,
  // which is the same as having no dot. Only a threshold crossing is news.
  const signals = useMemo(
    () => ({
      telemetry: hot.join(','),
      discovery: discovery?.active_job?.id ?? '',
      events: events.length,
    }),
    [hot, discovery, events.length]
  );

  const indicators = useTabActivity({ activeTab, signals });

  const tabs = useMemo(
    () => page.tabs.map((key) => ({ key, label: TAB_LABELS[key], indicator: indicators[key] ?? null })),
    [page.tabs, indicators]
  );
```

And mark the hot metrics on the strip, replacing the `stripMetrics` memo from Task 14:

```jsx
  const stripMetrics = useMemo(
    () =>
      STRIP_METRICS.map(({ key, label }) => ({
        key,
        label,
        value:
          telemetry?.latest?.summary?.[key] == null
            ? null
            : formatMetric(key, telemetry.latest.summary[key]),
        points: history.map((point) => point[key]).filter((value) => typeof value === 'number'),
        hot: hot.includes(key),
      })),
    [telemetry, history, hot]
  );
```

- [ ] **Step 6: Run the tests**

```bash
cd apps/frontend && npx vitest run src/__tests__/agent-reactivity.test.jsx src/__tests__/agent-tabs.test.jsx
```

Expected: PASS — 13 + 9 tests.

- [ ] **Step 7: Verify by eye against the running app**

jsdom performs no layout and does not run animations, so this step is not optional.

```bash
make dev
```

Open an agent with telemetry, switch to the **Discovery** tab, and confirm: the header sparklines keep moving; a metric crossing its threshold turns the strip value red and raises a dot on **Telemetry**; clicking Telemetry clears the dot.

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/src/lib/agentThresholds.js \
        apps/frontend/src/hooks/useTabActivity.js \
        apps/frontend/src/pages/AgentDetailPage.jsx \
        apps/frontend/src/__tests__/agent-reactivity.test.jsx
git commit -m "feat(agents): surface activity from tabs you are not on

Tabs hide content by design, so a spike on an inactive tab was invisible
until the operator happened to click over. This is the one real cost of the
shape and the thing that makes it safe.

Telemetry's signal is the set of metrics over threshold, not the sample time:
a signal changing on every sample leaves the dot permanently lit, which is
the same as no dot. That is the same rule the tile flash uses, from the same
list.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 20: Align the list page

**Files:**
- Modify: `apps/frontend/src/pages/AgentsPage.jsx`
- Modify: `apps/frontend/src/components/agents/FleetRow.jsx` (empty metric cells)
- Test (update): `apps/frontend/src/__tests__/agents-page.test.jsx`

**Interfaces:**
- Consumes: `Panel` (Task 1), `StatTile`'s absent-value convention (Task 4).
- Produces: no new exports.

**Scope.** Chrome only. The table keeps its 34px density, its `.fleet-*` vocabulary, its sort headers and its chips — spec §8 is explicit that the table is the strongest part of the feature.

| Change | Where |
|---|---|
| Server-key card → `<Panel title="Agent server key" summary={rotationStatus}>` | `AgentsPage.jsx`, around `ServerKeyRotationPanel` |
| Add-agent card → `<Panel title="Add agent">` | `AgentsPage.jsx`, around `AddAgentPanel` |
| Filter bar → `<Panel title="Filters" bodyless>` | `AgentsPage.jsx`, around the filter row |
| Empty metric cells render `—` | `FleetRow.jsx`, `MetricCell` |

- [ ] **Step 1: Write the failing test**

Add to `apps/frontend/src/__tests__/agents-page.test.jsx`:

```jsx
it('renders an em dash for a metric the agent has never reported', async () => {
  // A blank cell is indistinguishable from a rendering failure. This is the
  // same convention StatTile uses on the detail page.
  await renderPage({ agents: [{ ...PENDING_AGENT, latest: null }] });
  const row = screen.getByRole('row', { name: new RegExp(PENDING_AGENT.hostname) });
  expect(within(row).getAllByText('—').length).toBeGreaterThan(0);
});

it('frames the server key and add-agent cards as regions', async () => {
  await renderPage({ agents: [] });
  expect(screen.getByRole('region', { name: 'Agent server key' })).toBeTruthy();
  expect(screen.getByRole('region', { name: 'Add agent' })).toBeTruthy();
});
```

- [ ] **Step 2: Run the suite to verify the new assertions fail**

```bash
cd apps/frontend && npx vitest run src/__tests__/agents-page.test.jsx
```

Expected: FAIL — no region named "Agent server key".

- [ ] **Step 3: Apply the changes**

Wrap the three chrome blocks in `Panel` per the table above, and in `FleetRow.jsx`'s `MetricCell` render `—` where the value is `null` or `undefined`. Do not change the row height, the sort headers, `.fleet-chip`, or `PENDING_DETAIL_SPAN`.

- [ ] **Step 4: Run the suite**

```bash
cd apps/frontend && npx vitest run src/__tests__/agents-page.test.jsx src/__tests__/fleet-pending-row.test.jsx src/__tests__/fleet-summary-counts.test.jsx
```

Expected: PASS.

- [ ] **Step 5: Run the full gate**

```bash
make lint
make verify
```

Expected: PASS. **Do not lower the coverage gate.** If coverage dropped, the new components need tests, not a lower threshold.

- [ ] **Step 6: Verify both pages by eye**

```bash
make dev
```

Check the list page at a narrow width, the detail page for a pending agent (should be one decision, not eight empty sections), and the detail page for an online agent on every tab.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/pages/AgentsPage.jsx \
        apps/frontend/src/components/agents/FleetRow.jsx \
        apps/frontend/src/__tests__/agents-page.test.jsx
git commit -m "feat(agents): align the list page chrome with the primitives

The server-key, add-agent and filter blocks become Panels, and empty metric
cells render an em dash — the same convention StatTile uses on the detail
page, so a never-reported value reads the same on both.

The table itself is unchanged: 34px rows, the .fleet-* vocabulary, the sort
headers and the chips are the strongest part of this feature.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task:

| Spec | Task |
|---|---|
| §1.1–1.2 no design layer, no scale | 1–6 |
| §1.3 renders every state at once | 10, 14, 17 |
| §1.4 two list defects | 7, 8 |
| §3.1 `?tab=` routing | 14 |
| §3.2 decomposition | 14–17 |
| §4 the ten primitives | 1–6 |
| §5.1 header live strip | 13, 14 |
| §5.2 motion means data | 9, 13 |
| §5.3 off-tab spikes | 19 |
| §5.4 subscription policy | 11 |
| §5.5 flash policy | 4 (`data-flash`), 19 (`hotMetrics`) |
| §6 lifecycle composition | 10, 14, 15, 17 |
| §7 per-tab composition | 15–18 |
| §8 list page | 7, 8, 20 |
| §9 accessibility | 5 (tablist), 13 (`aria-hidden` sparklines), 4 (`Toggle` name), 8 (`role="status"`) |
| §10 testing | every task; `make verify` in 20 |
| §12 files touched | File Structure above |
| §13 sequencing | Task Dependency Order above |

**Type consistency.** `tone` is `ok|warn|danger|info|default` in `Panel` and `ok|warn|danger|info` in `Banner` throughout; `blockedReason` is `'approval'|'revocation'|null` in Tasks 10, 15 and 17; `StatTile.value` and `AgentLiveStrip.metrics[].value` are both pre-formatted strings or null; `panelPropsFor` is defined in Task 5 and consumed in Task 14 with the same shape.

**One known ordering constraint.** Task 14 introduces three temporary stubs and Tasks 15–17 delete them one at a time. Running 15–17 out of order leaves a stub in place — harmless, but the page renders a placeholder until its task lands. Run them in order.

---

## Execution Handoff

Two ways to run this:

**1. Subagent-driven (recommended)** — a fresh subagent per task, with review
between tasks. Each task in this plan is sized for that: one deliverable, its
own test cycle, its own commit. Tasks 1–6 and 7–8 have no dependencies on each
other and can be dispatched in parallel; 9–20 are ordered.

**2. Inline execution** — work through the tasks in one session with
checkpoints for review.

**Where this file lives.** The writing-plans skill defaults to
`docs/superpowers/plans/`, which is gitignored in this repo (`.gitignore:142`).
This plan sits beside its spec in `specs/`, which is tracked and already holds
fourteen designs under the same `YYYY-MM-DD-<topic>` convention.
