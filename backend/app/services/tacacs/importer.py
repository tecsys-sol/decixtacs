"""Apply a Shrubbery tac_plus import plan to a tenant (dry-run capable)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import encrypt_secret
from app.db.base import utcnow
from app.models import Device, Group, TacacsCommandPolicy, TacacsDevice, TacacsPolicy, TacacsUserMapping, User
from app.services.tacacs.crypt import tacacs_crypt
from app.services.tacacs.shrubbery import ImportPlan, build_plan, parse

VENDOR_MAP = {
    "juniper": "juniper",
    "cisco": "cisco",
    "arista": "arista",
    "fortinet": "fortinet",
    "sophos": "sophos",
    "mikrotik": "mikrotik",
}


@dataclass
class ImportResult:
    created: dict[str, list[str]] = field(
        default_factory=lambda: {"nas": [], "groups": [], "policies": [], "users": [], "mappings": []}
    )
    skipped: dict[str, list[str]] = field(
        default_factory=lambda: {"nas": [], "groups": [], "policies": [], "users": [], "mappings": []}
    )
    warnings: list[str] = field(default_factory=list)
    users_needing_password: list[str] = field(default_factory=list)


def import_config(db: Session, tenant_id: uuid.UUID, text: str) -> ImportResult:
    """Parse + apply. The caller commits (real import) or rolls back (dry run)."""
    plan: ImportPlan = build_plan(parse(text))
    res = ImportResult(warnings=list(plan.warnings))

    # --- NAS clients (existing keys preserved; matched to inventory by management IP)
    devices = {
        d.management_ip: d
        for d in db.scalars(select(Device).where(Device.tenant_id == tenant_id).options(selectinload(Device.vendor)))
    }
    existing_nas = list(db.scalars(select(TacacsDevice).where(TacacsDevice.tenant_id == tenant_id)))
    names = {n.name for n in existing_nas}
    addrs = {n.address for n in existing_nas}
    for n in plan.nas:
        dev = devices.get(n.address)
        name = dev.hostname if dev else n.name
        if name in names or n.address in addrs:
            res.skipped["nas"].append(f"{name} ({n.address})")
            continue
        vendor = VENDOR_MAP.get(dev.vendor.slug, "generic") if dev and dev.vendor else "generic"
        db.add(
            TacacsDevice(
                tenant_id=tenant_id,
                name=name,
                address=n.address,
                key_enc=encrypt_secret(n.key),
                vendor=vendor,
                device_id=dev.id if dev else None,
                key_rotated_at=utcnow(),
            )
        )
        names.add(name)
        addrs.add(n.address)
        res.created["nas"].append(f"{name} ({n.address})")

    # --- groups
    groups = {g.name: g for g in db.scalars(select(Group).where(Group.tenant_id == tenant_id))}
    for gname in plan.groups:
        if gname in groups:
            res.skipped["groups"].append(gname)
            continue
        groups[gname] = Group(tenant_id=tenant_id, name=gname, description="Imported from tac_plus")
        db.add(groups[gname])
        res.created["groups"].append(gname)
    db.flush()

    # --- policies
    existing_pol = set(db.scalars(select(TacacsPolicy.name).where(TacacsPolicy.tenant_id == tenant_id)))
    for p in plan.policies:
        if p.name in existing_pol:
            res.skipped["policies"].append(p.name)
            continue
        pol = TacacsPolicy(
            tenant_id=tenant_id,
            name=p.name,
            description=f"Imported from tac_plus group/user '{p.group}'",
            priority=p.priority,
            group_id=groups[p.group].id,
            privilege_level=max(0, min(15, p.privilege_level)),
            junos_class=p.junos_class,
            fortigate_profile=p.fortigate_profile,
            extra_attributes=p.extra_attributes,
            default_action=p.default_action,
        )
        seq = 10
        rules = []
        for action, rx in p.rules:
            try:
                re.compile(rx)
            except re.error as e:
                res.warnings.append(f"policy {p.name}: rule /{rx}/ is not a valid regex ({e}) - skipped")
                continue
            if len(rx) > 512:
                res.warnings.append(f"policy {p.name}: rule longer than 512 characters skipped")
                continue
            rules.append(TacacsCommandPolicy(tenant_id=tenant_id, sequence=seq, action=action, pattern=rx))
            seq += 10
        pol.command_rules = rules
        db.add(pol)
        res.created["policies"].append(p.name)

    # --- users + TACACS mappings
    users = {
        u.username: u
        for u in db.scalars(select(User).where(User.tenant_id == tenant_id).options(selectinload(User.groups)))
    }
    mapped = set(db.scalars(select(TacacsUserMapping.tacacs_username).where(TacacsUserMapping.tenant_id == tenant_id)))
    for pu in plan.users:
        user = users.get(pu.username)
        if user is None:
            # No portal password: the account exists for TACACS only until someone sets one.
            user = User(tenant_id=tenant_id, username=pu.username, full_name=pu.full_name, auth_source="local")
            db.add(user)
            users[pu.username] = user
            res.created["users"].append(pu.username)
        else:
            res.skipped["users"].append(pu.username)
        for gname in pu.groups:
            if gname in groups and groups[gname] not in user.groups:
                user.groups.append(groups[gname])
        db.flush()
        if pu.username in mapped:
            res.skipped["mappings"].append(pu.username)
            continue
        crypt_hash = pu.password_crypt or (tacacs_crypt(pu.cleartext) if pu.cleartext is not None else None)
        if crypt_hash is None:
            res.users_needing_password.append(pu.username)
        db.add(
            TacacsUserMapping(
                tenant_id=tenant_id,
                user_id=user.id,
                tacacs_username=pu.username,
                auth_method="crypt",
                password_crypt=crypt_hash,
                enabled=True,
                valid_until=pu.valid_until,
            )
        )
        mapped.add(pu.username)
        res.created["mappings"].append(pu.username)
    db.flush()
    return res
