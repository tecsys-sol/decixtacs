"""Deterministic demo data for a tenant (``python -m app.cli seed-demo --tenant <slug>``).

Everything goes through the real services - the backup engine (with a fake collector feeding
generated configs, back-dated so the Git history spans the last 30 days), TACACS log ingestion,
the compliance runner, the change-request state machine, the IXP Manager / birdseye sync code
(with canned API payloads) and alerting - so every page of the UI has realistic content. Used by
demos and the end-to-end test suite. Content is driven by a seeded RNG; timestamps are relative to
"now" so the 24h/7d dashboard windows are populated.
"""

from __future__ import annotations

import json
import random
import secrets
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_secret, hash_password, sha256
from app.db.base import utcnow
from app.models import (
    Alert,
    AlertChannel,
    AlertRule,
    ChangeRequest,
    ChangeRequestComment,
    CommandLog,
    ComplianceRun,
    ConfigBackup,
    ConfigIndexEntry,
    ConfigRestore,
    Credential,
    Device,
    DeviceGroup,
    DriftEvent,
    ExternalObject,
    GoldenConfig,
    Group,
    Integration,
    IxpMember,
    Platform,
    Rack,
    Region,
    ReportSchedule,
    Role,
    RoleBinding,
    RouteServerClient,
    SessionRecording,
    Site,
    TacacsAuthEvent,
    TacacsCommandPolicy,
    TacacsConfigRevision,
    TacacsDevice,
    TacacsPolicy,
    TacacsServer,
    TacacsUserMapping,
    Tenant,
    User,
)
from app.services import audit, metrics
from app.services.backup.collector import CollectResult, CollectTarget
from app.services.backup.engine import run_backups
from app.services.bootstrap import seed_global
from app.services.changes import apply_transition
from app.services.compliance.runner import run_compliance
from app.services.integrations import ixpmanager
from app.services.tacacs.crypt import tacacs_crypt
from app.services.tacacs.ingest import ingest_lines

DEMO_PASSWORD = "Demo-Passw0rd-2026"  # demo users only; documented in docs/deployment.md
DEMO_USERS = {
    "alice": ("Alice Engineer", "network-engineers"),
    "bob": ("Bob Operator", "noc-operators"),
    "carol": ("Carol Manager", "change-managers"),
}
DEMO_GROUPS = {"network-engineers": "network-engineer", "noc-operators": "noc", "change-managers": "change-manager"}
SITES = [
    ("fra1", "Frankfurt FRA1", "Europe", 50.1109, 8.6821),
    ("ams1", "Amsterdam AMS1", "Europe", 52.3676, 4.9041),
    ("blr1", "Bangalore BLR1", "APAC", 12.9716, 77.5946),
    ("sin1", "Singapore SIN1", "APAC", 1.3521, 103.8198),
]
# hostname, site, platform, role, model, os_version, group
DEVICES = [
    ("mx204-fra1-core", "fra1", "junos", "core", "MX204", "23.4R2-S2", "Core routers"),
    ("mx10003-fra1-edge", "fra1", "junos", "edge", "MX10003", "22.4R3-S4", "Core routers"),
    ("7280r3-fra1-peer1", "fra1", "eos", "switch", "DCS-7280CR3-32P4", "4.31.2F", "Peering switches"),
    ("7280r3-fra1-peer2", "fra1", "eos", "switch", "DCS-7280CR3-32P4", "4.31.2F", "Peering switches"),
    ("fg600f-fra1-fw", "fra1", "fortios", "firewall", "FortiGate-600F", "7.2.8", "Firewalls"),
    ("mx204-ams1-core", "ams1", "junos", "core", "MX204", "23.4R2-S2", "Core routers"),
    ("7050x3-ams1-peer1", "ams1", "eos", "switch", "DCS-7050SX3-48YC8", "4.30.5M", "Peering switches"),
    ("asr1001x-ams1-ce", "ams1", "ios", "ce", "ASR1001-X", "17.9.4a", "Customer edge"),
    ("mx204-blr1-core", "blr1", "junos", "core", "MX204", "22.4R3-S4", "Core routers"),
    ("isr4451-blr1-ce", "blr1", "ios", "ce", "ISR4451-X", "17.6.6a", "Customer edge"),
    ("fg200f-blr1-fw", "blr1", "fortios", "firewall", "FortiGate-200F", "7.2.8", "Firewalls"),
    ("7280r3-sin1-peer1", "sin1", "eos", "switch", "DCS-7280CR3-32P4", "4.31.2F", "Peering switches"),
    ("asr1001x-sin1-ce", "sin1", "ios", "ce", "ASR1001-X", "17.9.4a", "Customer edge"),
]
UNREACHABLE = "asr1001x-sin1-ce"
PEERS = [
    (13335, "Cloudflare", "AS-CLOUDFLARE"),
    (15169, "Google", "AS-GOOGLE"),
    (20940, "Akamai", "AS-AKAMAI"),
    (2906, "Netflix", "AS-NFLX"),
    (32934, "Meta", "AS-FACEBOOK"),
    (16509, "Amazon", "AS-AMAZON"),
    (8075, "Microsoft", "AS-MICROSOFT"),
    (6939, "Hurricane Electric", "AS-HURRICANE"),
]
RS_ASN = 65000


