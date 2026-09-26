"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArchiveRestore, CheckCircle2, FileUp, GitCompare, History, KeyRound, Loader2, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { KpiTile } from "@/components/common/kpi-tile";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { DiffViewer } from "@/components/diff/diff-viewer";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import { donutOption, type StatusColors } from "@/lib/charts";
import type { DiffOut } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

interface PlannedCredential {
  name: string;
  username: string;
  has_password: boolean;
  has_enable_secret: boolean;
  existing: boolean;
  is_default: boolean;
  devices: string[];
}

interface ImportResult {
  dry_run: boolean;
  credentials: PlannedCredential[];
  assigned: number;
  kept_existing: string[];
  no_login: string[];
  ssh_keys: string[];
  router_db_not_in_inventory: string[];
  router_db_down: string[];
  platforms_set: string[];
  warnings: string[];
}

interface CompareRow {
  id: string;
  rancid_name: string;
  rancid_group: string | null;
  device_id: string | null;
  hostname: string | null;
  platform: string | null;
  status: "identical" | "differs" | "no_portal_backup" | "not_in_inventory";
  rancid_lines: number;
  portal_lines: number;
  only_in_rancid: number;
  only_in_portal: number;
  similarity: number;
  portal_collected_at: string | null;
  imported_at: string;
}

const STATUS: Record<CompareRow["status"], { label: string; variant: BadgeVariant; tone: keyof StatusColors }> = {
  identical: { label: "Identical", variant: "success", tone: "success" },
  differs: { label: "Differs", variant: "warning", tone: "warning" },
  no_portal_backup: { label: "No NOM backup yet", variant: "danger", tone: "danger" },
  not_in_inventory: { label: "Not in inventory", variant: "muted", tone: "neutral" },
};

function readFile(setter: (v: string) => void) {
  return async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setter(await f.text());
    e.target.value = "";
  };
}

function NameList({ title, items, tone = "muted" }: { title: string; items: string[]; tone?: "muted" | "warning" | "danger" }) {
  if (!items.length) return null;
  return (
    <details className={cn("rounded-lg border p-3 text-sm", tone === "warning" && "border-warning/40 bg-warning/5", tone === "danger" && "border-danger/40 bg-danger/5")}>
      <summary className="cursor-pointer font-medium">
        {title} ({items.length})
      </summary>
      <p className="mt-1.5 font-mono text-xs leading-relaxed">{items.join(", ")}</p>
    </details>
  );
}

