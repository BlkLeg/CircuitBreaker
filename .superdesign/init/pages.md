# Key page dependency trees

## `/agents/:id?tab=telemetry` — Agent detail telemetry

Entry: `apps/frontend/src/pages/AgentDetailPage.jsx`

- `apps/frontend/src/components/agents/AgentIdentityHeader.jsx`
  - `apps/frontend/src/components/common/DetailHeader.jsx`
  - `apps/frontend/src/components/common/CopyField.jsx`
- `apps/frontend/src/components/agents/AgentStateBanner.jsx`
  - `apps/frontend/src/components/common/Banner.jsx`
  - `apps/frontend/src/components/agents/AgentStateChip.jsx`
- `apps/frontend/src/components/agents/AgentLiveStrip.jsx`
- `apps/frontend/src/components/common/Tabs.jsx`
- `apps/frontend/src/components/agents/AgentTelemetryTab.jsx`
  - `apps/frontend/src/components/common/Panel.jsx`
  - `apps/frontend/src/components/common/StatTile.jsx`
  - `apps/frontend/src/components/common/EmptyState.jsx`
  - `apps/frontend/src/components/common/Banner.jsx`
  - `apps/frontend/src/lib/time.js`
  - `apps/frontend/src/api/agents.js`
- `apps/frontend/src/components/agents/AgentOverviewTab.jsx`
- `apps/frontend/src/components/agents/AgentEventsPanel.jsx`
- `apps/frontend/src/components/agents/AssignedProbesSection.jsx`
- `apps/frontend/src/components/agents/DiscoveryScopeSection.jsx`
- `apps/frontend/src/components/agents/RemoteProbeConfigEditor.jsx`
- `apps/frontend/src/components/common/ConfirmDialog.jsx`
- `apps/frontend/src/hooks/useAgentDetail.js`
- `apps/frontend/src/styles/agents.css`
- `apps/frontend/src/styles/panels.css`
- `apps/frontend/src/styles/main.css`

## `/agents` — Agent fleet

Entry: `apps/frontend/src/pages/AgentsPage.jsx`

- `apps/frontend/src/components/agents/FleetTable.jsx`
  - `apps/frontend/src/components/agents/FleetRow.jsx`
  - `apps/frontend/src/components/agents/Sparkline.jsx`
  - `apps/frontend/src/components/agents/AgentStateChip.jsx`
- `apps/frontend/src/components/agents/AddAgentPanel.jsx`
- `apps/frontend/src/components/agents/AgentApprovalModal.jsx`
- `apps/frontend/src/components/common/Panel.jsx`
- `apps/frontend/src/components/common/ConfirmDialog.jsx`
- `apps/frontend/src/styles/agents.css`

## `/map` — Topology map

Entry: `apps/frontend/src/pages/MapPage.jsx`

- `apps/frontend/src/components/map/CustomNode.jsx`
- `apps/frontend/src/components/map/CustomEdge.jsx`
- `apps/frontend/src/components/map/MapCanvasOverlays.jsx`
- `apps/frontend/src/components/map/TelemetrySidebar.jsx`
- `apps/frontend/src/components/Map/Sidebar.jsx`
- `apps/frontend/src/components/MapToolbar.jsx`
- `apps/frontend/src/components/map/LegendPanel.jsx`
- `apps/frontend/src/components/map/NodeTypeFilterBar.jsx`
- `apps/frontend/src/components/security/PrivacyScoreWidget.jsx`
- `apps/frontend/src/components/security/HostileNetworkBanner.jsx`

## `/monitors` — Monitor fleet

Entry: `apps/frontend/src/pages/MonitorsPage.jsx`

- `apps/frontend/src/components/monitors/MonitorSummaryStrip.jsx`
- `apps/frontend/src/components/monitors/MonitorFilterBar.jsx`
- `apps/frontend/src/components/monitors/MonitorGroup.jsx`
  - `apps/frontend/src/components/monitors/MonitorCard.jsx`
- `apps/frontend/src/components/monitors/MonitorForm.jsx`
- `apps/frontend/src/styles/monitors.css`

## `/discovery` — Discovery operations

Entry: `apps/frontend/src/pages/DiscoveryPage.jsx`

- `apps/frontend/src/components/discovery/DiscoverySidebar.jsx`
- `apps/frontend/src/components/discovery/NewScanPage.jsx`
- `apps/frontend/src/components/discovery/ReviewQueuePanel.jsx`
- `apps/frontend/src/components/discovery/ScanProfilesPanel.jsx`
- `apps/frontend/src/pages/DiscoveryHistoryPage.jsx`
- `apps/frontend/src/styles/discovery.css`

## `/privacy` — Privacy and attack surface

Entry: `apps/frontend/src/pages/PrivacyPage.jsx`

- `apps/frontend/src/components/privacy/PrivacyScoreCard.jsx`
- `apps/frontend/src/components/privacy/FindingsOverviewChart.jsx`
- `apps/frontend/src/components/privacy/FindingsByCategoryChart.jsx`
- `apps/frontend/src/components/privacy/KeyFindingsList.jsx`
- `apps/frontend/src/components/privacy/FlaggedDevicesTable.jsx`
- `apps/frontend/src/components/privacy/AttackSurfaceTable.jsx`
- `apps/frontend/src/components/privacy/RemediationDrawer.jsx`

## `/settings` — Settings workspace

Entry: `apps/frontend/src/pages/SettingsPage.jsx`

- `apps/frontend/src/components/settings/SettingsNav.jsx`
- `apps/frontend/src/components/settings/SettingsActionBar.jsx`
- `apps/frontend/src/components/settings/SettingSection.jsx`
- `apps/frontend/src/components/settings/SettingField.jsx`
- `apps/frontend/src/components/settings/ThemeSettings.jsx`
- `apps/frontend/src/components/settings/BrandingSettings.jsx`
- `apps/frontend/src/components/settings/IntegrationsManager.jsx`
