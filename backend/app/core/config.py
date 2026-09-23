"""Application settings, loaded from environment variables (prefix ``NOM_``)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOM_", env_file=".env", extra="ignore")

    app_name: str = "NetworkOps Manager"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://nom:nom@localhost:5432/nom"
    redis_url: str = "redis://localhost:6379/0"
    # Redis Sentinel: "host:port,host:port". When set, the host part of redis_url is ignored (its
    # password and db number are still used) and clients follow the master named below.
    redis_sentinels: str = ""
    redis_sentinel_master: str = "mymaster"
    redis_sentinel_password: str = ""  # AUTH for the sentinels themselves (if they require it)

    # JWT
    jwt_secret: str = Field(default="change-me-in-production-please-32b+", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14

    # Secret encryption: comma separated Fernet keys, newest first (MultiFernet rotation).
    encryption_keys: str = ""

    # Password policy
    password_min_length: int = 12
    password_require_classes: int = 3
    password_history: int = 5
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Rate limiting (requests per window per client key)
    rate_limit_login: int = 10
    rate_limit_api: int = 600
    rate_limit_window_seconds: int = 60

    # LDAP / AD
    ldap_enabled: bool = False
    ldap_uri: str = "ldaps://ldap.example.net"
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base: str = "ou=people,dc=example,dc=net"
    ldap_user_filter: str = "(|(uid={username})(sAMAccountName={username}))"
    ldap_group_base: str = "ou=groups,dc=example,dc=net"
    ldap_group_attr: str = "memberOf"

    # OIDC / OAuth2 SSO
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:3000/auth/callback"
    oidc_groups_claim: str = "groups"

    # Config backups
    backup_repo_root: str = "/var/lib/nom/configs"
    backup_sanitize_secrets: bool = True
    backup_concurrency: int = 50
    # Sophos SFOS XML API collector (platform slug "sfos")
    sfos_api_port: int = 4444
    sfos_verify_tls: bool = True
    sfos_entities: str = (
        "Zone,Interface,VLAN,LAG,Alias,UnicastRoute,IPHost,IPHostGroup,FQDNHost,FQDNHostGroup,MACHost,"
        "Services,ServiceGroup,FirewallRule,FirewallRuleGroup,NATRule,DNS,DHCPServer,AdminSettings,"
        "AuthenticationServer,SNMPCommunity,SyslogServers,User"
    )

    # TACACS (the config file path on the TACACS host is owned by the agent: NOM_AGENT_CONFIG_PATH)
    tacacs_accounting_log: str = "/var/log/tac_plus-ng/acct.log"

    # Integrations. The URL/token pairs are bootstrap defaults: `python -m app.cli init` and
    # `python -m app.cli sync-integrations-from-env` create/update per-tenant Integration rows.
    netbox_url: str = ""
    netbox_token: str = ""
    netbox_sync_minutes: int = 15
    ixpmanager_url: str = ""
    ixpmanager_api_key: str = ""

    # Retention (days)
    retention_command_logs_days: int = 365
    retention_audit_days: int = 730
    retention_login_history_days: int = 365
    retention_session_recordings_days: int = 180
    retention_backup_rows_days: int = 90  # 'unchanged'/'failed' backup rows (changed rows are kept)
    retention_alerts_days: int = 180

    # SMTP
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_from: str = "networkops@example.net"
    smtp_starttls: bool = False
    smtp_username: str = ""
    smtp_password: str = ""

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
