import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Iterator
from typing import Any

from app.integrations.apc_ups import APCUPSClient
from app.integrations.idrac import IDRACClient
from app.integrations.ilo import ILOClient
from app.integrations.snmp_generic import SNMPGenericClient
from app.integrations.snmp_network_device import SNMPNetworkDeviceClient
from app.services.credential_vault import CredentialVault
from app.services.stream_faults import record_stream_fault

_logger = logging.getLogger(__name__)

# Reuse ILO/IDRAC clients per (profile, host, username) to avoid connection pool exhaustion.
_HW_CLIENT_CACHE_MAX = 64

# ── Cross-thread ownership of the cached clients ────────────────────────────
#
# poll_hardware is synchronous, but nothing calls it on the event loop any more:
# the collector dispatches it with asyncio.to_thread, and since 745a99b9 so does
# the manual "poll now" endpoint. Any admin can therefore fire N concurrent polls
# at one hardware row and land N worker threads in this function at once, all
# resolving to the same cache key.
#
# A cached client is an ILOClient, and an ILOClient owns a requests.Session.
# requests.Session is explicitly not thread-safe — concurrent requests interleave
# writes to the cookie jar, to redirect/auth state and to urllib3's pool
# bookkeeping. The failure mode is not an exception a caller can see; it is a
# response assembled from two devices' bytes, or a connection pool that never
# gives a connection back. So: one thread inside a given client at a time.
#
# The lock therefore lives ON the cache entry, welded to the client it protects,
# and is never reassigned. A maintainer must not "flatten" this back into a
# plain client cache plus a parallel `_hw_client_locks` dict keyed the same way.
# That was the first attempt at this fix and it did not hold: the two dicts
# drift. Eviction cleared the lock dict wholesale, while a client insert
# repopulated only the cache, so a key could end up cached with no registered
# lock — and the next caller minted a fresh lock, acquired it uncontended, read
# the cache and was handed the very client another thread was still polling
# with. Two threads, one Session, which is the entire defect (R8). With the lock
# bound to the entry that owns the client, "I hold the lock that came with this
# client" *is* the statement "nobody else has this client", and no eviction, no
# failed build and no timed-out wait can prise the two apart.
_hw_cache_guard = threading.Lock()


class _PooledClient:
    """One cached telemetry client plus the lock granting exclusive use of *it*.

    `client` is None only between the moment its builder publishes this entry and
    the moment that builder's `build()` returns. The builder holds `lock` across
    that whole gap, so no other thread can observe the half-built entry without
    first waiting for it — which is also what stops N simultaneous callers on a
    cold key from opening N Redfish sessions to the same BMC.
    """

    __slots__ = ("client", "lock")

    def __init__(self) -> None:
        self.client: Any = None
        self.lock = threading.Lock()


_hw_client_cache: dict[tuple[str, str, str], _PooledClient] = {}

# How long a poll waits for a busy client before giving up on the pool and
# building a private one. Short on purpose: a manual poll that timed out leaves
# its worker thread running — asyncio cannot interrupt a blocking socket read —
# so a wedged client can stay checked out for the device's whole timeout (~20s
# for iLO: two Redfish GETs at 10s each). Waiting that out would make one stuck
# BMC serialise every later poll of the same host into its own timeout, which is
# the event-loop stall B07 removed, rebuilt one lock down.
#
# The trade is real and is not free: every wait that runs out costs one extra
# TLS + basic-auth Redfish connection to a device that tolerates only a handful
# of them, and costs the caller two seconds of a blocked executor thread first.
# Several hardware rows aimed at one BMC, all slower than this bound, will
# therefore open one private session per row per collector cycle. That is the
# deliberate choice: a bounded burst of sockets against one slow BMC, rather
# than an unbounded queue of worker threads or — the thing this whole section
# exists to prevent — two threads sharing one Session. Raising this constant
# trades sockets back for latency; lowering it does the reverse. Do not "fix"
# the amplification by removing the bound.
_CLIENT_BUSY_WAIT_S = 2.0


