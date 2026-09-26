"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, History, PlayCircle, Upload } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { StatusBadge } from "@/components/common/status-badge";
import { UnifiedDiffBlock } from "@/components/diff/diff-viewer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/use-auth";
import { useOnChange } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { Backup, Change, Device, Page, RestoreOut } from "@/lib/types";
import { formatDateTime, shortSha } from "@/lib/utils";

/** Select backup -> dry run (device-side diff) -> confirm with an approved change request -> push. */
export function RestoreTab({ device }: { device: Device }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [backupId, setBackupId] = React.useState("");
  const [changeId, setChangeId] = React.useState("");
  const [confirmed, setConfirmed] = React.useState(false);
  const [dryRun, setDryRun] = React.useState<RestoreOut | null>(null);
  const [result, setResult] = React.useState<RestoreOut | null>(null);

  const backups = useQuery({
    queryKey: ["backups", "device", device.id, "restorable"],
    queryFn: () => api.get<Page<Backup>>("/backups", { device_id: device.id, limit: 500 }),
    // one entry per stored version: the backup that stored it, plus how often later runs confirmed it
    select: (p) => {
      const byCommit = new Map<string, { b: Backup; runs: number; last: string }>();
      for (const b of p.items) {
        if (!b.commit_sha || b.status === "failed") continue;
        const cur = byCommit.get(b.commit_sha);
        if (!cur) byCommit.set(b.commit_sha, { b, runs: 1, last: b.collected_at });
        else {
          cur.runs += 1;
          if (b.collected_at > cur.last) cur.last = b.collected_at;
          // represent the version by the backup that stored it (else the earliest run)
          if ((b.changed && !cur.b.changed) || (b.changed === cur.b.changed && b.collected_at < cur.b.collected_at)) cur.b = b;
        }
      }
      return [...byCommit.values()].sort((x, y) => (x.b.collected_at < y.b.collected_at ? 1 : -1));
    },
  });
  const changes = useQuery({
    queryKey: ["changes", "approved"],
    queryFn: () => api.get<Page<Change>>("/changes", { state: "approved", limit: 100 }),
    select: (p) => p.items.filter((c) => c.device_ids.map(String).includes(device.id)),
    enabled: can("changes:read"),
  });

  useOnChange(backupId, () => {
    setDryRun(null);
    setResult(null);
    setConfirmed(false);
  });

  const run = useMutation({
    mutationFn: (dry: boolean) =>
      api.post<RestoreOut>(`/devices/${device.id}/restore`, {
        backup_id: backupId,
        dry_run: dry,
        confirm: !dry,
        change_request_id: changeId || null,
      }),
    onSuccess: (r) => {
      if (r.dry_run) {
        setDryRun(r);
      } else {
        setResult(r);
        if (r.status === "pushed") toast.success("Configuration restored", `${device.hostname} is now at ${shortSha(selected?.commit_sha)}`);
        else toast.error("Restore failed", r.output ?? "The device rejected the configuration");
        void qc.invalidateQueries({ queryKey: ["backups"] });
        void qc.invalidateQueries({ queryKey: ["device", device.id] });
      }
    },
    onError: (e) => toast.error("Restore request failed", errorMessage(e)),
  });

  const selected = backups.data?.find((v) => v.b.id === backupId)?.b;

  if (!can("configs:restore")) {
    return <EmptyState icon={History} title="Restore not permitted" description="The configs:restore permission is required." />;
  }
  if (!device.platform) {
    return <EmptyState icon={AlertTriangle} title="No platform assigned" description="Assign a platform that supports atomic config replace." />;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle>1 · Select a backup</CardTitle>
          <CardDescription>The device will be replaced with this configuration.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {backups.isLoading ? (
            <Skeleton className="h-9" />
          ) : (
            <Field label="Backup revision" htmlFor="backup">
              <SimpleSelect
                id="backup"
                value={backupId}
                onValueChange={setBackupId}
                placeholder={backups.data?.length ? "Choose a backup" : "No restorable backups"}
                disabled={!backups.data?.length}
                options={(backups.data ?? []).map(({ b, runs, last }, i) => ({
                  value: b.id,
                  label: `${shortSha(b.commit_sha)} · ${i === 0 ? "current · " : ""}stored ${formatDateTime(b.collected_at)}${b.reason ? ` · ${b.reason}` : ""}${runs > 1 ? ` · confirmed by ${runs} backups, last ${formatDateTime(last)}` : ""}`,
                }))}
              />
            </Field>
          )}
          <Button onClick={() => run.mutate(true)} disabled={!backupId} loading={run.isPending && run.variables === true} variant="outline">
            <PlayCircle /> Dry run
          </Button>
          <p className="text-xs text-muted-foreground">
            Dry run loads the candidate configuration on the device and returns the device-computed diff without committing.
          </p>
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>2 · Review device diff</CardTitle>
          <CardDescription>
            {dryRun ? (
              <span className="flex items-center gap-2">
                Dry run <StatusBadge status={dryRun.status} dot={false} /> at {formatDateTime(dryRun.created_at)}
              </span>
            ) : (
              "Run a dry run to see what would change on the device."
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {dryRun ? (
            dryRun.device_diff ? (
              <UnifiedDiffBlock text={dryRun.device_diff} />
            ) : (
              <p className="rounded-md border bg-muted/30 p-4 text-sm text-muted-foreground">The device reports no differences.</p>
            )
          ) : (
            <p className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">No dry run yet.</p>
          )}
          {dryRun?.output ? <pre className="max-h-40 overflow-auto rounded-md border bg-muted/30 p-2 font-mono text-[11px]">{dryRun.output}</pre> : null}
        </CardContent>
      </Card>

      {dryRun && dryRun.status !== "failed" ? (
        <Card className="border-warning/40 lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" /> 3 · Push to device
            </CardTitle>
            <CardDescription>
              A pre-restore snapshot is taken automatically. Pushing usually requires an approved change request that covers this device.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-[minmax(0,420px)_1fr] md:items-end">
            <Field label="Change request" htmlFor="chg" hint={changes.data?.length ? undefined : "No approved change covers this device."}>
              <SimpleSelect
                id="chg"
                value={changeId}
                onValueChange={setChangeId}
                allowEmpty
                emptyLabel="None"
                placeholder="Select approved change"
                options={(changes.data ?? []).map((c) => ({ value: c.id, label: `CHG-${c.number} · ${c.title}` }))}
              />
            </Field>
            <div className="grid gap-3">
              <Checkbox
                checked={confirmed}
                onCheckedChange={setConfirmed}
                label={`I have reviewed the diff and want to replace the configuration of ${device.hostname}`}
              />
              <div>
                <Button variant="destructive" disabled={!confirmed} loading={run.isPending && run.variables === false} onClick={() => run.mutate(false)}>
                  <Upload /> Restore configuration
                </Button>
              </div>
            </div>
            {result ? (
              <div className="md:col-span-2">
                <p className="mb-1 flex items-center gap-2 text-sm">
                  Result <StatusBadge status={result.status} />
                </p>
                {result.output ? <pre className="max-h-60 overflow-auto rounded-md border bg-muted/30 p-2 font-mono text-[11px]">{result.output}</pre> : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
