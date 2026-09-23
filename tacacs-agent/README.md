# nom-tacacs-agent

Companion agent that runs next to **tac_plus-ng** (from Marc Huber's
[event-driven-servers](https://github.com/MarcJHuber/event-driven-servers)) and connects it to
NetworkOps Manager. It is stdlib + `httpx` only.

| Loop | What it does |
|---|---|
| **config** (every `NOM_AGENT_POLL_INTERVAL` s) | `GET /api/v1/tacacs/agent/config` with `If-None-Match: <running sha256>` → verify body sha256 == `ETag` → write candidate (mode 0640) next to the live file → `tac_plus-ng -P candidate` → `os.replace` over the live file → reload (SIGHUP to tac_plus-ng, or a command) → `POST /tacacs/agent/heartbeat {running_sha256, status, message}`. A failed validation keeps the running file; a failed reload restores the previous file and reloads again. Both send `status: "error"`, which raises a `tacacs_deploy_failed` alert. `404` (nothing deployed yet) and `409` (render differs from deployed revision) keep the running file. |
| **shipper** | Tails the access/authz/accounting logs and posts batches (`NOM_AGENT_BATCH_SIZE`) of raw lines to `POST /api/v1/accounting/ingest`. Offsets are persisted in `$STATE_DIR/offsets.json` **after** the platform acknowledged a batch (at-least-once). Handles logrotate rename/create, copytruncate and rotation while the agent was down (draining `acct.log.1` by inode). Retries with exponential backoff and jitter; `400/413/422` batches are bisected to isolate and drop a single poison line. |
| **recordings** | Uploads settled `*.cast` asciicast v2 files from `NOM_AGENT_SPOOL_DIR` to `POST /api/v1/sessions` (metadata from `<name>.json` sidecar or `user@device[@source]@anything.cast`). |

All three use the TACACS server's **agent token** (returned once by `POST /api/v1/tacacs/servers`).

## Commands

```
nom-tacacs-agent supervise     # container entrypoint: runs tac_plus-ng + `run`, restarts them, writes the pidfile
nom-tacacs-agent run           # the three loops (use under systemd on a classic host install)
nom-tacacs-agent sync-once     # one config poll (exit 1 on rejection/rollback)
nom-tacacs-agent ship-once     # ship one batch per log file
nom-tacacs-agent healthcheck   # tac_plus-ng pid alive and TCP port accepting
nom-tacacs-agent check-config  # validate NOM_AGENT_* settings
```

## Settings (`NOM_AGENT_*`)

| Variable | Default | Meaning |
|---|---|---|
| `API_URL` | – (required) | Platform base URL, e.g. `https://nom.example.net` |
| `API_PREFIX` | `/api/v1` | |
| `TOKEN` / `TOKEN_FILE` | – (required) | Agent token (`nomagent_...`) |
| `VERIFY_TLS` / `CA_FILE` | `true` / – | TLS verification / private CA bundle |
| `HTTP_TIMEOUT` | `30` | seconds |
| `CONFIG_PATH` | `/etc/tac_plus-ng/tac_plus-ng.cfg` | live config file (directory must be writable) |
| `BOOTSTRAP_CONFIG` | `/usr/local/share/nom-tacacs-agent/tac_plus-ng.bootstrap.cfg` | installed by `supervise` if no config exists |
| `TACPLUS_BIN` / `TACPLUS_ARGS` | `/usr/local/sbin/tac_plus-ng` / – | binary used for `-P` validation and by `supervise` |
| `LISTEN_PORT` | `49` | used by `healthcheck` |
| `RELOAD_MODE` | `signal` | `signal` (SIGHUP pid in `PIDFILE`), `command` (`RELOAD_COMMAND`, e.g. `systemctl reload tac_plus-ng`), `none` |
| `PIDFILE` | `/run/nom/tac_plus-ng.pid` | written by `supervise` |
| `POLL_INTERVAL` | `30` | seconds between config polls / heartbeats |
| `LOG_FILES` | `/var/log/tac_plus-ng/{acct,authz,access}.log` | comma separated; must match the rendered `log ... destination`s |
| `START_AT` | `beginning` | where to start in a file never seen before (`end` skips history) |
| `BATCH_SIZE` / `FLUSH_INTERVAL` | `500` / `2` | lines per ingest request / idle poll seconds |
| `SPOOL_DIR` | `/var/spool/nom-recordings` | empty disables the uploader |
| `SPOOL_SETTLE_SECONDS` / `SPOOL_KEEP` / `SPOOL_INTERVAL` | `10` / `false` / `15` | |
| `STATE_DIR` | `/var/lib/nom-agent` | offsets database (persist it!) |
| `LOG_LEVEL` | `INFO` | |

Use logrotate with `delaycompress` (compressed rotations cannot be drained after a restart).

## Development

```
uv venv .venv && uv pip install -e ".[dev]"
.venv/bin/pytest
```
