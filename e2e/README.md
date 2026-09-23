# End-to-end tests

A reproducible local "full stack" and two suites that drive it the way operators and devices do:

* **API suite** (`e2e/api`, pytest): real TACACS+ traffic from the `tacacs_plus` client against
  tac_plus-ng running a configuration rendered by the platform and installed by `nom-tacacs-agent`;
  real SSH config backups through the Celery worker.
* **Browser suite** (`e2e/tests`, Playwright + TypeScript): the Next.js production build in Chromium.

Nothing is mocked: PostgreSQL, Redis, uvicorn, Celery, `next start`, tac_plus-ng and sshd are real
processes.

```
make e2e-deps     # once: build tac_plus-ng, e2e/.venv, e2e + frontend node_modules
make e2e          # stack-up -> API suite -> browser suite -> stack-down (exit 1 on any failure)

make e2e-up       # start the stack and keep it (then run suites by hand, see below)
make e2e-down     # stop it and drop the database
```

## Prerequisites

| | |
|---|---|
| PostgreSQL 16 | a superuser (default `nom`/`nom` on `localhost:5432`; `CREATE DATABASE`, `pg_trgm`) |
| Redis | `redis://localhost:6379/5` by default (the E2E db number is flushed on stack-up) |
| Python 3.12 | `backend/.venv` (`pip install -e "backend[dev,collectors]"`), `tacacs-agent/.venv` (`pip install -e tacacs-agent`) |
| Node 22 | `frontend/node_modules`, `e2e/node_modules` (`npm ci`); Chromium for Playwright 1.63 (`npx playwright install chromium`, or a preinstalled `PLAYWRIGHT_BROWSERS_PATH`) |
| tac_plus-ng | `e2e/scripts/build-tac-plus-ng.sh` (below) |
| sshd | `openssh-server`; root or passwordless `sudo` (stack-up creates the device users `nomdev1`/`nomdev2` and starts sshd) |

`e2e/scripts/build-tac-plus-ng.sh` clones [event-driven-servers](https://github.com/MarcJHuber/event-driven-servers),
runs `./configure --prefix=$TACPLUS_PREFIX tac_plus-ng && make && make install` and records the
commit in `$TACPLUS_PREFIX/.built-commit`; re-running it for the same commit is a no-op
(`TACPLUS_REF` pins a branch/tag/sha, `INSTALL_DEPS=1` apt-installs the build dependencies).
Default prefix: `~/.cache/nom-e2e/tac_plus-ng`.

## The stack (`e2e/scripts/stack-up.sh`)

| Component | Default | Notes |
|---|---|---|
| database | `nom_e2e` | dropped/re-created, `alembic upgrade head` |
| tenants | `e2e` (admin `admin`), `acme` (superuser `operator`), `demo` (`demoadmin` + `app.cli seed-demo`) | passwords in `e2e/scripts/env.sh` |
| API | `127.0.0.1:$E2E_API_PORT` (8000) | uvicorn |
| worker | Celery, queues `collect,alerts,celery` | no beat |
| web | `127.0.0.1:$E2E_WEB_PORT` (3000) | `next build` (with `API_PROXY_TARGET` = the API) + `next start`; rebuilt only when frontend sources change |
| TACACS+ | `127.0.0.1:$E2E_TACACS_PORT` (4949) | `nom-tacacs-agent supervise` runs tac_plus-ng and the agent (poll every 2 s) with the token of the server object `e2e-tac` created through the API |
| devices | sshd on `127.0.0.{1,2,3}:$E2E_SSH_PORT` (2222) | users `nomdev1`, `nomdev2`; the `linux` platform's backup command is set to `cat ~/device.conf`, and each `~/device.conf` links to `e2e/.run/devices/<user>.conf`, which tests edit |

State, pid files and logs live in `e2e/.run/` (git-ignored): `stack.json` (URLs, tokens, ports;
read by both suites), `logs/{api,worker,web,tacacs,sshd,...}.log`, `tac/tac_plus-ng.cfg` (the
config the agent installed), `tac/log/{access,authz,acct}.log` (what tac_plus-ng wrote),
`configs/` (per-tenant Git repositories). All ports and credentials are environment variables,
see `e2e/scripts/env.sh`.

## Running suites against a running stack

```
e2e/.venv/bin/pytest -c e2e/api/pytest.ini e2e/api                 # API suite
cd e2e && npx playwright test                                       # browser suite
cd e2e && npx playwright test tests/04-tacacs-compliance.spec.ts --headed
cd e2e && npx playwright show-report
E2E_KEEP_STACK=1 e2e/scripts/run.sh                                 # full run, keep the stack
```

Both suites create their objects with a random suffix, so they can be re-run against the same
stack. The browser suite's global setup runs `e2e/scripts/seed_ui.py`, which (again through the
real stack) creates the linux devices, a TACACS+ policy/user deployed by the agent, real TACACS+
traffic (a permitted, a denied and a dangerous command), a session recording and the users the
RBAC / four-eyes / MFA specs log in with; it writes `e2e/.run/ui-seed.json`.

