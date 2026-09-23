#!/usr/bin/env bash
# Start the complete NetworkOps Manager stack locally for the E2E suites.
#
#   PostgreSQL + Redis (must already run)   -> fresh database $E2E_DB, Alembic migrations
#   app.cli init (3 tenants) + seed-demo     -> e2e (admin), acme (operator, superuser), demo (demoadmin)
#   uvicorn API             :$E2E_API_PORT
#   Celery worker           queues collect,alerts,celery
#   Next.js (next start)    :$E2E_WEB_PORT   (production build, /api proxied to the API)
#   sshd "devices"          127.0.0.{1,2,3}:$E2E_SSH_PORT (users $E2E_SSH_USERS, platform linux)
#   nom-tacacs-agent supervise -> tac_plus-ng :$E2E_TACACS_PORT (config pulled from the API)
#
# Background processes write pid files to $E2E_RUN/pids and logs to $E2E_RUN/logs.
# Stop everything with stack-down.sh. See e2e/README.md.
set -euo pipefail
# shellcheck source=env.sh
source "$(dirname "$0")/env.sh"

PIDS="$E2E_RUN/pids"
LOGS="$E2E_RUN/logs"

if [[ -d "$PIDS" ]] && compgen -G "$PIDS/*.pid" >/dev/null; then
  log "stack already (partially) running - stopping it first"
  "$E2E_ROOT/scripts/stack-down.sh" --keep-db
fi
rm -rf "$E2E_RUN"
mkdir -p "$PIDS" "$LOGS" "$E2E_RUN/configs" "$E2E_RUN/tac/log" "$E2E_RUN/tac/state" "$E2E_RUN/tac/spool" \
  "$E2E_RUN/devices" "$E2E_RUN/sshd"

# start_bg NAME CMD... : run in its own session (so the whole process group can be stopped)
start_bg() {
  local name=$1; shift
  setsid "$@" >"$LOGS/$name.log" 2>&1 < /dev/null &
  echo $! >"$PIDS/$name.pid"
}

wait_for() { # wait_for DESCRIPTION TIMEOUT_S CMD...
  local what=$1 timeout=$2; shift 2
  local deadline=$((SECONDS + timeout))
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS > deadline)); then
      log "timeout waiting for $what"; tail -n 40 "$LOGS"/*.log 2>/dev/null || true
      die "$what did not come up within ${timeout}s"
    fi
    sleep 0.5
  done
  log "$what is up"
}

# --- prerequisites ------------------------------------------------------------------------------
[[ -x "$BACKEND_VENV/bin/python" ]] || die "backend venv missing: $BACKEND_VENV (see README: Local development)"
[[ -x "$AGENT_VENV/bin/python" ]] || die "tacacs-agent venv missing: $AGENT_VENV"
[[ -x "$TACPLUS_BIN" ]] || die "tac_plus-ng not found at $TACPLUS_BIN - run e2e/scripts/build-tac-plus-ng.sh"
[[ -x "$SSHD_BIN" ]] || die "sshd not found (apt-get install openssh-server)"
[[ -d "$REPO_ROOT/frontend/node_modules" ]] || die "frontend/node_modules missing (cd frontend && npm ci)"
if [[ ! -x "$E2E_VENV/bin/python" ]]; then
  log "creating E2E venv $E2E_VENV"
  python3 -m venv "$E2E_VENV"
  "$E2E_VENV/bin/pip" install -q -r "$E2E_ROOT/requirements.txt"
fi

export PGPASSWORD="$E2E_PGPASSWORD"
PSQL=(psql -h "$E2E_PGHOST" -p "$E2E_PGPORT" -U "$E2E_PGUSER" -v ON_ERROR_STOP=1 -q)
"${PSQL[@]}" -d postgres -c "select 1" >/dev/null || die "PostgreSQL not reachable at $E2E_PGHOST:$E2E_PGPORT as $E2E_PGUSER"
"$BACKEND_VENV/bin/python" - <<'EOF' || die "Redis not reachable at $E2E_REDIS_URL"
import os, redis
redis.Redis.from_url(os.environ["E2E_REDIS_URL"]).ping()
EOF
redis_db="${E2E_REDIS_URL##*/}"
"$BACKEND_VENV/bin/python" -c "import os,redis; redis.Redis.from_url(os.environ['E2E_REDIS_URL']).flushdb()"
log "PostgreSQL and Redis (db $redis_db, flushed) reachable"

