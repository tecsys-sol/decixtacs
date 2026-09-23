"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Plus, Rocket, Server, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { RelativeTime } from "@/components/common/relative-time";
import { SecretDialog } from "@/components/common/secret-dialog";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useNow } from "@/hooks/use-now";
import { useLastDefined, useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { Revision, TacacsServer, TacacsServerCreated, TacacsServerIn } from "@/lib/types";
import { formatDateTime, parseDate, shortSha } from "@/lib/utils";

const HEARTBEAT_STALE_MS = 5 * 60_000;

function HeartbeatBadge({ at }: { at: string | null }) {
  const now = useNow();
  const d = parseDate(at);
  if (!d) return <Badge variant="muted" dot>Never</Badge>;
  const stale = now - d.getTime() > HEARTBEAT_STALE_MS;
  return (
    <Badge variant={stale ? "warning" : "success"} dot title={formatDateTime(d)}>
      <RelativeTime value={at} />
    </Badge>
  );
}

function CreateServerDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (s: TacacsServerCreated) => void }) {
  const qc = useQueryClient();
  const [f, setF] = React.useState<Required<TacacsServerIn>>({ name: "", address: "", port: 49, enabled: true, ldap_backend: false });
  useOnOpen(open, () => {
    setF({ name: "", address: "", port: 49, enabled: true, ldap_backend: false });
  });
  const create = useMutation({
    mutationFn: () => api.post<TacacsServerCreated>("/tacacs/servers", { ...f, name: f.name.trim(), address: f.address.trim(), port: Number(f.port) }),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["tacacs", "servers"] });
      onOpenChange(false);
      onCreated(s);
    },
    onError: (e) => toast.error("Could not create server", errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add TACACS+ server</DialogTitle>
          <DialogDescription>The tac_plus-ng agent on this host pulls its configuration with a one-time-displayed token.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Name" htmlFor="sname" required>
            <Input id="sname" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="tacacs-fra1" required />
          </Field>
          <div className="grid grid-cols-[1fr_100px] gap-3">
            <Field label="Address" htmlFor="saddr" required>
              <Input id="saddr" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className="font-mono" placeholder="10.0.0.5" required />
            </Field>
            <Field label="Port" htmlFor="sport">
              <Input id="sport" type="number" min={1} max={65535} value={f.port} onChange={(e) => setF({ ...f, port: Number(e.target.value) })} />
            </Field>
          </div>
          <Checkbox label="Use LDAP backend for authentication" checked={f.ldap_backend} onCheckedChange={(c) => setF({ ...f, ldap_backend: c })} />
          <Checkbox label="Enabled" checked={f.enabled} onCheckedChange={(c) => setF({ ...f, enabled: c })} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!f.name.trim() || !f.address.trim()}>
              Create server
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RevisionsDialog({ server: current, onClose }: { server: TacacsServer | null; onClose: () => void }) {
  const server = useLastDefined(current);
  const q = useQuery({
    queryKey: ["tacacs", "revisions", server?.id],
    queryFn: () => api.get<Revision[]>(`/tacacs/servers/${server?.id}/revisions`),
    enabled: !!server,
  });
  return (
    <Dialog open={!!current} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Revisions · {server?.name}</DialogTitle>
          <DialogDescription>Deployed configuration versions (newest first).</DialogDescription>
        </DialogHeader>
        {q.isLoading ? (
          <Skeleton className="h-40" />
        ) : q.data?.length ? (
          <ul className="max-h-80 divide-y overflow-y-auto rounded-md border text-sm">
            {q.data.map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-3 py-2">
                <Badge variant={r.version === server?.config_version ? "success" : "secondary"}>v{r.version}</Badge>
                <code className="flex-1 truncate font-mono text-xs" title={r.sha256}>
                  {shortSha(r.sha256, 16)}
                </code>
                <span className="text-xs text-muted-foreground">{formatDateTime(r.created_at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">Never deployed.</p>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ServersTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tacacs", "servers"], queryFn: () => api.get<TacacsServer[]>("/tacacs/servers"), refetchInterval: 60_000 });
  const [createOpen, setCreateOpen] = React.useState(false);
  const [token, setToken] = React.useState<string | null>(null);
  const [revisionsFor, setRevisionsFor] = React.useState<TacacsServer | null>(null);
  const confirmDeploy = useConfirm<TacacsServer>();
  const confirmDelete = useConfirm<TacacsServer>();

  const deploy = useMutation({
    mutationFn: (s: TacacsServer) => api.post<Revision>(`/tacacs/servers/${s.id}/deploy`),
    onSuccess: (r, s) => {
      toast.success(`Deployed v${r.version} to ${s.name}`, "The agent picks up the new configuration on its next poll.");
      confirmDeploy.close();
      void qc.invalidateQueries({ queryKey: ["tacacs"] });
    },
    onError: (e) => toast.error("Deploy failed", errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: (s: TacacsServer) => api.delete(`/tacacs/servers/${s.id}`),
    onSuccess: () => {
      toast.success("Server removed");
      confirmDelete.close();
      void qc.invalidateQueries({ queryKey: ["tacacs", "servers"] });
    },
  });

  const list = q.data ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>TACACS+ servers</CardTitle>
          <CardDescription>tac_plus-ng instances managed by this tenant</CardDescription>
        </div>
        {can("tacacs:write") ? (
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus /> Add server
          </Button>
        ) : null}
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Address</TableHead>
            <TableHead>Config</TableHead>
            <TableHead>Last deployed</TableHead>
            <TableHead>Agent heartbeat</TableHead>
            <TableHead>Flags</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={Server} title="No TACACS+ servers" description="Add a server and install the agent with the token shown once." />} />
          {list.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="font-medium">{s.name}</TableCell>
              <TableCell className="font-mono text-xs">
                {s.address}:{s.port}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">v{s.config_version}</Badge>
                  <code className="font-mono text-[11px] text-muted-foreground" title={s.config_sha256 ?? undefined}>
                    {shortSha(s.config_sha256, 10)}
                  </code>
                </div>
              </TableCell>
              <TableCell className="text-xs">
                <RelativeTime value={s.last_deployed_at} />
              </TableCell>
              <TableCell>
                <HeartbeatBadge at={s.last_heartbeat_at} />
              </TableCell>
              <TableCell>
                <div className="flex gap-1">
                  {s.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}
                  {s.ldap_backend ? <Badge variant="info">LDAP</Badge> : null}
                </div>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <div className="flex justify-end gap-1">
                  <Button variant="ghost" size="xs" onClick={() => setRevisionsFor(s)}>
                    <History /> Revisions
                  </Button>
                  {can("tacacs:deploy") ? (
                    <Button variant="outline" size="xs" onClick={() => confirmDeploy.ask(s)}>
                      <Rocket /> Deploy
                    </Button>
                  ) : null}
                  {can("tacacs:write") ? (
                    <Button variant="ghost" size="icon-sm" aria-label={`Delete ${s.name}`} onClick={() => confirmDelete.ask(s)}>
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <CreateServerDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={(s) => setToken(s.agent_token)} />
      <SecretDialog
        secret={token}
        title="Agent token"
        description="Configure this token on the tac_plus-ng agent (Authorization: Bearer). It is used to pull configuration, send heartbeats and ship accounting logs."
        onClose={() => setToken(null)}
      />
      <RevisionsDialog server={revisionsFor} onClose={() => setRevisionsFor(null)} />
      <ConfirmDialog
        open={confirmDeploy.open}
        onOpenChange={confirmDeploy.onOpenChange}
        title={`Deploy configuration to ${confirmDeploy.target?.name ?? ""}?`}
        description="Renders the current policies, NAS devices and users into a new tac_plus-ng configuration revision. Review the Config preview tab first."
        confirmLabel="Deploy"
        loading={deploy.isPending}
        onConfirm={() => confirmDeploy.target && deploy.mutate(confirmDeploy.target)}
      />
      <ConfirmDialog
        open={confirmDelete.open}
        onOpenChange={confirmDelete.onOpenChange}
        title={`Delete ${confirmDelete.target?.name ?? ""}?`}
        description="The agent token is invalidated immediately."
        destructive
        confirmLabel="Delete"
        loading={del.isPending}
        onConfirm={() => confirmDelete.target && del.mutate(confirmDelete.target)}
      />
    </Card>
  );
}
