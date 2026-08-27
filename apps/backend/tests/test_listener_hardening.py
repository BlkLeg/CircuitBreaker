"""B13 / B34 — the discovery listener under hostile multicast traffic.

Every test here fails against the pre-B13 listener. What each one pins:

* `_record_event` opened a session, ran a SELECT and an INSERT, and committed —
  all synchronously, on the API event loop, once per multicast packet. Any host
  on the LAN could therefore stall every request the API was serving simply by
  talking SSDP at it;
* the only brake was a 60-second dedup on `(ip_address, service_type)`, and
  `service_type` is read straight out of the attacker's own `ST:`/`NT:` header,
  so varying one header per packet defeated it completely;
* `listener_events` had no retention at all, so whatever got through stayed
  forever;
* a failed INSERT fell through to the NATS publish, announcing a discovery event
  for a row that was never written, while a dedup hit published nothing;
* B34: `properties_json` is JSONB, but the writer handed it `json.dumps(...)`,
  so Postgres stored a JSON *scalar string* rather than an object and every
  reader got a string back.

And what the *first* attempt at the above got wrong, which is pinned here too
because a fix that trades a data-shape bug for a remote kill switch is worse
than the bug:

* assigning the dict directly is right for the JSONB column, but it removed the
  accidental NUL escaping the double `json.dumps` used to perform, so one SSDP
  header carrying U+0000 turned every subsequent write into a psycopg2
  `UntranslatableCharacter` — a row dropped, a NATS publish suppressed and
  `discovery_listener.record/database` pinned at ERROR, all from one datagram;
* the admission gate was added to the SSDP half only, while `_handle_mdns_service`
  reached `_record_event` with no gate at all and a dedup key whose `ip` is an A
  record inside the advertiser's own packet;
* the per-key bucket denied nothing under the attack it was written for, because
  an unseen key is handed a full burst and the map is LRU-bounded, so rotating
  more addresses than it tracks bought a fresh bucket every packet;
* moving the write to `asyncio.to_thread` uncapped turned a strictly serialised
  path into one session checkout per default-executor slot, against a pgbouncer
  pool of 5 + 5 with a fail-fast `pool_timeout=5`.

`scheduler registration for the retention purge lives in `main.py` and is NOT
covered by this file` — see the module docstring of `services/listener_purge.py`.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services import listener_service as ls
from app.services import stream_faults


@pytest.fixture(autouse=True)
def _clean_listener_state():
    stream_faults.reset_stream_faults()
    _reset_rate_gate()
    yield
    stream_faults.reset_stream_faults()
    _reset_rate_gate()


def _reset_rate_gate() -> None:
    """Clear the admission gates between tests.

    Written with getattr so the fixture still runs against a tree that has no
    gate at all — it is the assertions, not the fixture, that must report the
    missing gate.
    """
    for attr in ("_ssdp_rate_state", "_mdns_rate_state"):
        state = getattr(ls, attr, None)
        if state is not None:
            state.clear()
    for attr in ("_reset_listener_rate_gate", "_reset_ssdp_rate_gate"):
        reset = getattr(ls, attr, None)
        if reset is not None:
            reset()
            break


class _SessionWrapper:
    """Hands the listener the test's own session, ignoring its close()."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:  # the fixture owns this session's lifetime
        return None

    # `purge_old_listener_events` uses `with SessionLocal() as db:`, and `with`
    # looks these up on the type, not through __getattr__ — forwarding them
    # would hand back the real session and close it on exit, taking the
    # fixture's transaction with it.
    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _ssdp_packet(st: str) -> str:
    return (
        "NOTIFY * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        f"NT: {st}\r\n"
        f"USN: uuid:{st}::{st}\r\n"
        "NTS: ssdp:alive\r\n"
        "\r\n"
    )


# ── The DB write must not run on the event loop ──────────────────────────────


