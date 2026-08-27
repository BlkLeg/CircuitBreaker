"""Always-on mDNS and SSDP listener for Phase 4 Discovery Engine 2.0.

Passively captures device advertisements from the local network without
triggering active scans.  Writes each unique finding to the listener_events
table and publishes a NATS discovery.listener.found message.

Gracefully degrades when zeroconf is unavailable (logs a warning, no crash).
"""

import asyncio
import contextvars
import functools
import logging
import socket
import struct
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.core.nats_client import nats_client
from app.core.subjects import DISCOVERY_LISTENER_FOUND, discovery_listener_found_payload
from app.db.models import ListenerEvent
from app.db.session import SessionLocal
from app.services.stream_faults import (
    FAULT_DATABASE,
    FAULT_DECODE,
    FAULT_TIMEOUT,
    FAULT_TRANSPORT,
    record_stream_fault,
)

_logger = logging.getLogger(__name__)

# REL-07 fault-metric identity. These two listeners consume unauthenticated
# multicast traffic that any host on the LAN can generate at will, so every
# per-packet failure path here is throttled and counted rather than logged raw.
_COMPONENT = "discovery_listener"
# Backoff after a socket read error, so a permanently broken socket cannot spin.
_SSDP_RECV_ERROR_BACKOFF_S = 1.0
# Consecutive read errors tolerated before the SSDP listener gives up and exits
# rather than looping on a socket that will never recover.
_SSDP_MAX_CONSECUTIVE_ERRORS = 10

try:
    from zeroconf import ServiceBrowser, Zeroconf

    _ZEROCONF_AVAILABLE = True
except ImportError:
    _ZEROCONF_AVAILABLE = False
    _logger.warning("zeroconf not installed — mDNS listener will not start.")

# mDNS service types to watch
_MDNS_SERVICES = [
    "_http._tcp.local.",
    "_https._tcp.local.",
    "_ssh._tcp.local.",
    "_snmp._udp.local.",
    "_smb._tcp.local.",
    "_ftp._tcp.local.",
    "_printer._tcp.local.",
    "_ipp._tcp.local.",
    "_workstation._tcp.local.",
    "_device-info._tcp.local.",
    "_afpovertcp._tcp.local.",
    "_sftp-ssh._tcp.local.",
]

# SSDP multicast address / port
_SSDP_ADDR = "239.255.255.250"
_SSDP_PORT = 1900
_SSDP_M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: ssdp:all\r\n"
    "\r\n"
)

# Deduplication window — skip if same (ip, service_type) seen within this interval
_DEDUP_WINDOW = timedelta(seconds=60)


