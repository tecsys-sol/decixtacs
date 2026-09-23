"""LDAP / Active Directory authentication and group sync."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings


@dataclass
class LdapIdentity:
    dn: str
    username: str
    email: str | None
    full_name: str | None
    groups: list[str] = field(default_factory=list)  # group CNs


def _escape(value: str) -> str:
    from ldap3.utils.conv import escape_filter_chars

    return escape_filter_chars(value)


def authenticate(username: str, password: str) -> LdapIdentity | None:
    """Bind as the service account, find the user, then bind as the user to verify the password."""
    if not password:
        return None
    from ldap3 import ALL, SUBTREE, Connection, Server
    from ldap3.core.exceptions import LDAPException

    s = get_settings()
    server = Server(s.ldap_uri, get_info=ALL, connect_timeout=5)
    try:
        svc = Connection(server, user=s.ldap_bind_dn, password=s.ldap_bind_password, auto_bind=True, receive_timeout=10)
        svc.search(
            s.ldap_user_base,
            s.ldap_user_filter.format(username=_escape(username)),
            SUBTREE,
            attributes=["mail", "displayName", "cn", s.ldap_group_attr],
        )
        if len(svc.entries) != 1:
            return None
        entry = svc.entries[0]
        dn = entry.entry_dn
        Connection(server, user=dn, password=password, auto_bind=True, receive_timeout=10).unbind()
    except LDAPException:
        return None
    groups = []
    for gdn in entry[s.ldap_group_attr].values if s.ldap_group_attr in entry else []:
        cn = str(gdn).split(",")[0]
        groups.append(cn.split("=", 1)[1] if "=" in cn else cn)
    return LdapIdentity(
        dn=dn,
        username=username,
        email=str(entry.mail) if "mail" in entry and entry.mail else None,
        full_name=str(entry.displayName) if "displayName" in entry and entry.displayName else None,
        groups=groups,
    )
