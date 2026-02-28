# Networks

Networks document the logical segmentation of your lab environment. This is primarily for recording VLANs, specific subnets, or dedicated gateway devices.

## Documenting Networks

To add a new network:

1. Navigate to **Networks** using the sidebar.
2. Click **Add Network**.
3. Fill in the details:
   - **Name**: A friendly name (e.g., `IoT VLAN`, `Trusted LAN`, `DMZ`).
   - **Subnet/VLAN ID**: Enter the specific IP range or VLAN ID (e.g., `192.168.10.0/24 (VLAN 10)`).
   - **Gateway/Role**: Briefly describe the gateway IP or primary routing role.

## Linking Networks

Networks serve as a shared resource that Services rely on. If a Service (like a smart home controller) must exist on the `IoT VLAN` to communicate with smart devices, you should link that Service to the `IoT VLAN` network entry.

This explicitly maps which services are exposed to which parts of your network infrastructure.