def _checkout(cache_key: tuple[str, str, str]) -> tuple[_PooledClient, bool]:
    """Return this key's cache entry and whether *this* thread must build it."""
    with _hw_cache_guard:
        entry = _hw_client_cache.get(cache_key)
        if entry is not None:
            return entry, False
        entry = _PooledClient()
        # Acquired under the guard, where it cannot block: nothing else can see
        # this entry yet. Publishing it already-locked is what makes the build
        # exclusive without holding the guard across it.
        entry.lock.acquire()
        if len(_hw_client_cache) >= _HW_CLIENT_CACHE_MAX:
            # Dropping entries that are in use right now is safe: their holders
            # keep the entry object, and the lock they hold is that entry's own
            # client's lock. They simply stop being shared with anyone new, and
            # the next caller for those keys builds a fresh entry.
            _hw_client_cache.clear()
        _hw_client_cache[cache_key] = entry
        return entry, True


def _close_private(client: Any, cache_key: tuple[str, str, str]) -> None:
    """Hand a private client's sockets back, and say so if that fails."""
    closer = getattr(client, "close", None)
    if not callable(closer):
        return
    try:
        closer()
    except Exception:
        # Not suppressed silently. This close is the only thing returning the
        # socket a contended poll opened against a BMC, so a close that starts
        # failing leaks precisely what this path was added to prevent, and it
        # would do so invisibly. Still non-fatal: the poll succeeded and the
        # caller is owed its data.
        _logger.warning(
            "Failed to close the private telemetry client for %s; its connection to the "
            "device may linger until garbage collection.",
            cache_key,
            exc_info=True,
        )


@contextlib.contextmanager
def _pooled_client(
    cache_key: tuple[str, str, str],
    build: Callable[[], Any],
) -> Iterator[Any]:
    """Yield a client for `cache_key` that no other thread is using right now.

    Normally that is the cached instance, with this thread holding the lock that
    belongs to it for the duration of the poll. If the cached instance is busy
    and stays busy past `_CLIENT_BUSY_WAIT_S`, this yields a private client
    instead and closes it on the way out — a caller never shares, and a caller
    never blocks indefinitely.

    Do not "simplify" this back to a bare dict lookup. The lock is the only thing
    keeping two worker threads out of one requests.Session (R8).
    """
    entry, is_builder = _checkout(cache_key)

    if is_builder:
        try:
            entry.client = build()
        except BaseException:
            # Withdraw the entry rather than leaving a permanently client-less
            # one parked in the cache: otherwise every later poll of this key
            # would find None and be shunted onto the private path forever,
            # and the key would pin a cache slot it can never use.
            with _hw_cache_guard:
                if _hw_client_cache.get(cache_key) is entry:
                    del _hw_client_cache[cache_key]
            entry.lock.release()
            raise
        try:
            yield entry.client
        finally:
            entry.lock.release()
        return

    if entry.lock.acquire(timeout=_CLIENT_BUSY_WAIT_S):
        # Whatever happened to the cache while we waited — eviction, another
        # key's insert — `entry.client` is the client this very lock protects.
        # It is never reassigned, so there is no window in which holding the
        # lock and using the client refer to two different objects.
        client = entry.client
        if client is not None:
            try:
                yield client
            finally:
                entry.lock.release()
            return
        # The builder we queued behind failed and withdrew this entry. Nothing
        # will ever be cached here; fall through and build our own.
        entry.lock.release()

    _logger.debug(
        "Telemetry client for %s is in use by another poll; using a private client.",
        cache_key,
    )
    private = build()
    try:
        yield private
    finally:
        # Private clients are not pooled, so nothing will reuse their sockets.
        # Close them here rather than leaving the Session for the garbage
        # collector, which is what actually exhausts a BMC's handful of
        # concurrent connections.
        _close_private(private, cache_key)


