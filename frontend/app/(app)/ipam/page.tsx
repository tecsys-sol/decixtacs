"use client";

import { useQuery } from "@tanstack/react-query";
import { Binary, ExternalLink, Globe2, Layers, Network, Route } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { KpiTile } from "@/components/common/kpi-tile";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { barOption, donutOption, palette } from "@/lib/charts";
import { formatNumber, humanize } from "@/lib/utils";

type Kind = "prefixes" | "vlans" | "ip-addresses" | "vrfs";

interface IpamSummary {
  counts: Record<Kind, number>;
  synced_at: string | null;
  prefix_status: Record<string, number>;
  prefix_family: Record<string, number>;
  ip_status: Record<string, number>;
  vlans_per_site: Record<string, number>;
}

type Row = Record<string, unknown> & { id: string; url: string | null; netbox_id: string };

interface IpamPage {
  items: Row[];
  total: number;
  limit: number;
  offset: number;
  synced_at: string | null;
}

const LIMIT = 100;

const STATUSES: Record<Kind, string[]> = {
  prefixes: ["active", "container", "reserved", "deprecated"],
  vlans: ["active", "reserved", "deprecated"],
  "ip-addresses": ["active", "reserved", "deprecated", "dhcp", "slaac"],
  vrfs: [],
};

const PLACEHOLDER: Record<Kind, string> = {
  prefixes: "Prefix, site, VLAN, description…",
  vlans: "VID, name, site…",
  "ip-addresses": "Address, DNS name, device, interface…",
  vrfs: "Name, RD…",
};

function Cell({ v, mono }: { v: unknown; mono?: boolean }) {
  if (v === null || v === undefined || v === "") return <span className="text-muted-foreground">—</span>;
  return <span className={mono ? "font-mono text-xs" : undefined}>{String(v)}</span>;
}

function NetBoxLink({ url }: { url: string | null }) {
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noreferrer" className="inline-flex text-muted-foreground hover:text-primary" aria-label="Open in NetBox" title="Open in NetBox">
      <ExternalLink className="h-3.5 w-3.5" />
    </a>
  );
}

function Status({ s }: { s: unknown }) {
  return s ? <StatusBadge status={String(s)} dot={false} /> : <span className="text-muted-foreground">—</span>;
}

