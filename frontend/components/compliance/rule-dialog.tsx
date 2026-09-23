"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { Field } from "@/components/common/field";
import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { useDeviceGroups, usePlatforms } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import { SEVERITIES } from "@/lib/constants";
import type { ComplianceRule, ComplianceRuleIn, ComplianceRuleType, Severity } from "@/lib/types";
import { humanize } from "@/lib/utils";

const RULE_TYPES: { value: ComplianceRuleType; label: string; hint: string }[] = [
  { value: "must_match", label: "Must match", hint: "At least one line must match the regex" },
  { value: "must_not_match", label: "Must not match", hint: "No line may match the regex" },
  { value: "count_at_least", label: "Count at least", hint: "The regex must match at least N lines" },
  { value: "block_must_match", label: "Block must match", hint: "Inside each block starting with 'block start', the regex must match" },
];

function validRegex(p: string): string | null {
  try {
    new RegExp(p);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : "Invalid regular expression";
  }
}

export function RuleDialog({ open, onOpenChange, rule }: { open: boolean; onOpenChange: (o: boolean) => void; rule?: ComplianceRule }) {
  const qc = useQueryClient();
  const platforms = usePlatforms();
  const groups = useDeviceGroups();
  const empty: ComplianceRuleIn = {
    name: "",
    description: "",
    rule_type: "must_match",
    pattern: "",
    block_start: "",
    min_count: 1,
    platforms: [],
    device_group_id: null,
    severity: "medium",
    remediation: "",
    enabled: true,
  };
  const [f, setF] = React.useState<ComplianceRuleIn>(empty);
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  useOnOpen(open, () => {
    setF(rule ? { ...empty, ...rule } : empty);
    setErrors({});
  });

  const set = <K extends keyof ComplianceRuleIn>(k: K, v: ComplianceRuleIn[K]) => setF((s) => ({ ...s, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const body: ComplianceRuleIn = {
        ...f,
        name: f.name.trim(),
        description: f.description?.trim() || null,
        block_start: f.rule_type === "block_must_match" ? f.block_start?.trim() || null : null,
        remediation: f.remediation?.trim() || null,
        min_count: Number(f.min_count) || 1,
      };
      return rule ? api.put<ComplianceRule>(`/compliance/rules/${rule.id}`, body) : api.post<ComplianceRule>("/compliance/rules", body);
    },
    onSuccess: () => {
      toast.success(rule ? "Rule updated" : "Rule created");
      void qc.invalidateQueries({ queryKey: ["compliance", "rules"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not save rule", errorMessage(e)),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.name.trim()) errs.name = "Name is required";
    if (!f.pattern.trim()) errs.pattern = "Pattern is required";
    else {
      const re = validRegex(f.pattern);
      if (re) errs.pattern = re;
    }
    if (f.rule_type === "block_must_match" && !f.block_start?.trim()) errs.block_start = "Block start is required";
    setErrors(errs);
    if (!Object.keys(errs).length) save.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{rule ? "Edit compliance rule" : "New compliance rule"}</DialogTitle>
          <DialogDescription>Rules are evaluated against the latest stored configuration of every matching device.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="name" required error={errors.name}>
              <Input id="name" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="NTP servers configured" />
            </Field>
            <Field label="Severity" htmlFor="sev">
              <SimpleSelect id="sev" value={f.severity ?? "medium"} onValueChange={(v) => set("severity", v as Severity)} options={SEVERITIES.map((s) => ({ value: s, label: humanize(s) }))} />
            </Field>
            <Field label="Rule type" htmlFor="type" hint={RULE_TYPES.find((r) => r.value === f.rule_type)?.hint} className="sm:col-span-2">
              <SimpleSelect id="type" value={f.rule_type} onValueChange={(v) => set("rule_type", v as ComplianceRuleType)} options={RULE_TYPES} />
            </Field>
            {f.rule_type === "block_must_match" ? (
              <Field label="Block start (regex)" htmlFor="block" required error={errors.block_start} className="sm:col-span-2">
                <Input id="block" value={f.block_start ?? ""} onChange={(e) => set("block_start", e.target.value)} className="font-mono" placeholder="^interface " />
              </Field>
            ) : null}
            <Field label="Pattern (regex)" htmlFor="pattern" required error={errors.pattern} className={f.rule_type === "count_at_least" ? "" : "sm:col-span-2"}>
              <Input id="pattern" value={f.pattern} onChange={(e) => set("pattern", e.target.value)} className="font-mono" placeholder="^set system ntp server " />
            </Field>
            {f.rule_type === "count_at_least" ? (
              <Field label="Minimum count" htmlFor="min">
                <Input id="min" type="number" min={1} value={f.min_count ?? 1} onChange={(e) => set("min_count", Number(e.target.value))} />
              </Field>
            ) : null}
            <Field label="Device group" htmlFor="dg" hint="Limit to a group (optional)">
              <SimpleSelect
                id="dg"
                value={f.device_group_id ?? ""}
                onValueChange={(v) => set("device_group_id", v || null)}
                allowEmpty
                emptyLabel="All devices"
                options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
              />
            </Field>
            <Field label="Platforms" hint="None selected = all platforms">
              <div className="flex max-h-24 flex-wrap gap-x-3 gap-y-1 overflow-y-auto rounded-md border p-2">
                {(platforms.data ?? []).map((p) => (
                  <Checkbox
                    key={p.id}
                    label={<span className="text-xs">{p.name}</span>}
                    checked={(f.platforms ?? []).includes(p.slug)}
                    onCheckedChange={(c) =>
                      set("platforms", c ? [...(f.platforms ?? []), p.slug] : (f.platforms ?? []).filter((x) => x !== p.slug))
                    }
                  />
                ))}
              </div>
            </Field>
            <Field label="Description" htmlFor="desc" className="sm:col-span-2">
              <Input id="desc" value={f.description ?? ""} onChange={(e) => set("description", e.target.value)} />
            </Field>
            <Field label="Remediation" htmlFor="rem" className="sm:col-span-2">
              <Textarea id="rem" value={f.remediation ?? ""} onChange={(e) => set("remediation", e.target.value)} rows={3} className="font-mono text-xs" />
            </Field>
          </div>
          <Checkbox label="Enabled" checked={f.enabled ?? true} onCheckedChange={(c) => set("enabled", c)} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              {rule ? "Save rule" : "Create rule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