class DemoExists(RuntimeError):
    pass


@dataclass
class DevState:
    """Configuration state of one demo device; rendered per platform."""

    hostname: str
    platform: str
    idx: int
    ntp: list[str] = field(default_factory=lambda: ["10.255.0.10"])
    syslog: bool = False
    snmp_public: bool = False
    telnet: bool = False
    re_filter: bool = False
    tacacs: bool = True
    vlans: list[int] = field(default_factory=list)
    neighbors: list[tuple[str, int, str]] = field(default_factory=list)
    policies: list[str] = field(default_factory=list)
    customers: int = 1

    def render(self) -> str:
        return {"junos": self._junos, "fortios": self._fortios}.get(self.platform, self._ios_like)()

    def _junos(self) -> str:
        out = [
            f"set system host-name {self.hostname}",
            "set system time-zone UTC",
            "set system login class noc permissions view",
            'set system login user netops authentication encrypted-password "$6$demo$0fT0Kc3y"',
            "set system services ssh protocol-version v2",
        ]
        if self.telnet:
            out.append("set system services telnet")
        if self.tacacs:
            out.append('set system tacplus-server 10.255.0.5 secret "$9$demoKey"')
        out += [f"set system ntp server {n}" for n in self.ntp]
        if self.syslog:
            out.append("set system syslog host 10.255.0.20 any notice")
        out.append(f"set snmp community {'public' if self.snmp_public else 'nom-ro-7f3a'} authorization read-only")
        out.append(f"set interfaces lo0 unit 0 family inet address 10.254.{self.idx}.1/32")
        if self.re_filter:
            out.append("set interfaces lo0 unit 0 family inet filter input PROTECT-RE")
            out.append("set firewall family inet filter PROTECT-RE term ssh from source-prefix-list MGMT")
            out.append("set firewall family inet filter PROTECT-RE term ssh then accept")
        for k in range(self.customers):
            out.append(f'set interfaces xe-0/1/{k} description "CUST-{1000 + self.idx * 10 + k} 10G transit"')
        for v in self.vlans:
            out.append(f'set interfaces ae0 unit {v} description "IX VLAN {v}"')
            out.append(f"set interfaces ae0 unit {v} vlan-id {v}")
        out.append("set protocols bgp group IX type external")
        for ip, asn, desc in self.neighbors:
            out.append(f'set protocols bgp group IX neighbor {ip} description "{desc}"')
            out.append(f"set protocols bgp group IX neighbor {ip} peer-as {asn}")
        out.append("set policy-options community IX-LEARNED members 65000:100")
        return "\n".join(out) + "\n"

    def _ios_like(self) -> str:
        out = [f"hostname {self.hostname}", "!"]
        if self.platform == "ios":
            out.append("ip ssh version 2")
        if self.tacacs:
            out += [
                "tacacs-server host 10.255.0.5 key 7 0822455D0A16",
                "aaa accounting commands 15 default start-stop group tacacs+",
            ]
        out += [f"ntp server {n}" for n in self.ntp]
        if self.syslog:
            out.append("logging host 10.255.0.20")
        out.append(f"snmp-server community {'public' if self.snmp_public else 'nom-ro-7f3a'} ro")
        out.append("!")
        for v in self.vlans:
            out += [f"vlan {v}", f"   name IX-VLAN-{v}", "!"]
        out += ["interface Loopback0", f"   ip address 10.254.{self.idx}.1/32", "!"]
        for k in range(self.customers):
            out += [f"interface Ethernet{k + 1}", f"   description CUST-{1000 + self.idx * 10 + k}", "!"]
        if self.neighbors:
            out.append("router bgp 65000")
            for ip, asn, desc in self.neighbors:
                out.append(f"   neighbor {ip} remote-as {asn}")
                out.append(f"   neighbor {ip} description {desc.replace(' ', '-')}")
            out.append("!")
        out.append("end")
        return "\n".join(out) + "\n"

    def _fortios(self) -> str:
        out = ["config system global", f'    set hostname "{self.hostname}"', '    set timezone "Etc/UTC"', "end"]
        out += ["config system ntp", "    set ntpsync enable", "    config ntpserver"]
        for i, n in enumerate(self.ntp, 1):
            out += [f"        edit {i}", f'            set server "{n}"', "        next"]
        out += ["    end", "end"]
        if self.syslog:
            out += ["config log syslogd setting", "    set status enable", '    set server "10.255.0.20"', "end"]
        if self.tacacs:
            out += [
                "config user tacacs+",
                '    edit "tac-fra1"',
                '        set server "10.255.0.5"',
                "        set key ENC demoKey",
                "    next",
                "end",
            ]
        out += ["config firewall policy"]
        for i, p in enumerate(self.policies, 1):
            out += [
                f"    edit {i}",
                f'        set name "{p}"',
                "        set action accept",
                "        set logtraffic all",
                "    next",
            ]
        out.append("end")
        return "\n".join(out) + "\n"