PROFILE_MAP = {
    "idrac6": IDRACClient,
    "idrac7": IDRACClient,
    "idrac8": IDRACClient,
    "idrac9": IDRACClient,
    "ilo4": ILOClient,
    "ilo5": ILOClient,
    "ilo6": ILOClient,
    "apc_ups": APCUPSClient,
    "cyberpower_ups": APCUPSClient,  # CyberPower uses same SNMP MIB structure as APC
    "snmp_generic": SNMPGenericClient,
    "ipmi_generic": SNMPGenericClient,  # Generic IPMI fallback (Supermicro, etc.)
    "snmp_network_device": SNMPNetworkDeviceClient,
}


def poll_hardware(hardware: Any, vault: CredentialVault) -> dict:
    """
    Resolves the correct client for a hardware node's telemetry profile,
    executes a poll, and returns normalized data + status string.
    """
    import json

    config = hardware.telemetry_config
    if not config:
        return {}

    # config may be a JSON string (from DB) or a dict
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            return {"error": "Invalid telemetry_config JSON", "status": "unknown"}

    if not config.get("enabled", True):
        return {}

    profile = config.get("profile")
    ClientClass = PROFILE_MAP.get(profile)
    if not ClientClass:
        return {"error": f"Unknown telemetry profile: {profile}", "status": "unknown"}

    host = config.get("host")
    if not host:
        return {"error": "No host configured", "status": "unknown"}
    password = vault.decrypt(config["password"]) if config.get("password") else None

    try:
        client: Any
        # The poll itself happens inside the ExitStack because the iLO branch
        # holds that client's lock for the whole call: building the client and
        # then using it outside the guard would put the Session back in reach of
        # a second thread, which is the whole defect.
        with contextlib.ExitStack() as stack:
            if profile in ("ilo4", "ilo5", "ilo6"):
                cache_key = (profile, host, config.get("username") or "")
                client = stack.enter_context(
                    _pooled_client(
                        cache_key,
                        lambda: ClientClass(host, config.get("username"), password),
                    )
                )
            elif profile in ("apc_ups", "cyberpower_ups"):
                client = ClientClass(host, config.get("snmp_community", "public"))
            elif profile in ("snmp_generic", "ipmi_generic"):
                client = ClientClass(
                    host, config.get("snmp_community", "public"), config.get("custom_oids", {})
                )
            elif profile == "snmp_network_device":
                client = SNMPNetworkDeviceClient(
                    host=config.get("host") or hardware.ip_address,
                    community=config.get("snmp_community") or "public",
                    port=config.get("port") or 161,
                )
            else:
                client = ClientClass(host, config.get("snmp_community", "public"))

            data = client.poll()
            status = client.get_status(data)
        result = {"data": data, "status": status}

        _fire_and_forget_publish(hardware.id, result)
        return result

    except Exception as e:
        error_result = {"error": str(e), "status": "unknown"}
        _fire_and_forget_publish(hardware.id, error_result, ttl=30)
        return error_result


def _fire_and_forget_publish(hardware_id: int, result: dict, ttl: int | None = None) -> None:
    """Schedule async Redis cache+publish without blocking the sync caller."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _logger.debug("Skipping async telemetry publish — no running event loop")
        return
    loop.create_task(_async_cache_and_publish(hardware_id, result, ttl))


async def _async_cache_and_publish(hardware_id: int, result: dict, ttl: int | None = None) -> None:
    from app.services.telemetry_cache import cache_telemetry, publish_telemetry

    try:
        await cache_telemetry(hardware_id, result, ttl=ttl)
        await publish_telemetry(hardware_id, result)
    except Exception as exc:
        # Fires once per polled device per cycle. Throttled and counted so a
        # Redis outage shows up as a number instead of as "the live telemetry
        # panel is blank and nothing in the log says why" (REL-07).
        record_stream_fault(
            "integration_dispatch.publish",
            exc,
            logger=_logger,
            context={"hardware_id": hardware_id},
        )
