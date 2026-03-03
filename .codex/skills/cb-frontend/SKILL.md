---
name: cb-frontend
description: React/Vite/Tailwind frontend development for Circuit Breaker — the self-hosted homelab visualization platform. Use when working on UI pages (frontend/src/pages/), components (frontend/src/components/), API client wrappers (frontend/src/api/), React context/hooks, the ReactFlow topology map (MapPage), Vitest component tests, or Tailwind/theme configuration. Covers entity CRUD modals, topology map layouts, rack simulator UI, theming system, command palette, auth flow, and OOBE wizard.
---

# Circuit Breaker — Frontend Skill

## Stack

- **React 18** (JSX, no TypeScript), Vite, Tailwind CSS 3, React Router 6
- **Topology map**: ReactFlow 11 + ELK.js (auto-layout) + D3-force + Dagre
- **Animations**: Framer Motion
- **Markdown editor**: `@uiw/react-md-editor`
- **Icons**: Lucide React + custom SVG slugs (`src/icons/`)
- **HTTP**: Axios (`src/api/`)
- **Event bus**: mitt (`src/lib/eventBus.js`)
- **Tests**: Vitest + React Testing Library + MSW (mock service worker)

## Repo layout

```
frontend/src/
├── api/          # Axios wrappers — one file per backend domain
├── components/   # Shared UI components (modals, tables, toast, dock, header…)
│   ├── auth/     # AuthModal, ProfileModal
│   └── common/   # Toast, SecurityBanner, ErrorBoundary, etc.
├── config/       # App-level constants
├── context/      # React contexts: Settings, Timezone, Auth
├── hooks/        # Custom hooks (useDiscoveryStream, etc.)
├── icons/        # SVG icon components
├── lib/          # eventBus.js, utils
├── pages/        # Top-level route pages (one per domain)
├── styles/       # Global CSS
├── theme/        # Theme presets and palette logic
└── utils/        # Helpers (formatting, IP utils, etc.)
```

## Pages

| Page | Route | Notes |
|------|-------|-------|
| HardwarePage | /hardware | Physical devices inventory |
| ComputeUnitsPage | /compute | VMs & containers |
| ServicesPage | /services | Self-hosted services |
| StoragePage | /storage | Disks, pools, datasets, shares |
| NetworksPage | /networks | VLANs/subnets |
| MiscPage | /misc | DNS, VPNs, SaaS, catch-all |
| ExternalNodesPage | /external | Off-prem / cloud nodes |
| MapPage | /map | ReactFlow topology map (lazy-loaded) |
| DiscoveryPage | /discovery | Auto-discovery scan UI |
| LogsPage | /logs | Audit log viewer |
| DocsPage | /docs | Markdown documentation (lazy-loaded) |
| SettingsPage | /settings | App settings (tabbed) |
| OOBEWizardPage | /setup | First-run wizard |

## Key conventions

### Adding a page / entity

1. Create `src/pages/<Entity>Page.jsx`.
2. Create `src/api/<entity>.js` — thin Axios wrappers mirroring backend routes.
3. Register route in `src/App.jsx` `<Routes>`.
4. Add dock entry in `src/components/Dock.jsx` (or settings).

### Component patterns

- Use **functional components** with hooks only — no class components.
- **Modals**: render as portals via the `Modal` base component in `components/common/`.
- **Tables**: use the shared `EntityTable` component where possible.
- **Toast notifications**: `useToast()` from `context/` — call `toast.success()` / `toast.error()`.
- **Tailwind**: use `cn()` helper (clsx + tailwind-merge) from `src/lib/utils.js` for conditional classes.
- **Framer Motion**: wrap enter/exit animations with `AnimatePresence` + `motion.div`.

### Theming

- Theme presets live in `src/theme/presets.js`.
- Active theme is stored in `AppSettings` (backend) and synced via `SettingsContext`.
- CSS variables (`--color-primary`, `--color-accent`, etc.) are set on `document.documentElement` from the active preset.
- 8+ built-in presets; custom colors override via `AppSettings.custom_colors` JSON.

### Topology map (`MapPage`)

- ReactFlow nodes represent Hardware, ComputeUnits, Services, Networks, ExternalNodes.
- Layout algorithms: cluster-centric (Dagre), top-down (ELK hierarchical), force-directed (D3).
- Node positions persisted to `GraphLayout` via `POST /api/v1/graph/layout`.
- Custom node types in `src/components/map/nodes/`.
- Live telemetry badges on hardware nodes from `LiveMetric` data.

### API client pattern

```js
// src/api/hardware.js
import axios from './client';
export const getHardware = () => axios.get('/hardware');
export const createHardware = (data) => axios.post('/hardware', data);
export const updateHardware = (id, data) => axios.put(`/hardware/${id}`, data);
export const deleteHardware = (id) => axios.delete(`/hardware/${id}`);
```

Base client configured in `src/api/client.js` — sets `baseURL` to `/api/v1`, attaches JWT from localStorage.

### Auth

- Auth state managed by `AuthContext` — `isAuthenticated`, `user`, `login()`, `logout()`.
- Auth is **optional** — gated by `AppSettings.auth_enabled`.
- `AuthModal` handles login; `ProfileModal` handles profile editing.
- JWT stored in `localStorage`; attached as `Authorization: Bearer <token>` header by the Axios client.

## Testing

- **Framework**: Vitest + React Testing Library + jsdom.
- **Mocking**: MSW (`src/__tests__/`) — intercepts Axios requests.
- **Run**: `npm test` (single pass) or `npm run test:watch` (watch mode).
- Tests live in `src/__tests__/`.

```jsx
// Example component test pattern
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import MyComponent from '../components/MyComponent';

describe('MyComponent', () => {
  it('renders label', () => {
    render(<MyComponent label="Hello" />);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });
});
```

## Reference files

- **`references/components.md`** — inventory of shared components, their props, and usage examples; read when building new UI components or pages.
