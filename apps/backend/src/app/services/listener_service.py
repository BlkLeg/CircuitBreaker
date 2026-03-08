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

from app.core.nats_client import nats_client
from app.core.subjects import DISCOVERY_LISTENER_FOUND, discovery_listener_found_payload
from app.db.models import ListenerEvent
from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)

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

    # ── Public API ───────────────────────────────────────────────────────────

    async def start(self, settings) -> None:
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
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._zeroconf:
            await asyncio.get_event_loop().run_in_executor(None, self._zeroconf.close)
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
                def __init__(inner_self):
                    pass

                def add_service(inner_self, zc, type_, name):
                    asyncio.run_coroutine_threadsafe(
                        self._handle_mdns_service(zc, type_, name), loop
                    )

                def remove_service(inner_self, zc, type_, name):
                    pass

                def update_service(inner_self, zc, type_, name):
                    asyncio.run_coroutine_threadsafe(
                        self._handle_mdns_service(zc, type_, name), loop
                    )

            await loop.run_in_executor(
                None, lambda: ServiceBrowser(self._zeroconf, _MDNS_SERVICES, _Handler())
            )
            self.mdns_active = True
            _logger.info("mDNS browser started for %d service types.", len(_MDNS_SERVICES))

            # Keep alive until cancelled
            while self.is_running:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _logger.warning("mDNS listener error: %s", exc)
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
                except Exception:
                    pass

            port = info.port
            props: dict = {}
            try:
                props = {
                    k.decode(errors="replace"): v.decode(errors="replace")
                    if isinstance(v, bytes)
                    else v
                    for k, v in (info.properties or {}).items()
                }
            except Exception:
                pass

            await self._record_event(
                source="mdns",
                service_type=type_,
                name=name,
                ip_address=ip,
                port=port,
                properties=props,
            )
        except Exception as exc:
            _logger.debug("mDNS service info error for %s: %s", name, exc)

    # ── SSDP via raw UDP ─────────────────────────────────────────────────────

    async def _run_ssdp(self) -> None:
        """Listen for SSDP NOTIFY and M-SEARCH responses via UDP multicast."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # not available on all platforms
            sock.bind(("", _SSDP_PORT))
            mcast_req = struct.pack("4sL", socket.inet_aton(_SSDP_ADDR), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mcast_req)
            sock.setblocking(False)

            loop = asyncio.get_running_loop()
            self.ssdp_active = True
            _logger.info("SSDP socket bound on %s:%d.", _SSDP_ADDR, _SSDP_PORT)

            # Send M-SEARCH to trigger responses from devices
            try:
                send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                send_sock.sendto(_SSDP_M_SEARCH.encode(), (_SSDP_ADDR, _SSDP_PORT))
                send_sock.close()
            except Exception:
                pass

            while self.is_running:
                try:
                    data, addr = await loop.run_in_executor(None, lambda: sock.recvfrom(4096))
                    await self._handle_ssdp_packet(data.decode(errors="replace"), addr[0])
                except (BlockingIOError, OSError):
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    _logger.debug("SSDP recv error: %s", exc)
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _logger.warning("SSDP listener error: %s", exc)
        finally:
            self.ssdp_active = False

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
            _logger.warning("Failed to record listener event: %s", exc)
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
        except Exception:
            pass


# Singleton instance imported by main.py
listener_service = ListenerService()