def _initial_state(rng: random.Random, i: int, hostname: str, platform: str) -> DevState:
    st = DevState(hostname, platform, i)
    st.ntp = ["10.255.0.10"] + (["10.255.0.11"] if rng.random() < 0.5 else [])
    st.syslog = rng.random() < 0.6
    st.snmp_public = hostname in ("mx204-ams1-core", "isr4451-blr1-ce", "7050x3-ams1-peer1")
    st.telnet = hostname == "mx204-blr1-core"
    st.re_filter = platform == "junos" and rng.random() < 0.5
    st.tacacs = hostname != "fg200f-blr1-fw"
    if platform in ("junos", "eos"):
        st.vlans = sorted(rng.sample([100, 200, 300, 400, 444, 445], 2))
        st.neighbors = [(f"185.1.{i}.{10 + k}", asn, name) for k, (asn, name, _) in enumerate(rng.sample(PEERS, 3))]
    if platform == "fortios":
        st.policies = ["MGMT-to-DEVICES", "NOC-to-MONITORING", "OUTBOUND-WEB"]
    return st


def _change_ops(st: DevState, rng: random.Random) -> list[tuple[str, Callable[[], object]]]:
    """(reason, mutation) candidates that make sense for the device right now."""
    ops: list[tuple[str, Callable[[], object]]] = []
    if st.platform != "fortios" and st.customers < 6:
        ops.append(("Provision customer port", lambda: setattr(st, "customers", st.customers + 1)))
    if len(st.ntp) < 2:
        ops.append(("Add secondary NTP server", lambda: st.ntp.append("10.255.0.11")))
    if not st.syslog:
        ops.append(("Send logs to central syslog collector", lambda: setattr(st, "syslog", True)))
    if st.platform in ("junos", "eos"):
        free = [v for v in (447, 500, 501, 600, 601) if v not in st.vlans]
        if free:
            v = free[0]
            ops.append((f"Added new IX VLAN {v}", lambda: st.vlans.append(v)))
        used = {asn for _, asn, _ in st.neighbors}
        cand = [p for p in PEERS if p[0] not in used]
        if cand:
            asn, name, _ = rng.choice(cand)
            ip = f"185.1.{st.idx}.{10 + len(st.neighbors) + rng.randint(3, 40)}"
            ops.append((f"New peering session with AS{asn} {name}", lambda: st.neighbors.append((ip, asn, name))))
        if len(st.neighbors) > 2:
            ops.append(("Remove depeered neighbour", lambda: st.neighbors.pop(0)))
    if st.platform == "junos" and not st.re_filter:
        ops.append(("Apply RE protection filter to lo0", lambda: setattr(st, "re_filter", True)))
    if st.platform == "fortios":
        n = len(st.policies)
        ops.append((f"Allow new monitoring flow #{n}", lambda: st.policies.append(f"MONITORING-{n}")))
    return ops


def _acct_lines(st: DevState, ip: str, user: str, when: datetime, reason: str) -> list[str]:
    ts = lambda d: (when - timedelta(minutes=d)).strftime("%Y-%m-%d %H:%M:%S +0000")  # noqa: E731
    pre = f"\t{ip}\t{user}\tssh\t192.0.2.{10 + len(user)}\tstop"
    if st.platform == "junos":
        cmds = ["configure private", "show | compare", f'commit comment "{reason}"', "exit"]
        svc = "junos-exec"
    elif st.platform == "fortios":
        cmds = ["config firewall policy", "edit 0", "end"]
        svc = "fortigate"
    else:
        cmds = ["configure terminal", "end", "write memory"]
        svc = "shell"
    return [f"{ts(8 - k)}{pre}\tservice={svc}\tcmd={c}" for k, c in enumerate(cmds)]


class _Collector:
    def __init__(self):
        self.configs: dict[str, str] = {}  # device_id -> running config
        self.failing: set[str] = set()

    def __call__(self, targets: list[CollectTarget]) -> list[CollectResult]:
        return [
            CollectResult(t.device_id, False, error="connection timed out after 60s")
            if t.device_id in self.failing
            else CollectResult(
                t.device_id, True, config=self.configs[t.device_id], duration_ms=900 + len(t.hostname) * 37
            )
            for t in targets
        ]


def _backdate(db: Session, tenant_id: uuid.UUID, marker: datetime, when: datetime) -> None:
    """Move alerts/drift events created since ``marker`` (wall clock) to the simulated time."""
    db.flush()
    db.execute(update(Alert).where(Alert.tenant_id == tenant_id, Alert.created_at >= marker).values(created_at=when))
    db.execute(
        update(DriftEvent)
        .where(DriftEvent.tenant_id == tenant_id, DriftEvent.detected_at >= marker)
        .values(detected_at=when)
    )