# ── Listener admission gates (B13) ───────────────────────────────────────────
# SSDP and mDNS are both unauthenticated multicast: any host on the LAN can emit
# as many advertisements a second as its NIC allows, and every one of them used
# to become a session checkout, a SELECT, an INSERT and a COMMIT. The dedup
# window above was the only brake, and it is keyed on `(ip_address,
# service_type)` — fields the sender chooses. On SSDP `service_type` is read
# straight out of the packet's own ST:/NT: header; on mDNS *both* halves come out
# of the advertisement, `ip_address` included, because it is
# `socket.inet_ntoa(info.addresses[0])`, an A record the advertiser wrote.
# Varying one field per packet defeated the dedup completely, so the brake has to
# live here, before the database is touched at all — and it has to cover both
# listeners. Gating only SSDP leaves the identical write amplification open on
# the other half of the same service.
#
# Three buckets, consulted in this order and for these reasons:
#
# * a per-key bucket, so one chatty or hostile advertiser cannot crowd out the
#   rest of the LAN. For SSDP the key is the source address ONLY — never a header
#   value, a header value is the attacker's to vary, which is the whole defect.
#   For mDNS there is no source address to be had (zeroconf hands the callback an
#   instance name, not a peer), so the key is the advertised identity and is
#   attacker-chosen by construction; the two buckets behind it are what make that
#   acceptable.
# * a new-key bucket, charged the first time a key is seen and only then. Without
#   it the per-key tier denies nothing at all under the attack it exists for: the
#   map is LRU-bounded and an unseen key is handed a full burst, so an attacker
#   rotating more addresses than the map tracks got a brand-new bucket on every
#   single packet and the whole two-tier design collapsed to one tier. Rotating
#   identities now costs a token from a bucket that refills slowly, while a LAN
#   full of already-known devices never touches it. The burst is sized past a
#   full /24 so a startup M-SEARCH answered by every device on the segment is
#   never mistaken for churn.
# * a process-wide bucket behind both, because this is the one that bounds total
#   database load no matter how the keys are chosen.
#
# The per-key bucket is charged first on purpose: a packet a later bucket rejects
# has still recorded its key, so the LRU eviction below sees the real key churn
# instead of being bypassed by an earlier gate short-circuiting.
#
# All three refill lazily on read — no timer, no background task — and the
# per-key maps are LRU-bounded, because a gate keyed on attacker-supplied data is
# a dict the attacker writes into and must not become the memory sink it exists
# to prevent. Ordinary LAN chatter is a few packets a second, well under every
# rate here.
_SSDP_RATE_PER_SECOND = 5.0
_SSDP_RATE_BURST = 10.0
_SSDP_RATE_MAX_TRACKED = 2048

# mDNS advertisements for one instance are re-announced, not streamed: a real
# device emits a handful at startup and then goes quiet, so this is tighter than
# the SSDP allowance.
_MDNS_RATE_PER_SECOND = 2.0
_MDNS_RATE_BURST = 5.0
_MDNS_RATE_MAX_TRACKED = 2048

_NEW_KEY_PER_SECOND = 4.0
_NEW_KEY_BURST = 256.0

_LISTENER_GLOBAL_PER_SECOND = 50.0
_LISTENER_GLOBAL_BURST = 100.0

_ssdp_rate_state: OrderedDict[str, tuple[float, float]] = OrderedDict()
_mdns_rate_state: OrderedDict[str, tuple[float, float]] = OrderedDict()
_new_key_tokens: float = _NEW_KEY_BURST
_new_key_refilled_at: float | None = None
_global_tokens: float = _LISTENER_GLOBAL_BURST
_global_refilled_at: float | None = None


def _reset_listener_rate_gate() -> None:
    """Drop all admission state.

    Called from `start()` so a listener restarted after an outage does not
    inherit a drained bucket from its previous run. Clearing the gate can only
    ever be more permissive, never less, so it is safe from anywhere.
    """
    global _new_key_tokens, _new_key_refilled_at, _global_tokens, _global_refilled_at

    _ssdp_rate_state.clear()
    _mdns_rate_state.clear()
    _new_key_tokens = _NEW_KEY_BURST
    _new_key_refilled_at = None
    _global_tokens = _LISTENER_GLOBAL_BURST
    _global_refilled_at = None


def _take_token(
    tokens: float, last: float, now: float, rate: float, burst: float
) -> tuple[bool, float]:
    """Refill one lazily-evaluated token bucket and try to spend a token.

    Returns ``(admitted, remaining_tokens)``. `max(0.0, ...)` guards a
    non-monotonic clock reading; `time.monotonic` should never go backwards, but
    a negative refill would silently drain the bucket if it ever did.
    """
    tokens = min(burst, tokens + max(0.0, now - last) * rate)
    if tokens < 1.0:
        return False, tokens
    return True, tokens - 1.0


