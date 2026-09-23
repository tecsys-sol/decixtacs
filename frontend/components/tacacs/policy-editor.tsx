"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Bell, Plus, Trash2 } from "lucide-react";
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
import { useDeviceGroups, useGroups } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { CommandRule, Policy, PolicyIn } from "@/lib/types";
import { cn } from "@/lib/utils";

interface RuleDraft extends CommandRule {
  key: string;
}

let keySeq = 0;
const nextKey = () => `r${++keySeq}`;

export function validatePolicyRules(rules: { pattern: string }[]): (string | null)[] {
  return rules.map((r) => {
    if (!r.pattern.trim()) return "Pattern required";
    try {
      new RegExp(r.pattern);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : "Invalid regex";
    }
  });
}

export function PolicyEditor({ open, onOpenChange, policy }: { open: boolean; onOpenChange: (o: boolean) => void; policy?: Policy }) {
  const qc = useQueryClient();
  const groups = useGroups();
  const deviceGroups = useDeviceGroups();

  const [f, setF] = React.useState<Omit<PolicyIn, "command_rules" | "extra_attributes">>({ name: "", group_id: "" });
  const [rules, setRules] = React.useState<RuleDraft[]>([]);
  const [extra, setExtra] = React.useState("{}");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [ruleErrors, setRuleErrors] = React.useState<(string | null)[]>([]);

  useOnOpen(open, () => {
    setF({
      name: policy?.name ?? "",
      description: policy?.description ?? "",
      priority: policy?.priority ?? 100,
      group_id: policy?.group_id ?? "",
      device_group_id: policy?.device_group_id ?? null,
      privilege_level: policy?.privilege_level ?? 1,
      junos_class: policy?.junos_class ?? "",
      fortigate_profile: policy?.fortigate_profile ?? "",
      arista_role: policy?.arista_role ?? "",
      default_action: policy?.default_action ?? "deny",
      time_window: policy?.time_window ?? "",
      enabled: policy?.enabled ?? true,
    });
    setRules(
      [...(policy?.command_rules ?? [])]
        .sort((a, b) => a.sequence - b.sequence)
        .map((r) => ({ ...r, key: nextKey() })),
    );
    setExtra(JSON.stringify(policy?.extra_attributes ?? {}, null, 2));
    setErrors({});
    setRuleErrors([]);
  });

  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((s) => ({ ...s, [k]: v }));
  const updateRule = (i: number, patch: Partial<RuleDraft>) => setRules((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i: number, d: -1 | 1) =>
    setRules((rs) => {
      const j = i + d;
      if (j < 0 || j >= rs.length) return rs;
      const n = [...rs];
      [n[i], n[j]] = [n[j], n[i]];
      return n;
    });

  const save = useMutation({
    mutationFn: (body: PolicyIn) => (policy ? api.put<Policy>(`/tacacs/policies/${policy.id}`, body) : api.post<Policy>("/tacacs/policies", body)),
    onSuccess: () => {
      toast.success(policy ? "Policy saved" : "Policy created", "Deploy the TACACS+ configuration to apply it.");
      void qc.invalidateQueries({ queryKey: ["tacacs"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not save policy", errorMessage(e)),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.name.trim()) errs.name = "Name is required";
    if (!f.group_id) errs.group_id = "Select the user group this policy applies to";
    const lvl = Number(f.privilege_level);
    if (!Number.isInteger(lvl) || lvl < 0 || lvl > 15) errs.privilege_level = "0–15";
    let extraObj: Record<string, unknown> = {};
    try {
      const parsed: unknown = JSON.parse(extra || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("must be a JSON object");
      extraObj = parsed as Record<string, unknown>;
    } catch (err) {
      errs.extra = `Invalid JSON: ${err instanceof Error ? err.message : ""}`;
    }
    const rErr = validatePolicyRules(rules);
    setErrors(errs);
    setRuleErrors(rErr);
    if (Object.keys(errs).length || rErr.some(Boolean)) return;
    save.mutate({
      ...f,
      name: f.name.trim(),
      description: f.description?.trim() || null,
      privilege_level: lvl,
      priority: Number(f.priority) || 0,
      junos_class: f.junos_class?.trim() || null,
      fortigate_profile: f.fortigate_profile?.trim() || null,
      arista_role: f.arista_role?.trim() || null,
      time_window: f.time_window?.trim() || null,
      extra_attributes: extraObj,
      command_rules: rules.map((r, i) => ({
        sequence: (i + 1) * 10,
        action: r.action,
        pattern: r.pattern,
        description: r.description?.trim() || null,
        alert_on_match: !!r.alert_on_match,
      })),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{policy ? `Edit policy · ${policy.name}` : "New TACACS+ policy"}</DialogTitle>
          <DialogDescription>
            Maps a user group to a privilege level, vendor attributes and ordered command authorisation rules. First matching rule wins.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Name" htmlFor="pname" required error={errors.name}>
              <Input id="pname" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="noc-operators" />
            </Field>
            <Field label="User group" htmlFor="pgroup" required error={errors.group_id}>
              <SimpleSelect id="pgroup" value={f.group_id} onValueChange={(v) => set("group_id", v)} placeholder="Select group" options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))} />
            </Field>
            <Field label="Device group" htmlFor="pdg" hint="Empty = all NAS devices">
              <SimpleSelect id="pdg" value={f.device_group_id ?? ""} onValueChange={(v) => set("device_group_id", v || null)} allowEmpty emptyLabel="All devices" options={(deviceGroups.data ?? []).map((g) => ({ value: g.id, label: g.name }))} />
            </Field>
            <Field label="Privilege level" htmlFor="ppriv" error={errors.privilege_level}>
              <Input id="ppriv" type="number" min={0} max={15} value={f.privilege_level ?? 1} onChange={(e) => set("privilege_level", Number(e.target.value))} />
            </Field>
            <Field label="Priority" htmlFor="pprio" hint="Lower is evaluated first">
              <Input id="pprio" type="number" value={f.priority ?? 100} onChange={(e) => set("priority", Number(e.target.value))} />
            </Field>
            <Field label="Default action" htmlFor="pdef">
              <SimpleSelect id="pdef" value={f.default_action ?? "deny"} onValueChange={(v) => set("default_action", v)} options={[{ value: "deny", label: "Deny" }, { value: "permit", label: "Permit" }]} />
            </Field>
            <Field label="Time window" htmlFor="ptime" hint="cron &quot;* 8-17 * * 1-5&quot; or UUCP &quot;Wk0800-1800&quot;">
              <Input id="ptime" value={f.time_window ?? ""} onChange={(e) => set("time_window", e.target.value)} />
            </Field>
            <Field label="Description" htmlFor="pdesc" className="sm:col-span-2">
              <Input id="pdesc" value={f.description ?? ""} onChange={(e) => set("description", e.target.value)} />
            </Field>
          </div>

          <fieldset className="grid gap-3 rounded-lg border p-3">
            <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Vendor attributes</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Junos class" htmlFor="pjunos">
                <Input id="pjunos" value={f.junos_class ?? ""} onChange={(e) => set("junos_class", e.target.value)} className="font-mono" placeholder="read-only" />
              </Field>
              <Field label="FortiGate profile" htmlFor="pforti">
                <Input id="pforti" value={f.fortigate_profile ?? ""} onChange={(e) => set("fortigate_profile", e.target.value)} className="font-mono" placeholder="super_admin_readonly" />
              </Field>
              <Field label="Arista role" htmlFor="parista">
                <Input id="parista" value={f.arista_role ?? ""} onChange={(e) => set("arista_role", e.target.value)} className="font-mono" placeholder="network-operator" />
              </Field>
            </div>
            <Field label="Extra attributes (JSON)" htmlFor="pextra" error={errors.extra}>
              <Textarea id="pextra" rows={3} value={extra} onChange={(e) => setExtra(e.target.value)} className="font-mono text-xs" spellCheck={false} />
            </Field>
          </fieldset>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Command rules</p>
              <Button
                type="button"
                size="xs"
                variant="outline"
                onClick={() => setRules((rs) => [...rs, { key: nextKey(), sequence: (rs.length + 1) * 10, action: "permit", pattern: "", description: "", alert_on_match: false }])}
              >
                <Plus /> Add rule
              </Button>
            </div>
            {rules.length === 0 ? (
              <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
                No command rules - every command gets the default action ({f.default_action}).
              </p>
            ) : (
              <ol className="grid gap-1.5">
                {rules.map((r, i) => (
                  <li key={r.key} className={cn("grid items-start gap-2 rounded-md border p-2 sm:grid-cols-[32px_110px_minmax(0,2fr)_minmax(0,1fr)_auto]", ruleErrors[i] && "border-destructive/60")}>
                    <span className="pt-2 text-center font-mono text-xs text-muted-foreground">{(i + 1) * 10}</span>
                    <SimpleSelect
                      aria-label="Action"
                      value={r.action}
                      onValueChange={(v) => updateRule(i, { action: v })}
                      options={[{ value: "permit", label: "Permit" }, { value: "deny", label: "Deny" }]}
                      className={cn("h-8", r.action === "deny" ? "text-destructive" : "text-success")}
                    />
                    <div>
                      <Input aria-label="Pattern" value={r.pattern} onChange={(e) => updateRule(i, { pattern: e.target.value })} placeholder="^show .*" className="h-8 font-mono text-xs" spellCheck={false} />
                      {ruleErrors[i] ? <p className="mt-0.5 text-[11px] text-destructive">{ruleErrors[i]}</p> : null}
                    </div>
                    <Input aria-label="Description" value={r.description ?? ""} onChange={(e) => updateRule(i, { description: e.target.value })} placeholder="Description" className="h-8 text-xs" />
                    <div className="flex items-center gap-0.5">
                      <Button type="button" variant={r.alert_on_match ? "secondary" : "ghost"} size="icon-sm" aria-label="Alert on match" aria-pressed={!!r.alert_on_match} title="Alert on match" onClick={() => updateRule(i, { alert_on_match: !r.alert_on_match })}>
                        <Bell className={r.alert_on_match ? "text-warning" : undefined} />
                      </Button>
                      <Button type="button" variant="ghost" size="icon-sm" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                        <ArrowUp />
                      </Button>
                      <Button type="button" variant="ghost" size="icon-sm" aria-label="Move down" disabled={i === rules.length - 1} onClick={() => move(i, 1)}>
                        <ArrowDown />
                      </Button>
                      <Button type="button" variant="ghost" size="icon-sm" aria-label="Remove rule" onClick={() => setRules((rs) => rs.filter((_, j) => j !== i))}>
                        <Trash2 />
                      </Button>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <Checkbox label="Enabled" checked={f.enabled ?? true} onCheckedChange={(c) => set("enabled", c)} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              {policy ? "Save policy" : "Create policy"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
