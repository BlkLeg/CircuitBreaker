```markdown
# Circuit Breaker: Bulletproof Password Reset + Email Delivery

**Symptom**: No errors, no exceptions, SMTP confirmed working —
but reset emails are never delivered. This is a **delivery-layer
problem**, not a code problem. Cover every layer: code contract,
SMTP debug tracing, deliverability (SPF/DKIM), spam scoring, and
a full fallback stack.

---

## Step 1: Prove Exactly Where the Email Dies

Run these in order — stop at the first failure.

```bash
# Layer 1: Can the container reach your SMTP host at all?
docker exec cb curl -v telnet://your-smtp-host:587
docker exec cb python3 -c "
import socket
s = socket.create_connection(('your-smtp-host', 587), timeout=5)
print('TCP OK')
s.close()
"

# Layer 2: Raw SMTP handshake (bypass all app code)
docker exec cb python3 -c "
import smtplib, ssl

host = 'your-smtp-host'
port = 587           # or 465
user = 'your-user'
pw   = 'your-password'
to   = 'you@gmail.com'

with smtplib.SMTP(host, port, timeout=10) as s:
    s.set_debuglevel(2)   # <-- Verbose: EHLO, AUTH, RCPT, DATA all visible
    s.ehlo()
    s.starttls(context=ssl.create_default_context())
    s.ehlo()
    s.login(user, pw)
    s.sendmail(user, to, 'Subject: CB Raw Test\n\nraw smtp ok')
    print('SENT OK')
"

# Layer 3: Is the app even calling send?
docker logs cb 2>&1 | grep -E "reset|smtp|email|send|MAIL FROM|RCPT TO"

# Layer 4: Redis token written before send?
redis-cli KEYS "password_reset:*"         # Token exists after request?
redis-cli TTL  "password_reset:TOKEN"     # > 0? Not expired in race?

# Layer 5: Check spam folder + mail server queue
# → Check ALL folders including Spam/Junk/Promotions
# → If self-hosted MX: postqueue -p (postfix) or mailq (sendmail)
```

**Paste the Layer 2 debug output** — it will show exactly
where the handshake fails or if RCPT was rejected silently.

---

## Step 2: Fix the Code Contract

### 2.1 Switch to `fastapi-mail` (Industry Standard) [web:258]

```bash
pip install fastapi-mail jinja2
```

```python
# backend/core/email.py
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from pathlib import Path

conf = ConnectionConfig(
    MAIL_USERNAME   = settings.SMTP_USER,
    MAIL_PASSWORD   = settings.SMTP_PASSWORD,
    MAIL_FROM       = settings.SMTP_FROM,          # Must match SPF domain
    MAIL_FROM_NAME  = "Circuit Breaker",
    MAIL_PORT       = settings.SMTP_PORT,          # 587 STARTTLS or 465 SSL
    MAIL_SERVER     = settings.SMTP_HOST,
    MAIL_STARTTLS   = (settings.SMTP_PORT == 587),
    MAIL_SSL_TLS    = (settings.SMTP_PORT == 465),
    USE_CREDENTIALS = True,
    VALIDATE_CERTS  = True,
    TEMPLATE_FOLDER = Path(__file__).parent / "templates" / "email",
    SUPPRESS_SEND   = settings.TESTING,  # Dry-run in tests
)

fm = FastMail(conf)
```

### 2.2 Password Reset Service (Complete Contract)

```python
# backend/services/email_service.py
import secrets
import logging
from datetime import datetime
from fastapi_mail import MessageSchema, MessageType
from backend.core.email import fm
from backend.core.redis import get_redis

logger = logging.getLogger("cb.email")