WIPE_ORDER = [
    ChangeRequestComment,
    ConfigRestore,
    ComplianceRun,
    DriftEvent,
    GoldenConfig,
    ConfigIndexEntry,
    ConfigBackup,
    ChangeRequest,
    Alert,
    AlertRule,
    AlertChannel,
    ReportSchedule,
    RouteServerClient,
    IxpMember,
    ExternalObject,
    TacacsUserMapping,
    TacacsCommandPolicy,
    TacacsPolicy,
    TacacsDevice,
    TacacsConfigRevision,
    TacacsServer,
    CommandLog,
    TacacsAuthEvent,
    SessionRecording,
    Device,
    DeviceGroup,
    Credential,
    Rack,
    Site,
    Region,
]


def wipe(db: Session, tenant: Tenant) -> None:
    """Remove the tenant's inventory/activity data (audit trail and non-demo users are kept)."""
    for model in WIPE_ORDER:
        db.execute(delete(model).where(model.tenant_id == tenant.id).execution_options(synchronize_session=False))
    db.execute(delete(Integration).where(Integration.tenant_id == tenant.id, Integration.name.like("%-demo")))
    demo_users = select(User.id).where(User.tenant_id == tenant.id, User.username.in_(DEMO_USERS))
    db.execute(delete(RoleBinding).where(RoleBinding.user_id.in_(demo_users)))
    db.execute(delete(User).where(User.tenant_id == tenant.id, User.username.in_(DEMO_USERS)))
    db.execute(delete(Group).where(Group.tenant_id == tenant.id, Group.name.in_(DEMO_GROUPS)))
    db.flush()
    s = get_settings()
    shutil.rmtree(Path(s.backup_repo_root) / tenant.slug, ignore_errors=True)
    shutil.rmtree(Path(s.backup_repo_root).parent / "recordings" / str(tenant.id), ignore_errors=True)
    db.expire_all()


