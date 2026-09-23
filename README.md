# NetworkOps Manager

**Network access & configuration management for ISPs, IXPs and MSPs** - TACACS+ AAA with
tac_plus-ng, Git-versioned configuration backups, diffs, drift and compliance, command
accounting and session recording, change management with pre/post snapshots and rollback, and
native integrations with NetBox, IXP Manager and BIRD route servers. Multi-tenant, API-first,
built to run 10,000+ devices.

```mermaid
flowchart LR
    eng([Engineers]) --> ui[Web UI<br/>Next.js] --> api[REST API<br/>FastAPI]
    auto([Automation / SDKs]) --> api
    api --> pg[(PostgreSQL)] & redis[(Redis)] & git[(Per-tenant Git repos)]
    workers[Celery workers<br/>Nornir + Scrapli/Netmiko] -->|SSH| dev[(Routers, switches,<br/>firewalls)]
    dev -->|TACACS+ :49| tac[tac_plus-ng + agent]
    tac -->|pull config, ship logs| api
    api --> nb([NetBox]) & ixpm([IXP Manager]) & rs([birdseye / BIRD RS])
```

## Features

The platform is organised in 20 modules (numbering used throughout the code):

| # | Module | Highlights |
|---|---|---|
| 1 | Users & RBAC/ABAC | local, LDAP/AD, OIDC SSO; TOTP MFA; roles bound to users/groups, scoped to sites or device groups, vendor/time conditions; API tokens with scopes |
| 2 | TACACS+ management | policies, NAS clients, user mappings → rendered tac_plus-ng config; explicit deploy; agent validates (`tac_plus-ng -P`), swaps atomically, reloads, reports back; Junos classes, FortiGate profiles, Arista roles, per-command regex authorization |
| 3 | Inventory | regions, sites, racks, devices, platforms, encrypted credentials |
| 4 | Config backup | Nornir-parallel collection, sanitising, per-tenant Git with author/reason/change-request trailers, unchanged detection |
| 5 | Diffs | unified, inline and side-by-side between any two revisions |
| 6 | Compliance | regex rule engine (must/must-not/count/block), severity-weighted device & tenant scores, golden configs |
| 7 | Command accounting | tac_plus-ng access/authz/acct logs ingested, searchable by user/device/command (substring or regex), dangerous-command flags |
| 8 | Session recording | asciicast v2 upload, command index, audited replay |
| 9 | Audit trail | every change with before/after, append-only table, per-tenant hash chain with verification |
| 10 | Change management | draft → approval (four-eyes) → implement → close; automatic pre/post-change backups |
| 11 | Restore / rollback | dry-run with device-computed diff, push gated by an approved change |
| 12 | Device groups | static/dynamic groups used by policies, RBAC scopes, golden configs |
| 13 | Network map | topology links (NetBox cables) |
| 14 | NetBox | sync of sites, racks, devices, cables, VLANs, prefixes, IPs, VRFs, ASNs, contacts; optional push-back |
| 15 | IXP Manager | IX-F member export, member/port data |
| 16 | Monitoring | Prometheus `nom_*` metrics, alert rules, Grafana dashboard |
| 17 | Alerting | email, Slack, Teams, webhooks; rules, severities, throttling, dedup |
| 18 | Reports | device/config changes, user activity, compliance, TACACS - CSV/XLSX/PDF, scheduled by email |
| 19 | Multi-tenancy | tenant isolation for every object, per-tenant Git/TACACS, MSP operators (`X-Tenant`) |
| 20 | Dashboard & search | tenant dashboard, global search |

ISP/IXP extras:

* **Route-server awareness** - BIRD route servers via birdseye: sessions, accepted/filtered/exported
  prefixes, IRR/RPKI filter reasons decoded from IXP Manager's large communities, per-member view.
* **Junos config intelligence search** - backups are parsed (Junos `display set`, Cisco/Arista
  hierarchical) into an index: *all devices using community 65000:100*, *all BGP neighbours of
  AS13335*, *all devices with prefix-list X*.
* **Drift detection** - running vs last backup on demand, backup vs golden config on every change,
  unplanned-change alerts when no change request covers a modification.
* **Change risk analysis** - every diff scored 0–100 (BGP/AAA/firewall removals, interface
  shutdowns, insecure services ...) with findings and a summary.

## Feature → code map

| Feature | API | Implementation |
|---|---|---|
| Login, MFA, tokens, SSO | `backend/app/api/v1/auth.py` | `services/auth/{login,ldap,oidc}.py`, `core/security.py` |
| Users, groups, roles, tenants | `api/v1/users.py` | `services/rbac.py`, `services/bootstrap.py` |
| Inventory, groups, topology | `api/v1/inventory.py` | `models/inventory.py` |
| TACACS+ render/deploy/agent | `api/v1/tacacs.py` | `services/tacacs/{generator,builder,crypt}.py`; agent: `tacacs-agent/` |
| Accounting ingest & search | `api/v1/activity.py` | `services/tacacs/{accounting,ingest}.py` |
| Backups, diffs, restore | `api/v1/configs.py` | `services/backup/*`, `services/{diff,restore}.py`, `workers/tasks.py` |
| Compliance, golden, drift | `api/v1/configs.py` | `services/compliance/*`, `services/drift.py` |
| Config intelligence, risk | `api/v1/configs.py` (`/config-search`, `/analyse-diff`) | `services/intel/parser.py`, `services/risk.py` |
| Recordings, audit, changes | `api/v1/activity.py` | `services/{audit,changes}.py` |
| NetBox, IXP Manager, birdseye | `api/v1/ops.py` | `services/integrations/{netbox,ixpmanager}.py` |
| Alerts, reports, dashboard, search | `api/v1/ops.py` | `services/{alerting,reports}.py` |
| Metrics | `/metrics` (`app/main.py`) | `services/metrics.py`, worker exporter `backend/docker/metrics_exporter.py` |
| Schema, partitions, audit trigger | - | `backend/alembic/versions/0001*,0002*` |
| Scheduled jobs | - | `backend/app/workers/celery_app.py` |
| UI | - | `frontend/` |

