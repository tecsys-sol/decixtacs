#!/usr/bin/env bash
# NetworkOps Manager container entrypoint.
#
# Usage: docker-entrypoint.sh <role> [extra args]
#   api                  uvicorn app.main:app on :${NOM_API_PORT:-8000}
#   worker               celery worker (queues from NOM_WORKER_QUEUES) + Prometheus exporter on :9808
#   beat                 celery beat scheduler - run EXACTLY ONE replica
#   migrate              wait for PostgreSQL, then `alembic upgrade head`
#   init                 seed catalogue + create first tenant/admin from NOM_INIT_* (idempotent)
#   wait-for-migrations  block until the database is at the Alembic head (init container)
#   cli <args>           python -m app.cli <args> (genkey, rotate-secrets, export-openapi ...)
#   <anything else>      exec'd verbatim (e.g. `bash`, `alembic current`)
#
# Any NOM_<NAME>_FILE variable is read into NOM_<NAME> (Docker / Kubernetes secret files).
set -euo pipefail

log() { printf '%s [entrypoint] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

# --- *_FILE secret indirection ---------------------------------------------------------------
while IFS='=' read -r name _; do
  case "$name" in
    NOM_*_FILE)
      target="${name%_FILE}"
      file="${!name}"
      if [[ -n "${!target:-}" ]]; then
        log "both $target and $name are set; $name wins"
      fi
      if [[ ! -r "$file" ]]; then
        log "ERROR: $name points to unreadable file $file"; exit 64
      fi
      export "$target"="$(<"$file")"
      unset "$name"
      ;;
  esac
done < <(env)

role="${1:-api}"
[[ $# -gt 0 ]] && shift
export NOM_ROLE="$role"
cd /app

wait_db() {
  python /app/docker/wait_for_migrations.py --db-only --timeout "${NOM_DB_WAIT_TIMEOUT:-120}"
}

case "$role" in
  api)
    exec uvicorn app.main:app \
      --host "${NOM_API_HOST:-0.0.0.0}" \
      --port "${NOM_API_PORT:-8000}" \
      --workers "${NOM_API_WORKERS:-1}" \
      --proxy-headers \
      --forwarded-allow-ips "${NOM_FORWARDED_ALLOW_IPS:-*}" \
      --no-server-header \
      --timeout-keep-alive "${NOM_API_KEEPALIVE:-5}" \
      --log-level "${NOM_LOG_LEVEL:-info}" \
      "$@"
    ;;

  worker)
    # prometheus_client multiprocess mode: every prefork child writes its samples to
    # PROMETHEUS_MULTIPROC_DIR, the exporter aggregates them on :NOM_WORKER_METRICS_PORT.
    metrics_port="${NOM_WORKER_METRICS_PORT:-9808}"
    if [[ "$metrics_port" != "0" ]]; then
      export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/nom-prometheus}"
      rm -rf "$PROMETHEUS_MULTIPROC_DIR" && mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
      python /app/docker/metrics_exporter.py --port "$metrics_port" &
    fi
    exec celery -A app.workers.celery_app worker \
      --queues "${NOM_WORKER_QUEUES:-collect,alerts,celery}" \
      --concurrency "${NOM_WORKER_CONCURRENCY:-4}" \
      --hostname "${NOM_WORKER_NAME:-worker}@%h" \
      --max-tasks-per-child "${NOM_WORKER_MAX_TASKS_PER_CHILD:-200}" \
      --prefetch-multiplier 1 \
      -O fair \
      --without-gossip --without-mingle \
      --loglevel "${NOM_LOG_LEVEL:-info}" \
      "$@"
    ;;

  beat)
    exec celery -A app.workers.celery_app beat \
      --schedule "${NOM_BEAT_SCHEDULE:-/tmp/celerybeat-schedule}" \
      --loglevel "${NOM_LOG_LEVEL:-info}" \
      "$@"
    ;;

  migrate)
    wait_db
    log "running alembic upgrade head"
    alembic upgrade head
    log "database schema at: $(alembic current 2>/dev/null | tail -n1)"
    ;;

  init)
    wait_db
    : "${NOM_INIT_ADMIN_PASSWORD:?NOM_INIT_ADMIN_PASSWORD (or NOM_INIT_ADMIN_PASSWORD_FILE) is required}"
    args=(--name "${NOM_INIT_TENANT_NAME:-Default}"
          --slug "${NOM_INIT_TENANT_SLUG:-default}"
          --username "${NOM_INIT_ADMIN_USERNAME:-admin}"
          --password "$NOM_INIT_ADMIN_PASSWORD")
    [[ -n "${NOM_INIT_ADMIN_EMAIL:-}" ]] && args+=(--email "$NOM_INIT_ADMIN_EMAIL")
    case "${NOM_INIT_SUPERUSER:-true}" in true|1|yes) args+=(--superuser) ;; esac
    exec python -m app.cli init "${args[@]}" "$@"
    ;;

  wait-for-migrations)
    exec python /app/docker/wait_for_migrations.py --timeout "${NOM_DB_WAIT_TIMEOUT:-600}" "$@"
    ;;

  cli)
    exec python -m app.cli "$@"
    ;;

  *)
    exec "$role" "$@"
    ;;
esac
