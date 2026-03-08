# Webhooks & Notifications

Circuit Breaker can emit events to external systems and route in-app notification sinks.

## Webhooks

Use webhooks to push selected events to tools like Slack, Discord, or custom endpoints.

Typical workflow:

1. Open **Settings → Webhooks**.
2. Create a webhook target (label + URL + optional headers).
3. Enable event groups for that target.
4. Run **Test webhook**.
5. Check recent deliveries/status for failures or retries.

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