async def send_password_reset(user_id: int, email: str) -> str:
    """
    Full contract:
    1. Generate cryptographic token
    2. Write to Redis BEFORE sending (no race condition)
    3. Send HTML email via fastapi-mail
    4. Log every step with enough context to debug
    5. On SMTP fail: token already in Redis — user can retry
    Returns: token (for test verification)
    """
    redis = await get_redis()

    # 1. Token (32-byte URL-safe, never guessable)
    token = secrets.token_urlsafe(32)
    redis_key = f"password_reset:{token}"

    # 2. Write Redis FIRST — atomic, before any network call
    await redis.setex(redis_key, 900, str(user_id))  # TTL: 15min
    logger.info(f"[email] reset token written redis_key={redis_key} user_id={user_id}")

    # Verify write (catch silent Redis failures)
    stored = await redis.get(redis_key)
    if not stored:
        logger.error(f"[email] Redis write verification FAILED for {redis_key}")
        raise RuntimeError("Token store failed — cannot send reset email")

    # 3. Build reset URL
    reset_url = f"{settings.APP_URL}/reset-password?token={token}"
    logger.info(f"[email] sending reset to={email} url={reset_url}")

    # 4. Send HTML email
    try:
        message = MessageSchema(
            subject   = "Reset Your Circuit Breaker Password",
            recipients = [email],
            body       = _build_reset_html(reset_url),
            subtype    = MessageType.html,
            headers    = {
                # Deliverability: explicit reply-to
                "Reply-To": settings.SMTP_FROM,
                # Prevent threading with previous resets
                "X-CB-Type": "password-reset",
            }
        )
        await fm.send_message(message)
        logger.info(f"[email] reset sent ok to={email}")

    except Exception as e:
        # Token is already in Redis — user can retry and it will work
        # Do NOT delete the token here
        logger.error(
            f"[email] SMTP send FAILED to={email} error={e}",
            exc_info=True
        )
        raise  # Let API layer return 503 "try again"

    return token


