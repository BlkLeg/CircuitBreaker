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
