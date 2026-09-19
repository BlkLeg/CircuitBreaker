# Circuit Breaker — seven operational workflows

## User direction

The seven UI workflows and the global navigator are approved. The audience is self-hosters interested in homelab infrastructure, with a professional, polished SOC dashboard direction, high reactivity, clear messaging, and a modern appearance. Canvas examples use synthetic data. Implementation is planned in [the approved UI plan set](../docs/design/approved-ui/README.md); this approval does not claim the backend has been integrated.

The subsequent user decision is authoritative: the navigator replaces both the top-right Routes dropdown and command palette, preserving the dock. All examples must become theme-aware production surfaces; the Gruvbox values below describe only the reference appearance.

## Shared direction

Extend the existing Agent Operations SOC draft and the established Circuit Breaker identity. The telemetry-specific scope in design-system.md describes the source draft; these seven sibling workflows have their own content below. Keep its visual foundations, not agent-specific headings or tabs. Preserve the real logo, global header, and bottom route dock. Use feature-local tabs or a narrow section rail where useful; do not invent an unrelated global sidebar.

In the Gruvbox reference, use charcoal surfaces, fine borders, amber primary actions, muted teal information, olive success, and reserved red/amber warnings. In production, every color comes from the active theme's semantic tokens, including charts, graphs, status states, and overlays; do not freeze these reference colors in feature CSS. Follow the app's font settings and shared system/monospace tokens. Use compact but readable 13px body copy and 11–12px secondary labels; do not inherit the source draft's excessively small 8–9px text. Use 6px radii, 12–24px spacing, disciplined alignment, tabular numbers, low-elevation panels, and restrained iconography. No decorative scan lines, giant KPI cards, excessive glow, meaningless pulse loops, or marketing hero areas.

Desktop-first workspace, comfortable at 1440px and at the source draft viewport. Content must fit rather than relying on fixed widths or tiny text. Collapse detail rails below primary content on narrow screens and let dense tables scroll locally. Support visible keyboard focus, textual status labels, touch-friendly controls, and reduced motion.

Reactivity means immediate selection feedback, inline validation, clear progress, reversible drawers, and visible save outcomes. Use functioning local prototype state for the primary workflow. All examples are synthetic and should carry one quiet 'Design preview · sample data' indicator. Do not show backend implementation details to ordinary operators. Avoid dead primary buttons and claims that a real scan, import, or alert delivery happened. No live external requests or production mutations.

Reuse the exact supplied Brand Asset logo in every logo position:
https://vgbujcuwptvheqijyjbe.supabase.co/storage/v1/object/public/hmac-uploads/projects/8b984ff8-fa32-4386-98b6-0de7bd58135b/brand-assets/apps-frontend-public-CB-AZ_Final.png/CB-AZ_Final.png
Never replace it with initials, emoji, generic marks, invented SVGs, or text alone. The existing GlobalHeader component is available in this project. Do not use the agent-specific AgentDetailHeader on unrelated workflows.

## Seven canvas targets

1. Inventory transfer: Data Management overview plus file validation, collision resolution, preview, confirmation, and result states. Distinguish portable inventory export from full-state backup and offline restore. Include relationships in previews and preserve user input across steps.
2. Docker discovery: daemon/source and host association, scan outcome, last successful observation, container inventory, reconciliation preview, unresolved parent correction. A failed scan preserves inventory; a successful empty scan is explicitly different. Partial scans are not authoritative absence.
3. Vulnerability assessment: assessability and feed freshness, matching identity, findings table, applicability evidence, and remediation next actions. Empty or stale data cannot imply safety. Do not introduce unapproved triage or offline import features.
4. Notification delivery: destination configuration, severity routing, test feedback, retry and rejection states, and existing diagnostic context. No secret echo and no invented durable delivery-history feature. A successful test is an accepted test message, not a guarantee of future delivery.
5. Dependency impact: focused graph and affected asset list, relationship provenance, confirmed versus inferred impact, and ordinary connectivity shown separately. Do not claim every peer on a subnet fails or present unsupported SPOF scoring.
6. Inventory workspace: server-style pagination/search/filter semantics, current-page versus all-matching selection, side-panel inspection, global entity picker, and inline structured IP-conflict correction without losing form data.
7. Metric alert rules: compact rule list and builder for metric, target, unit, threshold, duration, recovery/hysteresis, stale-data behavior, severity, destination, and an evaluation preview. This proposed expansion reuses the notification pipeline. No acknowledgement/escalation/correlation/maintenance subsystem in this slice.

## Quality bar

Each canvas page should show a strong, realistic populated first view and allow its main interaction to reveal another useful state. Use coherent synthetic homelab assets across screens, such as pve-01, docker-01, nas-01, jellyfin, paperless, grafana, and prometheus. Clearly distinguish current observed state, stale state, proposed change, and simulated impact. Explain actions in plain language.

The approved implementation plans and subsequent user decisions take precedence over prototype details; the functional assessment supplies the original evidence. Favor completion of these exact workflows over extra features. Use the active theme and shared design-system tokens for fonts, colors, spacing, and component styles. Do not introduce feature-specific palettes or ship the prototype's sample controls.
