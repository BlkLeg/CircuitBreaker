# apps/backend/tests/services/test_telemetry_ingest_stream_update.py
"""R12: the TELEMETRY retrofit must not re-default the fields it is not changing.

B15 taught `_ensure_stream` to reach back and bound a stream an older build created
limitless.  It did that by sending `update_stream(**{**cfg, "retention": ...})`, where
`cfg` is only the handful of keys this build cares about.  That is not a patch — it is a
whole `StreamConfig` with every other field left at its `None` default, and
`nats.js.api.Base.as_dict()` *drops* `None` fields from the JSON entirely.  The server
does not read a missing field as "leave it alone"; it reads it as zero and applies its
own default, so `num_replicas` comes back 1 and `storage` is re-derived.  On a clustered
NATS the first worker boot after an upgrade silently demotes an R3 telemetry stream to
R1 — no error, no log line, and the redundancy is gone until somebody runs
`nats stream info` and notices.

These tests therefore assert on the *wire payload*: the fake below reproduces
`JetStreamManager.update_stream` exactly (evolve the params onto a `StreamConfig`, then
`as_dict()`), because the `None`-dropping is the whole defect and a fake that merely
records kwargs cannot see it.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

from nats.js.api import DiscardPolicy, RetentionPolicy, StorageType, StreamConfig


class _RetrofitJetStream:
    """A JetStream whose TELEMETRY stream already exists, with a config of its own.

    `update_stream` mirrors nats-py's implementation rather than recording raw kwargs:
    the real client folds whatever it is given onto a `StreamConfig` and serialises that,
    and fields still `None` at that point never reach the server at all.  `wire_payloads`
    is what the STREAM.UPDATE request body would contain.

    It also mirrors the one server-side *rejection* this retrofit can trip over.  nats
    2.10 refuses the whole request when the body's `duplicate_window` exceeds its
    `max_age` (`err_code=10052`, "duplicates window can not be larger then max age") — it
    does not clamp and it does not apply the rest.  Recording the payload is therefore
    not enough to say the retrofit worked: `applied` is the config the server actually
    stored, and an empty `applied` is a stream left exactly as B15 found it, because
    `_update_stream_limits` swallows the error into a warning.
    """

    def __init__(self, stored: StreamConfig) -> None:
        self._stored = stored
        self.wire_payloads: list[dict[str, Any]] = []
        self.applied: list[dict[str, Any]] = []

    async def add_stream(self, **kwargs: Any) -> Any:
        raise Exception("nats: stream name already in use")

    async def stream_info(self, name: str) -> Any:
        return SimpleNamespace(config=self._stored)

    async def update_stream(self, config: StreamConfig | None = None, **params: Any) -> Any:
        if config is None:
            config = StreamConfig()
        config = config.evolve(**params)
        payload = config.as_dict()
        self.wire_payloads.append(payload)
        max_age = payload.get("max_age") or 0
        if max_age > 0 and (payload.get("duplicate_window") or 0) > max_age:
            raise Exception(
                "nats: ServerError: code=500 err_code=10052 "
                "description='duplicates window can not be larger then max age'"
            )
        self._stored = config
        self.applied.append(payload)
        return SimpleNamespace(config=config)


def _existing_stream() -> StreamConfig:
    """What a clustered deployment's pre-B15 TELEMETRY stream looks like on the server.

    `max_age=0.0` / `max_bytes=-1` are not padding: they are what a stream created by the
    pre-B15 code actually reports back, and they are what makes "the retrofit applies the
    limits" a real assertion.  Left unset they would arrive as `None`, be filtered out of
    the echo, and `cfg` would be the only possible source of those two keys no matter
    which way the merge ran.
    """
    return StreamConfig(
        name="TELEMETRY",
        subjects=["telemetry.ingest.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        num_replicas=3,
        discard=DiscardPolicy.NEW,
        max_msgs=1_000_000,
        max_consumers=4,
        max_age=0.0,
        max_bytes=-1,
        # nats-server stamps StreamDefaultDuplicatesWindow (120s) on a stream whose
        # creator said nothing about dedupe, which every pre-B15 TELEMETRY stream is.
        duplicate_window=120.0,
    )


def _retrofit(monkeypatch: Any, js: _RetrofitJetStream) -> None:
    from app.workers import telemetry_ingest_worker

    monkeypatch.setattr(
        telemetry_ingest_worker,
        "nats_client",
        SimpleNamespace(is_connected=True, _nc=SimpleNamespace(jetstream=lambda: js)),
    )
    asyncio.run(telemetry_ingest_worker._ensure_stream())


def test_the_telemetry_retrofit_keeps_the_streams_replica_count(monkeypatch):
    """An R3 stream must still be R3 after the limits are retrofitted onto it."""
    js = _RetrofitJetStream(_existing_stream())
    _retrofit(monkeypatch, js)

    assert len(js.wire_payloads) == 1, "the existing TELEMETRY stream was not updated"
    payload = js.wire_payloads[0]
    assert "num_replicas" in payload, (
        "num_replicas was omitted from the STREAM.UPDATE body — JetStream reads that as "
        "0 and re-defaults it to 1, silently demoting an R3 stream"
    )
    assert payload["num_replicas"] == 3


def test_the_telemetry_retrofit_keeps_the_streams_storage_backend(monkeypatch):
    js = _RetrofitJetStream(_existing_stream())
    _retrofit(monkeypatch, js)

    payload = js.wire_payloads[0]
    assert "storage" in payload, "storage was omitted from the STREAM.UPDATE body"
    assert payload["storage"] == "file"


def test_the_telemetry_retrofit_keeps_every_other_operator_set_field(monkeypatch):
    """Anything the operator tuned and this build has no opinion about must survive.

    `num_replicas` and `storage` are the two that cost durability, but they are only the
    two instances of the general shape: every field this build omits is a field the
    server resets.
    """
    js = _RetrofitJetStream(_existing_stream())
    _retrofit(monkeypatch, js)

    payload = js.wire_payloads[0]
    assert payload["max_msgs"] == 1_000_000
    assert payload["max_consumers"] == 4
    assert payload["discard"] == "new"
    # as_dict() re-encodes durations in nanoseconds on the way out.
    assert payload["duplicate_window"] == 120 * 1_000_000_000


def test_the_telemetry_retrofit_still_applies_the_limits_it_exists_to_apply(monkeypatch):
    """The B15 half must survive the R12 fix: preserving fields is not copying them all.

    The defect this pins is the over-correction — the echo winning over `cfg` instead of
    the other way round, which is one transposed `dict.update` away and would keep the
    replicas while quietly re-storing the limitless `max_age=0` / `max_bytes=-1` the
    server reports.  That is B15 again, wearing R12's clothes, and nothing else in this
    file would catch it: every other assertion here is about fields `cfg` does not carry.

    It reads `applied` rather than `wire_payloads` for the same reason: a body the server
    refuses is not a retrofit, however well-formed it looked on the way out.
    """
    js = _RetrofitJetStream(_existing_stream())
    _retrofit(monkeypatch, js)

    assert js.applied, "the STREAM.UPDATE was rejected — nothing was retrofitted"
    payload = js.applied[0]
    assert payload["name"] == "TELEMETRY"
    assert payload["subjects"] == ["telemetry.ingest.>"]
    # as_dict() converts max_age from seconds to nanoseconds.
    assert payload["max_age"] == 3600 * 1_000_000_000
    assert payload["max_bytes"] == 256 * 1024 * 1024
    # And the retention policy still comes from the server, because JetStream rejects
    # an update that changes it and would throw the limits away with the request.
    assert payload["retention"] == "limits"


def test_the_telemetry_retrofit_survives_a_max_age_under_the_stored_dedupe_window(monkeypatch):
    """A short CB_TELEMETRY_STREAM_MAX_AGE_S must not get the whole update thrown out.

    Echoing the server's stored config means the body now carries `duplicate_window`,
    which the pre-R12 body never sent.  JetStream refuses any update whose dedupe window
    is longer than its max_age (err_code=10052) rather than clamping it, and every stream
    nats-server created without an opinion on dedupe carries the 120s default.  So the
    moment an operator sets the age knob below 120 the retrofit is rejected wholesale,
    `_update_stream_limits` swallows the rejection into a warning, and the stream keeps
    the `max_age=0` / `max_bytes=-1` it was created with — B15's disk-exhaustion path,
    reopened permanently, because every subsequent boot fails in exactly the same way.

    The one outcome the server will accept is a dedupe window shrunk to fit, so that is
    what the code does; the cost is that a publisher retrying after `max_age` may be seen
    twice, against an unbounded stream as the alternative.
    """
    monkeypatch.setenv("CB_TELEMETRY_STREAM_MAX_AGE_S", "60")
    js = _RetrofitJetStream(_existing_stream())
    _retrofit(monkeypatch, js)

    assert js.applied, (
        "the STREAM.UPDATE was rejected (duplicate_window > max_age) — the warning is "
        "swallowed and the stream stays max_age=0/max_bytes=-1, unbounded forever"
    )
    payload = js.applied[0]
    assert payload["max_age"] == 60 * 1_000_000_000
    assert payload["max_bytes"] == 256 * 1024 * 1024
    assert payload["duplicate_window"] <= payload["max_age"]
    # …and the R12 half still holds while we are shrinking the window.
    assert payload["num_replicas"] == 3
