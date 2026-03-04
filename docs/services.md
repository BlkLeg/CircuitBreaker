# Services

Services are the apps and workloads your users rely on every day.

Examples include media servers, automation tools, databases, dashboards, and internal platforms.

---

## Adding a Service

1. Open **Services**.
2. Select **Add Service**.
3. Enter service details.
4. Save.

Useful fields to fill first:

- **Name**
- **Category** (existing or new)
- **Environment** (existing or new)
- **URL and port**
- **IP address**

---

## Linking Dependencies

Link dependencies to make the topology map truly useful:

1. **Host compute** where the service runs
2. **Dependent services** such as databases or internal APIs
3. **Storage** used by this service
4. **Networks** the service belongs to

These links power impact analysis and change planning.

---

## IP & Port Conflict Detection

Circuit Breaker warns about conflicts while you edit:

- **IP conflict warning** when an address is already in use
- **Port conflict warning** when a port overlaps on the same compute context

Warnings include direct links so you can open the conflicting item quickly.

---

## Related Guides

- [Compute](compute.md)
- [Networks](networks.md)
- [Storage](storage.md)
- [Topology Map](topology-map.md)
