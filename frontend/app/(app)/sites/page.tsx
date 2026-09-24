"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { TableState } from "@/components/common/table-skeleton";
import { SiteFormDialog } from "@/components/devices/site-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import type { Site } from "@/lib/types";
import { humanize } from "@/lib/utils";

interface Rack {
  id: string;
  name: string;
  site_id: string;
  u_height: number;
}

/** Sites and their racks (synced from NetBox or created here), with device counts. */
export default function SitesPage() {
  const { can } = useAuth();
  const [q, setQ] = React.useState("");
  const [open, setOpen] = React.useState<Record<string, boolean>>({});
  const [createOpen, setCreateOpen] = React.useState(false);
  const sites = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.get<Site[]>("/sites"),
  });
  const racks = useQuery({
    queryKey: ["racks"],
    queryFn: () => api.get<Rack[]>("/racks"),
  });

  const racksBySite = React.useMemo(() => {
    const m = new Map<string, Rack[]>();
    for (const r of racks.data ?? [])
      m.set(r.site_id, [...(m.get(r.site_id) ?? []), r]);
    return m;
  }, [racks.data]);
  const needle = q.trim().toLowerCase();
  const list = (sites.data ?? []).filter(
    (s) =>
      !needle ||
      s.name.toLowerCase().includes(needle) ||
      s.slug.toLowerCase().includes(needle),
  );
  const totalDevices = (sites.data ?? []).reduce(
    (n, s) => n + (s.device_count ?? 0),
    0,
  );
  const maxDevices = Math.max(1, ...list.map((s) => s.device_count ?? 0));

  return (
    <>
      <PageHeader
        title="Sites & racks"
        description={
          sites.data
            ? `${sites.data.length} sites · ${racks.data?.length ?? 0} racks · ${totalDevices} devices. NetBox-synced sites refresh on every sync.`
            : "Points of presence, data centres and their racks."
        }
        actions={
          can("devices:write") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> Add site
            </Button>
          ) : null
        }
      />
      <Card className="overflow-hidden">
        <div className="border-b p-3">
          <Input
            aria-label="Filter sites"
            placeholder="Filter by name or slug…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="max-w-sm"
          />
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Site</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Racks</TableHead>
              <TableHead className="w-[30%]">Devices</TableHead>
              <TableHead>Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState
              isLoading={sites.isLoading}
              error={sites.error}
              isEmpty={list.length === 0}
              cols={6}
              onRetry={() => void sites.refetch()}
              empty={
                <EmptyState
                  art="network"
                  icon={Building2}
                  title={needle ? "No matching sites" : "No sites yet"}
                  description={
                    needle ? (
                      "Try another name."
                    ) : (
                      <>
                        Sync NetBox under{" "}
                        <Link
                          href="/integrations"
                          className="font-medium text-primary"
                        >
                          Integrations
                        </Link>
                        , or add a site here.
                      </>
                    )
                  }
                />
              }
            />
            {list.map((s) => {
              const siteRacks = racksBySite.get(s.id) ?? [];
              const expanded = !!open[s.id];
              const count = s.device_count ?? 0;
              return (
                <React.Fragment key={s.id}>
                  <TableRow>
                    <TableCell>
                      {siteRacks.length ? (
                        <button
                          type="button"
                          aria-label={
                            expanded
                              ? `Hide racks of ${s.name}`
                              : `Show racks of ${s.name}`
                          }
                          aria-expanded={expanded}
                          className="rounded p-1 text-muted-foreground hover:bg-muted"
                          onClick={() =>
                            setOpen((o) => ({ ...o, [s.id]: !o[s.id] }))
                          }
                        >
                          {expanded ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{s.name}</div>
                      <div className="font-mono text-xs text-muted-foreground">
                        {s.slug}
                      </div>
                    </TableCell>
                    <TableCell>{s.kind ? humanize(s.kind) : "—"}</TableCell>
                    <TableCell>{siteRacks.length}</TableCell>
                    <TableCell>
                      <Link
                        href={`/devices?site=${s.id}`}
                        className="group flex items-center gap-3"
                        aria-label={`${count} devices at ${s.name}`}
                      >
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                          <span
                            className="block h-full rounded-full bg-primary transition-all group-hover:opacity-80"
                            style={{
                              width: `${Math.round((count / maxDevices) * 100)}%`,
                            }}
                          />
                        </span>
                        <span className="w-10 text-right font-medium tabular-nums text-primary group-hover:underline">
                          {count}
                        </span>
                      </Link>
                    </TableCell>
                    <TableCell>
                      {s.netbox_id ? (
                        <Badge variant="muted">NetBox #{s.netbox_id}</Badge>
                      ) : (
                        <Badge variant="muted">Local</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                  {expanded ? (
                    <TableRow className="bg-muted/30 hover:bg-muted/30">
                      <TableCell />
                      <TableCell colSpan={5}>
                        <div className="flex flex-wrap gap-2 py-1">
                          {siteRacks
                            .slice()
                            .sort((a, b) =>
                              a.name.localeCompare(b.name, undefined, {
                                numeric: true,
                              }),
                            )
                            .map((r) => (
                              <span
                                key={r.id}
                                className="rounded-md border bg-card px-2 py-1 text-xs"
                              >
                                {r.name}{" "}
                                <span className="text-muted-foreground">
                                  · {r.u_height}U
                                </span>
                              </span>
                            ))}
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </React.Fragment>
              );
            })}
          </TableBody>
        </Table>
      </Card>
      <SiteFormDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
