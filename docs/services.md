# Services

Services represent the actual software applications running in your homelab. These are the tools you interact with daily: Plex, Home Assistant, Pi-hole, Nextcloud, or even custom databases.

## Adding a Service

To add a new service:

1. Navigate to **Services** using the sidebar.
2. Click **Add Service**.
3. Provide the basic details:
   - **Name**: The application name (e.g., `Home Assistant`).
   - **Category**: A smart typeahead — start typing to see existing categories, or type a new name and select **Create "…"** to add it immediately. Manage all categories (rename, recolor, delete) from **Settings → Categories**.
   - **Environment**: Tag the service with an environment like `prod`, `staging`, or `lab`. Same inline creation — type and select **Create "…"**. Managed from **Settings → Environments**.
   - **URL/Port**: Where the service is accessible (e.g., `http://10.0.1.50:8123`).
   - **IP Address**: The internal IP assigned to the service container or VM.

## Linking Dependencies

The true power of Circuit Breaker comes from linking a Service to its dependencies:

1. **Host Compute**: Select which **Compute** unit (VM or Container) the service is running on.
2. **Dependent Services**: Does this service require a database? Link it to the `MariaDB` service.
3. **Storage**: Does it need access to bulk data? Link it to the `Media-Share` **Storage** item.
4. **Networks**: Does it reside on a specific VLAN? Link it to the appropriate **Network**.

Once linked, these relationships form the structure of your **Topology Map**.

---

## IP & Port Conflict Detection

Circuit Breaker catches address conflicts in real time as you type — before you hit Save.

- **IP address conflicts**: If the IP you enter is already assigned to another service or device, an inline warning appears immediately. It names the entity that holds the conflict and provides a direct link to open it.
- **Port conflicts**: The same check applies to ports. If a port is already bound by another service on the same compute unit, you'll see the conflict and a link to the conflicting service.

Conflict warnings are advisory — you can still save if you intentionally want duplicate values — but the warning will persist until the conflict is resolved.