def _admit_listener_event(
    state: OrderedDict[str, tuple[float, float]],
    key: str,
    *,
    rate: float,
    burst: float,
    max_tracked: int,
    now: float | None = None,
) -> bool:
    """Decide whether one advertisement may reach the database.

    Called only from the event loop — both listeners funnel through coroutines
    the loop runs — so the module state above needs no lock. Do not move this
    call onto a worker thread without adding one.
    """
    global _new_key_tokens, _new_key_refilled_at, _global_tokens, _global_refilled_at

    now = time.monotonic() if now is None else now

    # Per key. The pop-then-reinsert is what keeps the map in
    # least-recently-heard-from order, so the eviction drops a silent key rather
    # than an arbitrary one.
    known = key in state
    tokens, last = state.pop(key, (burst, now))
    admitted, tokens = _take_token(tokens, last, now, rate, burst)
    state[key] = (tokens, now)
    while len(state) > max_tracked:
        state.popitem(last=False)
    if not admitted:
        return False

    # Key churn. Charged only for a key the map had never heard of, so a stable
    # LAN never touches it and an attacker rotating identities pays per identity.
    if not known:
        if _new_key_refilled_at is None:
            _new_key_refilled_at = now
        admitted, _new_key_tokens = _take_token(
            _new_key_tokens, _new_key_refilled_at, now, _NEW_KEY_PER_SECOND, _NEW_KEY_BURST
        )
        _new_key_refilled_at = now
        if not admitted:
            return False

    # Process-wide.
    if _global_refilled_at is None:
        _global_refilled_at = now
    admitted, _global_tokens = _take_token(
        _global_tokens,
        _global_refilled_at,
        now,
        _LISTENER_GLOBAL_PER_SECOND,
        _LISTENER_GLOBAL_BURST,
    )
    _global_refilled_at = now
    return admitted


def _admit_ssdp_packet(ip: str, *, now: float | None = None) -> bool:
    """Admission for one SSDP datagram, keyed on its source address only."""
    return _admit_listener_event(
        _ssdp_rate_state,
        ip,
        rate=_SSDP_RATE_PER_SECOND,
        burst=_SSDP_RATE_BURST,
        max_tracked=_SSDP_RATE_MAX_TRACKED,
        now=now,
    )


def _admit_mdns_advertisement(key: str, *, now: float | None = None) -> bool:
    """Admission for one mDNS advertisement, keyed on the advertised identity."""
    return _admit_listener_event(
        _mdns_rate_state,
        key,
        rate=_MDNS_RATE_PER_SECOND,
        burst=_MDNS_RATE_BURST,
        max_tracked=_MDNS_RATE_MAX_TRACKED,
        now=now,
    )


# ── Text safety for the Postgres-bound row (B34) ─────────────────────────────
# Postgres cannot store U+0000 in a `text` column and jsonb cannot even parse an
# escaped one, so a single NUL anywhere in this row is not a data-quality
# wrinkle — it is a failed INSERT. Every field below is attacker-supplied: SSDP
# headers come from `data.decode(errors="replace")`, which preserves U+0000
# because U+0000 is perfectly valid UTF-8, and `str.strip()` does not remove it;
# mDNS TXT records legitimately carry binary bytes with no attacker at all.
#
# Before B34 the accidental double `json.dumps` escaped the NUL into six literal
# characters and the row landed. Assigning the dict straight to the JSONB column
# is the correct fix for the column, but it removes that accident — so the scrub
# has to be explicit, and it has to sit here, on the single path both listeners
# share. Without it one crafted datagram drops its row, suppresses the NATS
# publish and drives `discovery_listener.record/database` at ERROR for as long as
# the sender keeps sending: an unauthenticated LAN host with its hand on the
# operator's only "the listener's database is broken" signal, and on the
# `circuitbreaker_stream_faults_total{fault="database"}` counter behind it.
# Scrubbing only `properties` is not enough — `usn` becomes `name`, a text column
# of its own, and psycopg2 rejects the NUL there first.
#
# The length caps are the second half of the same argument. An SSDP datagram is
# bounded by the 4096-byte read; an mDNS TXT set is not, and none of these
# columns has a declared length. Truncation is right here because these rows are
# a recency signal, not a record: a shortened SERVER string is still a usable
# hint, an unbounded one is a write amplifier.
_MAX_TEXT_LEN = 512
_MAX_PROPERTIES = 64
_MAX_PROPERTY_KEY_LEN = 128
_MAX_PROPERTY_VALUE_LEN = 1024


