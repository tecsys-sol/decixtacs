"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";

export interface PlatformBackupSettings {
  slug: string;
  name: string;
  default_commands: string[];
  commands: string[] | null;
  timeout: number | null;
  concurrency: number | null;
  device_count: number;
}

export interface BackupSettings {
  default_timeout: number;
  max_concurrency: number;
  platforms: PlatformBackupSettings[];
}

interface Draft {
  timeout: string;
  concurrency: string;
  commands: string;
}

const toDraft = (p: PlatformBackupSettings): Draft => ({
  timeout: p.timeout ? String(p.timeout) : "",
  concurrency: p.concurrency ? String(p.concurrency) : "",
  commands: (p.commands ?? []).join("\n"),
});

function PlatformRow({ p, settings, writable }: { p: PlatformBackupSettings; settings: BackupSettings; writable: boolean }) {
  const qc = useQueryClient();
  const [d, setD] = React.useState<Draft>(() => toDraft(p));
  const [showCmds, setShowCmds] = React.useState(!!p.commands);
  const saved = toDraft(p);
  const dirty = d.timeout !== saved.timeout || d.concurrency !== saved.concurrency || d.commands.trim() !== saved.commands;
  const save = useMutation({
    mutationFn: (body: { timeout: number | null; concurrency: number | null; commands: string[] | null }) =>
      api.put<BackupSettings>(`/backup-settings/${p.slug}`, body),
    onSuccess: (s) => {
      qc.setQueryData(["backup-settings"], s);
      const np = s.platforms.find((x) => x.slug === p.slug);
      if (np) setD(toDraft(np));
      toast.success(`${p.name} backup settings saved`, "Used from the next backup run.");
    },
    onError: (e) => toast.error("Could not save", errorMessage(e)),
  });
  const submit = (reset = false) =>
    save.mutate(
      reset
        ? { timeout: null, concurrency: null, commands: null }
        : {
            timeout: d.timeout ? Number(d.timeout) : null,
            concurrency: d.concurrency ? Number(d.concurrency) : null,
            commands: d.commands.trim() ? d.commands.split("\n").map((c) => c.trim()).filter(Boolean) : null,
          },
    );
  const tuned = !!(p.timeout || p.concurrency || p.commands);

  return (
    <>
      <TableRow>
        <TableCell>
          <div className="font-medium">{p.name}</div>
          <div className="text-xs text-muted-foreground">
            {p.device_count} device{p.device_count === 1 ? "" : "s"} {tuned ? <Badge variant="info" className="ml-1">Tuned</Badge> : null}
          </div>
        </TableCell>
        <TableCell>
          <Input
            aria-label={`${p.name} timeout seconds`}
            type="number"
            min={5}
            max={900}
            placeholder={`default ${settings.default_timeout}`}
            value={d.timeout}
            onChange={(e) => setD({ ...d, timeout: e.target.value })}
            disabled={!writable}
            className="w-28"
          />
        </TableCell>
        <TableCell>
          <Input
            aria-label={`${p.name} parallel sessions`}
            type="number"
            min={1}
            max={settings.max_concurrency}
            placeholder={`max ${settings.max_concurrency}`}
            value={d.concurrency}
            onChange={(e) => setD({ ...d, concurrency: e.target.value })}
            disabled={!writable}
            className="w-28"
          />
        </TableCell>
        <TableCell className="max-w-[280px]">
          <button type="button" className="text-left text-xs text-primary hover:underline" onClick={() => setShowCmds((v) => !v)}>
            {p.commands ? "Custom commands" : "Default"} ({(p.commands ?? p.default_commands).length})
          </button>
          <p className="truncate font-mono text-[11px] text-muted-foreground" title={(p.commands ?? p.default_commands).join("\n")}>
            {(p.commands ?? p.default_commands)[0] ?? "(API collection)"}
          </p>
        </TableCell>
        <TableCell className="whitespace-nowrap text-right">
          {writable ? (
            <div className="flex justify-end gap-1">
              {tuned ? (
                <Button variant="ghost" size="icon-sm" aria-label={`Reset ${p.name} to defaults`} title="Reset to defaults" onClick={() => submit(true)}>
                  <RotateCcw />
                </Button>
              ) : null}
              <Button size="xs" disabled={!dirty} loading={save.isPending} onClick={() => submit()}>
                Save
              </Button>
            </div>
          ) : null}
        </TableCell>
      </TableRow>
      {showCmds ? (
        <TableRow className="bg-muted/30 hover:bg-muted/30">
          <TableCell colSpan={5}>
            <label htmlFor={`cmds-${p.slug}`} className="text-xs font-medium">
              Collection commands for {p.name}, one per line - empty uses the default:
            </label>
            <Textarea
              id={`cmds-${p.slug}`}
              value={d.commands}
              onChange={(e) => setD({ ...d, commands: e.target.value })}
              placeholder={p.default_commands.join("\n")}
              className="mt-1 min-h-[70px] font-mono text-xs"
              disabled={!writable}
              spellCheck={false}
            />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

/** Per-platform collection tuning: timeout, parallel SSH sessions and the commands that are run. */
export function BackupSettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["backup-settings"], queryFn: () => api.get<BackupSettings>("/backup-settings"), enabled: open });
  const platforms = (q.data?.platforms ?? []).slice().sort((a, b) => b.device_count - a.device_count || a.name.localeCompare(b.name));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Backup settings per platform</DialogTitle>
          <DialogDescription>
            Raise the timeout for devices with large configurations (e.g. big MX routers) and lower parallel sessions for platforms with a small SSH session
            limit. Empty fields use the defaults ({q.data?.default_timeout ?? 60}s, up to {q.data?.max_concurrency ?? "…"} sessions).
          </DialogDescription>
        </DialogHeader>
        {q.isLoading ? (
          <Skeleton className="h-64" />
        ) : q.data ? (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Platform</TableHead>
                  <TableHead>Timeout (s)</TableHead>
                  <TableHead>Parallel sessions</TableHead>
                  <TableHead>Commands</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {platforms.map((p) => (
                  <PlatformRow key={`${p.slug}-${p.timeout}-${p.concurrency}-${(p.commands ?? []).join("|")}`} p={p} settings={q.data} writable={can("configs:backup")} />
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
