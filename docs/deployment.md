# Production deployment guide

This guide covers a production installation of NetworkOps Manager (NOM): prerequisites and
sizing, Docker Compose (single host) and Kubernetes (HA), first-run initialisation, TLS,
directory/SSO integration, NetBox / IXP Manager / birdseye, the TACACS+ service and onboarding
devices of each vendor. Related: [architecture](architecture.md),
[high availability](high-availability.md), [disaster recovery](disaster-recovery.md),
[security hardening](security-hardening.md).

## 1. Prerequisites

| Component | Requirement |
|---|---|
| PostgreSQL | **16** (15+ works), `pg_trgm` available (migration 0002 runs `CREATE EXTENSION IF NOT EXISTS pg_trgm`; it is a trusted extension, so the database owner can create it) |
| Redis | **7**, no eviction (`maxmemory-policy noeviction`) - it is the Celery broker |
| Shared storage | a persistent volume for `NOM_BACKUP_REPO_ROOT` (default `/var/lib/nom/configs`) mounted **read-write by the API and every collect worker** - ReadWriteMany on Kubernetes (NFS, CephFS, EFS, Filestore, Azure Files). Session recordings live beside it (`/var/lib/nom/recordings`). |
| Container runtime | Docker 24+/Compose v2, or Kubernetes 1.27+ with an ingress controller, cert-manager, External Secrets Operator; optional: prometheus-operator, KEDA, CloudNativePG |
| Network | workers (and API) → devices: SSH (22 or the device's `ssh_port`); devices → TACACS VIP: TCP/49; API/workers → LDAP(S), OIDC issuer, NetBox, IXP Manager, birdseye, SMTP, webhook targets |
| Secrets | `NOM_JWT_SECRET` (≥ 32 chars), `NOM_ENCRYPTION_KEYS` (Fernet; mandatory when `NOM_ENVIRONMENT=production`), DB/Redis credentials |

Images (built by `.github/workflows/release.yml`, multi-arch amd64/arm64):
`ghcr.io/tecsys-sol/decixtacs/{backend,frontend,tacacs}:<version>`. The backend image serves
all backend roles through its entrypoint: `api | worker | beat | migrate | init |
wait-for-migrations | cli <args>`.

## 2. Sizing

| Deployment | Devices | API | Workers (4 processes each) | PostgreSQL | Redis | RWX volume | TACACS |
|---|---|---|---|---|---|---|---|
| Lab / small (Compose) | ≤ 500 | 1 × 1 vCPU / 1 GB | 1 × 2 vCPU / 3 GB | 2 vCPU / 4 GB / 50 GB | 256 MB | 10 GB | 1 (+1 recommended) |
| Medium | ≤ 3,000 | 3 × 1 vCPU / 1 GB | 2 × 4 vCPU / 6 GB | 4 vCPU / 16 GB / 200 GB, HA | 1 GB, HA | 50 GB | 2 per site |
| Large (reference) | 10,000 | 3–12 × 2 vCPU / 1.5 GB (HPA) | 3–20 × 4 vCPU / 6 GB (KEDA) | 3 × (8 vCPU / 32 GB / 500 GB NVMe + 50 GB WAL), sync replica | 2 GB, managed HA | 200 GB | 2–3 per site, per tenant |

Storage figures assume ~1M accounting records/day with 365-day retention; see
[architecture.md §5](architecture.md#5-scaling) for the derivation and the collection timing
model (40 chunks of 250 devices per hourly run).

## 3. Docker Compose (single host)

```bash
git clone https://github.com/tecsys-sol/decixtacs.git && cd decixtacs
cp .env.example .env
# set at least:
#   NOM_DB_PASSWORD, NOM_JWT_SECRET (openssl rand -base64 48), NOM_INIT_ADMIN_PASSWORD,
#   NOM_DOMAIN / NOM_PUBLIC_URL, GRAFANA_ADMIN_PASSWORD
docker compose run --rm --no-deps api cli genkey      # -> put the key in NOM_ENCRYPTION_KEYS
docker compose up -d --build                          # postgres, redis, migrate, api, worker, beat,
                                                      # frontend, tacacs, proxy, prometheus, grafana
docker compose run --rm init                          # first tenant + superuser (NOM_INIT_*)
docker compose ps
```

| Service | Role | Notes |
|---|---|---|
| `postgres` | PostgreSQL 16 | healthcheck `pg_isready`; volume `pgdata` |
| `redis` | Redis 7 (AOF) | volume `redisdata` |
| `migrate` | one-shot `alembic upgrade head` | api/worker/beat start after it completed successfully |
| `api` | uvicorn :8000 | `/readyz` healthcheck; volume `nom-data` |
| `worker` | Celery, queues `collect,alerts,celery` | `docker compose up -d --scale worker=4`; metrics :9808 |
| `beat` | Celery beat | exactly one |
| `frontend` | Next.js :3000 | |
| `tacacs` | tac_plus-ng + agent | publishes `:49/tcp`; set `NOM_TACACS_AGENT_TOKEN` (§8) |
| `proxy` | Caddy :80/:443 | `/api/*`, `/healthz`, `/readyz` → api; `/metrics` → 404; rest → frontend |
| `prometheus` / `grafana` | monitoring | bound to 127.0.0.1:9090 / :3001; dashboard "NetworkOps Manager" is provisioned |

Backend containers run as uid 10001 with a read-only root filesystem, `no-new-privileges` and
all capabilities dropped. `make compose-up`, `make compose-init`, `make compose-logs` wrap the
commands above.

**Docker subnets must not overlap your management network.** Docker puts `docker0` on
`172.17.0.0/16` and allocates Compose networks from `172.18.0.0/16` upwards (and
`192.168.x.0/20`). If devices live in those ranges (for example `172.17.148.2`), the host
routes their traffic into a local bridge: backups fail with *timed out reading from transport*
and the device shows as down, although SSH works from other hosts. Check with
`ip route get <device-ip>` - it must leave via the real interface (`eth0`/`ens5`), not
`docker0`/`br-…`. Move Docker to an unused range before the first `up` (or afterwards, then
`docker compose down && docker compose up -d` so the networks are recreated):

`/etc/docker/daemon.json` (pick ranges used nowhere in your network):

```json
{
  "bip": "192.168.200.1/24",
  "default-address-pools": [{ "base": "192.168.208.0/20", "size": 24 }]
}
```

```bash
docker compose down && sudo systemctl restart docker && docker compose up -d
ip route get 172.17.148.2         # now via the real interface
```

## 4. Kubernetes

Manifests: `deploy/k8s` (Kustomize).

```
deploy/k8s/
├── base/                        namespace (PSS restricted), ConfigMap, ExternalSecrets, RWX PVC,
│                                migrate Job, api (Deployment+Service+PDB+HPA), worker, beat,
│                                frontend, tacacs (StatefulSet + LoadBalancer :49), Ingress,
│                                NetworkPolicies (default deny)
├── components/
│   ├── monitoring/              ServiceMonitor (api + worker exporter), PrometheusRule
│   ├── keda/                    ScaledObject on the Redis 'collect' list length
│   ├── cloudnative-pg/          3-instance Cluster, sync replication, barman S3 backups, ScheduledBackup
│   └── in-cluster-datastores/   single Postgres + Redis (staging/labs only)
├── overlays/{staging,production}/
└── extras/                      init Job, secret shape example, git mirror CronJob
```

Steps:

1. **Cluster add-ons**: ingress-nginx, cert-manager with a `ClusterIssuer` (`letsencrypt-prod`),
   External Secrets Operator with a `ClusterSecretStore` named `networkops-secret-store`, an RWX
   `StorageClass`; for production also the CloudNativePG operator, KEDA and kube-prometheus-stack.
2. **Secrets** in your secret manager (never in Git), key `networkops/<env>/app` with properties
   `database_url, redis_url, jwt_secret, encryption_keys, ldap_bind_password, oidc_client_secret,
   smtp_username, smtp_password, init_admin_password` (+ `db_password`, `redis_address`,
   `redis_password` for the CNPG/KEDA components) and `networkops/<env>/tacacs-agent-tokens`
   (filled in step 7). Shape: `deploy/k8s/extras/secret.example.yaml`.
3. **Adapt the overlay**: hostnames (`nom.example.net`), `storageClassName` of `nom-data`, image
   tags, `loadBalancerSourceRanges` / LB annotations of `nom-tacacs`, egress CIDRs in
   `networkpolicies.yaml` (device management networks, managed Redis subnet), S3 bucket of the CNPG
   cluster, ConfigMap values (LDAP/OIDC/SMTP).
4. **Render and apply**:

   ```bash
   kubectl kustomize deploy/k8s/overlays/production | less        # review
   kubectl apply -k deploy/k8s/overlays/production
   kubectl -n networkops get pods -w
   ```

   Ordering: the `nom-migrate` Job is an Argo CD `PreSync` hook (sync-wave −1). With plain
   `kubectl apply` everything is applied at once and the api/worker/beat pods block in their
   `wait-for-migrations` init container until the schema is at the Alembic head. The Job has
   `ttlSecondsAfterFinished: 600`, so re-applying later re-runs migrations (idempotent). With Flux,
   put the Job in its own Kustomization and make the app depend on it.
5. **First-run init**: `kubectl -n networkops apply -f deploy/k8s/extras/init-job.yaml` and
   `kubectl -n networkops logs -f job/nom-init` (§5).
6. **DNS**: point `nom.example.net` at the ingress and a DNS name (e.g. `tacacs.example.net`) at the
   `nom-tacacs` LoadBalancer IP.
7. **TACACS agents**: create one TACACS server object per replica (`nom-tacacs-0`, `-1`, `-2`),
   store the returned agent tokens under those property names, then restart the StatefulSet (§8).

Security posture of the manifests: namespace enforces the *restricted* Pod Security Standard; all
pods run as non-root with `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`,
`capabilities: drop [ALL]`, `seccompProfile: RuntimeDefault`, no service-account token; tac_plus-ng
binds :49 via the safe sysctl `net.ipv4.ip_unprivileged_port_start=0`. NetworkPolicies are
default-deny with explicit allows (see `base/networkpolicies.yaml`).

The `nom-tacacs` Service uses `externalTrafficPolicy: Local`. **This is required**: tac_plus-ng
identifies a NAS - and chooses its shared key - by the packet's source address; SNAT to a node
address would break authentication for every device.

## 5. First-run initialisation

`python -m app.cli init` (container role `init`) seeds the permission catalogue, built-in roles,
vendors/platforms and default compliance rules, then creates the first tenant with an admin user
bound to the `admin` role. It is idempotent (an existing tenant slug is left untouched).

```bash
# container
docker compose run --rm init            # uses NOM_INIT_TENANT_NAME/SLUG, NOM_INIT_ADMIN_USERNAME/PASSWORD/EMAIL, NOM_INIT_SUPERUSER
# bare metal / venv
cd backend && python -m app.cli init --name "Example IX" --slug exampleix --username admin --superuser
```

`--superuser` makes the admin a **platform operator** (all permissions, may act in other tenants
with `X-Tenant`). For an MSP, create further tenants with `POST /api/v1/tenants` (permission
`tenants:admin`). The password must satisfy the policy (`NOM_PASSWORD_MIN_LENGTH`, character
classes). After the first login: enable MFA for the admin (`/auth/mfa/setup` + `/auth/mfa/verify`),
create named accounts, and stop using the bootstrap account.

`init` also creates/updates the tenant's NetBox / IXP Manager integrations from
`NOM_NETBOX_URL`/`NOM_NETBOX_TOKEN` and `NOM_IXPMANAGER_URL`/`NOM_IXPMANAGER_API_KEY` when those
are set (see §9).

Other CLI commands:

| Command | Purpose |
|---|---|
| `genkey` | new Fernet key |
| `rotate-secrets` | re-encrypt with the newest key, see [security-hardening.md](security-hardening.md#4-secret-encryption-and-key-rotation) |
| `sync-integrations-from-env --tenant <slug>` | create/update the env-managed integrations (§9) for an existing tenant |
| `seed-demo --tenant <slug> [--force] [--seed N]` | fill a tenant with deterministic demo data (below) |
| `export-openapi --output openapi.json` | write the OpenAPI document |

### Demo data

`python -m app.cli seed-demo --tenant demo` populates an **existing** tenant through the real
services: 4 sites, 13 devices (Junos, EOS, IOS, FortiOS) in 4 device groups, a 30-day Git history
produced by the backup engine with a built-in fake collector (back-dated commits, authors
correlated from ingested TACACS accounting), compliance runs, 6 change requests in every state
with pre/post snapshots, a TACACS server with NAS clients, policies and user mappings, 7 days of
accounting/authentication events, two session recordings, IXP members and route-server clients
(via the IXP Manager / birdseye sync code with canned payloads), alerts and a golden config. It
creates the users `alice` (network engineer), `bob` (NOC) and `carol` (change manager) with the
password `Demo-Passw0rd-2026` - **demo environments only**. It refuses to run when the tenant
already has devices; `--force` wipes the tenant's inventory, activity, TACACS and IXP data (the
audit trail and non-demo users are kept) and re-seeds. The RNG is seeded (`--seed`, default 42),
timestamps are relative to "now". The end-to-end suite uses it:

```bash
python -m app.cli init --slug demo --name Demo --password '<admin password>' --superuser
python -m app.cli seed-demo --tenant demo
```

## 6. TLS

* **Compose**: Caddy obtains and renews certificates automatically for `NOM_DOMAIN` (ports 80/443
  must be reachable for the ACME HTTP-01 challenge). For internal names use
  `tls internal` or mount your own certificate (`tls /certs/fullchain.pem /certs/key.pem`) in
  `deploy/caddy/Caddyfile`.
* **Kubernetes**: cert-manager issues `nom-tls` from the `cert-manager.io/cluster-issuer`
  annotation of the Ingress (`letsencrypt-prod`; staging overlay uses `letsencrypt-staging`).
* The API sets HSTS itself when `NOM_ENVIRONMENT=production`; the proxies set it too.
* Internal hops: use `sslmode=require` (or `verify-full`) in `NOM_DATABASE_URL` and `rediss://` for
  managed Redis. CloudNativePG serves TLS by default.
* The TACACS agent talks to the API over the cluster network by default
  (`NOM_AGENT_API_URL=http://nom-api:8000`); when agents run outside the cluster use the public
  HTTPS URL (`NOM_AGENT_CA_FILE` for a private CA).
* TACACS+ itself is not TLS-protected (RFC 8907 obfuscation with the shared key); keep it on the
  management network. (Recent tac_plus-ng builds can terminate TACACS+ over TLS 1.3; the platform
  does not render that configuration yet.)

## 7. Identity: LDAP / Active Directory and OIDC

### LDAP / AD (portal login + TACACS)

```bash
NOM_LDAP_ENABLED=true
NOM_LDAP_URI=ldaps://dc1.example.net
NOM_LDAP_BIND_DN=CN=svc-networkops,OU=Service Accounts,DC=example,DC=net
NOM_LDAP_BIND_PASSWORD=...                          # secret
NOM_LDAP_USER_BASE=OU=Staff,DC=example,DC=net
NOM_LDAP_USER_FILTER=(sAMAccountName={username})    # OpenLDAP: (uid={username})
NOM_LDAP_GROUP_BASE=OU=Groups,DC=example,DC=net
NOM_LDAP_GROUP_ATTR=memberOf
```

How it works (`services/auth/login.py`, `ldap.py`): unknown users or users with `auth_source`
`ldap`/`ad` are authenticated by binding as the service account, searching the user, then binding
as the user. On success the user is provisioned just-in-time, and membership of platform groups
whose `source` is `ldap`/`ad` is synchronised from the directory groups (matched by group name,
case-insensitive). Grant access by binding roles to those groups:

```bash
# 1. create a platform group mirroring the AD group "NetOps-Engineers"
curl -sX POST $NOM/api/v1/groups -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"NetOps-Engineers","source":"ad","external_dn":"CN=NetOps-Engineers,OU=Groups,DC=example,DC=net"}'
# 2. bind the built-in network-engineer role to it (optionally scoped to a site or device group)
curl -sX POST $NOM/api/v1/role-bindings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"role_id":"<network-engineer role id>","group_id":"<group id>"}'
```

TACACS users can authenticate against the same directory: set `ldap_backend: true` on the TACACS
server and `auth_method: "ldap"` on the user mapping. The rendered tac_plus-ng configuration then
uses the mavis LDAP module (`mavis_tacplus-ng_ldap.pl`, flavour `microsoft` when the user filter
contains `sAMAccountName`) with the same bind credentials.

### OIDC (Keycloak, Entra ID, Okta, Authentik ...)

```bash
NOM_OIDC_ENABLED=true
NOM_OIDC_ISSUER=https://login.example.net/realms/netops     # /.well-known/openid-configuration is appended
NOM_OIDC_CLIENT_ID=networkops
NOM_OIDC_CLIENT_SECRET=...                                  # secret
NOM_OIDC_REDIRECT_URI=https://nom.example.net/auth/callback
NOM_OIDC_GROUPS_CLAIM=groups
```

Register a confidential client with the redirect URI above, scopes `openid profile email groups`
and a `groups` claim in the ID token. The flow is authorization code + PKCE
(`GET /auth/oidc/authorize` → IdP → `GET /auth/oidc/callback`). Users are matched by `sub`,
provisioned on first login, and membership of platform groups with `source: "oidc"` follows the
groups claim; groups not sourced from OIDC are never touched. The pending state/PKCE verifier is
kept in Redis (10 min, single use), so no session affinity is needed with several API replicas
(see [high-availability.md](high-availability.md#api)).

## 8. TACACS+ service

1. **Register the server** and keep the agent token (shown once):

   ```bash
   curl -sX POST $NOM/api/v1/tacacs/servers -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name":"nom-tacacs-0","address":"192.0.2.49","port":49,"ldap_backend":false}'
   # -> {"id":"...","agent_token":"nomagent_..."}
   ```

   Compose: put it in `.env` as `NOM_TACACS_AGENT_TOKEN` and `docker compose up -d tacacs`.
   Kubernetes: store it under property `nom-tacacs-0` of `networkops/<env>/tacacs-agent-tokens`.
   Classic host install: `pip install ./tacacs-agent`, run `nom-tacacs-agent run` under systemd with
   `NOM_AGENT_RELOAD_MODE=command NOM_AGENT_RELOAD_COMMAND="systemctl reload tac_plus-ng"`
   (see `tacacs-agent/README.md`).
2. **NAS clients**: `POST /tacacs/devices/import-inventory` creates one NAS entry with a random
   key per inventory device (or `POST /tacacs/devices` for a CIDR entry). Read keys once from the
   create/rotate responses (`POST /tacacs/devices/{id}/rotate-key`) and configure them on the
   devices.
3. **Policies**: `POST /tacacs/policies` - group → privilege level, Junos class
   (`local-user-name`), FortiGate `admin_prof`, Arista role, ordered permit/deny command regexes,
   default action, optional time window, optional device group.
4. **Users**: `POST /tacacs/users` maps a platform user to a TACACS username (`crypt` with a
   password, or `ldap`).
5. **Preview and deploy**: `GET /tacacs/render?server_id=...` (keys redacted, warnings e.g. for
   MikroTik NAS entries) then `POST /tacacs/servers/{id}/deploy`. Within `NOM_AGENT_POLL_INTERVAL`
   (30 s) the agent validates, swaps and reloads; `last_heartbeat_at` and the heartbeat message show
   the result. Every later policy/user/NAS change requires a new deploy (the agent receives `409`
   until then and keeps the running configuration).

### Migrating from classic Shrubbery tac_plus (F4.0.4.x)

The platform manages **tac_plus-ng**; the classic `tac_plus` daemon uses a different configuration
language and cannot be driven by the agent. Migrate without touching devices or passwords:

1. **Import.** TACACS+ → *Import tac_plus config* (or `POST /api/v1/tacacs/import` with
   `{"content": "...", "dry_run": true}`). The preview shows what will be created and the resulting
   tac_plus-ng config; nothing changes until you confirm.
   * `host = X { key = … }` → NAS clients with the **same shared keys** (matched to inventory devices by
     management IP); the global `key` becomes catch-all NAS clients `0.0.0.0/0` and `::/0`.
   * `group` → platform group + policy (`member =` inheritance flattened; child settings win).
   * `user` → platform user + TACACS mapping. `login = des …` hashes (from `tac_pwd`) are kept - tac_plus-ng
     verifies them with crypt(3) - and `cleartext` passwords are re-hashed with SHA-512.
   * `service = exec|shell { priv-lvl }`, `junos-exec { local-user-name, allow/deny-commands }`,
     `fortigate { admin_prof }` and `cmd = X { permit|deny regex }` become privilege level, vendor attributes
     and ordered command rules. A user's own `service`/`cmd` entries become a personal policy that takes
     precedence over group policies.
   * Reported, not imported: `acl` (source restrictions), `enable`/`pap`/`chap` passwords,
     `login = file|PAM` and `default authentication = file …` (those users must get a password or use
     LDAP), `before/after authorization` scripts, `accounting file`. Re-importing skips existing objects.
2. **Review** the policies, set passwords for the users listed as needing one, compare *Config preview*
   with the old file.
3. **Cut over one server at a time.** Either point devices at the platform's own `tacacs` container, or
   install tac_plus-ng + the agent on the old host (build: `e2e/scripts/build-tac-plus-ng.sh`), stop the
   old `tac_plus`, start tac_plus-ng on port 49, add the server in the portal, set up the agent (above)
   and *Deploy*. Test logins and command authorization per vendor; roll back by stopping tac_plus-ng and
   starting the old daemon.

### Migrating backups from RANCID

**Configuration → RANCID migration**:

1. Paste `~rancid/.cloginrc` (and `cat /var/lib/rancid/*/router.db`) → **Preview** → **Import**. Each
   device gets the login clogin would use; the most common one becomes the default credential,
   the others are assigned per device, and router.db fills in missing platforms. Devices RANCID
   reaches with an SSH key are listed - add the key to a credential yourself.
2. Run a backup, then on the RANCID host `tar czf rancid-configs.tgz -C /var/lib/rancid .` and
   **Upload RANCID configs**. Each router shows *Identical* / *Differs* (with a side-by-side diff) /
   *No NOM backup yet*. Retire RANCID once everything is identical or differs only by recent changes.
3. Keep RANCID's change history: on the RANCID host (`RCSSYS=cvs`)
   `tar czf /tmp/rancid-cvs.tgz -C /var/lib/rancid/CVS .` and **Upload CVS archive**. A worker rebuilds
   every revision of `<group>/configs/<router>,v` (Attic included), converts it to NOM's format
   (Junos → `display set`, RANCID's comment header dropped, secrets masked when sanitising is on) and
   writes it, with its original date, author and log message, to a separate Git repository
   (`$NOM_BACKUP_REPO_ROOT/<tenant>-rancid`). History & diff and the Change history tab then list those
   revisions (marked *RANCID*) before NOM's own backups, and can diff across the boundary. Re-uploading
   replaces the import; **Remove** deletes it. The upload goes through nginx: keep
   `client_max_body_size` above the archive size (the API accepts up to 200 MB).

Slow or session-limited platforms: **Backups → Backup settings** sets timeout, parallel sessions
and collection commands per platform.

**Who changed what**: config diffs colour every changed line by the engineer whose TACACS+
accounting record produced it. For exact per-line attribution on Junos, send configuration
changes to TACACS+ accounting (`set system accounting events [ login change-log interactive-commands ]`);
IOS/EOS need `aaa accounting commands 15 ... start-stop group tacacs+`. With only
configure/commit logged, lines are attributed as *inferred* when one engineer configured the device.

### Ports & connections (DCIM view)

Each device's **Ports & connections** tab draws its front panel from the NetBox community
[devicetype-library](https://github.com/netbox-community/devicetype-library) (CC0) and fills every
port from the latest backed-up config: description, admin state, LAG, VLANs, addresses, IGP/MPLS.
Neighbours come from NetBox cables, the other end of point-to-point subnets, BGP neighbours on the
port (with IXP member names) and devices/ASNs named in descriptions.

* The model comes from NetBox (device type), else RANCID's header, else **Set model** on the tab.
* ~50 common models are bundled; others (and front-panel photos) are fetched from GitHub once and
  cached under `<NOM data>/devicetypes`. Needs outbound HTTPS to `api.github.com` and
  `raw.githubusercontent.com`; set `NOM_DEVICETYPE_INDEX_URL=` and `NOM_DEVICETYPE_LIBRARY_URL=`
  (empty) to stay offline with the bundled models.

## 9. Integrations

All integrations are per tenant: `POST /api/v1/integrations` (permission `integrations:write`),
token stored Fernet-encrypted; syncs run every `NOM_NETBOX_SYNC_MINUTES` and on demand with
`POST /api/v1/integrations/{id}/sync`.

Bootstrap from the environment: when `NOM_NETBOX_URL` (+ `NOM_NETBOX_TOKEN`) and/or
`NOM_IXPMANAGER_URL` (+ `NOM_IXPMANAGER_API_KEY`) are set, `python -m app.cli init` and
`python -m app.cli sync-integrations-from-env --tenant <slug>` create or update the integrations
named `netbox-env` / `ixpmanager-env` for that tenant (URL and token; options are left alone and
can be edited in the UI/API). Integrations created through the API are never modified. Running the
command again after changing a variable rotates the stored token (audited as
`integration.update`).

```jsonc
// NetBox 3.x/4.x - read-only API token (write if push_back is enabled)
{"kind": "netbox", "name": "netbox", "base_url": "https://netbox.example.net", "token": "<token>",
 "options": {
   "filters": {"tenant": "exampleix", "status": "active"},   // NetBox device query filters
   "platform_map": {"juniper-junos": "junos"},                // NetBox platform slug -> NOM platform
   "sync_cables": true,                                       // topology links from cables
   "mirror": ["vlan", "prefix", "ip", "vrf", "asn", "contact"],
   "push_back": false,                                        // write serial / os_version back
   "verify_tls": true}}

// IXP Manager - IX-F member export (API key of a read-only user)
{"kind": "ixpmanager", "name": "ixpm", "base_url": "https://portal.example-ix.net", "token": "<api key>"}

// birdseye (BIRD route server looking glass API) - one integration per route server / AFI
{"kind": "birdseye", "name": "rs1-v4", "base_url": "https://rs1-v4.lg.example-ix.net",
 "options": {"name": "rs1-v4", "rs_asn": 65000, "filter_reasons": true}}
```

Results: devices/sites/racks/links and mirrored IPAM objects (`GET /external-objects`), IXP members
(`GET /ixp/members`) and route-server sessions with accepted/filtered prefixes and IRR/RPKI filter
reasons (`GET /ixp/route-server-clients?only_problems=true`). Filter reasons are decoded from the
large communities of IXP Manager's standard route-server template (`options.filter_codes`
overrides the mapping for modified templates).

## 10. Onboarding devices to TACACS+

Common preparation:

* Add the device to the inventory (or sync it from NetBox), assign platform + credential, then
  create its NAS entry and deploy (§8). Configure the **same key** on the device.
* Point devices at the **TACACS VIP** (`192.0.2.49` below) and, where supported, at a second server
  as well. Source the packets from the address registered as NAS address (loopback or management
  interface) - the key is selected by source address.
* Keep a **local emergency account** and configure fallback to local authentication *only when the
  servers are unreachable* (details and per-vendor fallback in
  [disaster-recovery.md](disaster-recovery.md#device-side-fallback)). Keep console access local.
* Enable command accounting so backups can be attributed to the engineer who made the change.

### Juniper MX / PTX / QFX / SRX (Junos)

The platform returns `local-user-name` (the Junos class template account; default `remote-su` for
privilege 15 and `remote-ro` otherwise, or the policy's `junos_class`) plus
`allow-commands`/`deny-commands` regexes, which Junos enforces locally.

```
set system tacplus-server 192.0.2.49 secret "<nas-key>"
set system tacplus-server 192.0.2.49 source-address 10.255.0.1
set system tacplus-server 192.0.2.50 secret "<nas-key>"
set system tacplus-server 192.0.2.50 source-address 10.255.0.1
# if the servers are reached through the management instance:
# set system tacplus-server 192.0.2.49 routing-instance mgmt_junos
set system authentication-order [ tacplus password ]
set system login user remote-su uid 2001 class super-user
set system login user remote-ro uid 2002 class read-only
set system accounting events [ login change-log interactive-commands ]
set system accounting destination tacplus server 192.0.2.49 secret "<nas-key>"
set system accounting destination tacplus server 192.0.2.50 secret "<nas-key>"
```

### Arista EOS

```
ip tacacs vrf MGMT source-interface Management1
tacacs-server host 192.0.2.49 vrf MGMT key 0 <nas-key>
tacacs-server host 192.0.2.50 vrf MGMT key 0 <nas-key>
aaa group server tacacs+ NOM
   server 192.0.2.49 vrf MGMT
   server 192.0.2.50 vrf MGMT
aaa authentication login default group NOM local
aaa authorization exec default group NOM local
aaa authorization commands all default group NOM local
aaa accounting exec default start-stop group NOM
aaa accounting commands all default start-stop group NOM
```

The platform returns `priv-lvl` (and `roles` when the policy sets `arista_role`) plus
per-command permit/deny for `service=shell`.

### Cisco IOS / IOS-XE

```
aaa new-model
tacacs server NOM-1
 address ipv4 192.0.2.49
 key 0 <nas-key>
tacacs server NOM-2
 address ipv4 192.0.2.50
 key 0 <nas-key>
aaa group server tacacs+ NOM
 server name NOM-1
 server name NOM-2
 ip vrf forwarding Mgmt-intf
 ip tacacs source-interface GigabitEthernet0
aaa authentication login default group NOM local
aaa authorization exec default group NOM local if-authenticated
aaa authorization commands 1 default group NOM local if-authenticated
aaa authorization commands 15 default group NOM local if-authenticated
aaa authorization config-commands
aaa accounting exec default start-stop group NOM
aaa accounting commands 1 default start-stop group NOM
aaa accounting commands 15 default start-stop group NOM
line vty 0 15
 login authentication default
 authorization exec default
 authorization commands 15 default
 transport input ssh
```

NX-OS (short form):

```
feature tacacs+
tacacs-server host 192.0.2.49 key 0 <nas-key>
tacacs-server host 192.0.2.50 key 0 <nas-key>
aaa group server tacacs+ NOM
  server 192.0.2.49
  server 192.0.2.50
  use-vrf management
  source-interface mgmt0
aaa authentication login default group NOM
aaa authorization commands default group NOM local
aaa accounting default group NOM
```

### Fortinet FortiGate (FortiOS)

The platform answers `service=fortigate` with `admin_prof` (the policy's `fortigate_profile`,
default `super_admin` for privilege 15 else `prof_admin_readonly`) and `memberof`.

```
config user tacacs+
    edit "NOM-1"
        set server "192.0.2.49"
        set secondary-server "192.0.2.50"
        set key <nas-key>
        set authen-type ascii
        set authorization enable
        set source-ip 10.255.0.10
    next
end
config user group
    edit "NOM-admins"
        set member "NOM-1"
    next
end
config system admin
    edit "nom-tacacs"
        set remote-auth enable
        set wildcard enable
        set remote-group "NOM-admins"
        set accprofile "prof_admin_readonly"
        set accprofile-override enable
        set vdom "root"
    next
end
config log tacacs+accounting setting
    set status enable
    set server "192.0.2.49"
    set server-key <nas-key>
end
config log tacacs+accounting filter
    set login-audit enable
    set config-change-audit enable
    set cli-cmd-audit enable
end
```

`accprofile-override enable` makes FortiOS use the returned `admin_prof`. Local admin accounts
keep working independently of TACACS+.

### Sophos Firewall (SFOS)

Configuration backups of SFOS use the XML API, not SSH: enable it under *Backup & firmware > API*,
allow-list the collector workers' addresses and give the device a credential of an API-enabled
administrator (see [backup-architecture.md](backup-architecture.md#sophos-firewall-sfos)).

SFOS supports TACACS+ for **administrator authentication** (web admin and SSH console); per-command
authorization and command accounting are not available, so permissions come from the SFOS
administrator profile.

1. *Authentication → Servers → Add*: type **TACACS+**, server IP `192.0.2.49`, port 49, shared
   secret `<nas-key>` (add `192.0.2.50` as a second server).
2. *Authentication → Services → Administrator authentication methods*: select the TACACS+ servers
   first, then **Local**.
3. Map the users to an administrator profile (group settings of the authentication server /
   user import), and keep a local admin account for emergencies.

Menu names vary between SFOS versions (v19/v20/v21); check the Sophos documentation for yours.

### MikroTik RouterOS

RouterOS has **no TACACS+ client** - it supports RADIUS only. The platform still backs up
RouterOS devices over SSH (`/export terse`), but it renders MikroTik NAS entries as comments and
reports a warning ("use RADIUS"). Authenticate RouterOS logins against a RADIUS server (e.g.
FreeRADIUS backed by the same LDAP/AD); NOM does not provide a RADIUS server:

```
/radius add service=login address=192.0.2.60 secret=<radius-secret> src-address=10.255.0.20 timeout=2s
/user aaa set use-radius=yes default-group=read accounting=yes interim-update=5m
# keep a local admin; RouterOS falls back to local users when RADIUS does not answer
```

## 11. Upgrades

1. Read the release notes (migrations, configuration changes).
2. Back up: CloudNativePG on-demand backup (`kubectl cnpg backup nom-db`) or `pg_dump`, plus the
   RWX volume snapshot ([disaster-recovery.md](disaster-recovery.md)).
3. Bump the image tag in the overlay (or `NOM_VERSION` for Compose) and apply. Migrations run
   first (Job / `migrate` service); pods wait for the schema; API rolls with `maxUnavailable: 0`;
   beat is recreated; workers finish running tasks during their termination grace period.
4. Verify `/readyz`, `GET /api/v1/audit/verify`, the Grafana dashboard, and a TACACS heartbeat.

Alembic migrations are forward-only in production; roll back by restoring the database backup
together with the previous image.