def _scrub_text(value: str, limit: int) -> str:
    """Strip characters Postgres cannot hold, then bound the length."""
    if "\x00" in value:
        value = value.replace("\x00", "")
    return value[:limit]


def _scrub_optional_text(value: str | None, limit: int = _MAX_TEXT_LEN) -> str | None:
    return None if value is None else _scrub_text(value, limit)


def _scrub_properties(properties: dict | None) -> dict | None:
    """Make one advertisement's property bag safe for a JSONB column.

    Flat by design: SSDP headers and mDNS TXT records are both key/value, and a
    nested structure here would only ever have arrived because something upstream
    was confused. Non-string scalars are kept as they are — jsonb holds them
    natively — and anything else is stringified so a stray object cannot fail the
    insert at commit time, which is the failure mode this whole block exists to
    remove.
    """
    if not properties:
        return None

    scrubbed: dict[str, Any] = {}
    for raw_key, raw_value in properties.items():
        if len(scrubbed) >= _MAX_PROPERTIES:
            break
        if isinstance(raw_key, bytes):
            raw_key = raw_key.decode(errors="replace")
        key = _scrub_text(str(raw_key), _MAX_PROPERTY_KEY_LEN)
        if not key:
            continue
        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode(errors="replace")
        if raw_value is None or isinstance(raw_value, bool | int | float):
            scrubbed[key] = raw_value
        else:
            scrubbed[key] = _scrub_text(str(raw_value), _MAX_PROPERTY_VALUE_LEN)
    return scrubbed or None


# ── Off the loop, but bounded (B13) ──────────────────────────────────────────
# `_persist_event` is synchronous SQLAlchemy and must not run on the API event
# loop. Handing it to `asyncio.to_thread` uncapped is its own defect, though:
# before the move the DB block held no `await`, so the loop serialised it to
# exactly one `SessionLocal()` at a time, and afterwards nothing did — mDNS
# callbacks are dispatched fire-and-forget through
# `asyncio.run_coroutine_threadsafe`, so a burst of advertisements could check
# out one session per default-executor slot, up to `min(32, cpu + 4)` of them,
# from a background listener. `db/session.py` gives the pgbouncer deployment
# `pool_size=5, max_overflow=5` with a `pool_timeout=5` chosen deliberately to
# fail fast, so that burst does not queue behind live HTTP requests, it fails
# them — and only in that deployment, which is the worst shape a bug can have.
#
# Two workers on a pool of our own, not the shared default executor: bounded, and
# not competing with the SSE session validation in `api/events.py` or the nmap
# scans in `discovery_probes.py` that also live on the default one. The
# `contextvars.copy_context()` is not decoration — it is what `asyncio.to_thread`
# does internally, and `db/session.py`'s `_set_tenant_on_checkout` reads the
# `current_tenant_id` ContextVar on every checkout, so a plain
# `run_in_executor` would hand the worker a bare context and lose the tenant.
_PERSIST_MAX_WORKERS = 2
# A backlog cap on top of the worker cap: with the database slow rather than
# down, the admission gate still lets 50 events a second in and every one of them
# would otherwise park a coroutine on the queue for as long as the outage lasts.
_PERSIST_MAX_INFLIGHT = 64

_persist_pool: ThreadPoolExecutor | None = None
_persist_inflight = 0


def _get_persist_pool() -> ThreadPoolExecutor:
    global _persist_pool

    if _persist_pool is None:
        _persist_pool = ThreadPoolExecutor(
            max_workers=_PERSIST_MAX_WORKERS, thread_name_prefix="cb-listener-db"
        )
    return _persist_pool


