# 00 · Theme-aware shared foundations

Status: required for every approved design. Dependencies: none.

## Outcome

The approved layout and interaction language follows the active application theme immediately—including open dialogs, drawers, popovers, tooltips, charts, graph paths, selected rows, and error states. Gruvbox is one supported appearance, not embedded component styling.

## Existing integration points

- `apps/frontend/src/theme/applyTheme.js`, `presets.js`, `themepark.js`
- `apps/frontend/src/context/SettingsContext.jsx`
- `apps/frontend/src/styles/main.css`, `panels.css`
- `apps/frontend/src/components/common/`
- `apps/frontend/src/config/mapTheme.js` and the final map theme/render integration
- `apps/frontend/src/__tests__/UpdateThemeTokens.test.jsx`

The existing pipeline handles dark/light preset variants and custom colors. Theme.park presets deliberately mirror dark colors in their light entries; preserve that documented behavior rather than inventing a new palette. The current fixed raised-surface token and incomplete semantic status updates require attention.

## Token contract

| UI purpose | Required source |
| --- | --- |
| Page, panel, alternate/raised surfaces | Existing `--color-bg`, `--color-surface`, `--color-surface-alt`; make `--color-surface-raised` resolve from the active palette |
| Primary and muted text | `--color-text`, `--color-text-muted` |
| Borders, separators, grid | `--color-border`, `--color-grid-line` |
| Primary actions, selected controls, focus | `--color-primary`, `--color-primary-hover`; a centrally resolved contrasting foreground where needed |
| Status, warnings, errors, informational evidence | Existing success/warning/danger/info tokens and readable associated foreground/background combinations |
| Fonts, spacing, density, radii | Existing font/settings pipeline and shared spacing/type/radius variables |
| Chart/graph rendering that needs literal colors | A narrowly shared resolver of the same active tokens, invalidated on theme change |

Never treat `accent2` as automatically meaning success: decorative palette accents and operational severity are different concepts. Supply accessible semantic defaults centrally for each effective light/dark surface; allow explicit supported overrides without retaining values from the previous theme. Avoid page-specific hex values, hard-coded dark fallbacks, arbitrary opacity on already low-contrast text, and JS caches of the initial palette.

## Work packages

- [ ] **F1 — Audit and test resolution.** List required tokens used by the eight surfaces and shared primitives. Add tests for missing values and switching from a rich/custom palette to a sparse one. Include cold-load theme restoration and runtime theme changes.
- [ ] **F2 — Complete central resolution.** Extend the existing applyTheme/preset path only as necessary. Derive raised surfaces and status pairs centrally; reset optional properties deterministically. Add a contrasting primary-button foreground/focus token only if existing primitives cannot express it safely.
- [ ] **F3 — Preserve settings behavior.** Respect native presets, theme.park, custom colors, selected fonts/size, branding, and auto mode. If OS color-scheme changes are not subscribed to, add and clean up that listener in the existing settings/theme owner, not in every screen.
- [ ] **F4 — Reuse primitives.** Audit Panel, Banner, EmptyState, Tabs, ConfirmDialog, form fields, table controls, and toasts. Correct their token consumption once. Add only missing reusable behavior demonstrated by at least one planned workflow; keep feature state out of common components.
- [ ] **F5 — Non-DOM rendering.** For impact graphs and alert charts, prefer CSS variables/currentColor in SVG. Where a library needs concrete colors, update resolved colors on theme changes without resetting data, selections, graph position, or open forms. Coordinate only the needed map boundary.
- [ ] **F6 — Add browser coverage.** Apply the same theme checks to the navigator and each workflow while showing populated, empty, warning/error, selection, and overlay states.

## Verification and acceptance

- Test token completeness for every entry in THEME_PRESETS and its advertised modes, plus legacy/custom input.
- Browser-review every new surface in Gruvbox dark/light, a contrasting native preset such as Nord or Dracula, a theme.park preset, and a custom palette; include auto-mode changes while an overlay is open.
- Verify readable text (target 4.5:1 for normal text) and essential controls/focus boundaries (target 3:1), using computed foreground/background pairs rather than names. For inherently low-contrast custom combinations, provide consistent central correction or actionable validation; never promise arbitrary raw colors are accessible.
- Test text enlargement, forced-colors behavior, keyboard focus, and reduced motion. Status remains understandable from labels/icons/patterns when colors change.
- Scan new feature styles for literal palette colors and untracked fallback tokens. Central palette definitions, approved brand assets, and test fixtures are legitimate exceptions.
- Theme changes preserve unsaved edits, pinned navigation, selections, chart range, and current map context.
- Confirm existing agent/shared-panel surfaces do not regress when shared tokens change.

Done means the theme pipeline and consumers are verified. A component using `var(...)` with a permanently dark value is not theme-aware.
