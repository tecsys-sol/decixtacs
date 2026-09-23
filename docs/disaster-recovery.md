# Disaster recovery

What must survive a disaster, how it is protected, how fast it comes back, and how to rehearse
it. Items marked **(recommendation)** are operational procedures around the platform, not code
features.

## What to protect

| Asset | Location | Protection |
|---|---|---|
| Relational data (users, RBAC, inventory, TACACS policies, backups metadata, accounting, audit, changes) | PostgreSQL | WAL archiving + base backups (PITR), synchronous standby |
| Configuration history | Git repositories in `NOM_BACKUP_REPO_ROOT/<tenant>` (RWX volume) | volume snapshots + `git push --mirror` to an off-site Git server |
| Session recordings | `NOM_BACKUP_REPO_ROOT/../recordings/<tenant-id>/*.cast` | volume snapshots + sync to object storage |
| Secrets: `NOM_ENCRYPTION_KEYS`, `NOM_JWT_SECRET`, DB/Redis credentials, agent tokens | secret manager | secret manager replication / escrow - **without the Fernet keys every stored device credential, NAS key, integration token and MFA seed is unrecoverable** |
| TACACS runtime state | tac_plus-ng volume: last deployed config, logs, agent offsets | per-instance volume; reproducible from the database (redeploy) |
| Redis | broker queues, rate-limit counters | none needed (transient) |

## RPO / RTO targets

