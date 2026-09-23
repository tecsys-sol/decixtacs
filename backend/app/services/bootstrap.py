"""Seeding: RBAC catalogue, platforms/vendors, default compliance rules, first tenant + admin."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    PasswordPolicyError,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    validate_password_policy,
)
from app.models import ComplianceRule, Integration, Platform, Role, RoleBinding, Tenant, User, Vendor
from app.services import audit
from app.services.backup.collector import DEFAULT_PLATFORMS
from app.services.compliance.engine import DEFAULT_RULES
from app.services.rbac import seed_rbac

VENDOR_NAMES = {
    "juniper": "Juniper Networks",
    "arista": "Arista Networks",
    "cisco": "Cisco Systems",
    "fortinet": "Fortinet",
    "sophos": "Sophos",
    "mikrotik": "MikroTik",
    "vyos": "VyOS",
    "linux": "Linux",
}


def seed_platforms(db: Session) -> None:
    vendors = {v.slug: v for v in db.scalars(select(Vendor))}
    for slug, name in VENDOR_NAMES.items():
        if slug not in vendors:
            vendors[slug] = Vendor(slug=slug, name=name)
            db.add(vendors[slug])
    db.flush()
    existing = {p.slug for p in db.scalars(select(Platform))}
    for p in DEFAULT_PLATFORMS:
        if p["slug"] in existing:
            continue
        db.add(
            Platform(
                slug=p["slug"],
                name=p["name"],
                vendor_id=vendors[p["vendor"]].id,
                scrapli_platform=p.get("scrapli"),
                netmiko_device_type=p.get("netmiko"),
                backup_commands=p["commands"],
                tacacs_service=p.get("tacacs_service", "shell"),
                supports_tacacs=p.get("supports_tacacs", True),
                supports_config_replace=p.get("replace", False),
            )
        )
    db.flush()


def seed_global(db: Session) -> None:
    seed_rbac(db)
    seed_platforms(db)


def create_tenant(
    db: Session,
    name: str,
    slug: str,
    admin_username: str,
    admin_password: str,
    admin_email: str | None = None,
    superuser: bool = False,
) -> Tenant:
    try:
        validate_password_policy(admin_password, admin_username)
    except PasswordPolicyError as e:
        raise ValueError(str(e)) from e
    seed_global(db)
    t = Tenant(name=name, slug=slug)
    db.add(t)
    db.flush()
    admin = User(
        tenant_id=t.id,
        username=admin_username,
        email=admin_email,
        full_name="Tenant administrator",
        password_hash=hash_password(admin_password),
        is_superuser=superuser,
    )
    db.add(admin)
    db.flush()
    role = db.scalar(select(Role).where(Role.name == "admin", Role.tenant_id.is_(None)))
    db.add(RoleBinding(tenant_id=t.id, role_id=role.id, user_id=admin.id))
    for r in DEFAULT_RULES:
        db.add(ComplianceRule(tenant_id=t.id, **{k: v for k, v in r.items()}))
    db.flush()
    return t


# Integration rows managed from NOM_NETBOX_* / NOM_IXPMANAGER_* (bootstrap defaults).
ENV_INTEGRATIONS = {"netbox": "netbox-env", "ixpmanager": "ixpmanager-env"}


def integrations_from_env(db: Session, tenant: Tenant) -> dict[str, str]:
    """Create/update the tenant's env-managed NetBox / IXP Manager integrations from settings.

    Returns ``{kind: "created"|"updated"|"unchanged"}`` for every kind whose URL is set. Rows are
    matched on (tenant, kind, name) so integrations created in the UI are never touched.
    """
    s = get_settings()
    wanted = {"netbox": (s.netbox_url, s.netbox_token), "ixpmanager": (s.ixpmanager_url, s.ixpmanager_api_key)}
    out: dict[str, str] = {}
    for kind, (url, token) in wanted.items():
        if not url:
            continue
        name = ENV_INTEGRATIONS[kind]
        row = db.scalar(
            select(Integration).where(
                Integration.tenant_id == tenant.id, Integration.kind == kind, Integration.name == name
            )
        )
        if row is None:
            row = Integration(tenant_id=tenant.id, kind=kind, name=name, base_url=url, options={"managed_by": "env"})
            row.token_enc = encrypt_secret(token) if token else None
            db.add(row)
            out[kind] = "created"
        elif row.base_url != url or (decrypt_secret(row.token_enc) or "") != token:
            row.base_url = url
            row.token_enc = encrypt_secret(token) if token else None
            out[kind] = "updated"
        else:
            out[kind] = "unchanged"
        if out[kind] != "unchanged":
            db.flush()
            audit.record(
                db,
                tenant_id=tenant.id,
                action=f"integration.{out[kind][:-1]}",
                actor_name="bootstrap",
                target_type="integration",
                target_id=row.id,
                target_name=name,
                after={"kind": kind, "base_url": url, "source": "environment"},
            )
    return out
