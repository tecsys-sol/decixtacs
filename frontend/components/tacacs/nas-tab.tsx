"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, KeyRound, Plus, Router, Trash2 } from "lucide-react";
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
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useDeviceGroups, useDeviceNames } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import { TACACS_VENDORS, type Nas, type NasIn } from "@/lib/types";
import { humanize } from "@/lib/utils";

function NasDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (keyGenerated: boolean) => void }) {
  const qc = useQueryClient();
  const devices = useDeviceNames();
  const groups = useDeviceGroups();
  const blank: NasIn = { name: "", address: "", vendor: "juniper", key: "", device_id: null, device_group_id: null, enabled: true };
  const [f, setF] = React.useState<NasIn>(blank);
  useOnOpen(open, () => {
    setF(blank);
  });
  const create = useMutation({
    mutationFn: () => api.post<Nas>("/tacacs/devices", { ...f, name: f.name.trim(), address: f.address.trim(), key: f.key?.trim() || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tacacs", "nas"] });
      onOpenChange(false);
      onCreated(!f.key?.trim());
    },
    onError: (e) => toast.error("Could not add NAS", errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add NAS device</DialogTitle>
          <DialogDescription>A network device (or prefix) allowed to query the TACACS+ servers.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="nname" required>
              <Input id="nname" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
            </Field>
            <Field label="Address / prefix" htmlFor="naddr" required>
              <Input id="naddr" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className="font-mono" placeholder="192.0.2.0/24" required />
            </Field>
            <Field label="Vendor" htmlFor="nvendor">
              <SimpleSelect id="nvendor" value={f.vendor} onValueChange={(v) => setF({ ...f, vendor: v })} options={TACACS_VENDORS.map((v) => ({ value: v, label: humanize(v) }))} />
            </Field>
            <Field label="Shared key" htmlFor="nkey" hint="Leave empty to generate a random key">
              <Input id="nkey" type="password" autoComplete="new-password" value={f.key ?? ""} onChange={(e) => setF({ ...f, key: e.target.value })} />
            </Field>
            <Field label="Inventory device" htmlFor="ndev">
              <SimpleSelect id="ndev" value={f.device_id ?? ""} onValueChange={(v) => setF({ ...f, device_id: v || null })} allowEmpty emptyLabel="None" options={(devices.data ?? []).map((d) => ({ value: d.id, label: d.hostname }))} />
            </Field>
            <Field label="Device group" htmlFor="ngrp">
              <SimpleSelect id="ngrp" value={f.device_group_id ?? ""} onValueChange={(v) => setF({ ...f, device_group_id: v || null })} allowEmpty emptyLabel="None" options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))} />
            </Field>
          </div>
          <Checkbox label="Enabled" checked={f.enabled ?? true} onCheckedChange={(c) => setF({ ...f, enabled: c })} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!f.name.trim() || !f.address.trim()}>
              Add NAS
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function NasTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const groups = useDeviceGroups();
  const devices = useDeviceNames();
  const q = useQuery({ queryKey: ["tacacs", "nas"], queryFn: () => api.get<Nas[]>("/tacacs/devices") });
  const [createOpen, setCreateOpen] = React.useState(false);
  const [importOpen, setImportOpen] = React.useState(false);
  const [importGroup, setImportGroup] = React.useState("");
  const [key, setKey] = React.useState<{ name: string; key: string } | null>(null);
  const confirmRotate = useConfirm<Nas>();
  const confirmDelete = useConfirm<Nas>();
  const writable = can("tacacs:write");

  const importInv = useMutation({
    mutationFn: () => api.post<Nas[]>(`/tacacs/devices/import-inventory${importGroup ? `?device_group_id=${encodeURIComponent(importGroup)}` : ""}`),
    onSuccess: (created) => {
      toast.success(`Imported ${created.length} device(s)`, created.length ? "Rotate keys to reveal and configure them on the devices." : "Every inventory device already has a NAS entry.");
      setImportOpen(false);
      void qc.invalidateQueries({ queryKey: ["tacacs", "nas"] });
    },
    onError: (e) => toast.error("Import failed", errorMessage(e)),
  });
  const rotate = useMutation({
    mutationFn: (n: Nas) => api.post<{ key: string }>(`/tacacs/devices/${n.id}/rotate-key`),
    onSuccess: (r, n) => {
      confirmRotate.close();
      setKey({ name: n.name, key: r.key });
      void qc.invalidateQueries({ queryKey: ["tacacs", "nas"] });
    },
    onError: (e) => toast.error("Key rotation failed", errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: (n: Nas) => api.delete(`/tacacs/devices/${n.id}`),
    onSuccess: () => {
      toast.success("NAS removed");
      confirmDelete.close();
      void qc.invalidateQueries({ queryKey: ["tacacs", "nas"] });
    },
  });

  const list = q.data ?? [];
  const groupName = new Map((groups.data ?? []).map((g) => [g.id, g.name]));

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>NAS devices</CardTitle>
          <CardDescription>Clients permitted to use TACACS+, each with its own shared secret</CardDescription>
        </div>
        {writable ? (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setImportOpen(true)}>
              <Download /> Import from inventory
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus /> Add NAS
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Address</TableHead>
            <TableHead>Vendor</TableHead>
            <TableHead>Linked to</TableHead>
            <TableHead>Key rotated</TableHead>
            <TableHead>State</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={Router} title="No NAS devices" description="Import devices from inventory to create NAS entries with random keys." />} />
          {list.map((n) => (
            <TableRow key={n.id}>
              <TableCell className="font-medium">{n.name}</TableCell>
              <TableCell className="font-mono text-xs">{n.address}</TableCell>
              <TableCell>
                <Badge variant="outline">{n.vendor}</Badge>
              </TableCell>
              <TableCell className="text-xs">
                {n.device_id ? devices.map.get(n.device_id) ?? "device" : n.device_group_id ? `group: ${groupName.get(n.device_group_id) ?? "…"}` : "—"}
              </TableCell>
              <TableCell className="text-xs">
                <RelativeTime value={n.key_rotated_at} />
              </TableCell>
              <TableCell>{n.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}</TableCell>
              <TableCell className="whitespace-nowrap">
                {writable ? (
                  <div className="flex justify-end gap-1">
                    <Button variant="outline" size="xs" onClick={() => confirmRotate.ask(n)}>
                      <KeyRound /> Rotate key
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label={`Delete ${n.name}`} onClick={() => confirmDelete.ask(n)}>
                      <Trash2 />
                    </Button>
                  </div>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <NasDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(keyGenerated) => {
          toast.success("NAS added", keyGenerated ? "A random key was generated - rotate it to reveal a key you can configure." : undefined);
        }}
      />
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Import from inventory</DialogTitle>
            <DialogDescription>Creates a NAS entry with a random key for every inventory device that has none yet.</DialogDescription>
          </DialogHeader>
          <Field label="Device group" htmlFor="igrp" hint="Optional - limit the import to one group">
            <SimpleSelect id="igrp" value={importGroup} onValueChange={setImportGroup} allowEmpty emptyLabel="All devices" options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))} />
          </Field>
          <DialogFooter>
            <Button variant="outline" onClick={() => setImportOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => importInv.mutate()} loading={importInv.isPending}>
              Import
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmRotate.open}
        onOpenChange={confirmRotate.onOpenChange}
        title={`Rotate key for ${confirmRotate.target?.name ?? ""}?`}
        description="The old key stops working after the next deploy. Configure the new key on the device before deploying."
        confirmLabel="Rotate key"
        loading={rotate.isPending}
        onConfirm={() => confirmRotate.target && rotate.mutate(confirmRotate.target)}
      />
      <ConfirmDialog
        open={confirmDelete.open}
        onOpenChange={confirmDelete.onOpenChange}
        title={`Delete ${confirmDelete.target?.name ?? ""}?`}
        destructive
        confirmLabel="Delete"
        loading={del.isPending}
        onConfirm={() => confirmDelete.target && del.mutate(confirmDelete.target)}
      />
      <SecretDialog
        secret={key?.key ?? null}
        title={`New shared key · ${key?.name ?? ""}`}
        description="Configure this TACACS+ key on the device, then deploy the TACACS+ configuration."
        onClose={() => setKey(null)}
      />
    </Card>
  );
}
