# IPAM

IPAM (IP Address Management) is the unified network management center in Circuit Breaker.

It consolidates everything subnet-related into one place: network prefixes, individual IP addresses, VLANs, and logical sites.

> **Note:** The old standalone Networks page (`/networks`) now redirects here. All network management is done through IPAM.

---

## Navigating IPAM

Open **IPAM** from the navigation dock. The page has four tabs:

| Tab | What it manages |
|---|---|
| **Networks** | IP prefixes, subnets, and gateways |
| **IP Addresses** | Individual host addresses within your prefixes |
| **VLANs** | VLAN IDs, names, and descriptions |
| **Sites** | Logical groupings such as data center, lab room, or off-site |

---

## Networks Tab

The Networks tab replaces the old standalone Networks page.

### Adding a network

1. Open **IPAM → Networks**.
2. Click **Add Network**.
3. Enter a name, CIDR (e.g. `192.168.1.0/24`), gateway, and optional site.
4. Save.

### Fields

| Field | Description |
|---|---|
| Name | Human-readable label (e.g. `Trusted LAN`, `IoT VLAN`, `DMZ`) |
| CIDR | Subnet in CIDR notation (e.g. `10.0.0.0/24`) |
| Gateway | Default gateway address for the subnet |
| VLAN | Optional VLAN ID to associate this prefix |
| Site | Optional site this network belongs to |
| Notes | Free-form notes |

### Scanning a network

From a network row you can trigger a discovery scan of the entire subnet. Results appear in the **IP Addresses** tab filtered to that network.

---

## IP Addresses Tab

Tracks individual host addresses within your prefixes.

### Adding an IP address

1. Open **IPAM → IP Addresses**.
2. Click **Add IP**.
3. Enter the address, choose the parent network, and optionally link it to a hardware or service entity.
4. Save.

### Filter chips

| Chip | Shows |
|---|---|
| **All** | Every tracked address |
| **Manual** | Addresses you entered by hand |
| **Discovered** | Addresses pulled in via network discovery scans |

Use the **Network** dropdown to scope the list to a single prefix.

### Conflict detection

Adding an address that already exists in the same network returns a clear error rather than silently creating a duplicate.

---

## VLANs Tab

Manage VLAN IDs alongside your network definitions.

### Adding a VLAN

1. Open **IPAM → VLANs**.
2. Click **Add VLAN**.
3. Enter the VLAN ID, name, and an optional description.
4. Save.

VLANs can be associated with networks from the Networks tab to cross-link the two views.

---

## Sites Tab

Sites are logical location labels that group networks and hardware for documentation and discovery scoping.

Examples: `Main Rack`, `Server Room`, `Off-Site Backup`, `Parents' House`.

### Adding a site

1. Open **IPAM → Sites**.
2. Click **Add Site**.
3. Enter a name and optional description.
4. Save.

Once a site exists, you can assign it to networks and hardware entries to indicate physical location.

---

## Related Guides

- [Discovery](discovery.md) — scan subnets and populate IP address records automatically
- [Hardware](hardware.md) — link hardware entities to IP addresses and sites
- [Networks (legacy)](networks.md) — the old networks documentation
- [Topology Map](topology-map.md)
