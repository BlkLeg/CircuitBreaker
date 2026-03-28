# External / Cloud Nodes

External Nodes let you document infrastructure that lives outside your homelab — cloud VMs, managed databases, SaaS dependencies, CDN origins, VPN gateways, and similar resources.

They appear on the Topology Map alongside your local hardware and can be linked to local networks and services so you can see cross-boundary dependencies.

---

## Adding an External Node

1. Open **External / Cloud Nodes**.
2. Click **+ Add External Node**.
3. Fill in the details (see fields below).
4. Save.

### Fields

| Field | Description |
|---|---|
| **Name** | Descriptive label for the resource |
| **Icon** | Optional icon from the built-in catalog |
| **Provider** | Cloud or hosting provider (AWS, Azure, GCP, Hetzner, DigitalOcean, etc.) |
| **Kind** | Resource type — `vps`, `managed_db`, `saas`, `vpn_gateway`, `cdn`, `dns`, `object_storage`, `serverless`, `container_registry`, `load_balancer`, `other` |
| **Region** | Provider region or data-center label |
| **IP Address / Hostname** | Reachable address for the resource |
| **Environment** | `prod`, `staging`, `dev`, etc. |
| **Notes** | Free-form operational notes |
| **Tags** | Comma-separated tags for filtering and grouping |

---

## Filtering

The filter bar supports:

- **Search** — fuzzy match on name
- **Tags** — filter by tag
- **Provider** — filter by cloud provider
- **Kind** — filter by resource type
- **Environment** — filter by environment

---

## Linking to Local Networks

You can connect an external node to local networks (for example, the VPN tunnel subnet or a peered VPC).

1. Open the detail drawer for an external node (click any row).
2. In the **Connected Networks** section, click **+ Link Network**.
3. Select the network and choose a link type (`vpn`, `wan`, `wireguard`, `reverse_proxy`, `direct`, `other`).
4. Save.

To remove a link, click the **×** button next to the network entry.

---

## Dependent Services

The detail drawer also shows which local services depend on this external node.

Service dependencies are created from the Services page when you link a service to an external node.

---

## Topology Map

External nodes appear on the Topology Map under **External / Cloud Nodes** in the node type filters. They connect to services and networks with visible edges, letting you trace the path from a local service out to an external dependency.

---

## Related Guides

- [Services](services.md) — link services to external nodes
- [Networks (via IPAM)](ipam.md) — manage local network prefixes
- [Topology Map](topology-map.md)