async def test_recording_an_event_does_not_stall_the_event_loop(monkeypatch):
    """Every request the API is serving used to stop for the duration of the
    listener's SELECT + INSERT + COMMIT, once per multicast packet."""

    class _BlockingDb:
        def query(self, *_a, **_kw):
            return self

        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return None

        def add(self, _obj):
            return None

        def commit(self):
            time.sleep(0.25)  # a slow disk, a lock wait, a saturated pool

        def rollback(self):
            return None

        def close(self):
            return None

    async def _publish(*_a, **_kw):
        return None

    monkeypatch.setattr(ls, "SessionLocal", lambda: _BlockingDb())
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    ticks = 0

    async def _other_work() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    ticker = asyncio.create_task(_other_work())
    await asyncio.sleep(0.01)
    ticks_before = ticks

    service = ls.ListenerService()
    await service._record_event(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="printer",
        ip_address="10.0.0.5",
        port=None,
        properties={"nt": "upnp:rootdevice"},
    )

    ticker.cancel()
    progress = ticks - ticks_before
    assert progress >= 5, (
        f"the event loop made {progress} steps of progress during a 0.25s database "
        "write — the listener is blocking every other request in the process"
    )


# ── A flood from one source must be dropped before the database ──────────────


async def test_ssdp_flood_from_one_source_never_reaches_the_database(monkeypatch):
    """Dedup is keyed on `(ip, service_type)` and `service_type` is the packet's
    own NT header, so one host varying that header wrote one row per packet."""
    recorded: list[str] = []

    async def _record(**kwargs):
        recorded.append(kwargs["service_type"])

    service = ls.ListenerService()
    monkeypatch.setattr(service, "_record_event", _record)

    for i in range(200):
        await service._handle_ssdp_packet(_ssdp_packet(f"urn:evil:{i}"), "10.0.0.9")

    assert len(recorded) <= 20, (
        f"{len(recorded)} of 200 flood packets from a single source reached the "
        "recording path; dedup on an attacker-chosen header is not a brake"
    )
    assert len(recorded) >= 1, "the gate must still admit ordinary advertisements"
    counts = stream_faults.stream_fault_counts()
    assert any(key.startswith("discovery_listener.ssdp_flood/") for key in counts), (
        f"dropped packets were not counted anywhere: {counts}"
    )


async def test_ssdp_rate_gate_cannot_itself_become_a_memory_sink(monkeypatch):
    """A gate keyed on the source address is a dict an attacker writes into.
    Source addresses on a LAN are spoofable, so the gate needs its own bound."""
    recorded: list[str] = []

    async def _record(**kwargs):
        recorded.append(kwargs["ip_address"])

    service = ls.ListenerService()
    monkeypatch.setattr(service, "_record_event", _record)

    cap = ls._SSDP_RATE_MAX_TRACKED
    for i in range(cap * 2):
        await service._handle_ssdp_packet(
            _ssdp_packet("upnp:rootdevice"), f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}"
        )

    assert len(ls._ssdp_rate_state) <= cap, (
        f"the admission gate grew to {len(ls._ssdp_rate_state)} entries against a cap of {cap}"
    )


def test_ssdp_global_budget_survives_source_address_spoofing():
    """The per-source bucket is defeated by using a fresh source per packet, so
    there is a second, process-wide budget behind it.

    Driven on a frozen clock through the gate's own `now=` seam rather than by
    wall-clock looping: at 50 tokens/second refilled lazily, a version of this
    test that let real time pass while 2000 calls went through
    `record_stream_fault` was asserting against how fast the CI box happened to
    be, not against the budget.
    """
    frozen = 1_000.0
    admitted = sum(
        1 for i in range(2000) if ls._admit_ssdp_packet(f"10.1.{i // 256}.{i % 256}", now=frozen)
    )

    assert admitted <= ls._LISTENER_GLOBAL_BURST, (
        f"{admitted} of 2000 packets, each from a different spoofed source, cleared the "
        f"gate against a process-wide burst of {ls._LISTENER_GLOBAL_BURST}"
    )
    assert admitted >= 1, "the gate must still admit ordinary advertisements"