## Quickstart (Docker Compose)

```bash
cp .env.example .env
#   set NOM_DB_PASSWORD, NOM_JWT_SECRET (openssl rand -base64 48), NOM_INIT_ADMIN_PASSWORD,
#   GRAFANA_ADMIN_PASSWORD, and NOM_ENCRYPTION_KEYS from:
docker compose run --rm --no-deps api cli genkey
docker compose up -d --build
docker compose run --rm init          # first tenant + superuser admin
```

* UI: `https://localhost` (Caddy, self-signed for localhost) · API docs: `https://localhost/api/docs`
* Grafana: `http://127.0.0.1:3001` · Prometheus: `http://127.0.0.1:9090`
* TACACS+: `:49/tcp` - create a TACACS server in the UI/API, put its agent token into
  `NOM_TACACS_AGENT_TOKEN`, `docker compose up -d tacacs`, then deploy.
* Scale collectors: `docker compose up -d --scale worker=4`.

Production (Kubernetes, HA, TLS, SSO, device onboarding): [docs/deployment.md](docs/deployment.md).

## Local development

Requirements: Python 3.12, Node 22, Go 1.23+, PostgreSQL 16 and Redis 7 (e.g.
`docker compose up -d postgres redis` plus a port mapping, or local services).

```bash
# backend
python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -e "backend[dev,collectors]"
createdb -O nom nom_test                 # tests need a PostgreSQL DB "nom_test" owned by "nom"
                                         # (superuser, or pg_trgm pre-created)
cd backend
export NOM_DATABASE_URL=postgresql+psycopg://nom:nom@localhost:5432/nom
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli init --name Dev --slug dev --username admin --superuser
.venv/bin/uvicorn app.main:app --reload                      # http://localhost:8000/api/docs
.venv/bin/celery -A app.workers.celery_app worker -B -Q collect,alerts,celery   # jobs (+beat)
NOM_TEST_DATABASE_URL=postgresql+psycopg://nom:nom@localhost:5432/nom_test .venv/bin/pytest
.venv/bin/ruff check .

# frontend
cd frontend && npm ci && npm run dev     # http://localhost:3000 ; npm run lint / typecheck / test / build

# TACACS agent and SDKs
cd tacacs-agent && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
cd sdk/python   && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
cd sdk/go/networkops && go test -race ./...
```

The `Makefile` wraps these: `make help` lists `dev`, `dev-worker`, `dev-frontend`, `test`,
`lint`, `migrate`, `init`, `openapi`, `sdk`, `images`, `compose-up`, `compose-init`,
`check-manifests` ...

## Repository layout

```
backend/                 FastAPI app (app/), Alembic migrations, tests, Dockerfile, docker-entrypoint.sh
  app/api/v1/            REST routers        app/services/   domain logic
  app/models/            SQLAlchemy models   app/workers/    Celery app + tasks
frontend/                Next.js UI (own Dockerfile, port 3000)
tacacs-agent/            tac_plus-ng agent (config pull/validate/reload, log shipping, recordings) + image building tac_plus-ng
sdk/python/              Python client "networkops"
sdk/go/networkops/       Go client
sdk/openapi-generator/   configs for generated clients (make sdk)
deploy/k8s/              Kustomize base, components (monitoring, keda, cloudnative-pg, in-cluster datastores), overlays
deploy/prometheus/       scrape config + alert rules      deploy/grafana/   datasource + dashboard
deploy/caddy/            reverse proxy for Compose
docs/                    architecture, database, deployment, HA, DR, backups, security, API
docker-compose.yml       single-host stack                .github/workflows/  CI, release, security
```

## Documentation

* [Architecture](docs/architecture.md) - context, containers, data flows, multi-tenancy, scaling to 10k devices
* [Database](docs/database.md) - schema, ER diagram, partitioning, retention, audit chain
* [Deployment](docs/deployment.md) - Compose, Kubernetes, init, TLS, LDAP/OIDC, integrations, device onboarding (Junos, EOS, IOS, NX-OS, FortiGate, SFOS, RouterOS)
* [High availability](docs/high-availability.md) · [Disaster recovery](docs/disaster-recovery.md)
* [Backup architecture](docs/backup-architecture.md) · [Security hardening](docs/security-hardening.md)
* [API & SDKs](docs/api/README.md) - OpenAPI/Swagger, versioning policy, SDK generation
* [TACACS agent](tacacs-agent/README.md)

## CI/CD

* `ci.yml` - backend ruff + pytest on PostgreSQL 16/Redis 7, `alembic upgrade` + `alembic check`,
  OpenAPI freshness; frontend lint/typecheck/test/build; agent and SDK tests; manifest validation
  (compose, kustomize + kubeconform, promtool); Docker builds of all images (no push).
* `release.yml` - on `v*.*.*` tags: multi-arch images to GHCR with SBOM/provenance, generated SDKs,
  GitHub release with `openapi.json` and SDK artifacts.
* `security.yml` - CodeQL (Python, JS/TS), pip-audit, npm audit, Trivy (images + IaC), gitleaks.
