# Notifications

Circuit Breaker can route in-app notification sinks for alerting on events.

## Notifications

Notification sinks let you define where alerts should go and how they are grouped.

Typical workflow:

1. Open **Notifications** (admin navigation), or **Settings → Integrations → Notifications**.
2. Create sink destinations.
3. Add routes to control which severities each sink receives.
4. Test and validate delivery.

### Sink types

Each sink has a Name, a Provider Type, and one destination field.

| Provider Type | Required field | What the destination receives |
| --- | --- | --- |
| **Slack** | Webhook URL | A JSON POST of the form `{"text": "…"}` |
| **Discord** | Webhook URL | A JSON POST of the form `{"content": "…"}` |
| **Microsoft Teams** | Webhook URL | A JSON POST of a MessageCard (`"@type": "MessageCard"`) |
| **Email** | Recipient Email | An email sent through your configured SMTP settings |

### Routes

Routes connect a sink to a severity: `info`, `warning`, `critical`, or `*` for all of them. A sink with no
route receives nothing.

## Troubleshooting

- Verify the destination URL (or recipient address) on the sink.
- Confirm a route exists for the severity you expect, and that both sink and route are enabled.
- Use the sink's **Test** action and read the error it returns — this is the only delivery diagnostic; there
  is no delivery log or history view.
- For Email sinks, check the SMTP settings, since the sink sends through them.
- If behind a proxy, ensure outbound network access to target endpoints.

## Related

- [Settings](settings.md)
- [Audit Log](audit-log.md)
- [Deployment & Security](deployment-security.md)
