# Route map

Router: React Router DOM 7, configured in `apps/frontend/src/App.jsx`. Every authenticated route renders inside the application shell described in `layouts.md`.

| URL | Page source | Notes |
| --- | --- | --- |
| `/` | redirect | Redirects to `/map`. |
| `/map` | `apps/frontend/src/pages/MapPage.jsx` | Advanced interactive topology canvas. |
| `/hardware` | `apps/frontend/src/pages/HardwarePage.jsx` | Hardware inventory master/detail. |
| `/compute-units` | `apps/frontend/src/pages/ComputeUnitsPage.jsx` | Compute inventory. |
| `/services` | `apps/frontend/src/pages/ServicesPage.jsx` | Service inventory. |
| `/storage` | `apps/frontend/src/pages/StoragePage.jsx` | Storage inventory. |
| `/monitors` | `apps/frontend/src/pages/MonitorsPage.jsx` | Monitor fleet and status groups. |
| `/monitors/:id` | `apps/frontend/src/pages/MonitorDetailPage.jsx` | Monitor history and incidents. |
| `/privacy` | `apps/frontend/src/pages/PrivacyPage.jsx` | Privacy and attack-surface dashboard. |
| `/notifications` | `apps/frontend/src/pages/NotificationsPage.jsx` | Guarded notifications route. |
| `/external-nodes` | `apps/frontend/src/pages/ExternalNodesPage.jsx` | External topology objects. |
| `/docs` | `apps/frontend/src/pages/DocsPage.jsx` | Documentation. |
| `/ipam` | `apps/frontend/src/pages/IPAMPage.jsx` | Guarded IPAM workspace. |
| `/intel` | `apps/frontend/src/pages/IntelPage.jsx` | Capacity and efficiency intelligence. |
| `/logs`, `/logs/audit` | `apps/frontend/src/pages/LogsPage.jsx` | Guarded operational/audit log views. |
| `/settings` | `apps/frontend/src/pages/SettingsPage.jsx` | Guarded settings workspace. |
| `/discovery` | `apps/frontend/src/pages/DiscoveryPage.jsx` | Discovery fleet, scans, review queue and history. |
| `/agents`, `/agents/enroll` | `apps/frontend/src/pages/AgentsPage.jsx` | Agent fleet and enrollment. |
| `/agents/:id` | `apps/frontend/src/pages/AgentDetailPage.jsx` | Agent identity, health, telemetry, probes, discovery and events. |
| `/admin/users` | `apps/frontend/src/pages/AdminUsersPage.jsx` | Guarded user administration. |
| `/admin/tokens` | `apps/frontend/src/pages/AccessTokensPage.jsx` | Guarded token administration. |

Target route for this design task: `/agents/:id?tab=telemetry`.