def test_rotating_source_addresses_does_not_buy_a_fresh_bucket_per_packet():
    """The per-key tier is the one an attacker attacks, so it has to deny.

    `_ssdp_rate_state` is LRU-bounded and an unseen key is handed a full burst,
    so before the new-key bucket existed an attacker rotating more addresses
    than the map tracks got a brand-new 10-token bucket on every single packet
    and the per-source tier denied nothing, ever — leaving the two-tier design
    as one tier under exactly the attack it was added for.

    Modelled as a *sustained* flood -- 10 000 packets from 10 000 addresses over
    100 simulated seconds -- because that is the shape the process-wide bucket
    handles worst: it refills at 50/s, so over that window it alone would pass
    thousands of packets. The assertion is checked against both ceilings, so it
    cannot silently degrade into a restatement of the global budget.
    """
    packets = 10_000
    span_s = 100.0
    admitted = 0
    for i in range(packets):
        now = 5_000.0 + i * (span_s / packets)
        if ls._admit_ssdp_packet(f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}", now=now):
            admitted += 1

    churn_ceiling = ls._NEW_KEY_BURST + span_s * ls._NEW_KEY_PER_SECOND
    global_ceiling = ls._LISTENER_GLOBAL_BURST + span_s * ls._LISTENER_GLOBAL_PER_SECOND
    assert churn_ceiling * 2 < global_ceiling, (
        "this test would pass on the process-wide bucket alone; the per-key tier is "
        "not being exercised"
    )
    assert admitted <= churn_ceiling, (
        f"{admitted} of {packets} packets from {packets} rotating source addresses were "
        f"admitted over {span_s:.0f}s against a churn budget of {churn_ceiling:.0f}; "
        "a fresh address must not buy a fresh bucket"
    )


# ── A row that was not written must not be announced ─────────────────────────


async def test_a_failed_insert_does_not_publish_a_discovery_event(monkeypatch):
    """The DB block swallowed its exception and fell through to the publish, so
    the UI was told about devices whose rows never landed."""
    published: list[tuple] = []

    class _BrokenDb:
        def query(self, *_a, **_kw):
            return self

        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return None

        def add(self, _obj):
            return None

        def commit(self):
            raise RuntimeError("database is down")

        def rollback(self):
            return None

        def close(self):
            return None

    async def _publish(*args, **kwargs):
        published.append((args, kwargs))

    monkeypatch.setattr(ls, "SessionLocal", lambda: _BrokenDb())
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    service = ls.ListenerService()
    await service._record_event(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="printer",
        ip_address="10.0.0.5",
        port=None,
        properties={},
    )

    assert published == [], "a discovery event was announced for a row that was never written"
    assert stream_faults.stream_fault_counts()["discovery_listener.record/database"] == 1


# ── B34: JSONB must hold an object, not a JSON scalar string ─────────────────


async def test_properties_are_stored_as_a_jsonb_object(monkeypatch, db_session):
    from sqlalchemy import text

    from app.db.models import ListenerEvent

    async def _publish(*_a, **_kw):
        return None

    monkeypatch.setattr(ls, "SessionLocal", lambda: _SessionWrapper(db_session))
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    service = ls.ListenerService()
    await service._record_event(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="b34-probe",
        ip_address="198.51.100.34",
        port=None,
        properties={"server": "Linux/6.1 UPnP/1.0", "nts": "ssdp:alive"},
    )

    row = db_session.query(ListenerEvent).filter_by(name="b34-probe").one()
    kind = db_session.execute(
        text("SELECT jsonb_typeof(properties_json) FROM listener_events WHERE id = :i"),
        {"i": row.id},
    ).scalar_one()
    assert kind == "object", f"properties_json holds a JSON {kind}, not an object"
    assert row.properties_json == {"server": "Linux/6.1 UPnP/1.0", "nts": "ssdp:alive"}


# ── Retention: listener_events must not grow without bound ───────────────────


def test_listener_events_older_than_the_retention_window_are_purged(db_session):
    from datetime import timedelta

    from app.core.time import utcnow
    from app.db.models import ListenerEvent
    from app.services.listener_purge import (
        listener_event_retention_days,
        purge_listener_events,
    )

    now = utcnow()
    stale = ListenerEvent(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="stale",
        ip_address="198.51.100.1",
        seen_at=now - timedelta(days=listener_event_retention_days() + 1),
    )
    fresh = ListenerEvent(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="fresh",
        ip_address="198.51.100.2",
        seen_at=now - timedelta(hours=1),
    )
    db_session.add_all([stale, fresh])
    db_session.flush()

    deleted = purge_listener_events(db_session, now=now)

    assert deleted == 1
    remaining = {r.name for r in db_session.query(ListenerEvent).all()}
    assert remaining == {"fresh"}


