# shellcheck shell=bash
# Shared settings for the local E2E stack (sourced by stack-up.sh, stack-down.sh, run.sh).
# Every value can be overridden from the environment.

E2E_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$E2E_ROOT/.." && pwd)"
export E2E_ROOT REPO_ROOT
export E2E_RUN="${E2E_RUN:-$E2E_ROOT/.run}"

# ports
export E2E_API_PORT="${E2E_API_PORT:-8000}"
export E2E_WEB_PORT="${E2E_WEB_PORT:-3000}"
export E2E_TACACS_PORT="${E2E_TACACS_PORT:-4949}"
export E2E_SSH_PORT="${E2E_SSH_PORT:-2222}"

# datastores (a running PostgreSQL 16 with a superuser, and Redis)
export E2E_PGHOST="${E2E_PGHOST:-localhost}"
export E2E_PGPORT="${E2E_PGPORT:-5432}"
export E2E_PGUSER="${E2E_PGUSER:-nom}"
export E2E_PGPASSWORD="${E2E_PGPASSWORD:-nom}"
export E2E_DB="${E2E_DB:-nom_e2e}"
export E2E_REDIS_URL="${E2E_REDIS_URL:-redis://localhost:6379/5}"

# tools
export BACKEND_VENV="${BACKEND_VENV:-$REPO_ROOT/backend/.venv}"
export AGENT_VENV="${AGENT_VENV:-$REPO_ROOT/tacacs-agent/.venv}"
export E2E_VENV="${E2E_VENV:-$E2E_ROOT/.venv}"
export TACPLUS_PREFIX="${TACPLUS_PREFIX:-$HOME/.cache/nom-e2e/tac_plus-ng}"
export TACPLUS_BIN="${TACPLUS_BIN:-$TACPLUS_PREFIX/sbin/tac_plus-ng}"
export SSHD_BIN="${SSHD_BIN:-$(command -v sshd || echo /usr/sbin/sshd)}"

# accounts created by stack-up (passwords satisfy the default password policy)
export E2E_ADMIN_USER="${E2E_ADMIN_USER:-admin}"
export E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-Nom-E2e-Str0ng-Pass!}"
export E2E_OPERATOR_USER="${E2E_OPERATOR_USER:-operator}"
export E2E_OPERATOR_PASSWORD="${E2E_OPERATOR_PASSWORD:-Msp-E2e-Str0ng-Pass!}"
export E2E_DEMO_USER="${E2E_DEMO_USER:-demoadmin}"
export E2E_DEMO_PASSWORD="${E2E_DEMO_PASSWORD:-Ixp-E2e-Str0ng-Pass!}"
# local SSH "devices" (system users served by the stack's sshd)
export E2E_SSH_USERS="${E2E_SSH_USERS:-nomdev1 nomdev2}"
export E2E_SSH_PASSWORD="${E2E_SSH_PASSWORD:-E2e-Ssh-Pass-2026!}"

export E2E_API_URL="http://127.0.0.1:$E2E_API_PORT"
export E2E_WEB_URL="http://127.0.0.1:$E2E_WEB_PORT"

# backend settings shared by API, worker and the CLI
export NOM_DATABASE_URL="postgresql+psycopg://$E2E_PGUSER:$E2E_PGPASSWORD@$E2E_PGHOST:$E2E_PGPORT/$E2E_DB"
export NOM_REDIS_URL="$E2E_REDIS_URL"
export NOM_ENVIRONMENT="${NOM_ENVIRONMENT:-development}"
export NOM_JWT_SECRET="${NOM_JWT_SECRET:-e2e-jwt-secret-e2e-jwt-secret-e2e-jwt-secret}"
export NOM_BACKUP_REPO_ROOT="$E2E_RUN/configs"
export NOM_TACACS_ACCOUNTING_LOG="$E2E_RUN/tac/log/acct.log"
export NOM_TACACS_AUTHZ_LOG="$E2E_RUN/tac/log/authz.log"
export NOM_TACACS_ACCESS_LOG="$E2E_RUN/tac/log/access.log"
export NOM_RATE_LIMIT_LOGIN="${NOM_RATE_LIMIT_LOGIN:-10000}"
export NOM_RATE_LIMIT_API="${NOM_RATE_LIMIT_API:-100000}"
export NOM_CORS_ORIGINS="$E2E_WEB_URL,http://localhost:$E2E_WEB_PORT"
export NOM_BACKUP_CONCURRENCY="${NOM_BACKUP_CONCURRENCY:-4}"

SUDO=""
if [[ $(id -u) -ne 0 ]]; then SUDO="sudo"; fi
export SUDO

log() { printf '\033[36m[e2e]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[e2e] %s\033[0m\n' "$*" >&2; exit 1; }