## Coverage

API suite (`e2e/api`):

* `test_tacacs.py` - render -> deploy -> agent pull/`tac_plus-ng -P`/install/SIGHUP (sha256 of the
  live file = deployed revision, heartbeat), conditional GET (`ETag`/304, bad token 401); ASCII and
  PAP authentication (good/bad password, unknown user); command authorization per policy regex
  (exec `priv-lvl`, permit, deny rule, default deny, unmapped user); accounting start/stop; the agent
  ships the log lines -> `GET /accounting/commands` (user, device name via inventory correlation,
  source address, regex search), `unauthorized_command` alert, `GET /tacacs/events`; idempotent
  deploy; disabling a mapping locks the user out after the next deploy.
* `test_backups.py` - backups through the worker over SSH (Git commit, history, stored config =
  device file), unchanged detection, change + author correlation from TACACS accounting of a
  config-mode command, unified and side-by-side diff, unplanned-change alert, golden-config drift
  (drift event + alert), running-vs-backup drift check, config search (nothing indexed for linux),
  compliance run with a custom rule (per-device failures), failed backup (bad credential) + alert.

Browser suite (`e2e/tests`):

| Spec | Covers |
|---|---|
| `01-auth` | login, wrong password, redirect to `/login?next=`, MFA enrolment (QR + secret) and TOTP login (wrong code rejected) |
| `02-shell` | dashboard renders ECharts canvases with a clean console; Aurora <-> Meridian and light <-> dark persist across reloads; Ctrl/Cmd+K palette finds a device and navigates |
| `03-inventory-backup` | create a site and a device (linux, credential, port) in the UI, "Run backup" twice around a device change, Backups page, History & diff tab with side-by-side `added` rows, Commits tab |
| `04-tacacs-compliance` | group, user, NAS, policy (+ command rule) and TACACS+ user mapping via the UI, config preview (keys redacted), deploy -> new revision -> the agent installs it; compliance "Run now" -> score gauge |
| `05-accounting-changes-audit` | accounting shows the tac_plus-ng records (dangerous badge, denied result, regex filter); change request four-eyes (requester refused, second manager approves, implement, close); audit log entries and "Verify chain" intact |
| `06-rbac-tenancy-reports` | read-only user sees no write actions and gets 403 on API writes; another tenant sees nothing (UI, search, API, X-Tenant refused for non-operators); CSV / XLSX / PDF downloads |
| `07-sessions-map-ixp-mobile` | asciicast uploaded with the agent token plays in the replay page (audited); network map graph (demo tenant); IXP members and route-server tabs; 390 px viewport: no horizontal overflow on the main pages, navigation drawer |

## CI

`.github/workflows/ci.yml` job `e2e` installs the build dependencies, resolves the upstream
tac_plus-ng commit, restores `$TACPLUS_PREFIX` from `actions/cache` keyed on that commit (building
only on a miss), runs the `tac_plus-ng -P` backend unit test and `e2e/scripts/run.sh` with
PostgreSQL/Redis service containers, and uploads the Playwright report, test results and the
stack logs (including the installed `tac_plus-ng.cfg` and its log files) when it fails.

## Troubleshooting

* `stack-up.sh` prints the last log lines of every component when something does not come up;
  logs stay in `e2e/.run/logs` (copied to `e2e/test-results/stack-logs` by `run.sh`).
* tac_plus-ng rejected a deployed config: the agent logs the `tac_plus-ng -P` output in
  `logs/tacacs.log` and the API raises a `tacacs_deploy_failed` alert.
* tac_plus-ng renames its processes; stop it via its pid file (`e2e/.run/tac/tac_plus-ng.pid`) -
  `stack-down.sh` does this.