const COLUMNS: Record<Kind, { head: string; cell: (r: Row, setF: (p: Record<string, string>) => void) => React.ReactNode; className?: string }[]> = {
  prefixes: [
    {
      head: "Prefix",
      cell: (r) => (
        <span className="font-mono text-xs" style={{ paddingLeft: `${Math.min(Number(r.depth) || 0, 6) * 14}px` }}>
          {String(r.prefix)}
          {r.is_pool ? <Badge variant="muted" className="ml-1.5">pool</Badge> : null}
        </span>
      ),
    },
    { head: "Status", cell: (r) => <Status s={r.status} /> },
    { head: "VRF", cell: (r) => <Cell v={r.vrf ?? "global"} /> },
    { head: "Site", cell: (r) => <Cell v={r.site} /> },
    { head: "VLAN", cell: (r) => <Cell v={r.vlan} /> },
    { head: "Role", cell: (r) => <Cell v={r.role} /> },
    { head: "Tenant", cell: (r) => <Cell v={r.tenant} /> },
    {
      head: "Contents",
      cell: (r, setF) =>
        Number(r.children) > 0 ? (
          <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => setF({ within: String(r.prefix), offset: "0" })}>
            {formatNumber(Number(r.children))} child prefix{Number(r.children) === 1 ? "" : "es"}
          </button>
        ) : (
          <button type="button" className="text-xs text-muted-foreground hover:text-primary hover:underline" onClick={() => setF({ tab: "ip-addresses", within: String(r.prefix), q: "", offset: "0" })}>
            IPs inside
          </button>
        ),
    },
    { head: "Description", cell: (r) => <Cell v={r.description} />, className: "max-w-[260px] truncate" },
  ],
  vlans: [
    { head: "VID", cell: (r) => <span className="font-mono text-xs font-semibold">{String(r.vid ?? "—")}</span> },
    { head: "Name", cell: (r) => <span className="font-medium">{String(r.name ?? "—")}</span> },
    { head: "Status", cell: (r) => <Status s={r.status} /> },
    { head: "Site", cell: (r) => <Cell v={r.site} /> },
    { head: "Group", cell: (r) => <Cell v={r.group} /> },
    {
      head: "Prefixes",
      cell: (r, setF) => {
        const p = (r.prefixes as string[]) ?? [];
        return p.length ? (
          <div className="flex flex-wrap gap-1">
            {p.map((x) => (
              <button key={x} type="button" className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[11px] hover:bg-accent" onClick={() => setF({ tab: "ip-addresses", within: x, q: "", offset: "0" })} title="IP addresses in this prefix">
                {x}
              </button>
            ))}
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    { head: "Tenant", cell: (r) => <Cell v={r.tenant} /> },
    { head: "Description", cell: (r) => <Cell v={r.description} />, className: "max-w-[240px] truncate" },
  ],
  "ip-addresses": [
    { head: "Address", cell: (r) => <Cell v={r.address} mono /> },
    { head: "Status", cell: (r) => <Status s={r.status} /> },
    { head: "VRF", cell: (r) => <Cell v={r.vrf ?? "global"} /> },
    {
      head: "Device",
      cell: (r) =>
        r.device_id ? (
          <Link href={`/devices/${String(r.device_id)}`} className="font-medium text-primary hover:underline">
            {String(r.device)}
          </Link>
        ) : (
          <Cell v={r.device} />
        ),
    },
    { head: "Interface", cell: (r) => <Cell v={r.interface} mono /> },
    { head: "DNS name", cell: (r) => <Cell v={r.dns_name} mono /> },
    { head: "Role", cell: (r) => <Cell v={r.role ? humanize(String(r.role)) : null} /> },
    { head: "Description", cell: (r) => <Cell v={r.description} />, className: "max-w-[240px] truncate" },
  ],
  vrfs: [
    { head: "Name", cell: (r) => <span className="font-medium">{String(r.name)}</span> },
    { head: "RD", cell: (r) => <Cell v={r.rd} mono /> },
    {
      head: "Prefixes",
      cell: (r, setF) => (
        <button type="button" className="font-medium text-primary hover:underline" onClick={() => setF({ tab: "prefixes", vrf: String(r.name), q: "", offset: "0" })}>
          {formatNumber(Number(r.prefixes) || 0)}
        </button>
      ),
    },
    { head: "Tenant", cell: (r) => <Cell v={r.tenant} /> },
    { head: "Description", cell: (r) => <Cell v={r.description} /> },
  ],
};

export default function IpamPageView() {
  const theme = useChartTheme();
  const [f, setF] = useUrlState({ tab: "prefixes", q: "", status: "", family: "", vrf: "", within: "", offset: "0" });
  const kind = (["prefixes", "vlans", "ip-addresses", "vrfs"].includes(f.tab) ? f.tab : "prefixes") as Kind;
  const summary = useQuery({ queryKey: ["ipam", "summary"], queryFn: () => api.get<IpamSummary>("/ipam/summary") });
  const params = {
    q: f.q || undefined,
    status: f.status || undefined,
    family: f.family || undefined,
    vrf: f.vrf || undefined,
    within: kind === "prefixes" || kind === "ip-addresses" ? f.within || undefined : undefined,
    limit: LIMIT,
    offset: Number(f.offset) || 0,
  };
  const list = useQuery({ queryKey: ["ipam", kind, params], queryFn: () => api.get<IpamPage>(`/ipam/${kind}`, params) });
  const s = summary.data;
  const empty = s && Object.values(s.counts).every((n) => n === 0);

  const charts = React.useMemo(() => {
    if (!s) return null;
    const status = Object.entries(s.prefix_status).map(([name, value]) => ({ name: humanize(name), value }));
    const sites = Object.entries(s.vlans_per_site);
    return {
      status: donutOption({ items: status, centerValue: formatNumber(s.counts.prefixes), centerLabel: "prefixes", legend: "right" }, theme),
      family: donutOption(
        { items: Object.entries(s.prefix_family).map(([name, value]) => ({ name, value })), centerValue: String(Object.keys(s.prefix_family).length), centerLabel: "families", legend: "right" },
        theme,
      ),
      sites: barOption({ categories: sites.map(([n]) => n), series: [{ name: "VLANs", data: sites.map(([, v]) => v), color: palette(theme)[3] }], horizontal: true, labelWidth: 120 }, theme),
      nSites: sites.length,
      nStatus: status.length,
    };
  }, [s, theme]);

  const cols = COLUMNS[kind];
  const rows = list.data?.items ?? [];
  const filtered = !!(f.q || f.status || f.family || f.vrf || f.within);

  return (
    <>
      <PageHeader
        title="IPAM"
        description={
          <>
            Prefixes, VLANs, IP addresses and VRFs mirrored from NetBox
            {s?.synced_at ? (
              <>
                {" "}
                · synced <RelativeTime value={s.synced_at} />
              </>
            ) : null}
            . NetBox stays the source of truth - edit there, then sync.
          </>
        }
      />
      {empty ? (
        <Card>
          <EmptyState
            art="network"
            icon={Network}
            title="Nothing mirrored from NetBox yet"
            description={
              <>
                Run a sync under{" "}
                <Link href="/integrations" className="font-medium text-primary">
                  Integrations
                </Link>{" "}
                - VLANs, prefixes, IP addresses and VRFs are mirrored with every NetBox sync.
              </>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiTile label="Prefixes" value={formatNumber(s?.counts.prefixes ?? 0)} icon={Layers} loading={summary.isLoading} href="/ipam?tab=prefixes" />
            <KpiTile label="VLANs" value={formatNumber(s?.counts.vlans ?? 0)} icon={Route} loading={summary.isLoading} href="/ipam?tab=vlans" delay={1} />
            <KpiTile label="IP addresses" value={formatNumber(s?.counts["ip-addresses"] ?? 0)} icon={Binary} loading={summary.isLoading} href="/ipam?tab=ip-addresses" delay={2} />
            <KpiTile label="VRFs" value={formatNumber(s?.counts.vrfs ?? 0)} icon={Globe2} loading={summary.isLoading} href="/ipam?tab=vrfs" delay={3} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <ChartCard title="Prefixes by status">
              <ChartBody loading={summary.isLoading} empty={!charts?.nStatus} emptyTitle="No prefixes" height={200}>
                {charts ? <Chart option={charts.status} height={200} ariaLabel="Prefixes by status" /> : null}
              </ChartBody>
            </ChartCard>
            <ChartCard title="Address families" delay={1}>
              <ChartBody loading={summary.isLoading} empty={!s?.counts.prefixes} emptyTitle="No prefixes" height={200}>
                {charts ? <Chart option={charts.family} height={200} ariaLabel="Prefixes by address family" /> : null}
              </ChartBody>
            </ChartCard>
            <ChartCard title="VLANs per site" description="Top 12" delay={2}>
              <ChartBody loading={summary.isLoading} empty={!charts?.nSites} emptyTitle="No VLANs" height={200}>
                {charts ? <Chart option={charts.sites} height={200} ariaLabel="VLANs per site" /> : null}
              </ChartBody>
            </ChartCard>
          </div>

          <Tabs value={kind} onValueChange={(v) => setF({ tab: v, status: "", within: "", vrf: "", offset: "0" })}>
            <TabsList>
              <TabsTrigger value="prefixes">
                <Layers /> Prefixes
              </TabsTrigger>
              <TabsTrigger value="vlans">
                <Route /> VLANs
              </TabsTrigger>
              <TabsTrigger value="ip-addresses">
                <Binary /> IP addresses
              </TabsTrigger>
              <TabsTrigger value="vrfs">
                <Globe2 /> VRFs
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <Card className="overflow-hidden">
            <FilterBar className="border-b p-3">
              <TextFilter aria-label="Search" placeholder={PLACEHOLDER[kind]} value={f.q} onCommit={(v) => setF({ q: v, offset: "0" })} className="w-full sm:w-72" />
              {STATUSES[kind].length ? (
                <SimpleSelect aria-label="Status" value={f.status} onValueChange={(v) => setF({ status: v, offset: "0" })} allowEmpty emptyLabel="Any status" className="w-40" options={STATUSES[kind].map((x) => ({ value: x, label: humanize(x) }))} />
              ) : null}
              {kind === "prefixes" || kind === "ip-addresses" ? (
                <>
                  <SimpleSelect aria-label="Address family" value={f.family} onValueChange={(v) => setF({ family: v, offset: "0" })} allowEmpty emptyLabel="IPv4 + IPv6" className="w-36" options={[{ value: "4", label: "IPv4" }, { value: "6", label: "IPv6" }]} />
                  <TextFilter aria-label="Within prefix" placeholder="Within e.g. 185.1.0.0/24" value={f.within} onCommit={(v) => setF({ within: v, offset: "0" })} className="w-full font-mono sm:w-56" />
                </>
              ) : null}
              {f.vrf ? (
                <Badge variant="info" className="cursor-pointer" onClick={() => setF({ vrf: "", offset: "0" })} title="Remove VRF filter">
                  VRF {f.vrf} ×
                </Badge>
              ) : null}
            </FilterBar>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {cols.map((c) => (
                      <TableHead key={c.head}>{c.head}</TableHead>
                    ))}
                    <TableHead className="w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableState
                    cols={cols.length + 1}
                    isLoading={list.isLoading}
                    error={list.error}
                    onRetry={() => void list.refetch()}
                    isEmpty={rows.length === 0}
                    empty={<EmptyState icon={Network} title={filtered ? "Nothing matches these filters" : `No ${kind.replace("-", " ")} in NetBox`} description={filtered ? "Clear or change the filters." : undefined} />}
                  />
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      {cols.map((c) => (
                        <TableCell key={c.head} className={c.className}>
                          {c.cell(r, (p) => setF(p as Partial<typeof f>))}
                        </TableCell>
                      ))}
                      <TableCell>
                        <NetBoxLink url={r.url} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <Pagination total={list.data?.total ?? 0} limit={LIMIT} offset={Number(f.offset) || 0} onChange={(o) => setF({ offset: String(o) })} />
          </Card>
        </div>
      )}
    </>
  );
}
