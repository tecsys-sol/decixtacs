"""Monthly range partitioning helpers for high-volume log tables + retention.

command_logs, audit_events and tacacs_auth_events are created ``PARTITION BY RANGE (timestamp)``
in 0001. This revision adds:

* ``nom_ensure_partitions(table, months_ahead)`` - creates monthly partitions (``<table>_yYYYYmMM``)
  from last month up to N months ahead, plus a ``<table>_default`` catch-all.
* ``nom_drop_old_partitions(table, retention_days)`` - drops whole partitions older than retention
  (O(1) retention instead of bulk DELETEs).
* an append-only guard on audit_events (UPDATE/DELETE rejected unless ``nom.allow_audit_purge`` is set).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("command_logs", "audit_events", "tacacs_auth_events")

ENSURE = r"""
CREATE OR REPLACE FUNCTION nom_ensure_partitions(tbl text, months_ahead int DEFAULT 3) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    start_month date := date_trunc('month', now())::date - interval '1 month';
    m date;
    part text;
    created int := 0;
BEGIN
    FOR i IN 0..(months_ahead + 1) LOOP
        m := (start_month + (i || ' month')::interval)::date;
        part := format('%s_y%sm%s', tbl, to_char(m, 'YYYY'), to_char(m, 'MM'));
        IF to_regclass(part) IS NULL THEN
            EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                           part, tbl, m, (m + interval '1 month')::date);
            created := created + 1;
        END IF;
    END LOOP;
    IF to_regclass(tbl || '_default') IS NULL THEN
        EXECUTE format('CREATE TABLE %I PARTITION OF %I DEFAULT', tbl || '_default', tbl);
    END IF;
    RETURN created;
END $$;
"""

DROP_OLD = r"""
CREATE OR REPLACE FUNCTION nom_drop_old_partitions(tbl text, retention_days int) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    upper_bound date;
    dropped int := 0;
BEGIN
    PERFORM set_config('nom.allow_audit_purge', 'on', true);
    FOR r IN
        SELECT c.relname FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        WHERE p.relname = tbl AND c.relname ~ ('^' || tbl || '_y[0-9]{4}m[0-9]{2}$')
    LOOP
        upper_bound := (to_date(substring(r.relname from '_y([0-9]{4})m') || substring(r.relname from 'm([0-9]{2})$'),
                                'YYYYMM') + interval '1 month')::date;
        IF upper_bound < (now() - (retention_days || ' days')::interval)::date THEN
            EXECUTE format('DROP TABLE %I', r.relname);
            dropped := dropped + 1;
        END IF;
    END LOOP;
    RETURN dropped;
END $$;
"""

AUDIT_GUARD = r"""
CREATE OR REPLACE FUNCTION nom_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('nom.allow_audit_purge', true), 'off') <> 'on' THEN
        RAISE EXCEPTION 'audit_events is append-only';
    END IF;
    RETURN OLD;
END $$;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION nom_audit_append_only();
"""


def upgrade() -> None:
    op.execute(ENSURE)
    op.execute(DROP_OLD)
    for t in TABLES:
        op.execute(f"SELECT nom_ensure_partitions('{t}', 3)")
    op.execute(AUDIT_GUARD)
    # Trigram index for fast substring search over command history (optional extension).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_command_logs_command_trgm ON command_logs USING gin (command gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_config_index_attrs ON config_index USING gin (attributes jsonb_path_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_config_index_attrs")
    op.execute("DROP INDEX IF EXISTS ix_command_logs_command_trgm")
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS nom_audit_append_only()")
    op.execute("DROP FUNCTION IF EXISTS nom_drop_old_partitions(text, int)")
    op.execute("DROP FUNCTION IF EXISTS nom_ensure_partitions(text, int)")
