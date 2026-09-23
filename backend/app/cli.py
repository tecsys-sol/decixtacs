"""Operational CLI: ``python -m app.cli <command>``."""

from __future__ import annotations

import argparse
import getpass
import sys

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.db.session import SessionLocal


def cmd_init(args) -> None:
    from app.models import Tenant
    from app.services.bootstrap import create_tenant, seed_global

    password = args.password or getpass.getpass("Admin password: ")
    with SessionLocal() as db:
        seed_global(db)
        if db.scalar(select(Tenant).where(Tenant.slug == args.slug)):
            print(f"tenant {args.slug} already exists")
            db.commit()
            return
        t = create_tenant(db, args.name, args.slug, args.username, password, args.email, superuser=args.superuser)
        db.commit()
        print(f"created tenant {t.slug} ({t.id}) with admin '{args.username}'")


def cmd_genkey(_args) -> None:
    print(Fernet.generate_key().decode())


def cmd_rotate_secrets(_args) -> None:
    """Re-encrypt every secret with the newest key in NOM_ENCRYPTION_KEYS (put the new key first)."""
    from app.core.security import rotate_secret
    from app.models import AlertChannel, Credential, Integration, TacacsDevice, User

    fields = {Credential: ["password_enc", "ssh_key_enc", "enable_secret_enc"], TacacsDevice: ["key_enc"],
              Integration: ["token_enc"], AlertChannel: ["target_enc"], User: ["mfa_secret_enc"]}
    n = 0
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
    sub.add_parser("genkey", help="generate a Fernet key for NOM_ENCRYPTION_KEYS").set_defaults(fn=cmd_genkey)
    sub.add_parser("rotate-secrets", help="re-encrypt secrets with the newest key").set_defaults(fn=cmd_rotate_secrets)
    o = sub.add_parser("export-openapi")
    o.add_argument("--output", default="openapi.json")
    o.set_defaults(fn=cmd_export_openapi)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
