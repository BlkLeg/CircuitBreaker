# Compute

Compute units are the virtualized environments running on top of your physical hardware. In a typical lab, these are your Virtual Machines (VMs) and LXC/Docker containers.

## Adding Compute

To add a new compute instance:

1. Navigate to **Compute** using the sidebar.
2. Click **Add Compute**.
3. Fill in the details:
   - **Name**: The hostname or recognizable name (e.g., `docker-host-01`, `pihole-lxc`).
   - **Type**: Select whether this is a `VM` or a `Container/LXC`.
   - **Host**: **(Crucial)** Select the physical Hardware node that runs this compute instance.
   - **Resources**: A brief note on allocated resources (e.g., `4 vCPU, 8GB RAM`).
   - **Purpose**: A quick description of what this instance handles.

## The Role of Compute

Compute units act as the bridge between your physical Hardware and the actual Services you provide. By accurately linking Compute to Hardware, you can easily see which VMs need to be migrated or restarted if a physical host goes down for maintenance.
