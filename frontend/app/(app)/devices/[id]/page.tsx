"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  Cable,
  ClipboardCheck,
  DatabaseBackup,
  FileText,
  GitCompare,
  History,
  LayoutGrid,
  MoreHorizontal,
  Pencil,
  RotateCcw,
  Terminal,
  Trash2,
} from "lucide-react";
import * as React from "react";

import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { CommandsTab } from "@/components/devices/commands-tab";
import { ComplianceTab } from "@/components/devices/compliance-tab";
import { ConfigTab } from "@/components/devices/config-tab";
import { DeviceFormDialog } from "@/components/devices/device-form-dialog";
import { DiffTab } from "@/components/devices/diff-tab";
import { HistoryTab } from "@/components/devices/history-tab";
import { ActivityTab } from "@/components/devices/activity-tab";
import { PortsTab } from "@/components/devices/ports-tab";
import { OverviewTab } from "@/components/devices/overview-tab";
import { RestoreTab } from "@/components/devices/restore-tab";
import { DeviceChassis } from "@/components/illustrations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import type { BackupRunResult, Device } from "@/lib/types";
import { cn, humanize } from "@/lib/utils";

function ReachabilityPill({ value }: { value: string }) {
  const up = value === "reachable" || value === "up";
  const down = value === "unreachable" || value === "down";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-sans text-xs font-bold",
        up ? "bg-success-soft text-success" : down ? "bg-danger-soft text-danger" : "bg-secondary text-ink-3",
      )}
    >
      <span className={cn("h-[7px] w-[7px] rounded-full", up ? "live bg-[var(--ill-green)]" : down ? "bg-danger" : "bg-muted-foreground")} aria-hidden />
      {humanize(value)}
    </span>
  );
}

const TABS = ["overview", "activity", "ports", "config", "history", "diff", "compliance", "commands", "restore"] as const;

export default function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [state, setState] = useUrlState({ tab: "overview", rev: "HEAD", old: "", new: "" });
  const [editOpen, setEditOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);

  const device = useQuery({ queryKey: ["device", id], queryFn: () => api.get<Device>(`/devices/${id}`) });

  const backup = useMutation({
    mutationFn: () => api.post<BackupRunResult>("/backups/run", { device_ids: [id], reason: "manual (UI)", run_async: true }),
    onSuccess: () => {
      toast.success("Backup queued", "The new revision will appear in History once collected.");
      void qc.invalidateQueries({ queryKey: ["backups"] });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.delete(`/devices/${id}`),
    onSuccess: () => {
      toast.success("Device deleted");
      void qc.invalidateQueries({ queryKey: ["devices"] });
      router.replace("/devices");
    },
  });

  if (device.isLoading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }
  if (device.error || !device.data) return <ErrorState error={device.error} onRetry={() => void device.refetch()} />;
  const d = device.data;
  const tab = (TABS as readonly string[]).includes(state.tab) ? state.tab : "overview";
  const ports: ("up" | "down" | "idle")[] = [
    d.reachability === "reachable" ? "up" : d.reachability === "unreachable" ? "down" : "idle",
    d.last_backup_status === "failed" ? "down" : d.last_backup_status ? "up" : "idle",
    d.backup_enabled ? "up" : "idle",
    "idle",
    d.status === "active" ? "up" : "idle",
    d.credential_id ? "up" : "idle",
    d.platform ? "up" : "idle",
    "idle",
  ];

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Dashboard", href: "/dashboard" }, { label: "Devices", href: "/devices" }, { label: d.hostname }]}
        title={
          <span className="flex flex-wrap items-center gap-3">
            <span className="min-w-0 break-all">{d.hostname}</span>
            <ReachabilityPill value={d.reachability} />
            {d.groups?.slice(0, 2).map((g) => (
              <Badge key={g.id} variant="secondary" className="text-xs">
                {g.name}
              </Badge>
            ))}
          </span>
        }
        illustration={<DeviceChassis className="hidden h-[84px] w-[132px] shrink-0 md:block" ports={ports} />}
        actions={
          <>
            {can("configs:backup") ? (
              <Button variant="outline" onClick={() => backup.mutate()} loading={backup.isPending}>
                <DatabaseBackup /> Run backup
              </Button>
            ) : null}
            {can("configs:restore") ? (
              <Button onClick={() => setState({ tab: "restore" })}>
                <RotateCcw /> Restore a version
              </Button>
            ) : null}
            {can("devices:write") ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" aria-label="More actions">
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setEditOpen(true)}>
                    <Pencil /> Edit device
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem destructive onSelect={() => setDeleteOpen(true)}>
                    <Trash2 /> Delete device
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </>
        }
      >
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-3">
          <span>{[d.vendor?.name, d.platform?.name, d.os_version].filter(Boolean).join(" · ") || "No platform"}</span>
          <span className="font-mono">{d.management_ip}</span>
          <span>{d.site?.name ?? "No site"}</span>
          {d.serial ? <span>Serial <span className="font-mono">{d.serial}</span></span> : null}
        </div>
      </PageHeader>

      <Tabs value={tab} onValueChange={(v) => setState({ tab: v })}>
        <TabsList>
          <TabsTrigger value="overview"><LayoutGrid /> Overview</TabsTrigger>
          <TabsTrigger value="activity"><Activity /> Activity</TabsTrigger>
          <TabsTrigger value="ports"><Cable /> Ports &amp; connections</TabsTrigger>
          <TabsTrigger value="config"><FileText /> Configuration</TabsTrigger>
          <TabsTrigger value="history"><History /> Commits</TabsTrigger>
          <TabsTrigger value="diff"><GitCompare /> History &amp; diff</TabsTrigger>
          {can("compliance:read") ? <TabsTrigger value="compliance"><ClipboardCheck /> Compliance</TabsTrigger> : null}
          {can("accounting:read") ? <TabsTrigger value="commands"><Terminal /> Commands</TabsTrigger> : null}
          {can("configs:restore") ? <TabsTrigger value="restore"><RotateCcw /> Restore</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab device={d} />
        </TabsContent>
        <TabsContent value="activity">
          <ActivityTab device={d} />
        </TabsContent>
        <TabsContent value="ports">
          <PortsTab device={d} />
        </TabsContent>
        <TabsContent value="config">
          <ConfigTab device={d} rev={state.rev} onRevChange={(rev) => setState({ rev })} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryTab
            device={d}
            onDiff={(o, n) => setState({ tab: "diff", old: o, new: n })}
            onView={(rev) => setState({ tab: "config", rev })}
          />
        </TabsContent>
        <TabsContent value="diff">
          <DiffTab device={d} oldRev={state.old} newRev={state.new} onChange={(o, n) => setState({ old: o, new: n })} />
        </TabsContent>
        <TabsContent value="compliance">
          <ComplianceTab device={d} />
        </TabsContent>
        <TabsContent value="commands">
          <CommandsTab device={d} />
        </TabsContent>
        <TabsContent value="restore">
          <RestoreTab device={d} />
        </TabsContent>
      </Tabs>

      <DeviceFormDialog open={editOpen} onOpenChange={setEditOpen} device={d} />
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Delete ${d.hostname}?`}
        description="The device is removed from inventory. Its Git configuration history is retained for forensic purposes."
        confirmLabel="Delete device"
        destructive
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}
