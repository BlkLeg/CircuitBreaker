# Investigation Report: `test_forgot_password_uses_external_app_url_for_email_links` Failure

## Summary

The test fails with `KeyError: 'to_email'` because the mock `SmtpService.send_password_reset` is never called. An exception occurs earlier in `on_after_forgot_password`, which is caught and logged:

```
WARNING  app.core.users:users.py:198 Failed to send password reset email to test@example.com: 'types.SimpleNamespace' object has no attribute 'headers'
```

Because the exception prevents `send_password_reset` from being invoked, the `captured` dict remains empty, and `assert captured["to_email"] == DEFAULT_TEST_EMAIL` raises `KeyError: 'to_email'`.

---

## 1. Test Code and Expectations

**Location:** `tests/integration/test_auth.py` lines 349–382

**What the test does:**
1. Registers a user via `_register(client)`
2. Configures SMTP in settings (`smtp_enabled`, `smtp_from_email`, `api_base_url`)
3. Monkeypatches `SmtpService.send_password_reset` with `_capture_send_password_reset`, which stores `to_email`, `token`, and `base_url` in a `captured` dict
4. Creates a mock `request` as `SimpleNamespace(base_url="http://internal.local/", client=None)` — **no `headers` attribute**
5. Calls `manager.on_after_forgot_password(user, "reset-token", request)`
6. Asserts `captured["to_email"] == DEFAULT_TEST_EMAIL` and `captured["base_url"] == "https://circuitbreaker.example.com"`

**Intent:** Verify that when `api_base_url` is set, the password-reset email uses that external URL instead of the request’s internal `base_url`.

---

## 2. Production Code Path for Forgot-Password Email

**Location:** `apps/backend/src/app/core/users.py` lines 163–204

Flow:

1. `on_after_forgot_password` opens a DB session and loads settings via `get_or_create_settings(db)`.
2. If `cfg.smtp_enabled` and `cfg.smtp_from_email`:
   - If `request` is present:
     - `request_headers = getattr(request, "headers", None)`
     - `request_base_url = str(getattr(request, "base_url", "")).rstrip("/")`
     - `header_fallback = public_base_from_request_headers(request_headers, request_base_url)` **only when** `request_headers is not None`, else `request_base_url`
   - Else: `header_fallback = ""`
3. `base_url = resolve_public_base_url(cfg, header_fallback)` — prefers `cfg.api_base_url` when set
4. `await SmtpService(cfg).send_password_reset(user.email, token, base_url)`

`users.py` uses `getattr(request, "headers", None)`, so it does not directly access `request.headers`. The failure suggests some other code path or dependency is accessing `request.headers` on the mock `SimpleNamespace`, which has no `headers` attribute.

---

## 3. Why `to_email` Is Missing

`to_email` is missing because `send_password_reset` is never called. An exception occurs earlier in the try block, is caught at line 197, and logged. The mock `_capture_send_password_reset` is therefore never invoked, so `captured` stays empty and `captured["to_email"]` raises `KeyError`.

---

## 4. Root Cause: Mock Request Missing `headers`

The mock request is:

```python
request = SimpleNamespace(base_url="http://internal.local/", client=None)
```

It has no `headers` attribute. Some code in the forgot-password flow (or a dependency) expects a request-like object with `headers` and accesses it directly (e.g. `request.headers`), which raises:

```
'types.SimpleNamespace' object has no attribute 'headers'
```

Possible sources:

- A different code path that uses `request.headers` directly
- A dependency or helper that assumes a Starlette `Request`-like object
- A change in fastapi-users or related libraries that now expects `request.headers`

Regardless of the exact call site, the mock request must provide a `headers` attribute to avoid this error.

---

## 5. Recommended Fix

Add a `headers` attribute to the mock request so it behaves like a minimal request object. An empty dict is enough for the current logic:

```python
request = SimpleNamespace(
    base_url="http://internal.local/",
    client=None,
    headers={},  # Provide headers so code expecting request.headers does not raise
)
```

With `headers={}`:

- `getattr(request, "headers", None)` returns `{}` (truthy)
- `public_base_from_request_headers({}, request_base_url)` is called; `{}.get(...)` returns `""`, so it falls back to `request_base_url`
- `resolve_public_base_url(cfg, header_fallback)` still prefers `cfg.api_base_url` when set
- `send_password_reset` is called with the correct `base_url`
- The mock populates `captured`, and the assertions pass

---

## 6. Code Snippet for the Fix

**File:** `tests/integration/test_auth.py`

**Change:** Update line 378 from:

```python
request = SimpleNamespace(base_url="http://internal.local/", client=None)
```

to:

```python
request = SimpleNamespace(
    base_url="http://internal.local/",
    client=None,
    headers={},
)
```

This keeps the test’s intent (internal vs external URL) while making the mock request compatible with any code that expects `request.headers`.
