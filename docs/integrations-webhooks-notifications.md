# Notifications

Circuit Breaker can route in-app notification sinks for alerting on events.

## Notifications

Notification sinks let you define where alerts should go and how they are grouped.

Typical workflow:

1. Open **Settings → Notifications**.
2. Create sink destinations.
3. Add routing rules/event filters.
4. Test and validate delivery.

## Troubleshooting

- Verify destination URL and credentials/headers.
- Confirm the event type is enabled for that destination.
- Check delivery logs/history for HTTP status and error messages.
- If behind a proxy, ensure outbound network access to target endpoints.

## Related

- [Settings](settings.md)
- [Audit Log](audit-log.md)
- [Deployment & Security](deployment-security.md)
