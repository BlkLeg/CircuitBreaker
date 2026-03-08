# Getting Started

This guide will walk you through the basic workflow for documenting your infrastructure in Circuit Breaker.

## First Launch

On first launch, Circuit Breaker runs a short setup wizard. You'll be asked to:

- Create your first admin account (local email/password **or OAuth/OIDC sign-up**)
- **Choose your timezone** — all timestamps across the app (logs, telemetry readings, entity records) display in your local time. You can change this anytime from **Settings → General**.
- Optionally configure SMTP and your external URL for password reset/invite links
- Back up your vault key during the final setup step if shown

---

## The Basic Workflow

Documentation in Circuit Breaker works best when you build from the "ground up." We recommend the following sequence when adding a new service or mapping out your lab for the first time:

1. **Add the Physical Hardware**
   First, document the physical host where the service will live. (See [Hardware](hardware.md))

2. **Add the Compute Instance**
   Next, document the VM or Container that runs on that physical hardware. (See [Compute](compute.md))

3. **Add Shared Resources (Optional)**
   If your service depends on a specific VLAN or a shared network drive, document those resources. (See [Storage](storage.md) or [Networks](networks.md))

4. **Add the Service**
   Finally, add the service itself and link it to the Compute instance and any shared resources. (See [Services](services.md))

5. **Attach Documentation**
   Add any installation notes, update procedures, or runbooks to the service using the built-in Markdown editor. (See [Notes & Runbooks](notes.md))

> **Tip:** Category and environment fields throughout the app support inline creation — type a new name and select **Create "…"** to add it on the spot, without leaving the form.

## Navigation Overview

The Circuit Breaker interface is divided into two main areas:

- **The Map View**: A live, interactive topology map showing how all your documented components connect. Once your lab is set up, this is your primary dashboard.
- **The Sidebar**: Quick access to lists for Hardware, Compute, Services, Storage, and Networks. From here, you can add new items or search for existing ones.

## Example: Documenting Nextcloud

If you were setting up Nextcloud running in a Docker container on a Proxmox VM, your workflow would be:

1. Create a **Hardware** node named `pve-node-01`.
2. Create a **Compute** VM named `docker-host-01` and set its host to `pve-node-01`.
3. Create a **Service** named `Nextcloud` and set its host to `docker-host-01`.
4. (Optional) Create a **Storage** pool named `nas-share` and link `Nextcloud` to it.

Once completed, the [Topology Map](topology-map.md) will visually connect these four elements.
