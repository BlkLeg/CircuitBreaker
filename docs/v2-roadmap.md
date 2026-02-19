# Circuit Breaker – v2 Roadmap

**Status**: v1 is complete and production-ready. v2 focuses on power-user features, enterprise polish, and extensibility while maintaining simplicity for homelab users.

***

## Features

### 1. Map Context Menu (Right-Click Actions)

**Objective**: Enable rapid relationship creation directly from the topology map without leaving the visual context.

**Deliverables**:

#### Backend
- No new endpoints required (reuse existing relationship APIs from Phase 2).
- Ensure all relationship POST endpoints accept the same payloads as documented.

#### Frontend (Map HUD)
- **Right-click context menu** on any node:
  - Position: mouse coordinates, constrained to viewport.
  - Menu items (context-sensitive):
  - Also add an edit svg icon option.

```
For Service nodes:
├── Link to Hardware    → dropdown (current hardware list)
├── Link to Compute     → dropdown (current compute units)
├── Link to Storage     → dropdown (current storage)
├── Link to Network     → dropdown (current networks)
└── Link to Misc        → dropdown (current misc items)

For Compute nodes:
├── Link to Hardware    → dropdown (current hardware)
├── Link to Services    → dropdown (current services)
└── Link to Network     → dropdown (current networks)

For Hardware nodes:
├── Link to Compute     → dropdown (current compute units)
└── Link to Storage     → dropdown (current storage pools)

For Network nodes:
├── Link to Compute     → dropdown (current compute units)
└── Link to Services    → dropdown (current services)

For Storage nodes:
└── Link to Services    → dropdown (current services)
```

- **Dropdown behavior**:
  - Searchable (type to filter).
  - Shows name + tags + brief info.
  - Select → calls appropriate relationship API.
  - Success: refresh graph, show success toast.
  - Error: show error toast, keep menu open.

- **Visual feedback**:
  - New edge animates into place.
  - Related nodes pulse briefly.

**Exit criteria**:
- Right-click any service node → "Link to Storage" → select storage → edge appears on graph.
- Can link compute to networks, hardware to compute, etc.
- Invalid links prevented by API or client-side validation.

***

### 2. Enhanced Hardware/Compute Information

**Objective**: Show storage capacity and type directly in node details and map tooltips.

**Deliverables**:

#### Backend
- Extend existing entity schemas:
  - `hardware` → `storage_summary` field:
    ```json
    {
      "total_gb": 10000,
      "used_gb": 8000,
      "types": ["ssd", "hdd", "zfs"],
      "primary_pool": "tank"
    }
    ```
  - `compute_units` → `storage_allocated` field:
    ```json
    {
      "disk_gb": 500,
      "storage_pools": ["tank/media"]
    }
    ```
- Add to `/api/v1/graph/topology` node data:
  ```json
  {
    "id": "hw-1",
    "type": "hardware",
    "ref_id": 1,
    "label": "Node-1",
    "tags": ["prod"],
    "storage_summary": { "total_gb": 10000, "used_gb": 80 }
  }
  ```

#### Frontend
- **Map node tooltips**: show storage summary (capacity bar, primary pool).
- **Entity HUD detail panels**:
  - Hardware: storage capacity pie chart or progress bar.
  - Compute: allocated storage with pool names.
- **Map node badges**: small storage indicator (e.g., "10TB 80%").

**Exit criteria**:
- Hardware node tooltip shows "10TB (80% used, ZFS)".
- Detail HUD shows storage breakdown.
- Graph badges reflect storage status.

***

### 3. Authentication System

**Objective**: Optional authentication with Gravatar support and profile photo upload, defaulting to unauthenticated mode.

**Deliverables**:

#### Backend
- **Settings integration**: add auth config to `app_settings`:
  ```json
  {
    "auth_enabled": true,
    "jwt_secret": "random-32-char-secret-generated-on-first-run",
    "session_timeout_hours": 24
  }
  ```