function CredentialsStep() {
  const qc = useQueryClient();
  const [cloginrc, setCloginrc] = React.useState("");
  const [routerDb, setRouterDb] = React.useState("");
  const [setPlatforms, setSetPlatforms] = React.useState(true);
  const [overwrite, setOverwrite] = React.useState(false);
  const [result, setResult] = React.useState<ImportResult | null>(null);
  const clogRef = React.useRef<HTMLInputElement>(null);
  const dbRef = React.useRef<HTMLInputElement>(null);

  const run = useMutation({
    mutationFn: (dryRun: boolean) =>
      api.post<ImportResult>("/rancid/import-credentials", { cloginrc, router_db: routerDb, dry_run: dryRun, set_platforms: setPlatforms, overwrite }),
    onSuccess: (r) => {
      setResult(r);
      if (!r.dry_run) {
        void qc.invalidateQueries({ queryKey: ["credentials"] });
        void qc.invalidateQueries({ queryKey: ["devices"] });
        toast.success("RANCID logins imported", `${r.credentials.length} credential(s), ${r.assigned} device assignment(s). Run a backup to check them.`);
      }
    },
    onError: (e) => toast.error("Import failed", errorMessage(e)),
  });
  const reset = (fn: (v: string) => void) => (v: string) => {
    fn(v);
    setResult(null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-4 w-4" /> 1 · Backup logins from RANCID
        </CardTitle>
        <CardDescription>
          Paste <code>~rancid/.cloginrc</code> and, optionally, the groups&apos; <code>router.db</code> files. Each device gets the login clogin would use (first matching
          line); devices sharing a login share one credential and the most common one becomes the default. Nothing changes until you click Import.
        </CardDescription>
      </CardHeader>
      <div className="grid gap-4 px-6 pb-6">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="cloginrc" className="text-sm font-medium">
                .cloginrc
              </label>
              <input ref={clogRef} type="file" className="hidden" onChange={readFile(reset(setCloginrc))} />
              <Button variant="ghost" size="xs" onClick={() => clogRef.current?.click()}>
                <FileUp /> Upload
              </Button>
            </div>
            <Textarea
              id="cloginrc"
              value={cloginrc}
              onChange={(e) => reset(setCloginrc)(e.target.value)}
              placeholder={"add user     *            rancid\nadd password *.example.net {vty-pass} {enable-pass}\nadd method   *            ssh"}
              className="min-h-[180px] font-mono text-xs"
              spellCheck={false}
            />
          </div>
          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="routerdb" className="text-sm font-medium">
                router.db <span className="font-normal text-muted-foreground">(optional - all groups concatenated)</span>
              </label>
              <input ref={dbRef} type="file" className="hidden" onChange={readFile(reset(setRouterDb))} />
              <Button variant="ghost" size="xs" onClick={() => dbRef.current?.click()}>
                <FileUp /> Upload
              </Button>
            </div>
            <Textarea
              id="routerdb"
              value={routerDb}
              onChange={(e) => reset(setRouterDb)(e.target.value)}
              placeholder={"blr-01-ixp01.example.net;juniper;up\nsw1-fra;arista;up"}
              className="min-h-[180px] font-mono text-xs"
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">
              <code>cat /var/lib/rancid/*/router.db</code> - limits the import to the routers RANCID backs up and sets missing platforms.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <Checkbox label="Set missing platforms from router.db" checked={setPlatforms} onCheckedChange={(c) => { setSetPlatforms(c); setResult(null); }} />
          <Checkbox label="Replace credentials already assigned to devices" checked={overwrite} onCheckedChange={(c) => { setOverwrite(c); setResult(null); }} />
          <div className="ml-auto flex gap-2">
            <Button variant={result?.dry_run ? "outline" : "default"} disabled={!cloginrc.trim()} loading={run.isPending && run.variables === true} onClick={() => run.mutate(true)}>
              Preview
            </Button>
            {result?.dry_run ? (
              <Button loading={run.isPending && run.variables === false} onClick={() => run.mutate(false)}>
                Import
              </Button>
            ) : null}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">The file contains passwords: it is sent only to this portal over HTTPS; passwords are stored encrypted and never shown again.</p>

        {result ? (
          <div className="grid gap-3" data-testid="rancid-import-result">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {result.dry_run ? <Badge variant="muted">Preview - nothing changed yet</Badge> : <Badge variant="success"><CheckCircle2 className="h-3.5 w-3.5" /> Imported</Badge>}
              <span className="text-ink-3">
                {result.credentials.length} credential(s) · {result.assigned} device assignment(s) · {result.platforms_set.length} platform(s) set
              </span>
            </div>
            <div className="overflow-hidden rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Credential</TableHead>
                    <TableHead>Username</TableHead>
                    <TableHead>Secrets</TableHead>
                    <TableHead>Devices</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.credentials.map((c) => (
                    <TableRow key={c.name}>
                      <TableCell>
                        <span className="font-medium">{c.name}</span>{" "}
                        {c.is_default ? <Badge variant="success">Default</Badge> : null} {c.existing ? <Badge variant="muted">Reused</Badge> : <Badge variant="info">New</Badge>}
                      </TableCell>
                      <TableCell className="font-mono text-sm">{c.username}</TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {c.has_password ? <Badge variant="muted">Password</Badge> : null}
                          {c.has_enable_secret ? <Badge variant="muted">Enable</Badge> : null}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[420px]">
                        <span className="font-medium">{c.devices.length}</span>{" "}
                        <span className="text-xs text-muted-foreground" title={c.devices.join(", ")}>
                          {c.devices.slice(0, 6).join(", ")}
                          {c.devices.length > 6 ? ` +${c.devices.length - 6} more` : ""}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <NameList title="No .cloginrc line matches - these devices get no login" items={result.no_login} tone="danger" />
              <NameList title="Log in with an SSH key - add the key to a credential yourself" items={result.ssh_keys} tone="warning" />
              <NameList title="Kept their existing credential" items={result.kept_existing} />
              <NameList title="In router.db but not in inventory (sync NetBox or add them)" items={result.router_db_not_in_inventory} tone="warning" />
              <NameList title="Marked down in router.db" items={result.router_db_down} />
              <NameList title="Platform set from router.db" items={result.platforms_set} />
            </div>
            {result.warnings.length ? (
              <div className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
                <p className="mb-1 flex items-center gap-1.5 text-sm font-medium text-warning">
                  <AlertTriangle className="h-4 w-4" /> {result.warnings.length} note(s)
                </p>
                <ul className="list-inside list-disc">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function CompareDialog({ row, onClose }: { row: CompareRow | null; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["rancid", "compare", row?.id],
    queryFn: () => api.get<DiffOut & { junos_converted?: boolean }>(`/rancid/compare/${row?.id}`),
    enabled: !!row,
  });
  return (
    <Dialog open={!!row} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-6xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            RANCID vs NOM · {row?.hostname ?? row?.rancid_name}
          </DialogTitle>
          <DialogDescription>
            Left: RANCID&apos;s last copy. Right: NOM&apos;s latest backup. Both normalised - RANCID&apos;s comment header, volatile lines and secrets are ignored
            {q.data?.junos_converted ? "; RANCID's hierarchical Junos config was converted to set format and both sides sorted" : ""}.
          </DialogDescription>
        </DialogHeader>
        {q.isLoading ? (
          <Skeleton className="h-[50vh]" />
        ) : q.data ? (
          <DiffViewer diff={q.data} showRisk={false} oldLabel="RANCID" newLabel="NOM backup" mode="split" maxHeight="64vh" />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function CompareStep() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const theme = useChartTheme();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [open, setOpen] = React.useState<CompareRow | null>(null);
  const [confirmClear, setConfirmClear] = React.useState(false);
  const rows = useQuery({ queryKey: ["rancid", "compare"], queryFn: () => api.get<CompareRow[]>("/rancid/compare") });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post<{ files: number; matched: number; unmatched: string[] }>("/rancid/configs", fd);
    },
    onSuccess: (r) => {
      toast.success(`${r.files} RANCID config(s) uploaded`, `${r.matched} matched to inventory devices${r.unmatched.length ? `, ${r.unmatched.length} not` : ""}.`);
      void qc.invalidateQueries({ queryKey: ["rancid"] });
    },
    onError: (e) => toast.error("Upload failed", errorMessage(e)),
  });
  const clear = useMutation({
    mutationFn: () => api.delete("/rancid/configs"),
    onSuccess: () => {
      setConfirmClear(false);
      void qc.invalidateQueries({ queryKey: ["rancid"] });
    },
  });
  const list = React.useMemo(() => rows.data ?? [], [rows.data]);
  const counts = React.useMemo(() => {
    const c = { identical: 0, differs: 0, no_portal_backup: 0, not_in_inventory: 0 };
    for (const r of list) c[r.status] += 1;
    return c;
  }, [list]);
  const donut = React.useMemo(
    () =>
      donutOption(
        {
          items: (Object.keys(counts) as CompareRow["status"][]).map((k) => ({ name: STATUS[k].label, value: counts[k], color: theme.status[STATUS[k].tone] })),
          centerValue: list.length ? `${Math.round((counts.identical / list.length) * 100)}%` : "—",
          centerLabel: "identical",
          legend: "right",
        },
        theme,
      ),
    [counts, list.length, theme],
  );

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <CardTitle className="flex items-center gap-2">
            <GitCompare className="h-4 w-4" /> 2 · Compare RANCID&apos;s configs with NOM&apos;s backups
          </CardTitle>
          <CardDescription>
            On the RANCID host run <code>tar czf rancid-configs.tgz -C /var/lib/rancid .</code> and upload the archive (only <code>&lt;group&gt;/configs/*</code> is read).
            Every device should read <em>Identical</em> or differ only by changes made since RANCID&apos;s last run before you retire RANCID.
          </CardDescription>
        </div>
        {can("configs:backup") ? (
          <div className="flex gap-2">
            {list.length ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirmClear(true)}>
                <Trash2 /> Clear
              </Button>
            ) : null}
            <input
              ref={fileRef}
              type="file"
              accept=".tgz,.tar.gz,.tar,.zip,application/gzip,application/zip,application/x-tar"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
            <Button size="sm" loading={upload.isPending} onClick={() => fileRef.current?.click()}>
              <Upload /> Upload RANCID configs
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <div className="grid gap-4 px-6 pb-6">
        {list.length ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr_1fr_1.4fr]">
            <KpiTile label="Identical" value={formatNumber(counts.identical)} tone="success" icon={CheckCircle2} />
            <KpiTile label="Differ" value={formatNumber(counts.differs)} tone={counts.differs ? "warning" : "default"} icon={GitCompare} delay={1} />
            <KpiTile label="No NOM backup" value={formatNumber(counts.no_portal_backup)} tone={counts.no_portal_backup ? "danger" : "default"} icon={AlertTriangle} delay={2} sub="check credential / reachability" />
            <KpiTile label="Not in inventory" value={formatNumber(counts.not_in_inventory)} icon={ArchiveRestore} delay={3} sub="sync NetBox or rename" />
            <ChartCard title="Migration readiness" delay={4}>
              <ChartBody height={130}>
                <Chart option={donut} height={130} ariaLabel="RANCID comparison status" />
              </ChartBody>
            </ChartCard>
          </div>
        ) : null}
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>RANCID router</TableHead>
                <TableHead>NOM device</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-[200px]">Similarity</TableHead>
                <TableHead className="text-right">Only in RANCID</TableHead>
                <TableHead className="text-right">Only in NOM</TableHead>
                <TableHead>NOM backup</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableState
                cols={8}
                isLoading={rows.isLoading}
                error={rows.error}
                onRetry={() => void rows.refetch()}
                isEmpty={list.length === 0}
                empty={<EmptyState icon={GitCompare} title="No RANCID configs uploaded" description="Upload an archive of RANCID's configs directory to compare it with NOM's backups." />}
              />
              {list.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <span className="font-mono text-xs">{r.rancid_name}</span>
                    {r.rancid_group ? <span className="ml-1.5 text-xs text-muted-foreground">{r.rancid_group}</span> : null}
                  </TableCell>
                  <TableCell>
                    {r.device_id ? (
                      <Link href={`/devices/${r.device_id}`} className="font-medium text-primary hover:underline">
                        {r.hostname}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS[r.status].variant}>{STATUS[r.status].label}</Badge>
                  </TableCell>
                  <TableCell>
                    {r.status === "identical" || r.status === "differs" ? (
                      <div className="flex items-center gap-2">
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                          <span className={cn("block h-full rounded-full", r.similarity >= 99.5 ? "bg-success" : r.similarity >= 90 ? "bg-warning" : "bg-danger")} style={{ width: `${r.similarity}%` }} />
                        </span>
                        <span className="w-12 text-right text-xs tabular">{r.similarity}%</span>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-diff-del-fg">{r.only_in_rancid ? `−${formatNumber(r.only_in_rancid)}` : "0"}</TableCell>
                  <TableCell className="text-right font-mono text-xs text-diff-add-fg">{r.only_in_portal ? `+${formatNumber(r.only_in_portal)}` : "0"}</TableCell>
                  <TableCell className="text-xs">
                    <RelativeTime value={r.portal_collected_at} />
                  </TableCell>
                  <TableCell className="text-right">
                    {r.device_id ? (
                      <Button variant="outline" size="xs" onClick={() => setOpen(r)}>
                        <GitCompare /> Compare
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
      <CompareDialog row={open} onClose={() => setOpen(null)} />
      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Remove the uploaded RANCID configs?"
        description="Only the uploaded copies used for this comparison are deleted; NOM's backups are not touched."
        confirmLabel="Remove"
        destructive
        loading={clear.isPending}
        onConfirm={() => clear.mutate()}
      />
    </Card>
  );
}

interface HistoryStatus {
  status: "none" | "queued" | "running" | "done" | "failed" | "stalled";
  filename: string | null;
  size_bytes: number | null;
  requested_by: string | null;
  requested_at: string | null;
  started_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
  error: string | null;
  progress: { phase: "revisions" | "commits"; router?: string; done: number; total: number; revisions: number } | null;
  stats: {
    routers: number;
    matched: number;
    revisions: number;
    commits: number;
    unmatched: string[];
    errors: string[];
    first: string | null;
    last: string | null;
  } | null;
}

const CVS_TAR = "tar czf /tmp/rancid-cvs.tgz -C /var/lib/rancid/CVS .";

function HistoryStep() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [confirmClear, setConfirmClear] = React.useState(false);
  const status = useQuery({
    queryKey: ["rancid", "history"],
    queryFn: () => api.get<HistoryStatus>("/rancid/history"),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 3000 : false),
  });
  const st = status.data;
  const busy = st?.status === "queued" || st?.status === "running";
  const prev = React.useRef(st?.status);
  React.useEffect(() => {
    if (prev.current && ["queued", "running"].includes(prev.current) && st && !busy) {
      if (st.status === "done") toast.success("RANCID history imported", `${formatNumber(st.stats?.commits ?? 0)} revisions added to device history.`);
      else if (st.status === "failed" || st.status === "stalled") toast.error("RANCID history import failed", st.error ?? undefined);
      void qc.invalidateQueries({ queryKey: ["device"] });
    }
    prev.current = st?.status;
  }, [st, busy, qc]);
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post<HistoryStatus>("/rancid/history", fd);
    },
    onSuccess: (r) => qc.setQueryData(["rancid", "history"], r),
    onError: (e) => toast.error("Upload failed", errorMessage(e)),
  });
  const clear = useMutation({
    mutationFn: () => api.delete("/rancid/history"),
    onSuccess: () => {
      setConfirmClear(false);
      void qc.invalidateQueries({ queryKey: ["rancid", "history"] });
      void qc.invalidateQueries({ queryKey: ["device"] });
    },
    onError: (e) => toast.error("Could not remove the history", errorMessage(e)),
  });
  const s = st?.stats;

  return (
    <Card data-testid="rancid-history-step">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4" /> 3 · Import RANCID&apos;s change history
          </CardTitle>
          <CardDescription>
            RANCID keeps every earlier version of each config in CVS. On the RANCID host run <code>{CVS_TAR}</code> and upload the archive: every revision is added to the
            device&apos;s <em>History &amp; diff</em> (marked <Badge variant="muted">RANCID</Badge>) before NOM&apos;s own backups, with its original date, author and log message.
            A new upload replaces the previous import.
          </CardDescription>
        </div>
        {can("configs:backup") ? (
          <div className="flex gap-2">
            {st?.status === "done" || st?.status === "failed" || st?.status === "stalled" ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirmClear(true)}>
                <Trash2 /> Remove
              </Button>
            ) : null}
            <input
              ref={fileRef}
              type="file"
              accept=".tgz,.tar.gz,.tar,.zip,application/gzip,application/zip,application/x-tar"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
            <Button size="sm" loading={upload.isPending || busy} disabled={busy} onClick={() => fileRef.current?.click()}>
              <Upload /> {busy ? "Importing…" : "Upload CVS archive"}
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <div className="grid gap-4 px-6 pb-6">
        {status.isLoading ? <Skeleton className="h-20" /> : null}
        {busy ? (
          <div className="flex items-center gap-2 rounded-md border bg-accent/30 px-4 py-3 text-sm" role="status">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
            <div className="grid min-w-0 flex-1 gap-1.5">
              <span>
                {st?.status === "queued"
                  ? "Waiting for a worker…"
                  : st?.progress?.phase === "commits"
                    ? `Writing ${formatNumber(st.progress.revisions)} revisions to history…`
                    : st?.progress
                      ? `Rebuilding revisions: router ${formatNumber(st.progress.done + 1)} of ${formatNumber(st.progress.total)}${st.progress.router ? ` (${st.progress.router})` : ""} · ${formatNumber(st.progress.revisions)} revisions so far`
                      : "Reading the archive…"}{" "}
                {st?.filename ? <span className="text-muted-foreground">({st.filename})</span> : null}
              </span>
              {st?.progress?.total ? (
                <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.round((Math.min(st.progress.done, st.progress.total) / st.progress.total) * 100)}%` }} />
                </div>
              ) : null}
              {st?.started_at ? (
                <span className="text-xs text-muted-foreground">
                  Started <RelativeTime value={st.started_at} />
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
        {st?.status === "failed" || st?.status === "stalled" ? (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            <AlertTriangle className="mr-1 inline h-4 w-4" /> {st.status === "stalled" ? "Import stalled" : "Import failed"}: {st.error} - upload the archive again to retry.
          </div>
        ) : null}
        {st?.status === "done" && s ? (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <KpiTile label="Devices with history" value={formatNumber(s.matched)} icon={CheckCircle2} tone="success" sub={`of ${formatNumber(s.routers)} RANCID routers`} />
              <KpiTile label="Revisions added" value={formatNumber(s.commits)} icon={History} delay={1} sub={`${formatNumber(s.revisions)} in CVS; unchanged ones merged`} />
              <KpiTile label="Oldest" value={s.first ? new Date(s.first).toLocaleDateString() : "—"} icon={ArchiveRestore} delay={2} />
              <KpiTile label="Newest" value={s.last ? new Date(s.last).toLocaleDateString() : "—"} icon={GitCompare} delay={3} />
            </div>
            <p className="text-xs text-muted-foreground">
              Imported {st.finished_at ? <RelativeTime value={st.finished_at} /> : null}
              {st.requested_by ? ` by ${st.requested_by}` : ""}. Open any device&apos;s History &amp; diff or Change history tab to browse it.
            </p>
            {s.unmatched.length ? <NameList title="Not in inventory (history not imported)" items={s.unmatched} tone="warning" /> : null}
            {s.errors.length ? <NameList title="Unreadable RCS files" items={s.errors} tone="danger" /> : null}
          </>
        ) : null}
      </div>
      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Remove the imported RANCID history?"
        description="Device history then shows NOM's own backups only. The CVS archive can be imported again at any time."
        confirmLabel="Remove"
        destructive
        loading={clear.isPending}
        onConfirm={() => clear.mutate()}
      />
    </Card>
  );
}

export default function RancidPage() {
  const { can } = useAuth();
  return (
    <>
      <PageHeader
        title="RANCID migration"
        description="Move backups from RANCID to NetworkOps Manager: reuse RANCID's logins, then confirm NOM collects the same configurations before retiring RANCID."
      />
      <div className="grid gap-4">
        {can("credentials:write") ? <CredentialsStep /> : null}
        <CompareStep />
        <HistoryStep />
      </div>
    </>
  );
}