# --- database -----------------------------------------------------------------------------------
"${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)" -c "CREATE DATABASE $E2E_DB OWNER $E2E_PGUSER"
(cd "$REPO_ROOT/backend" && "$BACKEND_VENV/bin/alembic" upgrade head >"$LOGS/migrate.log" 2>&1) \
  || { tail -30 "$LOGS/migrate.log"; die "migrations failed"; }
cli() { (cd "$REPO_ROOT/backend" && "$BACKEND_VENV/bin/python" -m app.cli "$@"); }
cli init --name "E2E Networks" --slug e2e --username "$E2E_ADMIN_USER" --password "$E2E_ADMIN_PASSWORD" \
  --email admin@e2e.example >>"$LOGS/cli.log"
cli init --name "Acme MSP" --slug acme --username "$E2E_OPERATOR_USER" --password "$E2E_OPERATOR_PASSWORD" \
  --superuser >>"$LOGS/cli.log"
cli init --name "Demo IX" --slug demo --username "$E2E_DEMO_USER" --password "$E2E_DEMO_PASSWORD" >>"$LOGS/cli.log"
cli seed-demo --tenant demo >>"$LOGS/cli.log"
# The linux platform's recipe reads a file the tests control (per SSH user, see below).
"${PSQL[@]}" -d "$E2E_DB" -c "UPDATE platforms SET backup_commands = '[\"cat ~/device.conf\"]' WHERE slug = 'linux'"
log "database $E2E_DB migrated and seeded (tenants e2e, acme, demo)"

# --- SSH "devices" --------------------------------------------------------------------------------
for u in $E2E_SSH_USERS; do
  if ! id -u "$u" >/dev/null 2>&1; then
    $SUDO useradd --create-home --shell /bin/bash "$u"
  fi
  echo "$u:$E2E_SSH_PASSWORD" | $SUDO chpasswd
  cat >"$E2E_RUN/devices/$u.conf" <<EOF
# $u - managed by the NetworkOps Manager E2E suite
hostname $u
interface eth0
 description uplink
 ip address 192.0.2.$((RANDOM % 200 + 10))/24
ntp server 192.0.2.123
EOF
  chmod 0644 "$E2E_RUN/devices/$u.conf"
  $SUDO ln -sfn "$E2E_RUN/devices/$u.conf" "/home/$u/device.conf"
done
chmod o+x "$E2E_RUN" "$E2E_RUN/devices" 2>/dev/null || true
# every path component up to the device files must be traversable by the device users
p="$E2E_RUN"; while [[ "$p" != "/" ]]; do $SUDO chmod o+x "$p" 2>/dev/null || true; p=$(dirname "$p"); done
$SUDO ssh-keygen -q -t ed25519 -N "" -f "$E2E_RUN/sshd/host_ed25519" <<<y >/dev/null 2>&1 || true
$SUDO mkdir -p /run/sshd
cat >"$E2E_RUN/sshd/sshd_config" <<EOF
Port $E2E_SSH_PORT
ListenAddress 127.0.0.1
ListenAddress 127.0.0.2
ListenAddress 127.0.0.3
HostKey $E2E_RUN/sshd/host_ed25519
PidFile $E2E_RUN/sshd/sshd.pid
PasswordAuthentication yes
KbdInteractiveAuthentication no
PubkeyAuthentication no
PermitRootLogin no
UsePAM yes
AllowUsers $E2E_SSH_USERS
PrintMotd no
StrictModes no
LogLevel INFO
EOF
$SUDO "$SSHD_BIN" -t -f "$E2E_RUN/sshd/sshd_config" || die "sshd config invalid"
$SUDO "$SSHD_BIN" -f "$E2E_RUN/sshd/sshd_config" -E "$LOGS/sshd.log"
wait_for "sshd :$E2E_SSH_PORT" 20 test -s "$E2E_RUN/sshd/sshd.pid"
$SUDO cat "$E2E_RUN/sshd/sshd.pid" >"$PIDS/sshd.pid.root"

# --- API + worker -------------------------------------------------------------------------------
cd "$REPO_ROOT/backend"
start_bg api "$BACKEND_VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$E2E_API_PORT" --log-level info
start_bg worker "$BACKEND_VENV/bin/celery" -A app.workers.celery_app worker -Q collect,alerts,celery \
  --concurrency 2 --loglevel INFO -n "e2e@%h"
cd "$E2E_ROOT"
wait_for "API :$E2E_API_PORT" 60 curl -fsS "$E2E_API_URL/healthz"
wait_for "Celery worker" 60 bash -c "cd '$REPO_ROOT/backend' && '$BACKEND_VENV/bin/celery' -A app.workers.celery_app inspect ping -t 2"

