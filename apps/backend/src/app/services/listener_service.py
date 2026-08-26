"""Always-on mDNS and SSDP listener for Phase 4 Discovery Engine 2.0.

Passively captures device advertisements from the local network without
triggering active scans.  Writes each unique finding to the listener_events
table and publishes a NATS discovery.listener.found message.

Gracefully degrades when zeroconf is unavailable (logs a warning, no crash).
"""

import asyncio
import json
import logging
import socket
import struct
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.core.nats_client import nats_client
from app.core.subjects import DISCOVERY_LISTENER_FOUND, discovery_listener_found_payload
from app.db.models import ListenerEvent
from app.db.session import SessionLocal
from app.services.stream_faults import FAULT_DECODE, record_stream_fault

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
        """Deduplicate, write to DB, and publish NATS event."""
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
                return

            event = ListenerEvent(
                source=source,
                service_type=service_type,
                name=name,
                ip_address=ip_address,
                port=port,
                properties_json=json.dumps(properties) if properties else None,
            )
            db.add(event)
            db.commit()
            _logger.debug("Listener event: %s %s @ %s:%s", source, service_type, ip_address, port)
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
            )
            db.rollback()
        finally:
            db.close()

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
