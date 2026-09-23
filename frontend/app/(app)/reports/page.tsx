"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Download, FileBarChart, FileSpreadsheet, FileText, Plus } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Field } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { useUrlState } from "@/hooks/use-url-state";
import { api, errorMessage } from "@/lib/api";
import { REPORT_PERIODS, REPORT_TYPES, type ReportJson, type ReportSchedule } from "@/lib/types";
import { formatDateTime, humanize } from "@/lib/utils";

const TYPE_DESCRIPTIONS: Record<string, string> = {
  device_changes: "Per-device summary of configuration changes",
  config_changes: "Every configuration change with author, reason and risk",
  user_activity: "Portal logins, failures, device commands and portal actions per user",
  compliance: "Latest compliance score per device",
  tacacs: "TACACS+ authentication and authorisation activity",
};

function ScheduleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [f, setF] = React.useState({ name: "", report_type: "config_changes", period: "weekly", fmt: "pdf", recipients: "", enabled: true });
  useOnOpen(open, () => {
    setF({ name: "", report_type: "config_changes", period: "weekly", fmt: "pdf", recipients: "", enabled: true });
  });
  const recipients = f.recipients.split(/[,\s]+/).map((r) => r.trim()).filter(Boolean);
  const invalid = recipients.filter((r) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(r));
  const create = useMutation({
    mutationFn: () => api.post("/report-schedules", { ...f, name: f.name.trim(), recipients }),
    onSuccess: () => {
      toast.success("Schedule created");
      void qc.invalidateQueries({ queryKey: ["report-schedules"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not create schedule", errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Schedule report</DialogTitle>
          <DialogDescription>Generated at the end of each period and emailed to the recipients.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Name" htmlFor="sname" required>
            <Input id="sname" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Weekly change report" />
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Report" htmlFor="stype">
              <SimpleSelect id="stype" value={f.report_type} onValueChange={(v) => setF({ ...f, report_type: v })} options={REPORT_TYPES.map((t) => ({ value: t, label: humanize(t) }))} />
            </Field>
            <Field label="Period" htmlFor="speriod">
              <SimpleSelect id="speriod" value={f.period} onValueChange={(v) => setF({ ...f, period: v })} options={REPORT_PERIODS.map((p) => ({ value: p, label: humanize(p) }))} />
            </Field>
            <Field label="Format" htmlFor="sfmt">
              <SimpleSelect id="sfmt" value={f.fmt} onValueChange={(v) => setF({ ...f, fmt: v })} options={["pdf", "xlsx", "csv"].map((x) => ({ value: x, label: x.toUpperCase() }))} />
            </Field>
          </div>
          <Field label="Recipients" htmlFor="srec" required hint="Comma-separated email addresses" error={invalid.length ? `Invalid: ${invalid.join(", ")}` : null}>
            <Input id="srec" value={f.recipients} onChange={(e) => setF({ ...f, recipients: e.target.value })} placeholder="noc@example.net, cto@example.net" />
          </Field>
          <Checkbox label="Enabled" checked={f.enabled} onCheckedChange={(c) => setF({ ...f, enabled: c })} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!f.name.trim() || !recipients.length || invalid.length > 0}>
              Create schedule
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function ReportsPage() {
  const { can } = useAuth();
  const [f, setF] = useUrlState({ type: "config_changes", period: "daily", end: "" });
  const [downloading, setDownloading] = React.useState<string | null>(null);
  const [scheduleOpen, setScheduleOpen] = React.useState(false);
  const endIso = f.end ? new Date(`${f.end}T23:59:59`).toISOString() : undefined;

  const report = useQuery({
    queryKey: ["report", f.type, f.period, f.end],
    queryFn: () => api.get<ReportJson>(`/reports/${f.type}`, { period: f.period, fmt: "json", end: endIso }),
  });
  const schedules = useQuery({ queryKey: ["report-schedules"], queryFn: () => api.get<ReportSchedule[]>("/report-schedules") });

  const download = async (fmt: "csv" | "xlsx" | "pdf") => {
    setDownloading(fmt);
    try {
      const stamp = (f.end || new Date().toISOString().slice(0, 10)).replace(/-/g, "");
      await api.download(`/reports/${f.type}`, { period: f.period, fmt, end: endIso }, `${f.type}-${f.period}-${stamp}.${fmt}`);
    } catch (e) {
      toast.error("Download failed", errorMessage(e));
    } finally {
      setDownloading(null);
    }
  };

  const data = report.data;
  return (
    <>
      <PageHeader
        title="Reports"
        description="Operational and audit reports for change boards and compliance."
        actions={
          can("alerts:write") ? (
            <Button variant="outline" onClick={() => setScheduleOpen(true)}>
              <CalendarClock /> Schedule
            </Button>
          ) : null
        }
      />
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Parameters</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Field label="Report" htmlFor="rtype" hint={TYPE_DESCRIPTIONS[f.type]}>
              <SimpleSelect id="rtype" value={f.type} onValueChange={(v) => setF({ type: v })} options={REPORT_TYPES.map((t) => ({ value: t, label: humanize(t) }))} />
            </Field>
            <Field label="Period" htmlFor="rperiod">
              <SimpleSelect id="rperiod" value={f.period} onValueChange={(v) => setF({ period: v })} options={REPORT_PERIODS.map((p) => ({ value: p, label: humanize(p) }))} />
            </Field>
            <Field label="Ending on" htmlFor="rend" hint="Defaults to now">
              <Input id="rend" type="date" value={f.end} onChange={(e) => setF({ end: e.target.value })} />
            </Field>
            <div className="grid gap-2 pt-2">
              <p className="text-xs font-medium text-muted-foreground">Download</p>
              <div className="grid grid-cols-3 gap-2">
                <Button variant="outline" size="sm" onClick={() => void download("csv")} loading={downloading === "csv"}>
                  <FileText /> CSV
                </Button>
                <Button variant="outline" size="sm" onClick={() => void download("xlsx")} loading={downloading === "xlsx"}>
                  <FileSpreadsheet /> XLSX
                </Button>
                <Button variant="outline" size="sm" onClick={() => void download("pdf")} loading={downloading === "pdf"}>
                  <Download /> PDF
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>{data?.title ?? humanize(f.type)}</CardTitle>
            <CardDescription>
              {data ? `${formatDateTime(data.start)} → ${formatDateTime(data.end)} · ${data.rows.length} row(s)` : "Preview"}
            </CardDescription>
          </CardHeader>
          {report.isLoading ? (
            <CardContent>
              <Skeleton className="h-64" />
            </CardContent>
          ) : report.error ? (
            <ErrorState error={report.error} onRetry={() => void report.refetch()} />
          ) : data && data.rows.length ? (
            <div className="max-h-[65vh] overflow-auto scrollbar-thin">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-card">
                  <TableRow>
                    {data.columns.map((c) => (
                      <TableHead key={c}>{c}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rows.map((row, i) => (
                    <TableRow key={i}>
                      {row.map((cell, j) => (
                        <TableCell key={j} className={typeof cell === "number" ? "text-right tabular" : "max-w-[360px] truncate"} title={cell === null ? undefined : String(cell)}>
                          {cell === null || cell === "" ? "—" : String(cell)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState icon={FileBarChart} title="No data for this period" />
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Scheduled reports</CardTitle>
            <CardDescription>Delivered by email</CardDescription>
          </div>
          {can("alerts:write") ? (
            <Button size="sm" variant="outline" onClick={() => setScheduleOpen(true)}>
              <Plus /> New schedule
            </Button>
          ) : null}
        </CardHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Report</TableHead>
              <TableHead>Period</TableHead>
              <TableHead>Format</TableHead>
              <TableHead className="w-full">Recipients</TableHead>
              <TableHead>Last run</TableHead>
              <TableHead>State</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={7} isLoading={schedules.isLoading} error={schedules.error} onRetry={() => void schedules.refetch()} isEmpty={(schedules.data ?? []).length === 0} empty={<EmptyState icon={CalendarClock} title="No schedules" />} />
            {(schedules.data ?? []).map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium">{s.name}</TableCell>
                <TableCell>{humanize(s.report_type)}</TableCell>
                <TableCell>{humanize(s.period)}</TableCell>
                <TableCell>
                  <Badge variant="outline">{s.fmt.toUpperCase()}</Badge>
                </TableCell>
                <TableCell className="max-w-0 truncate text-xs">{s.recipients.join(", ")}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={s.last_run_at} />
                </TableCell>
                <TableCell>{s.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <ScheduleDialog open={scheduleOpen} onOpenChange={setScheduleOpen} />
    </>
  );
}
