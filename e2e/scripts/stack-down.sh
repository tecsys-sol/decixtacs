#!/usr/bin/env bash
# Stop everything stack-up.sh started and (unless --keep-db) drop the E2E database.
# PostgreSQL and Redis themselves are left running.
set -uo pipefail
# shellcheck source=env.sh
source "$(dirname "$0")/env.sh"
keep_db=0
[[ "${1:-}" == "--keep-db" ]] && keep_db=1
PIDS="$E2E_RUN/pids"

stop_group() { # stop_group NAME PID [sudo]
  local name=$1 pid=$2 sudo=${3:-}
  [[ -n "$pid" ]] || return 0
  if $sudo kill -0 "$pid" 2>/dev/null; then
    $sudo kill -TERM -- "-$pid" 2>/dev/null || $sudo kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 40); do $sudo kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    if $sudo kill -0 "$pid" 2>/dev/null; then
      $sudo kill -KILL -- "-$pid" 2>/dev/null || $sudo kill -KILL "$pid" 2>/dev/null
    fi
    log "stopped $name ($pid)"
  fi
}

if [[ -d "$PIDS" ]]; then
  # the web server and the agent first (the agent stops tac_plus-ng), then worker and API
  for name in web tacacs worker api; do
    f="$PIDS/$name.pid"
    [[ -f "$f" ]] && stop_group "$name" "$(cat "$f")" && rm -f "$f"
  done
  if [[ -f "$PIDS/sshd.pid.root" ]]; then
    pid=$(cat "$PIDS/sshd.pid.root")
    $SUDO kill -TERM "$pid" 2>/dev/null && log "stopped sshd ($pid)"
    rm -f "$PIDS/sshd.pid.root"
  fi
fi
# tac_plus-ng renames its processes (proctitle), so also stop by the pid file it was given
if [[ -f "$E2E_RUN/tac/tac_plus-ng.pid" ]]; then
  pid=$(cat "$E2E_RUN/tac/tac_plus-ng.pid"); kill -TERM "$pid" 2>/dev/null || true
fi

if [[ $keep_db -eq 0 ]]; then
  PGPASSWORD="$E2E_PGPASSWORD" psql -h "$E2E_PGHOST" -p "$E2E_PGPORT" -U "$E2E_PGUSER" -d postgres -q \
    -c "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)" && log "dropped database $E2E_DB"
fi
exit 0
