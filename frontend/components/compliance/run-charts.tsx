"use client";

import { CheckCircle2, ClipboardCheck } from "lucide-react";
import * as React from "react";

import { Chart } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { countBy, histogram } from "@/lib/aggregate";
import { barOption, donutOption, palette, STATUS, type ChartMode } from "@/lib/charts";
import type { ComplianceRunDetail } from "@/lib/types";
import { formatNumber, humanize } from "@/lib/utils";

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];

function severityColor(sev: string, mode: ChartMode): string {
  const s = STATUS[mode];
  return sev === "critical" ? s.danger : sev === "high" ? palette(mode)[1] : sev === "medium" ? s.warning : s.info;
}

/** Charts for one run's detail: failures by rule, score distribution, severity mix. */
export function RunCharts({ detail, mode, delay = 0 }: { detail: ComplianceRunDetail | undefined; mode: ChartMode; delay?: number }) {
  const byRule = React.useMemo(() => {
    const items = Object.entries(detail?.failures_by_rule ?? {})
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);
    return {
      n: items.length,
      option: barOption({ categories: items.map((i) => i.name), series: [{ name: "Failing devices", data: items.map((i) => i.value), color: palette(mode)[1] }], horizontal: true, valueLabels: true, labelWidth: 150 }, mode),
    };
  }, [detail, mode]);
  const hist = React.useMemo(() => {
    const h = histogram((detail?.devices ?? []).map((d) => d.score), 10);
    return barOption({ categories: h.labels.map((l) => `${l}%`), series: [{ name: "Devices", data: h.data, color: palette(mode)[0] }], barWidth: 26 }, mode);
  }, [detail, mode]);
  const sev = React.useMemo(() => {
    const counts = countBy(detail?.failures ?? [], (f) => f.severity);
    const items = counts
      .sort((a, b) => SEVERITY_ORDER.indexOf(a.name) - SEVERITY_ORDER.indexOf(b.name))
      .map((c) => ({ name: humanize(c.name), value: c.value, color: severityColor(c.name, mode) }));
    return donutOption({ items, centerValue: formatNumber(detail?.failures.length ?? 0), centerLabel: "failed checks" }, mode);
  }, [detail, mode]);
  const loading = !detail;
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
      <ChartCard title="Failures by rule" description="Devices failing each rule, top 10" delay={delay}>
        <ChartBody loading={loading} empty={!byRule.n} emptyTitle="No failing rules" emptyDescription="Every device passed every rule." emptyIcon={CheckCircle2} emptyArt="success" height={240}>
          <Chart option={byRule.option} height={Math.max(180, byRule.n * 32 + 20)} ariaLabel="Failures by rule" />
        </ChartBody>
      </ChartCard>
      <ChartCard title="Device score distribution" description="Number of devices per score band" delay={delay + 1}>
        <ChartBody loading={loading} empty={!detail?.devices.length} emptyTitle="No devices evaluated" emptyIcon={ClipboardCheck} height={240}>
          <Chart option={hist} height={240} ariaLabel="Device score histogram" />
        </ChartBody>
      </ChartCard>
      <ChartCard title="Severity breakdown" description="Failed checks by rule severity" delay={delay + 2} className="lg:col-span-2 xl:col-span-1">
        <ChartBody loading={loading} empty={!detail?.failures.length} emptyTitle="No failed checks" emptyIcon={CheckCircle2} emptyArt="success" height={240}>
          <Chart option={sev} height={240} ariaLabel="Failed checks by severity" />
        </ChartBody>
      </ChartCard>
    </div>
  );
}

