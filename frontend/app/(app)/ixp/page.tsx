"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, Network, RadioTower } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import type { IxpMember, RouteServerClient } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

function speed(mbps: number | null) {
  if (!mbps) return "—";
  return mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`;
}

function MemberConnections({ member }: { member: IxpMember }) {
  const conns = member.connections ?? [];
  if (!conns.length) return <p className="px-4 py-3 text-xs text-muted-foreground">No connections recorded.</p>;
  return (
    <div className="grid gap-3 p-3 md:grid-cols-2">
      {conns.map((c, i) => (
        <div key={i} className="rounded-md border bg-card p-3 text-xs">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-medium">Connection {i + 1}</span>
            {c.state ? <StatusBadge status={c.state} dot={false} /> : null}
          </div>
          <p className="mb-2 text-muted-foreground">
            Ports:{" "}
            {c.ports.length
              ? c.ports.map((p, j) => (
                  <span key={j} className="mr-2 font-mono text-foreground">
                    {String(p.switch ?? "?")} ({speed(p.speed_mbps)})
                  </span>
                ))
              : "—"}
          </p>
          <table className="w-full">
            <thead className="text-muted-foreground">
              <tr className="text-left">
                <th className="py-0.5 font-medium">VLAN</th>
                <th className="py-0.5 font-medium">IPv4</th>
                <th className="py-0.5 font-medium">IPv6</th>
                <th className="py-0.5 font-medium">RS</th>
                <th className="py-0.5 font-medium">Max-prefix</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {c.vlans.map((v, j) => (
                <tr key={j} className="border-t">
                  <td className="py-1 font-sans">{v.vlan ?? v.vlan_id ?? "—"}</td>
                  <td className="py-1">{v.ipv4 ?? "—"}</td>
                  <td className="py-1">{v.ipv6 ?? "—"}</td>
                  <td className="py-1 font-sans">
                    {v.rs_client_v4 ? <Badge variant="success" className="mr-1">v4</Badge> : null}
                    {v.rs_client_v6 ? <Badge variant="success">v6</Badge> : null}
                    {!v.rs_client_v4 && !v.rs_client_v6 ? <span className="text-muted-foreground">no</span> : null}
                  </td>
                  <td className="py-1">
                    {v.max_prefix_v4 ?? "—"} / {v.max_prefix_v6 ?? "—"}
                    {v.as_macro ? <span className="ml-1 font-sans text-muted-foreground">{v.as_macro}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function MembersTab({ q, setQ }: { q: string; setQ: (v: string) => void }) {
  const [open, setOpen] = React.useState<Set<string>>(new Set());
  const members = useQuery({ queryKey: ["ixp", "members", q], queryFn: () => api.get<IxpMember[]>("/ixp/members", { q }) });
  const list = members.data ?? [];
  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });


  return (
    <Card>
      <FilterBar>
        <TextFilter value={q} onCommit={setQ} placeholder="Name or ASN (e.g. AS13335)" className="w-72" aria-label="Search members" />
        <span className="ml-auto self-center text-xs text-muted-foreground">{list.length} members</span>
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-6" />
            <TableHead>ASN</TableHead>
            <TableHead className="w-full">Name</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Policy</TableHead>
            <TableHead>Connections</TableHead>
            <TableHead>Ports</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={members.isLoading} error={members.error} onRetry={() => void members.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={Network} title="No IXP members" description="Configure an IXP Manager integration and sync it." />} />
          {list.map((m) => {
            // a search narrowed to a single member (e.g. from global search) starts expanded
            const isOpen = list.length === 1 ? !open.has(m.id) : open.has(m.id);
            const ports = (m.connections ?? []).flatMap((c) => c.ports);
            const capacity = ports.reduce((a, p) => a + (p.speed_mbps ?? 0), 0);
            return (
              <React.Fragment key={m.id}>
                <TableRow className="cursor-pointer" onClick={() => toggle(m.id)} aria-expanded={isOpen}>
                  <TableCell className="pr-0">{isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</TableCell>
                  <TableCell className="font-mono text-xs">AS{m.asn}</TableCell>
                  <TableCell>
                    <span className="font-medium">{m.name}</span>
                    {m.url ? (
                      <a href={m.url} target="_blank" rel="noreferrer noopener" className="ml-2 inline-flex items-center text-xs text-muted-foreground hover:text-foreground" onClick={(e) => e.stopPropagation()}>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                  </TableCell>
                  <TableCell>{m.member_type ? <Badge variant="outline">{m.member_type}</Badge> : "—"}</TableCell>
                  <TableCell className="text-xs">{m.peering_policy ?? "—"}</TableCell>
                  <TableCell className="tabular">{m.connections?.length ?? 0}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs tabular">
                    {ports.length} × · {speed(capacity)}
                  </TableCell>
                </TableRow>
                {isOpen ? (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={7} className="bg-muted/20 p-0">
                      <MemberConnections member={m} />
                      {m.contacts?.length ? <p className="px-4 pb-3 text-xs text-muted-foreground">Contacts: {m.contacts.join(", ")}</p> : null}
                    </TableCell>
                  </TableRow>
                ) : null}
              </React.Fragment>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

function RsTab({ asn, setAsn }: { asn: string; setAsn: (v: string) => void }) {
  const [problems, setProblems] = React.useState(false);
  const asnNum = asn.toUpperCase().replace(/^AS/, "");
  const q = useQuery({
    queryKey: ["ixp", "rs", asnNum, problems],
    queryFn: () => api.get<RouteServerClient[]>("/ixp/route-server-clients", { asn: /^\d+$/.test(asnNum) ? Number(asnNum) : undefined, only_problems: problems || undefined }),
  });
  const list = q.data ?? [];
  return (
    <Card>
      <FilterBar>
        <TextFilter value={asn} onCommit={setAsn} placeholder="ASN" className="w-40 font-mono" aria-label="ASN" />
        <div className="flex h-9 items-center">
          <Checkbox label="Only sessions with problems" checked={problems} onCheckedChange={setProblems} />
        </div>
        <span className="ml-auto self-center text-xs text-muted-foreground">{list.length} sessions</span>
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Route server</TableHead>
            <TableHead>Member</TableHead>
            <TableHead>Neighbor</TableHead>
            <TableHead>AFI</TableHead>
            <TableHead>State</TableHead>
            <TableHead className="text-right">Accepted</TableHead>
            <TableHead className="text-right">Filtered</TableHead>
            <TableHead className="text-right">Exported</TableHead>
            <TableHead>IRR</TableHead>
            <TableHead>RPKI</TableHead>
            <TableHead>Since</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={11} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={RadioTower} title="No route-server sessions" description="Sync a birdseye integration to import route-server state." />} />
          {list.map((c) => (
            <TableRow key={c.id} className={cn(c.state !== "up" && "bg-destructive/5")}>
              <TableCell className="whitespace-nowrap text-xs">
                {c.route_server}
                <span className="ml-1 text-muted-foreground">{c.protocol}</span>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <span className="font-mono text-xs">AS{c.asn}</span> <span className="text-xs">{c.member ?? ""}</span>
              </TableCell>
              <TableCell className="font-mono text-xs">{c.neighbor}</TableCell>
              <TableCell className="text-xs">{c.afi}</TableCell>
              <TableCell>
                <StatusBadge status={c.state} />
              </TableCell>
              <TableCell className="text-right tabular">{formatNumber(c.accepted)}</TableCell>
              <TableCell className={cn("text-right tabular", (c.filtered ?? 0) > 0 && "font-medium text-warning")}>
                {formatNumber(c.filtered)}
                {(c.irr_filtered ?? 0) || (c.rpki_invalid ?? 0) ? (
                  <p className="text-[10px] font-normal text-muted-foreground">
                    IRR {c.irr_filtered ?? 0} · RPKI inv {c.rpki_invalid ?? 0}
                  </p>
                ) : null}
              </TableCell>
              <TableCell className="text-right tabular">{formatNumber(c.exported)}</TableCell>
              <TableCell>{c.irr_status ? <StatusBadge status={c.irr_status} dot={false} /> : "—"}</TableCell>
              <TableCell>{c.rpki ? <StatusBadge status={c.rpki} dot={false} /> : "—"}</TableCell>
              <TableCell className="whitespace-nowrap text-xs">
                <RelativeTime value={c.since} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

export default function IxpPage() {
  const [f, setF] = useUrlState({ tab: "members", q: "", asn: "" });
  // Global search links here as /ixp?asn=NNN: show the member list filtered to that ASN.
  const memberQ = f.q || (f.asn ? `AS${f.asn}` : "");
  return (
    <>
      <PageHeader title="IXP" description="Members from IXP Manager and route-server session state from birdseye." />
      <Tabs value={f.tab} onValueChange={(v) => setF({ tab: v })}>
        <TabsList>
          <TabsTrigger value="members"><Network /> Members</TabsTrigger>
          <TabsTrigger value="rs"><RadioTower /> Route-server clients</TabsTrigger>
        </TabsList>
        <TabsContent value="members">
          <MembersTab q={memberQ} setQ={(v) => setF({ q: v, asn: "" })} />
        </TabsContent>
        <TabsContent value="rs">
          <RsTab asn={f.asn} setAsn={(v) => setF({ asn: v })} />
        </TabsContent>
      </Tabs>
    </>
  );
}
