"use client";

import { CheckCircle2, ClipboardCheck } from "lucide-react";
import * as React from "react";

import { Chart } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { countBy, histogram } from "@/lib/aggregate";
import { useDesign } from "@/hooks/use-design";
import { barOption, donutOption, palette, severityColor, type ChartTheme } from "@/lib/charts";
import type { ComplianceRunDetail } from "@/lib/types";
import { formatNumber, humanize } from "@/lib/utils";

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];

const SEVERITY_TEXT: Record<string, string> = {
  critical: "text-sev-critical",
  high: "text-sev-high",
  medium: "text-sev-medium",
  low: "text-sev-low",
};

/** Meridian "Most-failed rules": rule name + severity, a grow-in bar in the severity colour, the count. */
function MostFailedRules({ rules, theme, total }: { rules: { name: string; value: number; severity: string }[]; theme: ChartTheme; total: number }) {
  const max = Math.max(1, total, ...rules.map((r) => r.value));
  return (
    <ul className="flex flex-col gap-3.5 pt-2" aria-label="Most-failed rules">
      {rules.map((r, i) => (
        <li key={r.name} className="flex flex-col gap-1.5">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold" title={r.name}>
              {r.name}
            </span>
            <span className={`shrink-0 text-xs font-semibold ${SEVERITY_TEXT[r.severity] ?? "text-muted-foreground"}`}>{humanize(r.severity)}</span>
          </span>
          <span className="flex items-center gap-3">
            <span className="h-3 flex-1 overflow-hidden rounded-full bg-secondary" aria-hidden>
              <span
                className="grow-bar block h-3 rounded-full"
                style={{ width: `${Math.max(3, (r.value / max) * 100)}%`, background: severityColor(r.severity, theme), animationDelay: `${0.3 + i * 0.08}s` }}
              />
            </span>
            <span className="w-10 text-right font-mono text-[13px] tabular">
              {formatNumber(r.value)}
              <span className="sr-only"> of {formatNumber(total)} devices failing</span>
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Charts for one run's detail: failures by rule, score distribution, severity mix. */
export function RunCharts({ detail, theme, delay = 0 }: { detail: ComplianceRunDetail | undefined; theme: ChartTheme; delay?: number }) {
  const { design } = useDesign();
  const byRule = React.useMemo(() => {
    const items = Object.entries(detail?.failures_by_rule ?? {})
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);
    const sevOf = new Map<string, string>();
    for (const f of detail?.failures ?? []) if (!sevOf.has(f.rule)) sevOf.set(f.rule, f.severity);
    return {
      n: items.length,
      rules: items.slice(0, 7).map((i) => ({ ...i, severity: sevOf.get(i.name) ?? "low" })),
      option: barOption({ categories: items.map((i) => i.name), series: [{ name: "Failing devices", data: items.map((i) => i.value), color: palette(theme)[1] }], horizontal: true, valueLabels: true, labelWidth: 150 }, theme),
    };
  }, [detail, theme]);
  const hist = React.useMemo(() => {
    const h = histogram((detail?.devices ?? []).map((d) => d.score), 10);
    return barOption({ categories: h.labels.map((l) => `${l}%`), series: [{ name: "Devices", data: h.data, color: palette(theme)[0] }], barWidth: 26 }, theme);
  }, [detail, theme]);
  const sev = React.useMemo(() => {
    const counts = countBy(detail?.failures ?? [], (f) => f.severity);
    const items = counts
      .sort((a, b) => SEVERITY_ORDER.indexOf(a.name) - SEVERITY_ORDER.indexOf(b.name))
      .map((c) => ({ name: humanize(c.name), value: c.value, color: severityColor(c.name, theme) }));
    return donutOption({ items, centerValue: formatNumber(detail?.failures.length ?? 0), centerLabel: "failed checks" }, theme);
  }, [detail, theme]);
  const loading = !detail;
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
      <ChartCard
        title={design === "meridian" ? "Most-failed rules" : "Failures by rule"}
        description={design === "meridian" ? `Devices failing, of ${formatNumber(detail?.devices.length ?? 0)} checked` : "Devices failing each rule, top 10"}
        delay={delay}
      >
        <ChartBody loading={loading} empty={!byRule.n} emptyTitle="No failing rules" emptyDescription="Every device passed every rule." emptyIcon={CheckCircle2} emptyArt="success" height={240}>
          {design === "meridian" ? (
            <MostFailedRules rules={byRule.rules} theme={theme} total={detail?.devices.length ?? 0} />
          ) : (
            <Chart option={byRule.option} height={Math.max(180, byRule.n * 32 + 20)} ariaLabel="Failures by rule" />
          )}
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

