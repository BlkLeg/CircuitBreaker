# Services

Services represent the actual software applications running in your homelab. These are the tools you interact with daily: Plex, Home Assistant, Pi-hole, Nextcloud, or even custom databases.

## Adding a Service

To add a new service:

1. Navigate to **Services** using the sidebar.
2. Click **Add Service**.
3. Provide the basic details:
   - **Name**: The application name (e.g., `Home Assistant`).
   - **Category**: A helpful grouping for the map (e.g., `Smart Home`, `Media`, `Infrastructure`).
   - **URL/Port**: Where the service is accessible (e.g., `http://10.0.1.50:8123`).
   - **IP Address**: The internal IP assigned to the service container or VM.

## Linking Dependencies

The true power of Circuit Breaker comes from linking a Service to its dependencies:

1. **Host Compute**: Select which **Compute** unit (VM or Container) the service is running on.
2. **Dependent Services**: Does this service require a database? Link it to the `MariaDB` service.
3. **Storage**: Does it need access to bulk data? Link it to the `Media-Share` **Storage** item.
4. **Networks**: Does it reside on a specific VLAN? Link it to the appropriate **Network**.

Once linked, these relationships form the structure of your **Topology Map**.
