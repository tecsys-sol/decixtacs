"use client";

import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";

import { CommandsTable } from "@/components/accounting/commands-table";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { CommandLog, Page } from "@/lib/types";
import { localInputToIso } from "@/lib/utils";

const DEFAULTS = { user: "", device: "", command: "", result: "", start: "", end: "", offset: "0" };

export default function AccountingPage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const offset = Number(f.offset) || 0;
  const set = (k: keyof typeof DEFAULTS) => (v: string) => setF({ [k]: v, offset: "0" });

  const q = useQuery({
    queryKey: ["accounting", "commands", f],
    queryFn: () =>
      api.get<Page<CommandLog>>("/accounting/commands", {
        user: f.user,
        device: f.device,
        command: f.command,
        result: f.result,
        start: localInputToIso(f.start),
        end: localInputToIso(f.end),
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (p) => p,
  });

  const dirty = Object.entries(f).some(([k, v]) => k !== "offset" && v);
  const dangerousOnPage = (q.data?.items ?? []).filter((c) => c.dangerous).length;

  return (
    <>
      <PageHeader
        title="Command accounting"
        description="Every command executed on network devices, as reported by TACACS+ accounting."
      />
      <Card>
        <FilterBar>
          <TextFilter value={f.user} onCommit={set("user")} placeholder="User (exact)" className="w-40" aria-label="User" />
          <TextFilter value={f.device} onCommit={set("device")} placeholder="Device hostname or IP" className="w-52" aria-label="Device" />
          <TextFilter
            value={f.command}
            onCommit={set("command")}
            placeholder="Command substring, or ~regex"
            className="w-72 flex-1 font-mono text-xs"
            aria-label="Command"
          />
          <SimpleSelect
            aria-label="Result"
            value={f.result}
            onValueChange={set("result")}
            allowEmpty
            emptyLabel="Any result"
            className="w-36"
            options={["accounted", "denied", "permit", "deny"].map((r) => ({ value: r, label: r }))}
          />
          <Input type="datetime-local" value={f.start} onChange={(e) => set("start")(e.target.value)} className="w-52" aria-label="From" title="From" />
          <Input type="datetime-local" value={f.end} onChange={(e) => set("end")(e.target.value)} className="w-52" aria-label="To" title="To" />
          {dirty ? (
            <Button variant="ghost" size="sm" onClick={() => setF(DEFAULTS)}>
              Clear
            </Button>
          ) : null}
        </FilterBar>
        <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5" />
          Prefix the command filter with <code className="rounded bg-muted px-1 font-mono">~</code> for a regular expression, e.g.{" "}
          <code className="rounded bg-muted px-1 font-mono">~^delete protocols bgp</code>.
          {dangerousOnPage ? <span className="ml-auto text-destructive">{dangerousOnPage} dangerous on this page</span> : null}
        </div>
        <CommandsTable items={q.data?.items ?? []} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} />
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
    </>
  );
}
