# Welcome to Circuit Breaker

The **Circuit Breaker** (formerly Service Layout Mapper) is a self-hosted tool designed to help you easily document, track, and visualize your homelab or small business network topology.

Unlike automated discovery tools that can be noisy or complex, Circuit Breaker provides a focused, manual documentation approach. You define your hardware, the compute instances running on them, and the services they host—giving you an accurate "at-a-glance" map of how your infrastructure connects. Auto-discovey lovers, your time is coming in v1 of the app so don't worry!

Curious about what's coming next? Check out our [Product Roadmap](roadmap.md) to see our plans for V1 and beyond.

## Why Circuit Breaker?

- **Visualize Your Lab**: See how a single service maps down through a VM, to a physical node, and which storage or network it depends on.
- **Centralized Runbooks**: Stop losing track of how a service was configured. Attach free-form Markdown notes directly to any application, hardware, or network.
- **Understand Dependencies**: Easily identify which services will be impacted if you need to take a physical node offline for maintenance.

## Core Concepts

In Circuit Breaker, your lab is built upon these fundamental layers:

1. **Hardware**: Physical components like servers (nodes), switches, firewalls, and NAS units.
2. **Compute**: Virtualized environments that run on your Hardware, such as VMs and LXC containers.
3. **Services**: The actual applications you host (e.g., Plex, Home Assistant, databases), which run on your Compute units.
4. **Storage & Networks**: Shared resources that Services and Hardware depend on, such as storage pools, ZFS datasets, and VLANs.

To see how to begin adding these components, proceed to [Getting Started](getting-started.md).
