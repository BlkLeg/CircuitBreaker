# Inventory workspace caller audit (2026-09-10)

Working notes for Stage C / plan 07. Fold into `07-inventory-workspace.md` when the
Hardware slice ships; keep this file until sibling migrations finish.

## Compatibility rule

| Bucket | Contract | Notes |
| --- | --- | --- |
| **page UI** | `GET /{resource}/page` → `{items,total,limit,offset,sort,direction}` | Hardware first |
| **picker / options** | `GET /inventory/options` | Bounded search + selected labels |
| **complete dataset** | Existing unbounded `GET /{resource}` (or filtered list) | Map, memberships, relationship UIs |

Selection model (frontend): `{ mode: 'ids' \| 'all_matching', ids: number[], filter: {q,role,tag,sort,direction}, totalMatching: number, exclusions: number[] }`.
Changing q/role/tag/sort clears selection. No new bulk-destructive API in this slice.

## `hardwareApi.list` callers

| Call site | Bucket | Action |
| --- | --- | --- |
| `pages/HardwarePage.jsx` | page UI | Switch to `hardwareApi.page` |
| `pages/ComputeUnitsPage.jsx` (hw side-load) | complete / picker | Prefer options or keep full list for dropdown |
| `pages/ServicesPage.jsx` (hw + cu side-load) | complete / picker | Same |
| `pages/StoragePage.jsx` (hw side-load) | complete / picker | Same |
| `pages/PrivacyPage.jsx` | complete dataset | Keep list |
| `components/DocLinkModal.jsx` | picker | Migrate to options later |
| `components/ipam/NetworksTab.jsx` | complete dataset | Keep list |
| `components/settings/transfer/ResolveDecisionDrawer.jsx` | picker | Migrate to EntityPicker later |
| `components/settings/NativeMonitorModal.jsx` | picker | Options later; keep list+limit for now |
| `components/details/NetworkDetail.jsx` | complete dataset | Keep list |
| `components/details/PortEditor.jsx` | picker | Options later |
| `components/details/ClusterDetail.jsx` | complete dataset | Keep list |
| `__tests__/hardware-page.test.jsx` | test | Mock `page` |

## Sibling page list owners (migration later)

| Page | Current fetch | Page endpoint today |
| --- | --- | --- |
| Hardware | `hardwareApi.list` | Yes — `/hardware/page` |
| Compute | `computeUnitsApi.list` | No |
| Services | `servicesApi.list` | No |
| Storage | `storageApi.list` | No |
| External nodes | `externalNodesApi.list` | No |
| IPAM Networks | own APIs | Out of Hardware slice |

## ACL note for conflict names

No row-level inventory ACL exists beyond mount auth / scopes. `entity_name` in
`ip_conflict` context follows the same visibility as `GET /hardware/{id}` for
authenticated inventory readers. Names are truncated strings only.