- **User table**:
  ```sql
  CREATE TABLE users (
      id          INTEGER PRIMARY KEY,
      email       TEXT UNIQUE NOT NULL,
      gravatar_hash TEXT,
      profile_photo TEXT,  -- path to uploaded file, max 5MB
      display_name TEXT,
      is_admin    BOOLEAN DEFAULT FALSE,
      created_at  TEXT,
      last_login  TEXT
  );
  ```
- **Auth endpoints**:
  ```
  POST /api/v1/auth/register
    Body: { "email": "...", "password": "..." }
    Returns: JWT token
  
  POST /api/v1/auth/login
    Body: { "email": "...", "password": "..." }
    Returns: JWT token
  
  GET /api/v1/auth/me
    Headers: Authorization: Bearer <token>
    Returns: user profile
  
  PUT /api/v1/auth/me
    Body: { "display_name": "...", "profile_photo": file }
  
  POST /api/v1/auth/logout
  ```
- **Middleware**: protect modifying endpoints when `auth_enabled=true`.
- **File storage**: profile photos → `/data/uploads/profiles/` (Docker volume).

#### Frontend
- **Unauthenticated default**: full read/write access until auth enabled.
- **Settings → Authentication tab**:
  - Toggle: `Enable authentication`.
  - If enabled:
    - Generate/show JWT secret (copy button).
    - Show first user registration instructions.
- **Auth UI** (minimal overlay):
  - Login/register form (email + password).
  - Profile editor (Gravatar auto-detect + photo upload).
  - Profile photo preview (Gravatar fallback).
- **HUD integration**:
  - User avatar in top-right (Gravatar/profile photo).
  - Dropdown: Profile, Logout.

**Exit criteria**:
- Settings → enable auth → register first user → all CRUD requires login.
- Profile photo uploads work (≤5MB), Gravatar falls back correctly.
- Logout clears session.

***

### 4. Enhanced Doc Editor

**Objective**: Production-grade Markdown editor with toolbar and rich formatting.

**Deliverables**:

#### Frontend (Docs HUD)
- Replace raw textarea with **React Markdown editor** (recommend **React-Markdown-Editor-Lite** or **MD Editor V5**).
- **Toolbar**:
  ```
  [B] [I] [U] [S] | H1 H2 H3 | Bold | Italic | Quote | Code | Link | Image | Table | Emoji 🎨 | Preview 📱
  ```
- **Features**:
  - Live preview (split-pane or toggle).
  - Emoji picker (native or library).
  - Code blocks (language detection, syntax highlighting).
  - Keyboard shortcuts (Ctrl+B, etc.).
  - Drag/drop image upload (store as base64 or upload to `/data/uploads/docs/`).
- **UI improvements**:
  - Dark theme matching app.
  - Resizable preview/editor split.
  - Auto-save every 30s (localStorage + backend sync).

#### Backend
- `docs` table → `body_html` column (rendered Markdown for fast display).
- Image upload endpoint: `POST /api/v1/docs/{id}/upload-image`.

**Exit criteria**:
- Docs HUD has full toolbar, live preview, emoji picker, code syntax highlighting.
- Images upload and embed correctly.
- Auto-save prevents data loss.

***

### 5. Branding

**Objective**: Professional app identity with customization.

**Deliverables**:

#### Backend
- Settings → branding config:
  ```json
  {
    "app_name": "Circuit Breaker",
    "favicon_path": "/icons/favicon.ico",
    "primary_color": "#00d4ff",
    "accent_colors": ["#00d4ff", "#ff6b6b", "#4ecdc4"]
  }
  ```

#### Frontend
- **Default favicon**: `frontend/public/favicon.ico` (circuit breaker/network themed).
- **Configurable favicon**: settings → file upload → `/data/uploads/favicon.ico`.
- **CSS variables** from settings:
  ```css
  :root {
    --primary: #00d4ff;
    --accent-1: #ff6b6b;
    --accent-2: #4ecdc4;
  }
  ```
