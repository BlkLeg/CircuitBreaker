# Notes & Runbooks

Use Notes & Runbooks to keep operational knowledge next to your infrastructure.

You can write Markdown docs, organize them, and link them directly to assets.

---

## Create a Document

1. Open **Notes & Runbooks**.
2. Select **New Doc**.
3. Add a title and content.
4. Save.

You can also open an entity and attach documents from that entity view.

---

## Organize Documents

You can:

- Pin important docs to the top
- Group docs by category
- Search docs quickly
- Duplicate docs for templates

---

## Link Docs to Infrastructure

Each document can be linked to one or more entities.

This helps with:

- Service runbooks
- Hardware maintenance procedures
- Network change plans
- Recovery instructions

Linked entities are visible in the document side panel.

---

## Import and Export

### Export options

- Export a single doc as Markdown (`.md`)
- Export all docs as a ZIP archive

### Import options

- Import one Markdown file
- Import a ZIP of docs

---

## Reading Experience

While viewing a doc, you get:

- Markdown rendering
- Heading outline for quick jump navigation
- Linked-entity context

---

## Use Cases for Notes

- **Runbooks**: Document the exact CLI commands required to restart a stubborn service or gracefully shut down a Proxmox cluster.
- **Configuration Details**: Paste complex `docker-compose.yml` snippets or Nginx reverse proxy configs so they are immediately accessible alongside the visual representation of the service.
- **External Links**: If you already maintain a wiki (like BookStack or Obsidian), use the Markdown editor to create simple hyper-links directly to your external documentation.

_Example Note:_

```markdown
### Update Procedure for Nextcloud

1. Exec into container: `docker exec -it nextcloud bash`
2. Run updater: `sudo -u www-data php updater/updater.phar`
3. Verify at `https://nextcloud.local`
```

By keeping these notes tied directly to the entity, you ensure that "future you" always knows exactly how to manage a system during an outage.

---

## Related Guides

- [Services](services.md)
- [Hardware](hardware.md)
- [Topology Map](topology-map.md)
