## v0.2.2 Brainstorm: Uptime Kuma + Beszel Integration

**Priority**: Tier 1 (homelab staples). Perfect fit for Circuit Breaker's "ecosystem integrations" roadmap.

***

### **Uptime Kuma** (Socket.io API + Python wrappers)

**What it is**: Self-hosted "Uptime Robot". Monitors HTTP/TCP/Ping, rich notifications (Discord/Slack/Telegram).

**Integration Ideas** (90% Socket.io + 10% REST):

1. **Bi-directional Sync** (`integrations_configs` table):
   ```
   Uptime Kuma (http://ukuma.local:3001)
   ├── API Key: [encrypted]
   ├── Auto-sync Monitors → Services
   │   HTTP:192.168.1.10:80 → Service "Web01" (runs on Server1)
   │   Ping:proxmox.local → Hardware "Proxmox"
   └── Push Circuit Breaker status → Uptime Kuma
       CB API → UP/DOWN badge in UK status page
   ```

2. **Node Badges** (Topology):
   ```
   Server Node → [UK: 99.8% ↑] ring badge
   │
   └── Click → "View in Uptime Kuma" → ukuma.local/monitor/123
   ```

3. **Auto-Creation**:
   ```
   Right-click Service → "Monitor with Uptime Kuma"
   → Auto-creates HTTP monitor + notification rules
   ```

4. **Live Status** (WebSocket push):
   ```
   UK monitor DOWN → Circuit Breaker node → Red pulse + toast
   ```

**Technical**:
- `python-uptime-kuma-api` wrapper (Socket.io client).
- Config: URL + API key (Settings → Integrations → Uptime Kuma).
- Sync: APScheduler hourly job pulls monitors → matches by IP/port → creates `services` if missing.
- Push: UK webhook → CB WebSocket → node status overlay.

**UI**:
```
Topology Node → Hover → "Uptime Kuma: 99.8% (24h) ↑"
                           [Open Monitor] [Mute Alerts]
```

***

### **Beszel** (SSH Agent + Hub)

**What it is**: Lightweight Prometheus alternative. Hub + SSH agents → CPU/RAM/Docker stats + alerts. Beautiful dashboard.

**Integration Ideas** (Hub API + Agent templates):

1. **Agent Deployment** (Zero-config):
   ```
   Right-click Server → "Install Beszel Agent"
   → Generates SSH-authorized agent deploy script
   → Auto-registers with Beszel Hub (CB sends agent token)
   ```

2. **Live Metrics Overlay** (Topology):
   ```
   Server Node → [CPU: 23% | RAM: 4.2/16GB | ↓0.8 load]
   │
   └── Sparkline history (1h CPU/RAM trends)
   ```

3. **Beszel Hub Linkage**:
   ```
   Settings → Integrations → Beszel Hub
   ├── Hub URL + Token
   └── Pull system stats → Node telemetry badges
   ```

4. **Alert Sync**:
   ```
   Beszel Alert "Server1 CPU >90%" → CB toast + node warning ring
   ```

**Technical**:
- Beszel Hub API (PocketBase REST) for agent management + metrics.
- CB generates unique agent tokens → one-click deploy.
- Metrics poll: CB cron → Beszel API → cache 5min → WebSocket push.
- Docker Compose snippet in UI for Hub.

**UI**:
```
Rack → Server → [Beszel: CPU 23% | 4.2GB | Temp 42°C]
               ↓
           [Live Chart Mini] [Beszel Dashboard]
```

***

### **Combined UX Vision**

```
Topology Map:
Server1 [CPU:23% | UK:99.8%↑ | ↓0.8] ← Beszel + UKuma badges
  ↓
Service-Web [UK Monitor ↑] ← Auto-synced

Sidebar → Integrations:
✅ Uptime Kuma (ukuma.local:3001) → [Resync] [Create Monitor]
✅ Beszel (beszel.local) → [Deploy Agent] [View Dashboard]
```

***

### **Implementation Priority** (v0.2.2)

```
Week 1: Uptime Kuma
├── Config + API wrapper (2d)
├── Monitor sync → Services (1d)
├── Node badges + click-thru (1d)
└── Push CB status (1d)

Week 2: Beszel
├── Hub config + metrics poll (1.5d)
├── Agent deploy generator (1d)
├── Live sparkline badges (1.5d)
└── Alert sync (1d)

Week 3: Polish
├── UI consistency (badges, modals)
├── Tests + docs
└── Release v0.2.2
```

***

### **Data Model** (`integration_configs`)

```sql
CREATE TABLE integration_configs (
  id INTEGER PRIMARY KEY,
  type TEXT,           -- "uptime_kuma", "beszel"
  name TEXT,           -- "Main UKuma"
  config_url TEXT,     -- "http://ukuma.local:3001"
  config_token_enc TEXT,  -- Fernet-encrypted API key
  auto_sync BOOLEAN,
  last_sync DATETIME,
  sync_interval_minutes INTEGER DEFAULT 60
);
```

### **Monetization Angle** (Future)
```
Free: Config + manual sync
Pro: Auto-deploy agents + live metrics + alert sync
```

**Perfect v0.2.2 scope**: Makes CB the "missing topology layer" for UKuma/Beszel users. Visual metrics badges make the map come alive. One-click agent deploy = killer UX.