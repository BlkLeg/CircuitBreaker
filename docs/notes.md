# Notes & Runbooks

Circuit Breaker provides an integrated Markdown editor allowing you to attach free-form notes, runbooks, or configuration snippets to almost any entity in your lab.

## Adding Notes

To add a note to a specific item:

1. Navigate to the detail page for the Hardware, Compute, Service, Storage, or Network item.
2. Locate the **Attached Notes** section.
3. Use the integrated editor to write your markdown.

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
