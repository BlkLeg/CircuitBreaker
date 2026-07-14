# Windscribe Integration — Design

**Date:** 2026-07-14
**Status:** Draft / Planning
**Author:** Shawnji (with Claude)

## Problem

Currently, CircuitBreaker excels at raw network discovery and capability brokering, answering the question: *"What is on my network?"* However, it stops short of answering: *"Is my network safe? What are these devices doing?"* 

By integrating Windscribe's ecosystem (R.O.B.E.R.T. threat intelligence, Control D, and network telemetry), we can elevate CircuitBreaker from a passive scanner to an active, insightful Privacy & Threat Dashboard. The goal is to ensure any backend data logic explicitly powers a meaningful frontend experience that guides the user to action.

## Goals

- **Threat Context:** Cross-reference discovered devices and their activity with Windscribe's intelligence feeds (malware, botnets, trackers).
- **Privacy Posture:** Assess the overall health and safety of the local network (e.g., captive portals, DNS hijacking, unencrypted DNS).
- **Actionable UX:** Ensure all backend data has a clear frontend representation (badges, scores, alerts) and provides 1-click remediation paths.

## Feature Overview & Frontend Impact

### 1. Network Privacy Score
**Frontend Meaning:** A prominent "Privacy Score" (A-F or 0-100) widget on the main dashboard. Shows factors affecting the score (e.g., "Unencrypted DNS in use (-10)", "Open FTP port on router (-15)"). 

### 2. Device Threat Profiling (R.O.B.E.R.T. Integration)
**Frontend Meaning:** Device cards in the UI gain threat badges. Instead of just showing a MAC and IP, a device might display a red "Compromised: Botnet C2" badge or an orange "Heavy Tracker" badge, based on its traffic patterns or port signatures matched against Windscribe data.

### 3. Hostile Network Alerts
**Frontend Meaning:** A high-priority banner/alert when joining a new network. Warns the user of active MITM attacks, captive portals, or DNS spoofing, using Windscribe's connectivity checks.

### 4. Seamless Remediation
**Frontend Meaning:** Action buttons attached to insights. e.g., Next to the "Unencrypted DNS" warning, a button to *"Configure Control D Secure DNS"*. Next to a compromised device, *"View Isolation Guide"*.

---

## Backend Specifications

### 1. Intelligence API Client (`app/services/windscribe_intel.py`)
- **Purpose:** Communicate with Windscribe/Control D APIs to pull threat feeds, IP reputation data, and network telemetry.
- **Data Caching:** To avoid excessive API calls, R.O.B.E.R.T. signatures and IP reputation blocklists should be cached locally (e.g., SQLite or Redis) and refreshed periodically.

### 2. Privacy Scoring Engine (`app/services/privacy_score.py`)
- **Purpose:** Aggregates discovery data (from `nmap`/`scapy`) and runs it against the intelligence ruleset.
- **Ruleset Examples:**
  - `dns_hijacked`: True/False (tests if public DNS like 1.1.1.1 is being rerouted).
  - `risky_ports_exposed`: Checks if discovered router/gateway has Telnet (23), FTP (21), or UPnP exposed.
  - `captive_portal_detected`: Hits a known Windscribe `/generate_204` endpoint to check for interception.

### 3. API Endpoints for Frontend
- `GET /api/v1/network/privacy-score`
  - Returns the aggregated score, list of deductions/issues, and recommended actions.
- `GET /api/v1/network/threat-alerts`
  - Returns active hostile network states (captive portals, MITM).
- `GET /api/v1/devices/{id}/threat-profile`
  - Returns specific threat tags (e.g., `["malware_c2", "ad_tracker"]`) for a given device based on local activity matched against Windscribe lists.

---

## Frontend Specifications

### 1. Dashboard Enhancements
- **Privacy Score Widget:**
  - Circular progress or letter-grade UI component.
  - Expandable list showing exact deductions (e.g., "Router has UPnP enabled").
  - Remediation CTA buttons linked to deductions.
- **Hostile Network Banner:**
  - Sticky banner at the top of the dashboard.
  - States: `SAFE`, `WARNING` (Captive Portal), `CRITICAL` (DNS Hijacked/MITM).

### 2. Device List & Details View (`DeviceCard` / `DeviceDetails`)
- **Threat Badges:**
  - Small, color-coded pills (Red: Danger, Orange: Warning, Blue: Privacy).
  - Hover states explaining the threat (e.g., "Device is communicating with a known malware domain").
- **Device Isolation UI:**
  - If a device is flagged as critical, a "Take Action" panel appears in the device details, offering instructions on how to block the device at the router level.

### 3. Data Polling & Real-time Updates
- The frontend will poll the `/api/v1/network/privacy-score` and `/threat-alerts` endpoints (or subscribe via WebSocket) to update the UI dynamically as discovery sweeps complete or as network conditions change.

---

## Deprecations

To simplify the application and focus on actionable privacy and threat insights, the following existing features and their associated codebase (frontend pages and backend logic) are being deprecated in this design:
- **Racks Page**
- **Status Page**
- **Webhooks Page**

---

## Phased Implementation Plan

1. **Phase 1: Foundation & Hostile Network Detection**
   - Backend: Windscribe `generate_204` connectivity checks and DNS spoofing detection.
   - Frontend: Hostile Network Banner implementation.
2. **Phase 2: Privacy Scoring Engine**
   - Backend: Ruleset engine parsing nmap results for risky ports/UPnP.
   - Frontend: Dashboard Privacy Score Widget.
3. **Phase 3: R.O.B.E.R.T. Threat Profiling**
   - Backend: Integration with Windscribe threat feeds and device profiling.
   - Frontend: Device threat badges and remediation UI.