def _persist_event(
    source: str,
    service_type: str | None,
    name: str | None,
    ip_address: str | None,
    port: int | None,
    properties: dict | None,
) -> bool:
    """Dedup-check and insert one listener event. True if a row actually landed.

    Synchronous SQLAlchemy: this MUST be reached through the bounded worker pool
    in `_record_event` and never awaited inline, and never through a bare
    `asyncio.to_thread` either — see the note on `_PERSIST_MAX_WORKERS` for why
    the cap and the pool are both load-bearing. Until B13 the whole body ran on
    the API event loop, so a session checkout, a SELECT, an INSERT and a COMMIT —
    four round trips — stalled every request the process was serving, once per
    multicast packet. The shape matches `core/update_check.py` and
    `core/job_lock.py`.
    """
    source = _scrub_text(source, _MAX_TEXT_LEN)
    service_type = _scrub_optional_text(service_type)
    name = _scrub_optional_text(name)
    ip_address = _scrub_optional_text(ip_address)
    scrubbed_properties = _scrub_properties(properties)

    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC) - _DEDUP_WINDOW
        existing = (
            db.query(ListenerEvent)
            .filter(
                ListenerEvent.ip_address == ip_address,
                ListenerEvent.service_type == service_type,
                ListenerEvent.seen_at >= cutoff,
            )
            .first()
        )
        if existing:
            return False

        event = ListenerEvent(
            source=source,
            service_type=service_type,
            name=name,
            ip_address=ip_address,
            port=port,
            # The dict itself, not `json.dumps(dict)`. `properties_json` is JSONB
            # and SQLAlchemy already serializes it; handing it a `str` made
            # Postgres store a JSON *scalar string* rather than an object, so
            # every reader got a quoted blob back and `properties_json ->> 'nt'`
            # was NULL (B34). Do not re-introduce the dumps() — and do not drop
            # the scrub above on the way past, because the dumps() is what used
            # to be escaping the NUL bytes this column cannot hold.
            properties_json=scrubbed_properties,
        )
        db.add(event)
        db.commit()
        return True
    except Exception as exc:
        # One WARNING per failed insert is a log storm here, not a log
        # line: multicast chatter on a busy LAN is hundreds of packets a
        # minute and every one of them takes this path while the database
        # is down. Throttled and counted instead (REL-07).
        record_stream_fault(
            f"{_COMPONENT}.record",
            exc,
            logger=_logger,
            context={"source": source, "ip": ip_address},
            fault=FAULT_DATABASE,
        )
        db.rollback()
        return False
    finally:
        db.close()