def test_the_zero_argument_scheduler_entrypoint_actually_purges(monkeypatch, db_session):
    """`callable(...)` was the whole of this test, and a no-op stub is callable.

    The scheduler calls `purge_old_listener_events()` with no arguments and
    ignores what it returns, so the entry point owning its own session and
    actually issuing the DELETE is the only part of it anything checks. Pin the
    behaviour, not the symbol.

    What this test deliberately does NOT cover: whether `main.py` registers the
    job. It does not, at the time of writing — see `services/listener_purge.py`.
    """
    from datetime import timedelta

    from app.core.time import utcnow
    from app.db.models import ListenerEvent
    from app.services import listener_purge

    monkeypatch.setattr(listener_purge, "SessionLocal", lambda: _SessionWrapper(db_session))

    stale = ListenerEvent(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="entrypoint-stale",
        ip_address="198.51.100.7",
        seen_at=utcnow() - timedelta(days=listener_purge.listener_event_retention_days() + 1),
    )
    db_session.add(stale)
    db_session.flush()

    deleted = listener_purge.purge_old_listener_events()

    assert deleted == 1, "the scheduler entry point did not delete the row past retention"
    assert db_session.query(ListenerEvent).filter_by(name="entrypoint-stale").count() == 0


def test_a_malformed_retention_env_value_does_not_kill_the_process(monkeypatch):
    """The retention window was read with a bare `int(os.getenv(...))` at import
    time, inside the scheduler-registration import in `main.py`'s startup — so a
    typo in one env var was not a bad window, it was a process that would not
    boot. Fall back to the default and say so instead."""
    from app.services import listener_purge

    monkeypatch.setenv("CB_LISTENER_EVENT_RETENTION_DAYS", "fourteen")

    assert listener_purge.listener_event_retention_days() == listener_purge.DEFAULT_RETENTION_DAYS


# -- A NUL byte in one packet must not become a remote kill switch ------------


async def test_a_nul_byte_in_a_packet_cannot_kill_the_write_path(monkeypatch, db_session):
    """U+0000 is valid UTF-8, so `data.decode(errors="replace")` preserves it and
    `str.strip()` does not remove it -- a `SERVER: Linux\x00UPnP/1.0` header
    reaches the row intact. Postgres cannot store U+0000 in `text` and jsonb
    cannot parse an escaped one, so before the scrub this single datagram raised
    `psycopg2.errors.UntranslatableCharacter`, dropped the row, suppressed the
    NATS publish, and counted a `database` fault at ERROR -- once per packet, for
    as long as an unauthenticated LAN host cared to keep sending.

    Both halves matter: `usn` becomes `name`, a `String` column, and the headers
    become `properties_json`, a JSONB one. Scrubbing only the dict leaves the
    same kill switch open one field over.
    """
    from app.db.models import ListenerEvent

    published: list[tuple] = []

    async def _publish(*args, **kwargs):
        published.append((args, kwargs))

    monkeypatch.setattr(ls, "SessionLocal", lambda: _SessionWrapper(db_session))
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    raw = (
        "NOTIFY * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        "NT: upnp:rootdevice\r\n"
        "USN: uuid:nul\x00probe\r\n"
        "SERVER: Linux\x006.1 UPnP/1.0\r\n"
        "\r\n"
    )
    service = ls.ListenerService()
    await service._handle_ssdp_packet(raw, "198.51.100.99")

    counts = stream_faults.stream_fault_counts()
    assert "discovery_listener.record/database" not in counts, (
        f"one crafted datagram put the listener's database fault counter under remote "
        f"control: {counts}"
    )

    row = db_session.query(ListenerEvent).filter_by(ip_address="198.51.100.99").one()
    assert "\x00" not in (row.name or ""), "a NUL reached a text column"
    assert isinstance(row.properties_json, dict)
    for key, value in row.properties_json.items():
        assert "\x00" not in key and "\x00" not in str(value), (
            f"a NUL reached the JSONB column via {key!r}"
        )
    assert row.properties_json["server"] == "Linux6.1 UPnP/1.0"
    assert len(published) == 1, "the row landed but the discovery event was not published"


