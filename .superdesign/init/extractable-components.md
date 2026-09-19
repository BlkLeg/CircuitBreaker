# Extractable components

## Header
- Source: `apps/frontend/src/components/Header.jsx`
- Category: layout
- Description: global branded header with widgets, route navigation, user actions, theme control and search trigger.
- Extractable props: `onOpenPalette`
- Hardcoded: layout, icon choices, action labels, logo position, widget position, CSS variable usage.

## MacOSDOCK
- Source: `apps/frontend/src/components/MacOSDOCK.jsx`
- Category: layout
- Description: auto-hiding route dock with permission-aware items and status badges.
- Extractable props: `pendingCount`, `wsStatus`
- Hardcoded: icon placement, mobile subset, animation and route structure.

## DetailHeader
- Source: `apps/frontend/src/components/common/DetailHeader.jsx`
- Category: layout
- Description: detail-page identity, metadata, status chips, actions and always-visible metric strip.
- Extractable props: `backTo`, `backLabel`, `title`, `chips`, `meta`, `actions`, `strip`
- Hardcoded: structural CSS classes and hierarchy.

## Panel
- Source: `apps/frontend/src/components/common/Panel.jsx`
- Category: basic
- Description: titled bordered surface with tone, summary and action slots.
- Extractable props: `title`, `summary`, `tone`, `bodyless`
- Hardcoded: header/body hierarchy and CSS classes.

## StatTile
- Source: `apps/frontend/src/components/common/StatTile.jsx`
- Category: basic
- Description: live numerical metric with sparkline and hot/flash states.
- Extractable props: `label`, `value`, `points`, `hot`, `flash`
- Hardcoded: sparkline geometry and zero-baseline normalization.

## Tabs
- Source: `apps/frontend/src/components/common/Tabs.jsx`
- Category: basic
- Description: keyboard-accessible tablist with activity indicators.
- Extractable props: `tabs`, `active`
- Hardcoded: ARIA semantics and focus model.

## Banner
- Source: `apps/frontend/src/components/common/Banner.jsx`
- Category: basic
- Description: status/remediation callout with optional disclosure and actions.
- Extractable props: `tone`, `title`, `body`, `detail`
- Hardcoded: hierarchy and accessibility role.

## AgentLiveStrip
- Source: `apps/frontend/src/components/agents/AgentLiveStrip.jsx`
- Category: basic
- Description: compact agent freshness and five-metric strip with sparklines.
- Extractable props: `freshness`, `metrics`, `dimmed`
- Hardcoded: metric strip layout and chart geometry.