| Scenario | RPO | RTO | Mechanism |
|---|---|---|---|
| Loss of one node / zone | 0 | < 5 min (automatic) | replicas, PDBs, CNPG sync standby failover |
| PostgreSQL primary loss | 0 (sync replica) | < 1 min | CNPG / Patroni automatic promotion |
| Logical corruption / bad migration / operator error | ≤ 5 min (WAL `archive_timeout`) | 1–2 h | point-in-time recovery to a new cluster |
| Loss of the RWX volume | ≤ 15 min (mirror interval) or last snapshot | 1–2 h | restore snapshot or clone mirrors |
| Loss of the whole region / cluster | ≤ 15 min | 4 h | rebuild cluster from Git (manifests) + S3 (PITR) + Git mirrors |
| TACACS management plane down (API/DB) | n/a | **0 for device logins** | tac_plus-ng keeps serving its last configuration |
| All TACACS servers unreachable | n/a | 0 for emergency access | device-local fallback accounts ([below](#device-side-fallback)) |

Accounting records produced while the API is down are not lost: they remain in the tac_plus-ng log
files and are shipped from the persisted offsets when the API is back (keep enough log retention
on the TACACS volume - days, not hours).

## Backups in detail

### PostgreSQL: WAL archiving and PITR

Kubernetes / CloudNativePG (`deploy/k8s/components/cloudnative-pg`):

* `spec.backup.barmanObjectStore` → continuous WAL archiving (gzip) to
  `s3://example-networkops-pg-backups/production`, `retentionPolicy: 30d`.
* `ScheduledBackup nom-db-nightly` → base backup daily 01:00 UTC (`immediate: true` takes one at
  creation).
* Enable S3 versioning + Object Lock (compliance mode) on the bucket and replicate it to a second
  region **(recommendation)**.

VMs: pgBackRest or WAL-G with the same policy (continuous archive, nightly full/differential,
30-day retention, off-site copy).

### Configuration repositories

The platform writes commits locally only. **(recommendation)** mirror them:

```bash
# on a host/pod that mounts NOM_BACKUP_REPO_ROOT (the example CronJob does exactly this)
for repo in /var/lib/nom/configs/*/; do
  git -C "$repo" push --mirror "git@git.example.net:networkops-configs/$(basename "$repo").git"
done
```

`deploy/k8s/extras/git-mirror-cronjob.yaml` runs this every 15 minutes with a deploy key. Mirrors
are complete repositories: every commit with author (engineer), reason, change request and
trigger trailers. Because Git history is content-addressed, a mirror also lets you prove that no
past configuration was altered.

Also snapshot the RWX volume daily (CSI `VolumeSnapshot`, EFS/Filestore backups, NetApp
snapshots).

### Session recordings

Recordings are stored as files (`storage_uri = file://...`); object storage is not implemented in
the API (the replay endpoint returns 501 for non-`file://` URIs). **(recommendation)** sync the
directory to versioned object storage:

```bash
rclone sync /var/lib/nom/recordings s3:example-networkops-recordings --checksum --immutable
```

and apply a lifecycle rule matching `NOM_RETENTION_SESSION_RECORDINGS_DAYS` (that setting is not
enforced by the code).

### Secrets

Keep `NOM_ENCRYPTION_KEYS` (all keys still referenced by ciphertexts), `NOM_JWT_SECRET` and the
database credentials in a replicated secret manager, plus an offline escrow copy (sealed envelope /
HSM backup) under dual control.

## Restore runbook

Order matters: secrets → database → repositories → application → TACACS → verification.

1. **Declare the incident**, freeze changes (no deploys, no restores to devices). Devices keep
   working through tac_plus-ng or local fallback.
2. **Infrastructure**: provision the cluster (or hosts), add-ons (ingress, cert-manager, External
   Secrets, CNPG, storage classes) from your infrastructure code.
3. **Secrets**: restore the secret-manager entries `networkops/<env>/app` and
   `.../tacacs-agent-tokens`. Verify the Fernet keys match the backup era (the newest key first; keep
   every older key that may still be referenced).
4. **Database** (CloudNativePG recovery into a new cluster):

   ```yaml
   apiVersion: postgresql.cnpg.io/v1
   kind: Cluster
   metadata: {name: nom-db, namespace: networkops}
   spec:
     instances: 3
     imageName: ghcr.io/cloudnative-pg/postgresql:16.4
     storage: {size: 200Gi}
     walStorage: {size: 50Gi}
     bootstrap:
       recovery:
         source: nom-db-backup
         recoveryTarget:
           targetTime: "2026-09-23 09:55:00+00"    # omit for "latest"
     externalClusters:
       - name: nom-db-backup
         barmanObjectStore:
           destinationPath: s3://example-networkops-pg-backups/production
           serverName: nom-db
           s3Credentials:
             accessKeyId: {name: nom-db-s3, key: ACCESS_KEY_ID}
             secretAccessKey: {name: nom-db-s3, key: ACCESS_SECRET_KEY}
           wal: {maxParallel: 8}
   ```

   Point the new cluster's `backup.barmanObjectStore.destinationPath` at a **new** path so it does
   not overwrite the archive you recovered from. Patroni/VMs: `pgbackrest --type=time
   --target="..." restore` on a fresh data directory.
5. **Repositories**: restore the RWX volume from its snapshot, or clone the mirrors:

   ```bash
   cd /var/lib/nom/configs
   for t in exampleix customer-a; do git clone --mirror git@git.example.net:networkops-configs/$t.git $t/.git \
     && git -C $t config --bool core.bare false && git -C $t reset --hard; done
   chown -R 10001:10001 /var/lib/nom/configs
   ```

   Commits made after the mirror's last push are lost; the next hourly backup re-collects current
   configurations (they will be recorded as changes relative to the restored HEAD). Rows in
   `config_backups` whose `commit_sha` no longer exists in the repository show "revision not
   found" for diffs; this is cosmetic.
6. **Recordings**: `rclone sync s3:example-networkops-recordings /var/lib/nom/recordings`.
7. **Application**: `kubectl apply -k deploy/k8s/overlays/production`. The migrate Job brings the
   schema to head (a no-op when restoring the same version). Check `/readyz`.
8. **TACACS**: agents reconnect automatically (same tokens). For each TACACS server run
   `POST /api/v1/tacacs/servers/{id}/deploy`: if the restored database predates the last deploy, the
   render differs from what the agents run and they keep their current config (409) until you
   redeploy. If a TACACS volume was lost, the pod starts with the bootstrap config (rejects
   everything) until its first successful poll - restore the API first, or restore the TACACS volume
   too.
9. **Verification**:
   * `GET /api/v1/audit/verify` → `intact: true` (a PITR to a point in time keeps the chain intact);
   * log in with a TACACS account on a test device; check accounting appears in the UI;
   * trigger a backup of a few devices (`POST /backups/run`) and look at the diff;
   * Grafana: backups succeed, `NomTargetDown` clear;
   * integrations sync (`POST /integrations/{id}/sync`).
10. **Close**: unfreeze changes, write the post-incident report, record actual RPO/RTO.

## Device-side fallback

TACACS+ must never be the only way into a device. Configure local fallback that is used **only
when no TACACS server answers** (a TACACS *reject* must not fall through to local), keep one
break-glass local account per device with a strong, vaulted, regularly rotated password, and keep
console authentication local.

**Juniper Junos** - `password` after `tacplus` is consulted only if no server responds:

```
set system authentication-order [ tacplus password ]
set system login user breakglass class super-user authentication encrypted-password "<hash>"
# console: root/local users always work on the console
```

**Arista EOS** - `local` is tried only when the group is unreachable:

```
aaa authentication login default group NOM local
aaa authorization exec default group NOM local
aaa authorization commands all default group NOM local
username breakglass privilege 15 role network-admin secret sha512 <hash>
aaa authentication login console local
```

**Cisco IOS / IOS-XE** - `local` on error only; `if-authenticated` keeps authorization working
for already authenticated sessions:

```
aaa authentication login default group NOM local
aaa authentication login CONSOLE local
aaa authorization exec default group NOM local if-authenticated
aaa authorization commands 15 default group NOM local if-authenticated
username breakglass privilege 15 algorithm-type scrypt secret <secret>
line con 0
 login authentication CONSOLE
```

**Cisco NX-OS** - remote login falls back to local when all servers are unreachable
(`aaa authentication login error-enable` shows the reason):

```
aaa authentication login default group NOM
aaa authentication login console local
username breakglass password 5 <hash> role network-admin
```

**Fortinet FortiGate** - local administrators are evaluated independently of the wildcard
TACACS+ admin, so they keep working when the servers are down:

```
config system admin
    edit "breakglass"
        set accprofile "super_admin"
        set vdom "root"
        set password <password>
        set trusthost1 10.255.0.0 255.255.0.0
    next
end
```

**Sophos SFOS** - keep **Local** in *Administrator authentication methods* after the TACACS+
servers and keep the default `admin` account (with a vaulted password).

**MikroTik RouterOS** (RADIUS, no TACACS+) - local users are used when RADIUS does not respond:

```
/user add name=breakglass group=full password=<password>
/user aaa set use-radius=yes
```

**(recommendation)** The break-glass passwords are themselves inventory secrets: rotate them after
every use, alert on local logins (syslog), and review usage in the post-incident report.

## DR drill checklist

Run at least twice a year; record timings against the RPO/RTO table.

- [ ] Restore the latest base backup + WAL to a scratch CNPG cluster (PITR to "15 minutes ago"); compare row counts of `devices`, `config_backups`, `audit_events` with production.
- [ ] `GET /audit/verify` on the restored instance returns `intact: true`.
- [ ] Clone every Git mirror; `git fsck`; compare `HEAD` of 5 random device files with production.
- [ ] Restore one recording from object storage and replay it in the UI.
- [ ] Start the application (staging overlay) against the restored data with the escrowed secrets; decrypt one device credential (run a backup) and one NAS key (render a TACACS config) - proves the Fernet keys are complete.
- [ ] Stop all tac_plus-ng instances of one site: engineers can still log in via the second site's VIP.
- [ ] Stop all tac_plus-ng instances: break-glass login works on one device per vendor (Junos, EOS, IOS-XE, NX-OS, FortiGate, SFOS, RouterOS); console login works.
- [ ] Stop the API for 30 minutes: TACACS logins keep working; afterwards accounting from the outage appears (ingest catch-up) and `last_heartbeat_at` resumes.
- [ ] Kill the PostgreSQL primary: API recovers < 1 min, no failed backups beyond one chunk.
- [ ] Measure: time to restored database, time to first successful login via the restored platform, amount of data lost.
- [ ] Update this runbook with anything that surprised you.
