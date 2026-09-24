"""Apply a Shrubbery tac_plus import plan to a tenant (dry-run capable)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import decrypt_secret, encrypt_secret
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
    # same name/address already in the portal but defined differently in this file (kept as in the portal)
    conflicts: list[str] = field(default_factory=list)
    # changes applied to existing objects (e.g. extra group memberships)
    updated: list[str] = field(default_factory=list)


# crypt(3) schemes tac_plus/tac_pwd and the portal produce - used to check a cleartext password
# from the file against an existing hash.
_CRYPT = CryptContext(schemes=["sha512_crypt", "sha256_crypt", "md5_crypt", "des_crypt"])


def _same_password(existing_hash: str | None, new_hash: str | None, cleartext: str | None) -> bool | None:
    """True/False when it can be decided, None when two different hashes may still hide the same password."""
    if cleartext is not None:
        if not existing_hash:
            return False
        try:
            return _CRYPT.verify(cleartext, existing_hash)
        except (ValueError, TypeError):
            return None
    if new_hash is None or existing_hash is None:
        return new_hash == existing_hash
    return True if new_hash == existing_hash else None


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
    by_addr = {n.address: n for n in existing_nas}
    for n in plan.nas:
        dev = devices.get(n.address)
        name = dev.hostname if dev else n.name
        if n.address in by_addr:
            res.skipped["nas"].append(f"{name} ({n.address})")
            old = by_addr[n.address]
            if old is not None and old.key_enc and decrypt_secret(old.key_enc) != n.key:
                res.conflicts.append(
                    f"NAS {n.address}: shared key differs from the portal's '{old.name}' - "
                    "devices using this server's key would fail after the cut-over"
                )
            continue
        if name in names:
            res.skipped["nas"].append(f"{name} ({n.address})")
            res.conflicts.append(f"NAS name '{name}' already exists with a different address than {n.address}")
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
        by_addr[n.address] = None  # type: ignore[assignment]
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
    existing_pol = {
        p.name: p
        for p in db.scalars(
            select(TacacsPolicy)
            .where(TacacsPolicy.tenant_id == tenant_id)
            .options(selectinload(TacacsPolicy.command_rules))
        )
    }
    for p in plan.policies:
        if p.name in existing_pol:
            res.skipped["policies"].append(p.name)
            diff = _policy_diff(existing_pol[p.name], p)
            if diff:
                res.conflicts.append(f"policy {p.name} (group '{p.group}'): {'; '.join(diff)}")
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
    mapped = {
        m.tacacs_username: m
        for m in db.scalars(select(TacacsUserMapping).where(TacacsUserMapping.tenant_id == tenant_id))
    }
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
        added = [g for g in pu.groups if g in groups and groups[g] not in user.groups]
        for gname in added:
            user.groups.append(groups[gname])
        if added and pu.username not in res.created["users"]:
            res.updated.append(f"user {pu.username}: added to group(s) {', '.join(added)}")
        db.flush()
        if pu.username in mapped:
            res.skipped["mappings"].append(pu.username)
            m = mapped[pu.username]
            if m is None:  # defined twice in this file
                continue
            same = _same_password(m.password_crypt, pu.password_crypt, pu.cleartext)
            if same is False:
                res.conflicts.append(f"user {pu.username}: password differs from the portal's - the portal's is kept")
            elif same is None:
                res.conflicts.append(
                    f"user {pu.username}: password hash differs from the portal's (may be the same "
                    "password with another salt) - the portal's is kept; confirm with the user"
                )
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
        mapped[pu.username] = None  # type: ignore[assignment]
        res.created["mappings"].append(pu.username)
    db.flush()
    return res


def _policy_diff(existing: TacacsPolicy, planned) -> list[str]:
    out = []
    if existing.privilege_level != planned.privilege_level:
        out.append(f"priv-lvl {existing.privilege_level} in portal vs {planned.privilege_level} in file")
    if existing.default_action != planned.default_action:
        out.append(f"default service {existing.default_action} vs {planned.default_action}")
    if (existing.junos_class or None) != (planned.junos_class or None):
        out.append(f"Junos class {existing.junos_class} vs {planned.junos_class}")
    if (existing.fortigate_profile or None) != (planned.fortigate_profile or None):
        out.append(f"FortiGate profile {existing.fortigate_profile} vs {planned.fortigate_profile}")
    old_rules = [(r.action, r.pattern) for r in sorted(existing.command_rules, key=lambda r: r.sequence)]
    if old_rules != list(planned.rules):
        added = [f"{a} /{p}/" for a, p in planned.rules if (a, p) not in old_rules]
        removed = [f"{a} /{p}/" for a, p in old_rules if (a, p) not in planned.rules]
        detail = []
        if added:
            detail.append("only in file: " + ", ".join(added[:5]))
        if removed:
            detail.append("only in portal: " + ", ".join(removed[:5]))
        out.append("command rules differ" + (f" ({'; '.join(detail)})" if detail else " (order)"))
    return out