- **Theme park compatibility**:
  - Export settings as JSON compatible with Theme Park.
  - Import button in settings.

**Exit criteria**:
- Custom favicon uploads and displays.
- Primary/accent colors apply to HUD, buttons, highlights.
- Theme Park import works.

***

### 6. Advanced Theming

**Objective**: 6–10 professional theme presets + customization.

**Deliverables**:

#### Frontend
- **Settings → Themes tab**:
  - **Presets** (6–10 options):
    ```
    1. Cyberpunk Neon  (cyan/pink)
    2. Dark Matter     (deep purple/black)
    3. Solarized Dark  (classic)
    4. Nord            (arctic blue/gray)
    5. Dracula         (purple/pink/green)
    6. Gruvbox Dark    (brown/orange)
    7. Monokai         (green/purple)
    8. One Dark        (GitHub dark)
    ```
  - **Custom**:
    - Color picker for primary, secondary, accent1, accent2.
    - Preview panel showing HUD with new colors.
- **CSS framework**:
  - Use CSS custom properties throughout.
  - Hot-reload theme changes (no page refresh needed).

#### Backend
- Settings → `theme_preset` + `custom_colors` JSON.

**Exit criteria**:
- 8+ theme presets switch instantly.
- Custom colors apply to entire app.
- Theme changes persist across sessions.

***

### 7. Data Portability & Security (Phase 4 Carryover)

**Objective**: Make it safe to adopt long-term (backup/restore) and secure for homelab exposure.

**Deliverables**:

#### Backend
- **Export**: `GET /api/v1/admin/export`
  - Returns full JSON snapshot (entities, tags, docs, relationships).
- **Import**: `POST /api/v1/admin/import`
  - Accepts JSON snapshot.
  - "Wipe before import" option.
- **Auth**:
  - Optional static API token (env var or config).
  - Middleware checks `Authorization: Bearer <token>` on mutation endpoints.

#### Frontend
- **Settings → Admin Tab**:
  - "Export Backup" button.
  - "Restore Backup" file upload (with big red warning).
  - API Token input field (saved to localStorage).

**Exit criteria**:
- Full backup → nuke DB → restore works perfectly.
- Enabling auth blocks unkeyed write requests.

***

### 8. Quality of Life Improvements

**Objective**: Polish the day-to-day experience and fix usability rough edges.

**Deliverables**:

#### Frontend
- **"Recent Changes" Dashboard Widget**:
  - List of last 10 modified entities (requires `updated_at` sort on backend).
- **Inline Validation**:
  - Real-time feedback on forms (e.g., duplicate names, invalid IP/CIDR).
  - Toast notifications for all success/error actions.
- **Keyboard Shortcuts**:
  - `Ctrl+K` global search focus.
  - `Esc` to close modals/panels.

#### Backend
- **Query Optimization**:
  - Ensure `updated_at` sorting is performant for "Recent Changes".

**Exit criteria**:
- Forms feel responsive and "safe" to use.
- Recent context is easily accessible.

***

## v2 Exit Criteria

**Circuit Breaker v2 is complete when**:

1. ✅ Map right-click → link entities in 2 clicks.
2. ✅ Hardware/compute nodes show storage capacity/type.
3. ✅ Auth works: enable → register → protected CRUD (or Token Auth from Phase 4).
4. ✅ Doc editor has toolbar, emojis, code blocks, live preview.
5. ✅ Custom favicon + color scheme from settings.
6. ✅ 8+ theme presets + custom color picker.
7. ✅ Full Import/Export (JSON backup/restore).
8. ✅ QOL: Recent Changes widget + inline validation.
9. ✅ All v1 features remain fully functional.

**Priority order**: 1→2→7→8→3→4→5→6

**Estimated effort**: 3–5 days for experienced developer.

---