from datetime import UTC, datetime

from app.schemas.cve import AssessmentIdentity, AssessmentResult
from app.services.intelligence.fleet_cache import (
    CACHE_MAX_ENTRIES,
    cached_outcome,
    clear_identity_cache,
    identity_cache_key,
    remember_outcome,
)


def _result():
    return AssessmentResult(
        state="completed",
        reason_code="completed",
        identity=AssessmentIdentity(
            vendor="acme",
            product="widget",
            version="1.9",
            version_scheme="dotted_numeric",
            provenance="inventory",
            revision=0,
        ),
        identity_revision=0,
        feed_generation="gen-1",
        feed_age_seconds=60,
        assessed_at=datetime.now(UTC),
        findings=[],
        total=0,
        completeness="complete",
        limitations=[],
    )


def test_an_outcome_is_returned_for_the_same_generation_and_identity():
    clear_identity_cache()
    key = identity_cache_key("gen-1", "ready", ("acme", "widget", "1.9", "dotted_numeric"))
    remember_outcome(key, _result())

    assert cached_outcome(key) is not None


def test_a_new_feed_generation_does_not_serve_the_old_outcome():
    clear_identity_cache()
    identity = ("acme", "widget", "1.9", "dotted_numeric")
    remember_outcome(identity_cache_key("gen-1", "ready", identity), _result())

    assert cached_outcome(identity_cache_key("gen-2", "ready", identity)) is None


def test_a_generation_that_has_gone_stale_does_not_serve_its_ready_outcome():
    clear_identity_cache()
    identity = ("acme", "widget", "1.9", "dotted_numeric")
    remember_outcome(identity_cache_key("gen-1", "ready", identity), _result())

    assert cached_outcome(identity_cache_key("gen-1", "stale", identity)) is None


def test_the_cache_is_bounded_and_evicts_the_oldest_entry():
    clear_identity_cache()
    for index in range(CACHE_MAX_ENTRIES + 1):
        remember_outcome(
            identity_cache_key(
                "gen-1", "ready", ("acme", f"widget{index}", "1.9", "dotted_numeric")
            ),
            _result(),
        )

    first = identity_cache_key("gen-1", "ready", ("acme", "widget0", "1.9", "dotted_numeric"))
    newest = identity_cache_key(
        "gen-1", "ready", ("acme", f"widget{CACHE_MAX_ENTRIES}", "1.9", "dotted_numeric")
    )

    assert cached_outcome(first) is None
    assert cached_outcome(newest) is not None