async def test_oversized_advertisement_values_are_bounded_before_the_row(monkeypatch, db_session):
    """None of these columns has a declared length, and an mDNS TXT set is not
    bounded by a 4096-byte datagram read the way an SSDP one is."""
    from app.db.models import ListenerEvent

    async def _publish(*_a, **_kw):
        return None

    monkeypatch.setattr(ls, "SessionLocal", lambda: _SessionWrapper(db_session))
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    service = ls.ListenerService()
    await service._record_event(
        source="mdns",
        service_type="_http._tcp.local.",
        name="x" * 10_000,
        ip_address="198.51.100.77",
        port=80,
        properties={f"k{i}": "v" * 10_000 for i in range(500)},
    )

    row = db_session.query(ListenerEvent).filter_by(ip_address="198.51.100.77").one()
    assert len(row.name or "") <= ls._MAX_TEXT_LEN
    assert len(row.properties_json or {}) <= ls._MAX_PROPERTIES
    assert all(len(v) <= ls._MAX_PROPERTY_VALUE_LEN for v in (row.properties_json or {}).values())


# -- The mDNS half is the other half of the same listener --------------------


async def test_mdns_advertisements_pass_through_an_admission_gate(monkeypatch):
    """`_handle_mdns_service` reached `_record_event` with no gate at all, and
    the dedup key it relies on is `(ip_address, service_type)` where *both*
    halves come out of the advertisement -- `ip_address` is
    `socket.inet_ntoa(info.addresses[0])`, an A record the advertiser wrote.
    Gating only SSDP left the identical unauthenticated write amplification wide
    open on the other listener."""

    class _Info:
        addresses = [b"\xc6\x33\x64\x2a"]  # 198.51.100.42
        port = 8080
        properties: dict = {b"txtvers": b"1"}

    class _Zc:
        def get_service_info(self, _type, _name):
            return _Info()

    recorded: list[str] = []

    async def _record(**kwargs):
        recorded.append(kwargs["name"])

    service = ls.ListenerService()
    monkeypatch.setattr(service, "_record_event", _record)

    for _ in range(200):
        await service._handle_mdns_service(_Zc(), "_http._tcp.local.", "evil._http._tcp.local.")

    assert len(recorded) <= 10, (
        f"{len(recorded)} of 200 advertisements for one instance reached the recording "
        "path; the mDNS half has no admission gate"
    )
    assert len(recorded) >= 1, "the gate must still admit ordinary advertisements"
    counts = stream_faults.stream_fault_counts()
    assert any(key.startswith("discovery_listener.mdns_flood/") for key in counts), (
        f"dropped mDNS advertisements were not counted anywhere: {counts}"
    )


# -- Off the loop, but not unbounded -----------------------------------------


async def test_listener_database_writes_are_capped_in_concurrency(monkeypatch):
    """`asyncio.to_thread` with no cap traded one defect for another. Before the
    move the DB block held no `await`, so the loop serialised it to exactly one
    `SessionLocal()` at a time; after it, the mDNS callbacks -- dispatched
    fire-and-forget through `asyncio.run_coroutine_threadsafe` -- could check out
    one session per default-executor slot, up to `min(32, cpu + 4)`. The
    pgbouncer deployment gives the whole process `pool_size=5, max_overflow=5`
    with a deliberately fail-fast `pool_timeout=5`, so that burst does not queue
    behind HTTP requests, it fails them."""
    import threading

    lock = threading.Lock()
    live = 0
    peak = 0

    class _Db:
        def query(self, *_a, **_kw):
            return self

        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return None

        def add(self, _obj):
            return None

        def commit(self):
            time.sleep(0.05)

        def rollback(self):
            return None

        def close(self):
            nonlocal live
            with lock:
                live -= 1

    def _factory():
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        return _Db()

    async def _publish(*_a, **_kw):
        return None

    monkeypatch.setattr(ls, "SessionLocal", _factory)
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    service = ls.ListenerService()
    await asyncio.gather(
        *(
            service._record_event(
                source="mdns",
                service_type="_http._tcp.local.",
                name=f"host-{i}",
                ip_address=f"198.51.100.{i}",
                port=80,
                properties={},
            )
            for i in range(24)
        )
    )

    assert peak <= ls._PERSIST_MAX_WORKERS, (
        f"{peak} listener database sessions were checked out at once against a cap of "
        f"{ls._PERSIST_MAX_WORKERS}; a multicast burst can exhaust the request pool"
    )


# -- The B34 data repair, proven against the rows the buggy writer produced ---

