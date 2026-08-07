"""
Sync model factories — create real DB rows via the ORM.
Each factory method returns the model instance after flush (ID assigned).
"""

from faker import Faker

fake = Faker()


class Factories:
    def __init__(self, session):
        self.session = session

    # ── Users ─────────────────────────────────────────────────────────────────

    def user(self, role: str = "viewer", password: str = "TestPassword123!", **kwargs):
        from app.core.security import hash_password
        from app.core.time import utcnow_iso
        from app.db.models import User

        defaults = {
            "email": fake.unique.email(),
            "hashed_password": hash_password(password),
            "role": role,
            "is_admin": role in ("admin", "superuser"),
            "is_superuser": role == "superuser",
            "is_active": True,
            "display_name": fake.name(),
            "provider": "local",
            "created_at": utcnow_iso(),
        }
        defaults.update(kwargs)
        user = User(**defaults)
        self.session.add(user)
        self.session.flush()
        return user

    # ── Hardware ──────────────────────────────────────────────────────────────

    def hardware(self, **kwargs):
        from app.db.models import Hardware

        defaults = {"name": fake.unique.hostname()}
        defaults.update(kwargs)
        hw = Hardware(**defaults)
        self.session.add(hw)
        self.session.flush()
        return hw

    # ── Compute Units ─────────────────────────────────────────────────────────

    def compute_unit(self, **kwargs):
        from app.db.models import ComputeUnit

        defaults = {
            "name": fake.unique.hostname(),
            "kind": "vm",
        }
        defaults.update(kwargs)
        cu = ComputeUnit(**defaults)
        self.session.add(cu)
        self.session.flush()
        return cu

    # ── Networks ──────────────────────────────────────────────────────────────

    def network(self, **kwargs):
        from app.db.models import Network

        defaults = {
            "name": fake.unique.slug(),
            "cidr": "10.0.0.0/24",
        }
        defaults.update(kwargs)
        net = Network(**defaults)
        self.session.add(net)
        self.session.flush()
        return net

    # ── Services ──────────────────────────────────────────────────────────────

    def service(self, **kwargs):
        import re

        from app.db.models import Service

        defaults = {"name": fake.unique.slug()}
        defaults.update(kwargs)
        if "slug" not in defaults:
            defaults["slug"] = re.sub(r"[^a-z0-9]+", "-", defaults["name"].lower()).strip("-")
        svc = Service(**defaults)
        self.session.add(svc)
        self.session.flush()
        return svc

    # ── External nodes ────────────────────────────────────────────────────────

    def external_node(self, **kwargs):
        from app.db.models import ExternalNode

        defaults = {"name": fake.unique.slug(), "provider": "Hetzner", "kind": "vps"}
        defaults.update(kwargs)
        node = ExternalNode(**defaults)
        self.session.add(node)
        self.session.flush()
        return node

    # ── Integrations ──────────────────────────────────────────────────────────

    def integration(self, **kwargs):
        from app.db.models import Integration

        defaults = {
            "type": "uptime_kuma",
            "name": fake.unique.slug(),
            "base_url": "http://uptime-kuma.test:3001",
            "slug": "default",
            "enabled": True,
        }
        defaults.update(kwargs)
        intg = Integration(**defaults)
        self.session.add(intg)
        self.session.flush()
        return intg

    # ── Discovery profiles ────────────────────────────────────────────────────

    def discovery_profile(self, **kwargs):
        from app.db.models import DiscoveryProfile

        defaults = {
            "name": fake.unique.slug(),
            "cidr": "192.168.1.0/24",
            "scan_types_json": '["nmap"]',
            "enabled": True,
        }
        defaults.update(kwargs)
        profile = DiscoveryProfile(**defaults)
        self.session.add(profile)
        self.session.flush()
        return profile

    # ── Agents ────────────────────────────────────────────────────────────────

    def agent(self, status: str = "pending", **kwargs):
        import hashlib
        import secrets

        from app.db.models import Agent

        device_pk = kwargs.pop("device_pk", secrets.token_hex(32))
        defaults = {
            "device_pk": device_pk,
            "fingerprint": hashlib.sha256(bytes.fromhex(device_pk)).hexdigest()[:32],
            "status": status,
            "hostname": fake.hostname(),
            "os": "linux",
            "arch": "amd64",
            "agent_version": "0.1.0",
        }
        defaults.update(kwargs)
        agent = Agent(**defaults)
        self.session.add(agent)
        self.session.flush()
        return agent

    def agent_capability_grant(
        self,
        agent,
        capability: str = "host_telemetry",
        enabled: bool = True,
        **kwargs,
    ):
        from app.db.models import AgentCapabilityGrant

        defaults = {"agent_id": agent.id, "capability": capability, "enabled": enabled}
        defaults.update(kwargs)
        grant = AgentCapabilityGrant(**defaults)
        self.session.add(grant)
        return grant

    def agent_event(self, agent, event_type: str = "enrolled", **kwargs):
        from app.db.models import AgentEvent

        defaults = {"agent_id": agent.id, "event_type": event_type}
        defaults.update(kwargs)
        event = AgentEvent(**defaults)
        self.session.add(event)
        return event

    def agent_network(self, agent, facts=None, **kwargs):
        """The agent's one current `hello.networks` report (D-1).

        `facts` must already be in the normalized form
        `agent_registry.record_network_facts` writes — sorted interfaces, each
        with sorted flags and addresses — since callers that compare against a
        fresh report compare against that.
        """
        from app.core.time import utcnow
        from app.db.models import AgentNetwork

        defaults = {
            "agent_id": agent.id,
            "generation": 1,
            "observed_at": utcnow(),
            "facts": facts
            if facts is not None
            else [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.0.0.5/24"]}],
        }
        defaults.update(kwargs)
        row = AgentNetwork(**defaults)
        self.session.add(row)
        self.session.flush()
        return row

    # ── Agent telemetry ───────────────────────────────────────────────────────

    def agent_host_sample(self, agent, hardware=None, **kwargs):
        """One `agent_host_samples` row.

        `hardware` (or an explicit `hardware_id=`) overrides the agent's own
        link; omitting both mirrors production, where `ingest_host_sample`
        stamps `agent.hardware_id`. `sample_id` defaults to a fresh 32-char
        lowercase hex string so repeated calls never collide on
        `uq_agent_host_sample` (agent_id, sample_id, collected_at).
        """
        import secrets

        from app.core.time import utcnow
        from app.db.models import AgentHostSample

        defaults = {
            "agent_id": agent.id,
            "hardware_id": hardware.id if hardware is not None else agent.hardware_id,
            "sample_id": secrets.token_hex(16),
            "collected_at": utcnow(),
            "status": "healthy",
        }
        defaults.update(kwargs)
        defaults.setdefault(
            "raw",
            {
                "schema": 1,
                "sample_id": defaults["sample_id"],
                "status": defaults["status"],
                "summary": {},
            },
        )
        row = AgentHostSample(**defaults)
        self.session.add(row)
        self.session.flush()
        return row

    def agent_capability_readiness(
        self,
        agent,
        collector: str = "host.core",
        state: str = "ready",
        **kwargs,
    ):
        """One `agent_capability_readiness` row — the composite PK is
        (agent_id, collector), so vary `collector` for multiple rows."""
        from app.core.time import utcnow
        from app.db.models import AgentCapabilityReadiness

        defaults = {
            "agent_id": agent.id,
            "collector": collector,
            "state": state,
            "reason": None,
            "remediation": None,
            "missing": [],
            "updated_at": utcnow(),
        }
        defaults.update(kwargs)
        row = AgentCapabilityReadiness(**defaults)
        self.session.add(row)
        self.session.flush()
        return row

    def agent_host_sample_hourly(self, agent, bucket_at, sample_count: int = 1, summary=None):
        """One `agent_host_sample_hourly` rollup row (PK: agent_id, bucket_at)."""
        from app.db.models import AgentHostSampleHourly

        row = AgentHostSampleHourly(
            agent_id=agent.id,
            bucket_at=bucket_at,
            sample_count=sample_count,
            summary=summary if summary is not None else {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def hardware_live_metric(self, hardware, **kwargs):
        """One `hardware_live_metrics` row — the agent projection target."""
        from app.core.time import utcnow
        from app.db.models import HardwareLiveMetric

        defaults = {
            "hardware_id": hardware.id,
            "collected_at": utcnow(),
            "status": "healthy",
            "source": "agent",
        }
        defaults.update(kwargs)
        row = HardwareLiveMetric(**defaults)
        self.session.add(row)
        self.session.flush()
        return row

    # ── Monitors ──────────────────────────────────────────────────────────────

    def monitor_item(self, **kwargs):
        """One `monitor_items` row — a standalone ICMP monitor by default.

        Pass `probe_agent_id=` to give it a remote vantage; leaving it unset is
        server execution, which is what every pre-Slice-3 monitor is.
        """
        from app.core.time import utcnow
        from app.db.models import MonitorItem

        defaults = {
            "name": fake.unique.slug(),
            "host": fake.ipv4_private(),
            "check_type": "icmp",
            "params": {},
            "interval_secs": 60,
            "next_due_at": utcnow(),
        }
        defaults.update(kwargs)
        item = MonitorItem(**defaults)
        self.session.add(item)
        self.session.flush()
        return item

    def monitor_probe_run(self, monitor, agent, status: str = "queued", **kwargs):
        """One `monitor_probe_runs` lease.

        Not flushed: the partial unique index on the in-flight statuses is a
        thing callers deliberately provoke, so the flush stays with the test.
        `run_id` defaults to a fresh 128-bit hex token, as
        `monitor_service` mints them.
        """
        import secrets

        from app.core.time import utcnow
        from app.db.models import MonitorProbeRun

        defaults = {
            "monitor_id": monitor.id,
            "agent_id": agent.id,
            "run_id": secrets.token_hex(16),
            "status": status,
            "scheduled_at": utcnow(),
        }
        defaults.update(kwargs)
        run = MonitorProbeRun(**defaults)
        self.session.add(run)
        return run
