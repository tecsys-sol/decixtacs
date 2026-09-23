"""Assemble generator input from the database for one tenant."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.models import DeviceGroup, Group, TacacsDevice, TacacsPolicy, TacacsServer, TacacsUserMapping
from app.services.tacacs import generator as g


def build_inputs(db: Session, tenant_id: uuid.UUID, server: TacacsServer | None = None):
    s = get_settings()
    groups = {gr.id: gr for gr in db.scalars(select(Group).where(Group.tenant_id == tenant_id))}
    dgroups = {
        dg.id: dg
        for dg in db.scalars(
            select(DeviceGroup).where(DeviceGroup.tenant_id == tenant_id).options(selectinload(DeviceGroup.devices))
        )
    }
    device_tags: dict[uuid.UUID, list[str]] = {}
    for dg in dgroups.values():
        for d in dg.devices:
            device_tags.setdefault(d.id, []).append(dg.name)

    nas: list[g.NasEntry] = []
    for td in db.scalars(select(TacacsDevice).where(TacacsDevice.tenant_id == tenant_id, TacacsDevice.enabled)):
        tags = list(device_tags.get(td.device_id, [])) if td.device_id else []
        if td.device_group_id and td.device_group_id in dgroups:
            tags.append(dgroups[td.device_group_id].name)
        nas.append(g.NasEntry(td.name, td.address, decrypt_secret(td.key_enc) or "", td.vendor, tags))

    profiles: list[g.Profile] = []
    policies = db.scalars(
        select(TacacsPolicy)
        .where(TacacsPolicy.tenant_id == tenant_id, TacacsPolicy.enabled)
        .options(selectinload(TacacsPolicy.command_rules))
    )
    for p in policies:
        grp = groups.get(p.group_id)
        if grp is None:
            continue
        profiles.append(
            g.Profile(
                name=p.name,
                group=grp.name,
                priority=p.priority,
                privilege_level=p.privilege_level,
                device_tags=[dgroups[p.device_group_id].name] if p.device_group_id in dgroups else [],
                commands=[g.CommandRule(r.action, r.pattern, r.sequence) for r in p.command_rules],  # type: ignore[arg-type]
                default_action=p.default_action,  # type: ignore[arg-type]
                junos_class=p.junos_class,
                fortigate_profile=p.fortigate_profile,
                arista_role=p.arista_role,
                extra_attributes=p.extra_attributes or {},
                timespan=p.time_window,
            )
        )

    users: list[g.TacUser] = []
    mappings = db.scalars(
        select(TacacsUserMapping).where(TacacsUserMapping.tenant_id == tenant_id, TacacsUserMapping.enabled)
    )
    for m in mappings:
        if m.user is None or not m.user.is_active:
            continue
        users.append(
            g.TacUser(
                username=m.tacacs_username,
                groups=[gr.name for gr in m.user.groups],
                auth_method=m.auth_method,  # type: ignore[arg-type]
                password_crypt=m.password_crypt,
                valid_until=m.valid_until.date().isoformat() if m.valid_until else None,
            )
        )

    ldap = None
    if server is not None and server.ldap_backend and s.ldap_enabled:
        ldap = g.LdapBackend(
            server_type="microsoft" if "sAMAccountName" in s.ldap_user_filter else "generic",
            hosts=s.ldap_uri,
            base=s.ldap_user_base,
            bind_dn=s.ldap_bind_dn,
            bind_password=s.ldap_bind_password,
            exec_path=s.tacacs_mavis_ldap_exec,
        )
    settings = g.ServerSettings(
        listen_port=server.port if server else 49,
        access_log=s.tacacs_access_log,
        authz_log=s.tacacs_authz_log,
        acct_log=s.tacacs_accounting_log,
        ldap=ldap,
    )
    return nas, profiles, users, settings


def render_for_tenant(db: Session, tenant_id: uuid.UUID, server: TacacsServer | None = None) -> g.RenderResult:
    nas, profiles, users, settings = build_inputs(db, tenant_id, server)
    header = f"server: {server.name}" if server else ""
    return g.render(nas, profiles, users, settings, header=header)
