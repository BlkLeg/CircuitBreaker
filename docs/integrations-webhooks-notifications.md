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

### Email sinks

An email sink holds the recipient address and nothing else. The server, port, credentials, TLS mode,
and sender address all come from **Settings → SMTP** — the same configuration used for invites — so
there is no per-sink SMTP setup and no per-sink credential to manage.

This means an email sink cannot deliver until SMTP is configured. The sink form says so when it is
not, and both **Test** and real delivery return *"SMTP is not configured"* rather than a connection
error.

### Webhook URL storage

An incoming-webhook URL is a credential: anyone holding it can post into that channel. Circuit Breaker
encrypts webhook URLs with the vault key before storing them, and the sinks list shows only a masked
preview — enough to tell two destinations apart, never enough to use one.

When editing a sink, leave the masked value as it is to keep the current URL; replace it outright to
point the sink somewhere new. Rotating the vault key (**Settings → Security**) re-encrypts stored
webhook URLs along with every other secret.

### Routes

Routes connect a sink to a severity: `info`, `warning`, `critical`, or `*` for all of them. A sink with no
route receives nothing.

## Troubleshooting

- Verify the destination URL (or recipient address) on the sink.
- Confirm a route exists for the severity you expect, and that both sink and route are enabled.
- Use the sink's **Test** action and read the error it returns — this is the only delivery diagnostic; there
  is no delivery log or history view. **Test** sends down the same path as a real alert, so a green
  test means delivery works.
- For Email sinks, check **Settings → SMTP**, since the sink sends through it.
- If a sink starts failing right after a vault key change, re-save its webhook URL — the stored
  ciphertext can no longer be decrypted with the current key.
- If behind a proxy, ensure outbound network access to target endpoints.

## Related

- [Settings](settings.md)
- [Audit Log](audit-log.md)
- [Deployment & Security](deployment-security.md)