class ListenerService:
    """Manages mDNS ServiceBrowser + SSDP UDP socket as asyncio background tasks."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._zeroconf: Zeroconf | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.is_running: bool = False
        self.mdns_active: bool = False
        self.ssdp_active: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()

    # ── Public API ───────────────────────────────────────────────────────────

    async def start(self, settings: Any) -> None:
        """Start listener tasks based on settings flags."""
        if self.is_running:
            return
        self._loop = asyncio.get_running_loop()
        self.is_running = True
        _reset_listener_rate_gate()

        if getattr(settings, "mdns_enabled", True) and _ZEROCONF_AVAILABLE:
            t = asyncio.create_task(self._run_mdns(), name="mdns_listener")
            self._tasks.append(t)

        if getattr(settings, "ssdp_enabled", True):
            t = asyncio.create_task(self._run_ssdp(), name="ssdp_listener")
            self._tasks.append(t)

    async def stop(self) -> None:
        """Cancel all listener tasks and clean up zeroconf."""
        self.is_running = False
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._zeroconf:
            # get_running_loop(), not get_event_loop(): this is inside a
            # coroutine, and get_event_loop()'s no-running-loop fallback is
            # deprecated (REL-08).
            await asyncio.get_running_loop().run_in_executor(None, self._zeroconf.close)
            self._zeroconf = None
        self.mdns_active = False
        self.ssdp_active = False
        _logger.info("Listener service stopped.")

    # ── mDNS via zeroconf ────────────────────────────────────────────────────

    async def _run_mdns(self) -> None:
        """Start zeroconf ServiceBrowser for all registered mDNS service types."""
        try:
            loop = asyncio.get_running_loop()
            self._zeroconf = await loop.run_in_executor(None, Zeroconf)

            class _Handler:
                def __init__(inner_self) -> None:
                    pass

                def add_service(inner_self, zc: Any, type_: str, name: str) -> None:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_mdns_service(zc, type_, name), loop
                    )

                def remove_service(inner_self, zc: Any, type_: str, name: str) -> None:
                    pass

                def update_service(inner_self, zc: Any, type_: str, name: str) -> None:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_mdns_service(zc, type_, name), loop
                    )

            zc = self._zeroconf
            if zc:
                _handler_instance = cast(Any, _Handler())
                await loop.run_in_executor(
                    None, lambda: ServiceBrowser(zc, _MDNS_SERVICES, _handler_instance)
                )
            self.mdns_active = True
            _logger.info("mDNS browser started for %d service types.", len(_MDNS_SERVICES))

            # Keep alive until cancelled
            await self._stop_event.wait()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            record_stream_fault(
                f"{_COMPONENT}.mdns", exc, logger=_logger, context={"services": len(_MDNS_SERVICES)}
            )
        finally:
            self.mdns_active = False

    async def _handle_mdns_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
        # B13, second half. The gate belongs here — ahead of `get_service_info`,
        # which is a network round trip of its own on an executor thread, and
        # ahead of `_record_event`, which this path used to reach with no
        # admission control whatsoever while SSDP had two buckets in front of it.
        # The key is the advertised instance identity because zeroconf gives the
        # callback nothing else: `add_service`/`update_service` receive a type
        # and a name, not a peer address. Do not "improve" this by keying on
        # `info.addresses[0]` once the info is fetched — that is an A record
        # inside the advertisement, the same attacker-chosen field that made the
        # dedup window useless in the first place, and using it here would move
        # the defect rather than close it. The new-key and process-wide buckets
        # behind this one are what bound an advertiser that simply invents a new
        # instance name per packet.
        if not _admit_mdns_advertisement(f"{type_}\x1f{name}"):
            record_stream_fault(
                f"{_COMPONENT}.mdns_flood",
                RuntimeError("mDNS admission budget exceeded"),
                logger=_logger,
                context={"service_type": type_, "tracked_instances": len(_mdns_rate_state)},
                fault=FAULT_TRANSPORT,
            )
            return

        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: zc.get_service_info(type_, name))
            if not info:
                return

            ip = None
            if info.addresses:
                try:
                    ip = socket.inet_ntoa(info.addresses[0])
                except OSError as exc:
                    # inet_ntoa only rejects a non-4-byte address, i.e. an IPv6
                    # record. Recording the event without an IP is correct; it
                    # is counted so a network that is all-IPv6 is visible as
                    # such instead of looking like an idle one.
                    record_stream_fault(
                        f"{_COMPONENT}.mdns_address",
                        exc,
                        logger=_logger,
                        context={"name": name, "octets": len(info.addresses[0])},
                        fault=FAULT_DECODE,
                    )

            port = info.port
            props: dict = {}
            try:
                props = {
                    k.decode(errors="replace"): v.decode(errors="replace")
                    if isinstance(v, bytes)
                    else v
                    for k, v in (info.properties or {}).items()
                }
            except (AttributeError, TypeError, ValueError) as exc:
                record_stream_fault(
                    f"{_COMPONENT}.mdns_properties",
                    exc,
                    logger=_logger,
                    context={"name": name},
                    fault=FAULT_DECODE,
                )

            await self._record_event(
                source="mdns",
                service_type=type_,
                name=name,
                ip_address=ip,
                port=port,
                properties=props,
            )
        except Exception as exc:
            record_stream_fault(
                f"{_COMPONENT}.mdns_service",
                exc,
                logger=_logger,
                context={"service_type": type_, "name": name},
            )

    # ── SSDP via raw UDP ─────────────────────────────────────────────────────

    def _open_ssdp_socket(self) -> socket.socket:
        """Bind the SSDP multicast socket. Raises OSError if the port is taken."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # not available on all platforms
            sock.bind((_SSDP_ADDR, _SSDP_PORT))
            # Join the multicast group on all interfaces
            mcast_req = struct.pack("4sL", socket.inet_aton(_SSDP_ADDR), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mcast_req)
            sock.setblocking(False)
        except BaseException:
            # A half-configured socket must not outlive this call — closing it
            # here is what keeps a failed bind from leaking a descriptor and a
            # multicast membership on every restart attempt.
            sock.close()
            raise
        return sock

    def _send_msearch(self) -> None:
        """Emit one M-SEARCH so devices answer immediately instead of at their
        next NOTIFY, which can be minutes away."""
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            send_sock.sendto(_SSDP_M_SEARCH.encode(), (_SSDP_ADDR, _SSDP_PORT))
        finally:
            send_sock.close()

    async def _ssdp_recv_loop(self, sock: socket.socket) -> None:
        """Forward SSDP datagrams until cancelled or the socket stops working."""
        loop = asyncio.get_running_loop()
        consecutive_errors = 0
        while self.is_running:
            try:
                # sock_recvfrom is proper async (epoll/select) — no thread pool needed.
                # The old run_in_executor on a non-blocking socket was burning 10 thread
                # slots/second returning BlockingIOError immediately.
                data, addr = await loop.sock_recvfrom(sock, 4096)
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                # A read error used to be a DEBUG line and a 1s sleep, forever:
                # a socket closed out from under the listener (interface down,
                # descriptor revoked) became an invisible infinite loop that
                # reported itself as `ssdp_active = True`. Bounded now, so the
                # task exits and the flag tells the truth (REL-07).
                consecutive_errors += 1
                record_stream_fault(
                    f"{_COMPONENT}.ssdp_recv",
                    exc,
                    logger=_logger,
                    context={"consecutive_errors": consecutive_errors},
                )
                if consecutive_errors >= _SSDP_MAX_CONSECUTIVE_ERRORS:
                    _logger.error(
                        "SSDP listener stopping after %d consecutive read errors.",
                        consecutive_errors,
                    )
                    return
                await asyncio.sleep(_SSDP_RECV_ERROR_BACKOFF_S)
                continue
            consecutive_errors = 0
            await self._handle_ssdp_packet(data.decode(errors="replace"), addr[0])

    async def _run_ssdp(self) -> None:
        """Listen for SSDP NOTIFY and M-SEARCH responses via UDP multicast."""
        sock: socket.socket | None = None
        try:
            sock = self._open_ssdp_socket()
            self.ssdp_active = True
            _logger.info("SSDP socket bound on %s:%d.", _SSDP_ADDR, _SSDP_PORT)

            try:
                self._send_msearch()
            except OSError as exc:
                # Not fatal — passive NOTIFY capture still works — but it does
                # mean discovery is slower, which is worth a counted line
                # rather than the silent `pass` that used to be here.
                record_stream_fault(f"{_COMPONENT}.ssdp_msearch", exc, logger=_logger)

            await self._ssdp_recv_loop(sock)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            record_stream_fault(
                f"{_COMPONENT}.ssdp", exc, logger=_logger, context={"port": _SSDP_PORT}
            )
        finally:
            self.ssdp_active = False
            if sock is not None:
                # The socket used to be left open on every exit path, so each
                # stop()/start() cycle leaked a descriptor and an IGMP group
                # membership until the process died.
                sock.close()

    async def _handle_ssdp_packet(self, raw: str, ip: str) -> None:
        if not _admit_ssdp_packet(ip):
            # Counted, never logged per packet: a flood is precisely the case
            # where one log line per datagram is the second denial of service.
            # record_stream_fault always increments the metric and throttles the
            # line, so the drop shows up on the dashboard without showing up as
            # a log storm. FAULT_TRANSPORT rather than a seventh fault class:
            # stream_faults documents its six classes as metric label values
            # with bounded cardinality, and this is a condition of the multicast
            # socket itself.
            record_stream_fault(
                f"{_COMPONENT}.ssdp_flood",
                RuntimeError("SSDP admission budget exceeded"),
                logger=_logger,
                context={"ip": ip, "tracked_sources": len(_ssdp_rate_state)},
                fault=FAULT_TRANSPORT,
            )
            return

        headers: dict[str, str] = {}
        for line in raw.splitlines()[1:]:
            if ":" in line:
                key, _, val = line.partition(":")
                headers[key.strip().lower()] = val.strip()

        service_type = headers.get("st") or headers.get("nt") or "ssdp"
        name = headers.get("usn") or headers.get("server") or ip

        await self._record_event(
            source="ssdp",
            service_type=service_type,
            name=name,
            ip_address=ip,
            port=None,
            properties=headers,
        )

    # ── Shared recording ────────────────────────────────────────────────────

    async def _record_event(
        self,
        source: str,
        service_type: str | None,
        name: str | None,
        ip_address: str | None,
        port: int | None,
        properties: dict,
    ) -> None:
        """Deduplicate, write the row off the loop, and publish a NATS event."""
        global _persist_inflight

        if _persist_inflight >= _PERSIST_MAX_INFLIGHT:
            # Shed rather than queue. These rows are a recency signal, so the
            # newest one is the one worth keeping and an unbounded backlog of
            # them behind a slow database is just a second failure. FAULT_TIMEOUT
            # rather than FAULT_DATABASE on purpose: nothing here failed, the
            # write never got a slot, and FAULT_DATABASE logs at ERROR — the
            # exact operator signal an unauthenticated sender must not be able to
            # drive.
            record_stream_fault(
                f"{_COMPONENT}.persist_backlog",
                RuntimeError("listener persistence backlog full"),
                logger=_logger,
                context={"inflight": _persist_inflight, "source": source},
                fault=FAULT_TIMEOUT,
            )
            return

        loop = asyncio.get_running_loop()
        context = contextvars.copy_context()
        _persist_inflight += 1
        try:
            wrote = await loop.run_in_executor(
                _get_persist_pool(),
                functools.partial(
                    context.run,
                    _persist_event,
                    source,
                    service_type,
                    name,
                    ip_address,
                    port,
                    properties,
                ),
            )
        finally:
            _persist_inflight -= 1
        if not wrote:
            # Nothing landed: either the dedup window swallowed the event or the
            # insert failed. The old code fell straight through to the publish on
            # the failure path, announcing discoveries for rows that do not
            # exist — a NATS event is a claim about the database, so it is only
            # honest to emit one when the database agrees.
            return

        _logger.debug("Listener event: %s %s @ %s:%s", source, service_type, ip_address, port)

        # Publish NATS (fire-and-forget; don't block on NATS failure)
        try:
            await nats_client.publish(
                DISCOVERY_LISTENER_FOUND,
                discovery_listener_found_payload(
                    source=source,
                    ip=ip_address,
                    name=name,
                    service_type=service_type,
                    port=port,
                ),
            )
        except Exception as exc:
            # Was a bare `pass`: with NATS down, live discovery events stopped
            # reaching the UI with no log line and no metric anywhere. The row
            # is already committed, so this stays non-fatal — but it is now
            # visible.
            record_stream_fault(
                f"{_COMPONENT}.publish",
                exc,
                logger=_logger,
                context={"subject": DISCOVERY_LISTENER_FOUND, "source": source},
            )


# Singleton instance imported by main.py
listener_service = ListenerService()
