# Approved map design references

Date: 2026-09-29. Status: approved visual references; application implementation pending.

The [design record](../../2026-09-29-map-console-and-connection-walkthrough.md)
defines scope and behavior. These artifacts freeze its visual references without
relying on mutable remote draft previews.

| Artifact | Approved source |
| --- | --- |
| [Console HTML](map-console-v5.html) and [screenshot](map-console-v5.png) | Draft `d065afe9-56b1-4c40-b88e-ecb6dd755281`, version 5. |
| [Walkthrough HTML](connection-walkthrough-v7.html) | Draft `c8e6462a-4db9-44f4-86eb-042aa156bd05`, version 7. |
| [Editor screenshot](walkthrough-editor-v7.png) | Walkthrough's default desktop editor. |
| [Review screenshot](walkthrough-review-v7.png) | Walkthrough after staging an additional relationship, endpoint uplink changes and an acknowledged ownership reassignment. |

HTML is design scaffolding, not application source. It references the hosted
shared header component, uploaded map screenshot, Tailwind and Iconify resources;
it is not a self-contained offline export. Screenshots are the portable visual
reference. The native-map preview uses screenshot imagery; telemetry and entities
are illustrative, and the walkthrough performs no backend writes.