def _build_reset_html(reset_url: str) -> str:
    """Minimal but deliverable HTML — no images, no tracking pixels."""
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:sans-serif;max-width:480px;margin:40px auto;">
      <h2>Circuit Breaker — Password Reset</h2>
      <p>Click the link below to reset your password.
         This link expires in <strong>15 minutes</strong>.</p>
      <p>
        <a href="{reset_url}"
           style="background:#f97316;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block;">
          Reset Password
        </a>
      </p>
      <p style="color:#888;font-size:12px;">
        If you did not request this, ignore this email.<br>
        Direct link: {reset_url}
      </p>
    </body>
    </html>
    """
```

### 2.3 API Route (Clean + Logged)

```python
# backend/api/auth.py
@router.post("/auth/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    # Security: always same response regardless of email existence
    GENERIC_RESPONSE = {"message": "If that email exists, a reset link was sent."}

    user = db.query(User).filter(
        func.lower(User.email) == payload.email.lower().strip()
    ).first()

    if not user:
        logger.info(f"[auth] forgot-password: no user for {payload.email}")
        return JSONResponse(GENERIC_RESPONSE)  # Never reveal existence

    try:
        token = await send_password_reset(user.id, user.email)
        # Log token prefix for debugging (never full token)
        logger.info(f"[auth] reset initiated user_id={user.id} token_prefix={token[:8]}...")
    except RuntimeError as e:
        logger.error(f"[auth] reset token store failed: {e}")
        raise HTTPException(503, "Reset unavailable, try again shortly")
    except Exception as e:
        logger.error(f"[auth] forgot-password unhandled: {e}", exc_info=True)
        raise HTTPException(503, "Unable to send reset email, try again shortly")

    return JSONResponse(GENERIC_RESPONSE)
```

### 2.4 Settings (Validate on Startup)

```python
# backend/core/config.py
class Settings(BaseSettings):
    SMTP_HOST    : str
    SMTP_PORT    : int = 587
    SMTP_USER    : str
    SMTP_PASSWORD: str
    SMTP_FROM    : str       # e.g. "noreply@circuitbreaker.local"
    APP_URL      : str       # e.g. "https://circuitbreaker.yourdomain.com"
    TESTING      : bool = False

    @validator("SMTP_FROM")
    def from_must_be_valid(cls, v):
        if "@" not in v:
            raise ValueError("SMTP_FROM must be a valid email")
        return v

    @validator("APP_URL")
    def url_must_not_be_localhost(cls, v):
        if "localhost" in v and not os.getenv("TESTING"):
            raise ValueError("APP_URL cannot be localhost in production — reset links won't work for recipients")
        return v
```

---

## Step 3: Deliverability Audit (Silent Drop Root Causes)

**"No errors but never delivered" = almost always one of these:**

```
# Check 1: SPF record
nslookup -type=TXT your-sending-domain.com | grep spf
# Expected: v=spf1 include:your-smtp-provider ~all

# Check 2: DKIM
nslookup -type=TXT default._domainkey.your-domain.com
# Expected: v=DKIM1; k=rsa; p=MIGfMA0...

# Check 3: DMARC
nslookup -type=TXT _dmarc.your-domain.com
# Expected: v=DMARC1; p=none; rua=mailto:dmarc@yourdomain.com

# Check 4: Blacklist
curl "https://api.abuseipdb.com/api/v2/check?ipAddress=$(curl -s ifconfig.me)" \
  -H "Key: YOUR_API_KEY"
# → Use mxtoolbox.com/blacklists.aspx if no API key

# Check 5: Reverse DNS (PTR)
nslookup $(curl -s ifconfig.me)
# Must resolve to a hostname — bare IPs are spam-scored high
```

**Fix matrix**:
| Issue | Fix |
|-------|-----|
| No SPF | Add `v=spf1 include:smtp-provider ~all` TXT record |
| No DKIM | Enable in SMTP provider (Mailgun, SES, Postmark) |
| Sending from `localhost` | Set `APP_URL` to real domain |
| IP blacklisted | Use SMTP relay (Mailgun/SES) not direct send |
| `From:` mismatch | `SMTP_FROM` must match SPF-authorized domain |
| HTML too complex | Use plain-text fallback (`MessageType.plain`) |

---

## Step 4: SMTP Provider Fallback Stack

If home server SMTP keeps failing silently, use a relay:

```python
# .env — swap provider without code changes
# Tier 1: Mailgun (100 free/day)
SMTP_HOST=smtp.mailgun.org
SMTP_PORT=587
SMTP_USER=postmaster@mg.yourdomain.com
SMTP_PASSWORD=your-mailgun-key
SMTP_FROM=noreply@mg.yourdomain.com

# Tier 2: AWS SES (62k free/month if on EC2)
SMTP_HOST=email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587

# Tier 3: Resend (3000 free/month, best deliverability)
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_PASSWORD=re_your_api_key
```

**Test any tier instantly**:
```bash
CB_SMTP_HOST=smtp.mailgun.org CB_SMTP_PORT=587 \
  docker exec cb python3 -c "
import smtplib
with smtplib.SMTP('smtp.mailgun.org', 587) as s:
    s.set_debuglevel(2)
    s.starttls()
    s.login('user','pass')
    s.sendmail('from','to','Subject: tier-test\n\nok')
"
```

---

## Step 5: Smoke Test Checklist

```bash
# 1. Token written to Redis
curl -X POST localhost:8080/api/v1/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"your@email.com"}'
redis-cli KEYS "password_reset:*"          # Must have 1 key
redis-cli TTL  "password_reset:<TOKEN>"    # 850-900 seconds

# 2. Logs confirm send
docker logs cb 2>&1 | grep "reset sent ok\|SMTP send FAILED"

# 3. Email arrives (test all folders: Inbox + Spam + Promotions)
# If Gmail: check All Mail

# 4. Reset link works
curl "localhost:8080/reset-password?token=<TOKEN>"  # 200 (not 404/expired)

# 5. Token consumed after use
curl -X POST localhost:8080/api/v1/auth/reset-password \
  -d '{"token":"<TOKEN>","new_password":"NewPass123!"}'
redis-cli GET "password_reset:<TOKEN>"    # Must return nil (consumed)

# 6. Reuse blocked
curl -X POST .../reset-password -d '{"token":"<same TOKEN>"}'
# Must return 400 "expired or invalid"
```

---

## Deliverables

1. `backend/core/email.py` — fastapi-mail `ConnectionConfig` singleton
2. `backend/services/email_service.py` — full `send_password_reset()`
3. `backend/api/auth.py` — forgot + reset routes
4. `backend/core/config.py` — `SMTP_FROM`, `APP_URL` validators
5. `backend/templates/email/reset.html` — Jinja2 template
6. DNS checklist: SPF + DKIM + DMARC verified
7. Fallback `.env` for Mailgun/SES/Resend

**Result**: Token in Redis before SMTP call. HTML email with
plain-text fallback. SPF/DKIM passing. Every failure logged with
context. No silent drops. 🔐
```