#: The corrected repair for B34's already-written rows, kept here because the
#: obvious one is wrong and was proven wrong at runtime. The naive
#:
#:     UPDATE listener_events SET properties_json = (properties_json #>> '{}')::jsonb
#:      WHERE jsonb_typeof(properties_json) = 'string';
#:
#: aborts the *entire* Alembic revision on exactly the rows the buggy writer
#: produced from a NUL-bearing packet: the double `json.dumps` turned the NUL
#: into six literal characters, so the extracted text reparses as a JSON escape
#: jsonb refuses ("unsupported Unicode escape sequence ... cannot be converted to
#: text"). Under CB_AUTO_MIGRATE that is a container that will not start, not a
#: partial repair. Guarding with `LIKE '{%'` does not help -- the extracted text
#: does begin with `{`.
#:
#: This version repairs each row inside its own subtransaction, strips the
#: escaped NUL exactly as the writer now does, and leaves a row it still cannot
#: parse at its original value rather than taking the revision down. It is
#: re-runnable: a second pass finds no `string`-typed rows left to convert.
B34_DATA_REPAIR = r"""
DO $$
DECLARE
    r RECORD;
    reparsed jsonb;
BEGIN
    FOR r IN
        SELECT id, properties_json #>> '{}' AS raw
          FROM listener_events
         WHERE properties_json IS NOT NULL
           AND jsonb_typeof(properties_json) = 'string'
    LOOP
        BEGIN
            reparsed := replace(r.raw, '\u0000', '')::jsonb;
        EXCEPTION WHEN others THEN
            CONTINUE;
        END;
        IF jsonb_typeof(reparsed) = 'object' THEN
            UPDATE listener_events SET properties_json = reparsed WHERE id = r.id;
        END IF;
    END LOOP;
END
$$;
"""

_B34_NAIVE_REPAIR = """
UPDATE listener_events
   SET properties_json = (properties_json #>> '{}')::jsonb
 WHERE properties_json IS NOT NULL
   AND jsonb_typeof(properties_json) = 'string'
   AND properties_json #>> '{}' LIKE '{%';
"""


def test_the_b34_data_repair_survives_rows_written_from_nul_bearing_packets(db_session):
    """Both halves are asserted: that the obvious repair really does abort on the
    rows the buggy writer produced, and that the one this tree proposes does
    not."""
    import json

    from sqlalchemy import text

    def _legacy_row(name: str, properties: dict) -> None:
        # Exactly what the pre-B34 writer produced: json.dumps() into a JSONB
        # column, so SQLAlchemy serialised the string a second time and Postgres
        # stored a JSON scalar string.
        db_session.execute(
            text(
                "INSERT INTO listener_events (source, service_type, name, ip_address, "
                "seen_at, properties_json) VALUES ('ssdp', 'upnp:rootdevice', :n, "
                "'198.51.100.200', now(), to_jsonb(cast(:p as text)))"
            ),
            {"n": name, "p": json.dumps(properties)},
        )

    _legacy_row("legacy-clean", {"server": "Linux/6.1 UPnP/1.0"})
    _legacy_row("legacy-nul", {"server": "Linux\x00UPnP/1.0"})
    db_session.flush()

    savepoint = db_session.begin_nested()
    with pytest.raises(Exception) as caught:
        db_session.execute(text(_B34_NAIVE_REPAIR))
    assert "unsupported Unicode escape sequence" in str(caught.value), (
        f"expected the naive repair to abort on the NUL-bearing row, got {caught.value}"
    )
    savepoint.rollback()

    db_session.connection().exec_driver_sql(B34_DATA_REPAIR)

    kinds = dict(
        db_session.execute(
            text(
                "SELECT name, jsonb_typeof(properties_json) FROM listener_events "
                "WHERE ip_address = '198.51.100.200'"
            )
        ).all()
    )
    assert kinds == {"legacy-clean": "object", "legacy-nul": "object"}, (
        f"the repair did not convert every legacy row: {kinds}"
    )

    repaired = dict(
        db_session.execute(
            text(
                "SELECT name, properties_json ->> 'server' FROM listener_events "
                "WHERE ip_address = '198.51.100.200'"
            )
        ).all()
    )
    assert repaired == {
        "legacy-clean": "Linux/6.1 UPnP/1.0",
        "legacy-nul": "LinuxUPnP/1.0",
    }, f"the repaired rows do not read back as objects: {repaired}"

    # Re-runnable: a second pass has nothing left to do and still does not raise.
    db_session.connection().exec_driver_sql(B34_DATA_REPAIR)
