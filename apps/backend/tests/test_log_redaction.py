import logging

from app.core.log_redaction import LogRedactionFilter, sanitize_log_text


def test_sanitize_log_text_redacts_bearer_and_token_pairs():
    message = "Authorization: Bearer abc.def.ghi token=super-secret-value"
    sanitized = sanitize_log_text(message)
    assert "abc.def.ghi" not in sanitized
    assert "super-secret-value" not in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_log_text_redacts_url_credentials():
    message = "dispatching to https://user:pa55word@example.internal:9443/hook?token=abc"
    sanitized = sanitize_log_text(message)
    assert "pa55word" not in sanitized
    assert "user:[REDACTED]@" in sanitized


def test_log_redaction_filter_rewrites_log_record(caplog):
    logger = logging.getLogger("cb.test.log_redaction")
    logger.handlers = []
    logger.propagate = True
    logger.setLevel(logging.INFO)
    logger.addFilter(LogRedactionFilter())

    with caplog.at_level(logging.INFO, logger="cb.test.log_redaction"):
        logger.info("password=%s", "my-secret-password")

    assert caplog.records
    rendered = caplog.records[-1].getMessage()
    assert "my-secret-password" not in rendered
    assert "[REDACTED]" in rendered