# --- TACACS server object + agent ---------------------------------------------------------------
"$E2E_VENV/bin/python" "$E2E_ROOT/scripts/bootstrap.py"
cat >"$E2E_RUN/tac/bootstrap.cfg" <<EOF
# E2E bootstrap: lets tac_plus-ng start until the agent installs the deployed revision
id = spawnd {
	listen = { port = $E2E_TACACS_PORT }
	spawn = { instances min = 1 instances max = 4 }
	background = no
}
id = tac_plus-ng {
	log accesslog { destination = "$NOM_TACACS_ACCESS_LOG" }
	log authzlog { destination = "$NOM_TACACS_AUTHZ_LOG" }
	log acctlog { destination = "$NOM_TACACS_ACCOUNTING_LOG" }
	authentication log = accesslog
	authorization log = authzlog
	accounting log = acctlog
}
EOF
(
  export NOM_AGENT_API_URL="$E2E_API_URL"
  export NOM_AGENT_TOKEN_FILE="$E2E_RUN/agent-token"
  export NOM_AGENT_CONFIG_PATH="$E2E_RUN/tac/tac_plus-ng.cfg"
  export NOM_AGENT_BOOTSTRAP_CONFIG="$E2E_RUN/tac/bootstrap.cfg"
  export NOM_AGENT_TACPLUS_BIN="$TACPLUS_BIN"
  export NOM_AGENT_LISTEN_PORT="$E2E_TACACS_PORT"
  export NOM_AGENT_RELOAD_MODE=signal
  export NOM_AGENT_PIDFILE="$E2E_RUN/tac/tac_plus-ng.pid"
  export NOM_AGENT_POLL_INTERVAL="${NOM_AGENT_POLL_INTERVAL:-2}"
  export NOM_AGENT_LOG_FILES="$NOM_TACACS_ACCOUNTING_LOG,$NOM_TACACS_AUTHZ_LOG,$NOM_TACACS_ACCESS_LOG"
  export NOM_AGENT_FLUSH_INTERVAL=0.5
  export NOM_AGENT_BATCH_SIZE=200
  export NOM_AGENT_SPOOL_DIR="$E2E_RUN/tac/spool"
  export NOM_AGENT_SPOOL_SETTLE_SECONDS=1
  export NOM_AGENT_SPOOL_INTERVAL=2
  export NOM_AGENT_STATE_DIR="$E2E_RUN/tac/state"
  export NOM_AGENT_LOG_LEVEL=INFO
  cd "$REPO_ROOT/tacacs-agent"
  "$AGENT_VENV/bin/python" -m nom_tacacs_agent check-config >/dev/null
  start_bg tacacs "$AGENT_VENV/bin/python" -m nom_tacacs_agent supervise
)
wait_for "tac_plus-ng :$E2E_TACACS_PORT" 30 bash -c "exec 3<>/dev/tcp/127.0.0.1/$E2E_TACACS_PORT"

# --- frontend -----------------------------------------------------------------------------------
cd "$REPO_ROOT/frontend"
export NEXT_TELEMETRY_DISABLED=1
export API_PROXY_TARGET="$E2E_API_URL"
stamp=$( { echo "$API_PROXY_TARGET"; git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true;
  find app components hooks lib public package-lock.json next.config.ts tailwind.config.ts -type f -print0 \
    | sort -z | xargs -0 sha1sum; } | sha1sum | cut -d' ' -f1)
if [[ "${E2E_FORCE_BUILD:-0}" != "1" && -f .next/BUILD_ID && "$(cat .next/e2e-stamp 2>/dev/null)" == "$stamp" ]]; then
  log "frontend build is current (stamp $stamp)"
else
  log "building frontend (API_PROXY_TARGET=$API_PROXY_TARGET)"
  npm run build >"$LOGS/web-build.log" 2>&1 || { tail -40 "$LOGS/web-build.log"; die "frontend build failed"; }
  echo "$stamp" >.next/e2e-stamp
fi
start_bg web npx next start -H 127.0.0.1 -p "$E2E_WEB_PORT"
cd "$E2E_ROOT"
wait_for "web :$E2E_WEB_PORT" 60 curl -fsS -o /dev/null "$E2E_WEB_URL/login"
wait_for "web -> API proxy" 30 bash -c "curl -s -o /dev/null -w '%{http_code}' '$E2E_WEB_URL/api/v1/auth/me' | grep -q 401"

log "stack is up: web $E2E_WEB_URL  api $E2E_API_URL/api/docs  tacacs 127.0.0.1:$E2E_TACACS_PORT  ssh 127.0.0.1:$E2E_SSH_PORT"
log "state: $E2E_RUN/stack.json   logs: $LOGS"
