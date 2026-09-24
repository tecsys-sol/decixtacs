"""Operational CLI: ``python -m app.cli <command>``."""

from __future__ import annotations

import argparse
import getpass
import sys

from cryptography.fernet import Fernet
from sqlalchemy import select


def cmd_init(args) -> None:
    from app.models import Tenant
    from app.services.bootstrap import create_tenant, integrations_from_env, seed_global

    password = args.password or getpass.getpass("Admin password: ")
    from app.db.session import SessionLocal  # lazy: genkey must work without config

    with SessionLocal() as db:
        seed_global(db)
        t = db.scalar(select(Tenant).where(Tenant.slug == args.slug))
        if t is not None:
            print(f"tenant {args.slug} already exists")
        else:
            t = create_tenant(db, args.name, args.slug, args.username, password, args.email, superuser=args.superuser)
            print(f"created tenant {t.slug} ({t.id}) with admin '{args.username}'")
        _report_env_integrations(integrations_from_env(db, t))
        db.commit()


def _report_env_integrations(result: dict[str, str]) -> None:
    for kind, what in result.items():
        print(f"integration {kind} (from environment): {what}")


def _tenant(db, slug: str):
    from app.models import Tenant

    t = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if t is None:
        sys.exit(f"tenant {slug} not found")
    return t


def cmd_sync_integrations(args) -> None:
    from app.db.session import SessionLocal  # lazy: genkey must work without config
    from app.services.bootstrap import integrations_from_env

    with SessionLocal() as db:
        result = integrations_from_env(db, _tenant(db, args.tenant))
        db.commit()
    if not result:
        print("nothing to do: NOM_NETBOX_URL / NOM_IXPMANAGER_URL are not set")
    _report_env_integrations(result)


def cmd_seed_demo(args) -> None:
    from app.db.session import SessionLocal  # lazy: genkey must work without config
    from app.services.demo import DemoExists, seed_demo

    with SessionLocal() as db:
        try:
            stats = seed_demo(db, _tenant(db, args.tenant), force=args.force, seed=args.seed)
        except DemoExists as e:
            sys.exit(str(e))
        db.commit()
    print("demo data: " + ", ".join(f"{k}={v}" for k, v in stats.items()))


def cmd_genkey(_args) -> None:
    print(Fernet.generate_key().decode())


def cmd_rotate_secrets(_args) -> None:
    """Re-encrypt every secret with the newest key in NOM_ENCRYPTION_KEYS (put the new key first)."""
    from app.core.security import rotate_secret
    from app.models import AlertChannel, Credential, Integration, TacacsDevice, User

    fields = {
        Credential: ["password_enc", "ssh_key_enc", "enable_secret_enc"],
        TacacsDevice: ["key_enc"],
        Integration: ["token_enc"],
        AlertChannel: ["target_enc"],
        User: ["mfa_secret_enc"],
    }
    n = 0
    from app.db.session import SessionLocal  # lazy: genkey must work without config

    with SessionLocal() as db:
        for model, cols in fields.items():
            for row in db.scalars(select(model)):
                for c in cols:
                    if getattr(row, c):
                        setattr(row, c, rotate_secret(getattr(row, c)))
                        n += 1
        db.commit()
    print(f"re-encrypted {n} secrets; the old key can now be removed")


def cmd_export_openapi(args) -> None:
    import json

    from app.main import app

    with open(args.output, "w") as f:
        json.dump(app.openapi(), f, indent=2)
    print(f"wrote {args.output}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nom")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="seed catalogue and create the first tenant + admin")
    i.add_argument("--name", default="Default")
    i.add_argument("--slug", default="default")
    i.add_argument("--username", default="admin")
    i.add_argument("--email")
    i.add_argument("--password")
    i.add_argument("--superuser", action="store_true", help="platform operator (MSP) account")
    i.set_defaults(fn=cmd_init)
    si = sub.add_parser(
        "sync-integrations-from-env", help="create/update NetBox + IXP Manager integrations from NOM_* settings"
    )
    si.add_argument("--tenant", required=True, help="tenant slug")
    si.set_defaults(fn=cmd_sync_integrations)
    sd = sub.add_parser("seed-demo", help="populate a tenant with deterministic demo data")
    sd.add_argument("--tenant", required=True, help="tenant slug")
    sd.add_argument("--force", action="store_true", help="wipe the tenant's inventory/activity data and re-seed")
    sd.add_argument("--seed", type=int, default=42, help="RNG seed")
    sd.set_defaults(fn=cmd_seed_demo)
    sub.add_parser("genkey", help="generate a Fernet key for NOM_ENCRYPTION_KEYS").set_defaults(fn=cmd_genkey)
    sub.add_parser("rotate-secrets", help="re-encrypt secrets with the newest key").set_defaults(fn=cmd_rotate_secrets)
    o = sub.add_parser("export-openapi")
    o.add_argument("--output", default="openapi.json")
    o.set_defaults(fn=cmd_export_openapi)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
