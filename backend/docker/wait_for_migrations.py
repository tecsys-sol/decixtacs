"""Block until PostgreSQL is reachable (``--db-only``) or the schema is at the Alembic head.

Used by the container entrypoint (``migrate``/``init`` roles) and as a Kubernetes init
container on API / worker / beat pods so they never start against an old schema.
Exit codes: 0 ready, 1 timed out.
"""

from __future__ import annotations

import argparse
import sys
import time

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db-only", action="store_true", help="only wait for a working connection")
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--interval", type=float, default=3)
    p.add_argument("--alembic-ini", default="/app/alembic.ini")
    a = p.parse_args()

    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    heads: set[str] = set()
    if not a.db_only:
        heads = set(ScriptDirectory.from_config(Config(a.alembic_ini)).get_heads())
    deadline = time.monotonic() + a.timeout
    last = ""
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                if a.db_only:
                    print("database reachable", file=sys.stderr)
                    return 0
                current = set(MigrationContext.configure(conn).get_current_heads())
                if current == heads:
                    print(f"schema at head {sorted(heads)}", file=sys.stderr)
                    return 0
                msg = f"schema at {sorted(current) or 'base'}, waiting for {sorted(heads)}"
        except Exception as exc:  # noqa: BLE001 - any connection problem means "not yet"
            msg = f"database not ready: {exc.__class__.__name__}: {str(exc).splitlines()[0][:200]}"
        if msg != last:
            print(msg, file=sys.stderr)
            last = msg
        if time.monotonic() > deadline:
            print("timed out", file=sys.stderr)
            return 1
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