def seed_demo(db: Session, tenant: Tenant, *, force: bool = False, seed: int = 42) -> dict[str, int]:
    has_devices = db.scalar(select(func.count()).select_from(Device).where(Device.tenant_id == tenant.id))
    if has_devices and not force:
        raise DemoExists(f"tenant {tenant.slug} already has {has_devices} devices; use --force to wipe and re-seed")
    if force:
        wipe(db, tenant)
    rng = random.Random(seed)  # noqa: S311 - deterministic demo content, not security
    now = utcnow().replace(microsecond=0)
    tid = tenant.id
    seed_global(db)

    # --- people ---------------------------------------------------------------------------
    roles = {r.name: r for r in db.scalars(select(Role).where(Role.tenant_id.is_(None)))}
    groups: dict[str, Group] = {}
    for gname, role in DEMO_GROUPS.items():
        g = Group(tenant_id=tid, name=gname, description=f"Demo group ({role})")
        db.add(g)
        db.flush()
        db.add(RoleBinding(tenant_id=tid, role_id=roles[role].id, group_id=g.id))
        groups[gname] = g
    users: dict[str, User] = {}
    for uname, (full, gname) in DEMO_USERS.items():
        u = User(
            tenant_id=tid,
            username=uname,
            email=f"{uname}@example.net",
            full_name=full,
            password_hash=hash_password(DEMO_PASSWORD),
            password_changed_at=now,
        )
        u.groups = [groups[gname]]
        db.add(u)
        users[uname] = u
    db.flush()

    # --- inventory ------------------------------------------------------------------------
    platforms = {p.slug: p for p in db.scalars(select(Platform))}
    regions: dict[str, Region] = {}
    sites: dict[str, Site] = {}
    for slug, name, region, lat, lon in SITES:
        if region not in regions:
            regions[region] = Region(tenant_id=tid, name=region, slug=region.lower())
            db.add(regions[region])
            db.flush()
        sites[slug] = Site(
            tenant_id=tid, slug=slug, name=name, kind="pop", region_id=regions[region].id, latitude=lat, longitude=lon
        )
        db.add(sites[slug])
    db.flush()
    for s in sites.values():
        db.add(Rack(tenant_id=tid, site_id=s.id, name=f"{s.slug.upper()}-R01"))
    cred = Credential(
        tenant_id=tid, name="demo-backup", username="nom-backup", password_enc=encrypt_secret("demo"), rotated_at=now
    )
    db.add(cred)
    dgroups = {
        name: DeviceGroup(tenant_id=tid, name=name, kind=kind, description=f"Demo: {name.lower()}")
        for name, kind in [
            ("Core routers", "core-routers"),
            ("Peering switches", "custom"),
            ("Firewalls", "firewalls"),
            ("Customer edge", "customer-edge"),
        ]
    }
    db.add_all(dgroups.values())
    db.flush()
    devices: dict[str, Device] = {}
    states: dict[str, DevState] = {}
    for i, (host, site, plat, role, _model, osv, gname) in enumerate(DEVICES, 1):
        p = platforms[plat]
        d = Device(
            tenant_id=tid,
            hostname=host,
            management_ip=f"10.{10 + [s[0] for s in SITES].index(site)}.0.{i}",
            site_id=sites[site].id,
            platform_id=p.id,
            vendor_id=p.vendor_id,
            credential_id=cred.id,
            serial=f"{plat[:2].upper()}{rng.randint(10**7, 10**8 - 1)}",
            os_version=osv,
            role=role,
            tags=["demo", site] + (["ixp"] if role == "switch" else []),
            custom_fields={"model": _model},
        )
        d.groups = [dgroups[gname]]
        db.add(d)
        devices[host] = d
        states[host] = _initial_state(rng, i, host, plat)
    db.flush()

    # --- TACACS+ --------------------------------------------------------------------------
    server = TacacsServer(
        tenant_id=tid, name="tac-fra1", address="10.255.0.5", agent_token_hash=sha256(secrets.token_urlsafe(32))
    )
    db.add(server)
    vendor_map = {"junos": "juniper", "eos": "arista", "ios": "cisco", "fortios": "fortinet"}
    for host, d in devices.items():
        db.add(
            TacacsDevice(
                tenant_id=tid,
                name=host,
                address=d.management_ip,
                device_id=d.id,
                vendor=vendor_map[states[host].platform],
                key_enc=encrypt_secret(secrets.token_urlsafe(24)),
                key_rotated_at=now - timedelta(days=rng.randint(10, 200)),
            )
        )
    eng = TacacsPolicy(
        tenant_id=tid,
        name="engineers-full",
        description="Network engineers: full access, everything accounted",
        priority=10,
        group_id=groups["network-engineers"].id,
        privilege_level=15,
        junos_class="super-user",
        fortigate_profile="super_admin",
        arista_role="network-admin",
        default_action="permit",
    )
    noc = TacacsPolicy(
        tenant_id=tid,
        name="noc-readonly",
        description="NOC: operational commands only",
        priority=20,
        group_id=groups["noc-operators"].id,
        privilege_level=1,
        junos_class="read-only",
        fortigate_profile="prof_admin_ro",
        arista_role="network-operator",
        default_action="deny",
    )
    db.add_all([eng, noc])
    db.flush()
    for seq, (action, pattern, alert) in enumerate(
        [
            ("deny", "^request system (reboot|halt|power-off)", True),
            ("permit", "^show ", False),
            ("permit", "^ping ", False),
            ("permit", "^traceroute ", False),
            ("permit", "^monitor interface", False),
        ],
        1,
    ):
        db.add(
            TacacsCommandPolicy(
                tenant_id=tid, policy_id=noc.id, sequence=seq * 10, action=action, pattern=pattern, alert_on_match=alert
            )
        )
    for uname, u in users.items():
        db.add(
            TacacsUserMapping(
                tenant_id=tid,
                user_id=u.id,
                tacacs_username=uname,
                auth_method="crypt",
                password_crypt=tacacs_crypt(DEMO_PASSWORD),
                valid_until=(now + timedelta(days=90)) if uname == "bob" else None,
            )
        )
    db.flush()

    # --- Git history through the backup engine ---------------------------------------------
    collector = _Collector()
    ids = {h: str(d.id) for h, d in devices.items()}
    stats = {"backups": 0, "changes": 0, "compliance_runs": 0}

    def snapshot(hosts: list[str], when: datetime, **kw) -> list[ConfigBackup]:
        for h in hosts:
            collector.configs[ids[h]] = states[h].render()
        marker = utcnow()
        out = run_backups(db, tid, [devices[h].id for h in hosts], collector=collector, at=when, **kw)
        _backdate(db, tid, marker, when)
        stats["backups"] += len(out)
        return out

    def change(host: str, when: datetime) -> None:
        st = states[host]
        ops = _change_ops(st, rng)
        if not ops:
            return
        why, op = rng.choice(ops)
        op()
        author = rng.choice(["alice", "alice", "bob", "dave"])
        ingest_lines(db, tid, _acct_lines(st, devices[host].management_ip, author, when, why))
        snapshot([host], when)
        stats["changes"] += 1

    def compliance(when: datetime) -> None:
        marker = utcnow()
        run = run_compliance(db, tid)
        run.started_at, run.finished_at = when, when + timedelta(seconds=42)
        _backdate(db, tid, marker, when)
        stats["compliance_runs"] += 1

    # Everything below is scheduled on a plan and executed in time order, so Git history, author
    # correlation (accounting "since the last change") and change-request snapshots line up.
    plan: list[tuple[datetime, int, Callable[[], object]]] = []

    def at(when: datetime, fn: Callable[[], object]) -> None:
        plan.append((when, len(plan), fn))

    start = now - timedelta(days=30)
    at(start, partial(snapshot, list(devices), start, reason="Initial backup"))
    at(start + timedelta(hours=1), partial(compliance, start + timedelta(hours=1)))
    hosts = [h for h in devices if h != UNREACHABLE]
    days = sorted(rng.sample(range(1, 29), 16))
    for day in days:
        for host in rng.sample(hosts, rng.choice([1, 1, 2])):
            when = start + timedelta(days=day, hours=rng.randint(8, 18), minutes=rng.randint(0, 59))
            at(when, partial(change, host, when))
        if day in (days[3], days[8], days[12]):
            when = start + timedelta(days=day, hours=23)
            at(when, partial(compliance, when))

    # --- change requests ------------------------------------------------------------------
    alice, carol = users["alice"], users["carol"]
    perms = {"changes:write", "changes:approve"}
    crs: dict[str, ChangeRequest] = {}

    def new_cr(key: str, title: str, hosts_: list[str], risk: str, created: datetime, **kw) -> None:
        cr = ChangeRequest(
            tenant_id=tid,
            number=len(crs) + 1,
            title=title,
            risk=risk,
            requested_by=alice.id,
            device_ids=[ids[h] for h in hosts_],
            created_at=created,
            implementation_plan="1. Pre-checks\n2. Apply configuration\n3. Verify BGP sessions / ports",
            rollback_plan="Restore the pre-change backup from NetworkOps Manager.",
            **kw,
        )
        db.add(cr)
        db.flush()
        crs[key] = cr

    def step(key: str, name: str, actor: User, when: datetime, comment: str = "") -> None:
        cr = crs[key]
        before = cr.state
        apply_transition(cr, name, actor, perms)
        for attr in ("approved_at", "implemented_at", "closed_at"):
            if getattr(cr, attr) and abs((getattr(cr, attr) - when).total_seconds()) > 60:
                setattr(cr, attr, when)
        db.add(
            ChangeRequestComment(
                tenant_id=tid,
                change_request_id=cr.id,
                author_id=actor.id,
                body=comment,
                transition=f"{before}->{cr.state}",
                created_at=when,
            )
        )
        if name in ("approve", "implement"):
            kind = "pre" if name == "approve" else "post"
            hosts_ = [h for h in devices if ids[h] in cr.device_ids and h != UNREACHABLE]
            backups = snapshot(
                hosts_,
                when,
                trigger="change",
                reason=f"CHG-{cr.number} {kind}-change snapshot",
                change_request_id=cr.id,
            )
            attr = "pre_backup_ids" if kind == "pre" else "post_backup_ids"
            setattr(cr, attr, [*getattr(cr, attr), *(str(b.id) for b in backups)])
        db.flush()

    def cr_change(key: str, host: str, when: datetime, why: str, mutate: Callable[[DevState], object]) -> None:
        mutate(states[host])
        ingest_lines(db, tid, _acct_lines(states[host], devices[host].management_ip, "alice", when, why))
        snapshot([host], when, trigger="change", change_request_id=crs[key].id)
        stats["changes"] += 1

    def script(key: str, created: datetime, title: str, hosts_: list[str], risk: str, steps: list, **kw) -> None:
        at(created, partial(new_cr, key, title, hosts_, risk, created, **kw))
        for offset, what, *rest in steps:
            when = created + offset
            if callable(what):
                at(when, partial(what, when))
            else:
                at(when, partial(step, key, what, *rest[:1], when, *rest[1:]))

    h1, d1 = timedelta(hours=1), timedelta(days=1)
    script(
        "cr1",
        now - 21 * d1,
        "Add IX VLAN 446 to the FRA peering fabric",
        ["7280r3-fra1-peer1"],
        "medium",
        [
            (h1, "submit", alice),
            (5 * h1, "approve", carol, "Approved for the Tuesday window"),
            (
                d1 + h1,
                lambda w: cr_change("cr1", "7280r3-fra1-peer1", w, "Add IX VLAN 446", lambda s: s.vlans.append(446)),
            ),
            (d1 + 2 * h1, "implement", alice, "VLAN live, members notified"),
            (2 * d1, "close", alice, "No incidents"),
        ],
        external_ticket="NOC-4711",
    )
    script(
        "cr6",
        now - 9 * d1,
        "Disable IPv6 RA guard on CE ports",
        ["asr1001x-ams1-ce", "isr4451-blr1-ce"],
        "high",
        [(h1, "submit", alice), (d1, "reject", carol, "Needs a security review first")],
    )
    unpublic = lambda s: setattr(s, "snmp_public", False)  # noqa: E731
    script(
        "cr2",
        now - 4 * d1,
        "Harden SNMP communities on AMS and BLR",
        ["mx204-ams1-core", "isr4451-blr1-ce"],
        "low",
        [
            (timedelta(minutes=20), "submit", alice),
            (3 * h1, "approve", carol, "OK - low risk"),
            (d1, lambda w: cr_change("cr2", "mx204-ams1-core", w, "Remove public SNMP community", unpublic)),
            (d1 + h1 / 4, lambda w: cr_change("cr2", "isr4451-blr1-ce", w, "Remove public SNMP community", unpublic)),
            (d1 + h1 / 2, "implement", alice, "Both devices done"),
        ],
    )
    script(
        "cr3",
        now - 2 * d1,
        "Upgrade Junos on mx204-blr1-core to 23.4R2-S2",
        ["mx204-blr1-core"],
        "high",
        [(h1 / 6, "submit", alice), (6 * h1, "approve", carol, "Make sure traffic is drained first")],
        scheduled_start=now + 5 * d1,
        scheduled_end=now + 5 * d1 + 2 * h1,
    )
    script(
        "cr4",
        now - 20 * h1,
        "New peering session with AS6939 at SIN1",
        ["7280r3-sin1-peer1"],
        "medium",
        [(h1, "submit", alice)],
    )
    script(
        "cr5",
        now - 6 * h1,
        "Migrate syslog to the new collector",
        ["mx204-fra1-core", "mx204-ams1-core", "7280r3-fra1-peer1", "fg600f-fra1-fw"],
        "low",
        [],
    )

    # --- golden config, a late change, last compliance run ---------------------------------
    def golden(_when: datetime) -> None:
        db.add(
            GoldenConfig(
                tenant_id=tid,
                name="Junos NTP + syslog baseline",
                device_group_id=dgroups["Core routers"].id,
                mode="snippet",
                content="set system ntp server 10.255.0.10\nset system ntp server 10.255.0.11\n"
                "set system syslog host 10.255.0.20 any notice\n",
            )
        )
        db.flush()

    when = now - d1 - 4 * h1
    at(when, partial(golden, when))
    at(when + h1, partial(change, "mx204-fra1-core", when + h1))
    at(now - d1, partial(compliance, now - d1))
    for _when, _, fn in sorted(plan, key=lambda x: (x[0], x[1])):
        fn()

    # --- TACACS accounting / authentication (last 7 days) + final poll ---------------------
    ops_cmds = [
        "show bgp summary",
        "show interfaces terse",
        "show log messages | last 50",
        "show route 185.1.0.0/16",
        "ping 185.1.1.10 count 5",
        "show ip bgp summary",
        "show interfaces status",
        "traceroute 8.8.8.8",
        "show system alarms",
        "show lldp neighbors",
    ]
    lines: list[str] = []
    for k in range(260):
        when = now - timedelta(minutes=rng.randint(5, 7 * 24 * 60))
        host = rng.choice(hosts)
        user = rng.choice(["alice", "bob", "bob", "carol", "dave"])
        ts = when.strftime("%Y-%m-%d %H:%M:%S +0000")
        ip, src = devices[host].management_ip, f"192.0.2.{10 + len(user)}"
        lines.append(f"{ts}\t{ip}\t{user}\tssh\t{src}\tstop\ttask_id={k}\tcmd={rng.choice(ops_cmds)}")
        if k % 4 == 0:
            lines.append(f"{ts}\t{ip}\t{user}\tssh\t{src}\tshell login succeeded")
        if k % 5 == 0:
            lines.append(f"{ts}\t{ip}\t{user}\tssh\t{src}\tpermit\tcmd={rng.choice(ops_cmds)}")
    for _ in range(6):
        ts = (now - timedelta(hours=rng.randint(1, 20))).strftime("%Y-%m-%d %H:%M:%S +0000")
        lines.append(f"{ts}\t{devices['mx204-fra1-core'].management_ip}\tadmin\tssh\t203.0.113.66\tshell login failed")
    ts = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S +0000")
    lines.append(
        f"{ts}\t{devices['mx204-ams1-core'].management_ip}\tbob\tssh\t192.0.2.13\tdeny\tcmd=request system reboot"
    )
    marker = utcnow()
    acct = ingest_lines(db, tid, lines)
    _backdate(db, tid, marker, now - timedelta(hours=3))
    collector.failing.add(ids[UNREACHABLE])
    snapshot(list(devices), now - timedelta(minutes=35))
    compliance(now - timedelta(minutes=30))

    # --- session recordings ---------------------------------------------------------------
    rec_root = Path(get_settings().backup_repo_root).parent / "recordings" / str(tid)
    rec_root.mkdir(parents=True, exist_ok=True)
    for user, host, cmds in [
        ("alice", "mx204-fra1-core", ["show bgp summary", "show interfaces terse ae0", "exit"]),
        ("bob", "7280r3-fra1-peer1", ["show interfaces status", "show vlan", "exit"]),
    ]:
        began = now - timedelta(hours=rng.randint(2, 30))
        events, tcur, typed = [], 0.4, []
        prompt = f"{user}@{host}> " if states[host].platform == "junos" else f"{host}#"
        events.append([tcur, "o", prompt])
        for c in cmds:
            tcur += 1.2
            events.append([round(tcur, 3), "i", c + "\r"])
            typed.append({"t": round(tcur, 3), "cmd": c})
            tcur += 0.6
            events.append([round(tcur, 3), "o", f"\r\n... output of '{c}' ...\r\n{prompt}"])
        cast = (
            "\n".join(
                [json.dumps({"version": 2, "width": 120, "height": 40, "timestamp": int(began.timestamp())})]
                + [json.dumps(e) for e in events]
            )
            + "\n"
        )
        rid = uuid.uuid4()
        path = rec_root / f"{rid}.cast"
        path.write_text(cast)
        db.add(
            SessionRecording(
                id=rid,
                tenant_id=tid,
                username=user,
                device_id=devices[host].id,
                device_address=devices[host].management_ip,
                source_address="192.0.2.50",
                started_at=began,
                ended_at=began + timedelta(seconds=tcur),
                duration_s=tcur,
                storage_uri=f"file://{path}",
                size_bytes=len(cast.encode()),
                sha256=sha256(cast),
                commands=typed,
            )
        )

    # --- IXP Manager + route server (real sync code, canned API payloads) -------------------
    class _Ixf:
        def ixf_export(self) -> dict:
            members = []
            for k, (asn, name, macro) in enumerate(PEERS):
                members.append(
                    {
                        "asnum": asn,
                        "name": name,
                        "url": f"https://www.peeringdb.com/asn/{asn}",
                        "peering_policy": rng.choice(["open", "selective", "open"]),
                        "member_type": "peering",
                        "contact_email": [f"peering@as{asn}.example"],
                        "connection_list": [
                            {
                                "state": "active",
                                "if_list": [{"switch_id": 1 + k % 2, "if_speed": rng.choice([10000, 100000, 400000])}],
                                "vlan_list": [
                                    {
                                        "vlan_id": 1,
                                        "ipv4": {
                                            "address": f"185.1.1.{10 + k}",
                                            "routeserver": k != 5,
                                            "as_macro": macro,
                                            "max_prefix": 1000 * (k + 1),
                                        },
                                        "ipv6": {"address": f"2001:7f8:1::{asn:x}:1", "routeserver": k != 5},
                                    }
                                ],
                            }
                        ],
                    }
                )
            return {
                "ixp_list": [
                    {
                        "switch": [{"id": 1, "name": "7280r3-fra1-peer1"}, {"id": 2, "name": "7280r3-fra1-peer2"}],
                        "vlan": [{"id": 1, "name": "Peering LAN FRA"}],
                    }
                ],
                "member_list": members,
            }

    class _Birdseye:
        def bgp_protocols(self) -> dict:
            out = {}
            for k, (asn, _, _) in enumerate(PEERS):
                if k == 5:
                    continue
                out[f"pb_{k + 1:04d}_as{asn}"] = {
                    "neighbor_address": f"185.1.1.{10 + k}",
                    "neighbor_as": asn,
                    "state": "down" if k == 7 else "up",
                    "state_changed": (now - timedelta(days=rng.randint(1, 60))).strftime("%Y-%m-%d %H:%M:%S"),
                    "routes": {
                        "imported": 0 if k == 7 else rng.randint(50, 12000),
                        "filtered": [0, 3, 0, 12, 0, 0, 1, 0][k],
                        "exported": rng.randint(150000, 190000),
                    },
                }
            return out

        def filtered_routes(self, protocol: str) -> list[dict]:
            k = int(protocol[3:7]) - 1
            n = [0, 3, 0, 12, 0, 0, 1, 0][k]
            codes = [[RS_ASN, 1101, 9], [RS_ASN, 1101, 12], [RS_ASN, 1101, 3]]
            return [{"bgp": {"large_communities": [codes[j % len(codes)]]}} for j in range(n)]

    ixp_int = Integration(
        tenant_id=tid,
        kind="ixpmanager",
        name="ixpmanager-demo",
        base_url="https://ixp.demo.invalid",
        enabled=False,
        options={"demo": True},
    )
    rs_int = Integration(
        tenant_id=tid,
        kind="birdseye",
        name="rs1-fra-v4-demo",
        base_url="https://rs1-fra.demo.invalid",
        enabled=False,
        options={"name": "rs1-fra-v4", "rs_asn": RS_ASN, "filter_reasons": True, "demo": True},
    )
    db.add_all([ixp_int, rs_int])
    db.flush()
    ixpmanager.sync_members(db, ixp_int, client=_Ixf())
    ixpmanager.sync_route_server(db, rs_int, client=_Birdseye())

    # --- alerting config, acknowledge old alerts -------------------------------------------
    ch = AlertChannel(
        tenant_id=tid,
        name="NOC mailbox (demo)",
        kind="email",
        target_enc=encrypt_secret("noc@example.net"),
        enabled=False,
    )
    db.add(ch)
    db.flush()
    db.add(
        AlertRule(
            tenant_id=tid,
            name="Backup failures to NOC",
            event_type="backup_failed",
            min_severity="medium",
            channel_ids=[str(ch.id)],
        )
    )
    db.add(
        ReportSchedule(
            tenant_id=tid,
            name="Weekly compliance",
            report_type="compliance",
            period="weekly",
            fmt="pdf",
            recipients=["noc@example.net"],
            enabled=False,
        )
    )
    db.execute(
        update(Alert)
        .where(Alert.tenant_id == tid, Alert.created_at < now - timedelta(days=5))
        .values(
            acknowledged_at=now - timedelta(days=4),
            acknowledged_by=db.scalar(select(User.id).where(User.tenant_id == tid, User.username == "bob")),
        )
    )
    audit.record(
        db,
        tenant_id=tid,
        action="demo.seed",
        actor_name="seed-demo",
        after={"seed": seed, **stats, "accounting": acct["accounting"], "auth": acct["auth"]},
    )
    db.flush()
    metrics.safe_refresh_device_gauge(db)
    return {
        "devices": len(devices),
        "users": len(users),
        **stats,
        "accounting_records": acct["accounting"],
        "auth_events": acct["auth"],
        "change_requests": len(crs),
        "ixp_members": len(PEERS),
        "alerts": db.scalar(select(func.count()).select_from(Alert).where(Alert.tenant_id == tid)) or 0,
    }
