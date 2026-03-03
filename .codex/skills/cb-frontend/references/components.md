# Circuit Breaker — Frontend Component Reference

## Table of Contents

1. [Shared UI Components](#shared-ui-components)
2. [Common Components (`components/common/`)](#common-components)
3. [Entity Form & Table](#entity-form--table)
4. [Map Components (`components/map/`)](#map-components)
5. [Context / Hooks API](#context--hooks-api)
6. [API Client Modules (`src/api/`)](#api-client-modules)

---

## Shared UI Components

### `EntityTable`

Generic sortable/filterable table for inventory pages.

```jsx
<EntityTable
  columns={[
    { key: 'name', label: 'Name', sortable: true },
    { key: 'role', label: 'Role' },
  ]}
  data={hardwareList}
  onEdit={(item) => openModal(item)}
  onDelete={(item) => handleDelete(item.id)}
  searchFields={['name', 'role', 'ip_address']}
/>
```

### `EntityForm`

Modal form generator — renders fields from a schema array.

```jsx
<EntityForm
  title="Add Hardware"
  fields={[
    { name: 'name', label: 'Name', type: 'text', required: true },
    { name: 'role', label: 'Role', type: 'select', options: ['server', 'switch', 'ups'] },
    { name: 'memory_gb', label: 'Memory (GB)', type: 'number' },
  ]}
  initialValues={editTarget}
  onSubmit={handleSubmit}
  onClose={() => setModalOpen(false)}
/>
```

### `SearchBox`

Debounced search input used at the top of inventory pages.

```jsx
<SearchBox
  value={query}
  onChange={setQuery}
  placeholder="Search hardware…"
/>
```

### `TagFilter`

Multi-select tag chip filter bar.

```jsx
<TagFilter
  selected={activeTags}
  onChange={setActiveTags}
  entityType="hardware"
  entityId={item.id}
/>
```

### `CatalogSearch`

Typeahead search component backed by the vendor device catalog API.  
Fires `onSelect(catalogEntry)` when the user picks a model — caller applies the auto-filled spec fields.

```jsx
<CatalogSearch onSelect={(entry) => applySpecs(entry)} />
```

### `TelemetryPanel`

Shows live health data pulled from a hardware node's `telemetry_data` field.  
Renders CPU %, memory %, power status, and fan/temp badges.

```jsx
<TelemetryPanel hardwareId={hw.id} />
```

### `IPAddressInput`

Controlled input with CIDR/IP validation feedback.

```jsx
<IPAddressInput
  value={ipAddress}
  onChange={setIpAddress}
  allowCIDR={false}
/>
```

### `IPConflictBanner` / `IpStatusBadge`

`IPConflictBanner` — renders a warning bar when `service.ip_conflict === true`.  
`IpStatusBadge` — small inline chip: green = no conflict, orange = inherited, red = conflict.

### `PortsEditor`

Manages a JSON array of `{port, protocol, description}` objects with add/remove rows.

```jsx
<PortsEditor value={ports} onChange={setPorts} />
```

### `DocEditor` / `MarkdownViewer`

`DocEditor` — full `@uiw/react-md-editor` with preview toggle and save.  
`MarkdownViewer` — read-only rendered Markdown using `react-markdown` + syntax highlighting.

### `TimestampCell`

Formats a UTC ISO string into the user's preferred timezone (from `TimezoneContext`).

```jsx
<TimestampCell value={item.created_at} />
```

### `CommandPalette`

Global fuzzy search triggered by `Ctrl+K` / `Cmd+K`.  
Searches across all entity types via `GET /api/v1/search?q=`.

### `ThemePalette`

Live theme switcher — shows all presets with a color swatch preview.  
Persists selection to `AppSettings` via API.

### `Dock`

Sticky bottom navigation bar. Order and hidden items come from `AppSettings.dock_order` / `dock_hidden_items`.

### `Header`

Top bar with app name/logo, user avatar, auth button, and `CommandPalette` trigger.

---

## Common Components

### `FormModal`

Wraps any form in a centered modal dialog with backdrop.

```jsx
<FormModal
  title="Edit Service"
  isOpen={open}
  onClose={() => setOpen(false)}
>
  <YourFormHere />
</FormModal>
```

### `ConfirmDialog`

Destructive-action confirmation dialog.

```jsx
<ConfirmDialog
  open={confirmOpen}
  title="Delete hardware?"
  description="This cannot be undone."
  onConfirm={handleDelete}
  onCancel={() => setConfirmOpen(false)}
/>
```

### `Drawer`

Slide-in side panel (right edge).

```jsx
<Drawer isOpen={open} onClose={close} title="Details">
  {children}
</Drawer>
```

### `DocsPanel`

Renders entity-attached documentation links + inline preview.

```jsx
<DocsPanel entityType="hardware" entityId={hw.id} />
```

### `Toast` / `useToast`

Notification system. Import the hook:

```jsx
import { useToast } from './components/common/Toast';
const { toast } = useToast();
toast.success('Hardware saved');
toast.error('Failed to save');
```

### `EnvironmentCombobox` / `CategoryCombobox`

Combobox selects backed by the environment/category API endpoints.

```jsx
<EnvironmentCombobox value={envId} onChange={setEnvId} />
<CategoryCombobox value={catId} onChange={setCatId} />
```

### `IconPickerModal`

Modal that lets users search and select a Lucide icon or custom user-uploaded icon slug.

```jsx
<IconPickerModal
  value={iconSlug}
  onChange={setIconSlug}
  onClose={() => setPickerOpen(false)}
/>
```

### `SecurityBanner`

Beta security notice shown when `AppSettings.auth_enabled === false`.

### `ClearLabDialog`

Danger-zone modal to wipe all lab data (admin only).

---

## Entity Form & Table

### `DocLinkModal`

Links/unlinks a `Doc` to any entity polymorphically.

```jsx
<DocLinkModal
  entityType="service"
  entityId={svc.id}
  onClose={close}
/>
```

### `MobileOverflowSheet` / `MobileTabBar`

Bottom sheet and tab bar used on narrow viewports (< 768px).

---

## Map Components

All live in `frontend/src/components/map/`.

### `CustomNode`

ReactFlow node — renders a hardware/service/network card with:
- Entity name + icon slug
- Environment badge
- Telemetry health indicator (for hardware)
- Drag handle

### `CustomEdge` / `SmartEdge`

`CustomEdge` — labeled bezier edge with connection-type badge.  
`SmartEdge` — routes around other nodes using ELK orthogonal routing.

### `MapContextMenu`

Right-click context menu on nodes — options: view details, remove from map, pin.

### `WifiOverlay`

Renders Wi-Fi signal range circles on the canvas for AP hardware nodes.

### `mapConstants.js`

Exports: node type registry, edge type registry, layout algorithm configs, default viewport.

---

## Context / Hooks API

### `SettingsContext`

```jsx
const { settings, updateSettings } = useSettings();
// settings mirrors AppSettings DB row
// updateSettings(patch) PATCHes /api/v1/settings and refreshes
```

### `AuthContext`

```jsx
const { user, isAuthenticated, login, logout, authModalOpen, setAuthModalOpen } = useAuth();
```

### `TimezoneContext`

```jsx
const { timezone, formatDate } = useTimezone();
// formatDate(isoString) → locale string in user's IANA timezone
```

### `useDiscoveryStream`

```jsx
const { pendingCount, latestJob } = useDiscoveryStream();
// Subscribes to the WebSocket at /api/v1/ws/discovery for real-time scan progress
```

---

## API Client Modules

All modules in `src/api/` wrap Axios with the base path `/api/v1`.  
JWT is attached automatically by `src/api/client.js`.

| File | Endpoints |
|------|-----------|
| `hardware.js` | GET/POST/PUT/DELETE `/hardware` |
| `compute.js` | GET/POST/PUT/DELETE `/compute` |
| `services.js` | GET/POST/PUT/DELETE `/services` |
| `storage.js` | GET/POST/PUT/DELETE `/storage` |
| `networks.js` | GET/POST/PUT/DELETE `/networks` |
| `misc.js` | GET/POST/PUT/DELETE `/misc` |
| `external_nodes.js` | GET/POST/PUT/DELETE `/external-nodes` |
| `graph.js` | GET/PUT `/graph/layout/:name` |
| `discovery.js` | POST `/discovery/scan`, GET `/discovery/jobs` |
| `categories.js` | GET/POST/PUT/DELETE `/categories` |
| `environments.js` | GET/POST/PUT/DELETE `/environments` |
| `catalog.js` | GET `/catalog/search?q=` |
| `logs.js` | GET `/logs` |
| `auth.js` | POST `/auth/login`, POST `/auth/logout` |
| `settings.js` | GET/PATCH `/settings` |
| `docs.js` | GET/POST/PUT/DELETE `/docs` |
| `search.js` | GET `/search?q=` |
