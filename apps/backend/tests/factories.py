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
        from app.db.models import Service

        slug = fake.unique.slug()
        defaults = {"name": slug, "slug": slug}
        defaults.update(kwargs)
        svc = Service(**defaults)
        self.session.add(svc)
        self.session.flush()
        return svc

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def webhook(self, target_url: str = "https://hooks.example.com/cb", **kwargs):
        from app.db.models import WebhookRule

        defaults = {
            "name": fake.unique.slug(),
            "target_url": target_url,
            "events_json": '["hardware.created"]',
            "enabled": True,
        }
        defaults.update(kwargs)
        wh = WebhookRule(**defaults)
        self.session.add(wh)
        self.session.flush()
        return wh

    # ── Compute Units ──────────────────────────────────────────────────────

    def compute_unit(self, hardware_id: int | None = None, **kwargs):
        from app.db.models import ComputeUnit

        if hardware_id is None:
            hardware_id = self.hardware().id
        defaults = {
            "name": fake.unique.hostname(),
            "kind": "vm",
            "hardware_id": hardware_id,
        }
        defaults.update(kwargs)
        cu = ComputeUnit(**defaults)
        self.session.add(cu)
        self.session.flush()
        return cu

    # ── Clusters ───────────────────────────────────────────────────────────

    def cluster(self, **kwargs):
        from app.db.models import HardwareCluster

        defaults = {"name": fake.unique.slug()}
        defaults.update(kwargs)
        cl = HardwareCluster(**defaults)
        self.session.add(cl)
        self.session.flush()
        return cl

    # ── External Nodes ─────────────────────────────────────────────────────

    def external_node(self, **kwargs):
        from app.db.models import ExternalNode

        defaults = {
            "name": fake.unique.slug(),
            "provider": "AWS",
            "kind": "vps",
        }
        defaults.update(kwargs)
        en = ExternalNode(**defaults)
        self.session.add(en)
        self.session.flush()
        return en

    # ── Environments ───────────────────────────────────────────────────────

    def environment(self, **kwargs):
        from app.core.time import utcnow_iso
        from app.db.models import Environment

        defaults = {
            "name": fake.unique.slug(),
            "created_at": utcnow_iso(),
        }
        defaults.update(kwargs)
        env = Environment(**defaults)
        self.session.add(env)
        self.session.flush()
        return env

    # ── Misc Items ─────────────────────────────────────────────────────────

    def misc_item(self, **kwargs):
        from app.db.models import MiscItem

        defaults = {"name": fake.unique.slug(), "kind": "cable"}
        defaults.update(kwargs)
        mi = MiscItem(**defaults)
        self.session.add(mi)
        self.session.flush()
        return mi

    # ── Racks ──────────────────────────────────────────────────────────────

    def rack(self, **kwargs):
        from app.db.models import Rack

        defaults = {"name": fake.unique.slug(), "height_u": 42}
        defaults.update(kwargs)
        r = Rack(**defaults)
        self.session.add(r)
        self.session.flush()
        return r

    # ── Storage ────────────────────────────────────────────────────────────

    def storage(self, **kwargs):
        from app.db.models import Storage

        defaults = {"name": fake.unique.slug(), "kind": "disk"}
        defaults.update(kwargs)
        s = Storage(**defaults)
        self.session.add(s)
        self.session.flush()
        return s

    # ── Status Pages ───────────────────────────────────────────────────────

    def status_page(self, **kwargs):
        from app.db.models import StatusPage

        defaults = {
            "name": fake.unique.slug(),
            "slug": fake.unique.slug(),
        }
        defaults.update(kwargs)
        sp = StatusPage(**defaults)
        self.session.add(sp)
        self.session.flush()
        return sp

    # ── Monitor Config ─────────────────────────────────────────────────────

    def monitor_config(self, hardware_id: int | None = None, **kwargs):
        from app.core.time import utcnow_iso
        from app.db.models import HardwareMonitor

        if hardware_id is None:
            hardware_id = self.hardware().id
        defaults = {
            "hardware_id": hardware_id,
            "enabled": True,
            "interval_secs": 60,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
        }
        defaults.update(kwargs)
        mc = HardwareMonitor(**defaults)
        self.session.add(mc)
        self.session.flush()
        return mc

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
