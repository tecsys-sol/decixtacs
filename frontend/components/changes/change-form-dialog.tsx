"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Field } from "@/components/common/field";
import { DeviceMultiSelect } from "@/components/devices/device-multi-select";
import { Button } from "@/components/ui/button";
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
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import { CHANGE_RISKS } from "@/lib/constants";
import type { Change, ChangeIn } from "@/lib/types";
import { humanize, isoToLocalInput, localInputToIso } from "@/lib/utils";

interface FormState {
  title: string;
  description: string;
  risk: string;
  device_ids: string[];
  start: string;
  end: string;
  implementation_plan: string;
  rollback_plan: string;
  external_ticket: string;
}

function initial(c?: Change): FormState {
  return {
    title: c?.title ?? "",
    description: c?.description ?? "",
    risk: c?.risk ?? "medium",
    device_ids: (c?.device_ids ?? []).map(String),
    start: isoToLocalInput(c?.scheduled_start),
    end: isoToLocalInput(c?.scheduled_end),
    implementation_plan: c?.implementation_plan ?? "",
    rollback_plan: c?.rollback_plan ?? "",
    external_ticket: c?.external_ticket ?? "",
  };
}

export function ChangeFormDialog({ open, onOpenChange, change }: { open: boolean; onOpenChange: (o: boolean) => void; change?: Change }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [f, setF] = React.useState<FormState>(() => initial(change));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  useOnOpen(open, () => {
    setF(initial(change));
    setErrors({});
  });
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const body: ChangeIn = {
        title: f.title.trim(),
        description: f.description.trim() || null,
        risk: f.risk,
        device_ids: f.device_ids,
        scheduled_start: localInputToIso(f.start) ?? null,
        scheduled_end: localInputToIso(f.end) ?? null,
        implementation_plan: f.implementation_plan.trim() || null,
        rollback_plan: f.rollback_plan.trim() || null,
        external_ticket: f.external_ticket.trim() || null,
      };
      return change ? api.patch<Change>(`/changes/${change.id}`, body) : api.post<Change>("/changes", body);
    },
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["changes"] });
      void qc.invalidateQueries({ queryKey: ["change", c.id] });
      toast.success(change ? "Change updated" : `CHG-${c.number} created`, change ? undefined : "Submit it for approval when ready.");
      onOpenChange(false);
      if (!change) router.push(`/changes/${c.id}`);
    },
    onError: (e) => toast.error("Could not save change", errorMessage(e)),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.title.trim()) errs.title = "Title is required";
    if (f.start && f.end && new Date(f.end) <= new Date(f.start)) errs.end = "End must be after start";
    setErrors(errs);
    if (!Object.keys(errs).length) save.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{change ? `Edit CHG-${change.number}` : "New change request"}</DialogTitle>
          <DialogDescription>Approved changes snapshot pre- and post-change backups of the affected devices.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <div className="grid gap-3 sm:grid-cols-[1fr_160px_200px]">
            <Field label="Title" htmlFor="ctitle" required error={errors.title}>
              <Input id="ctitle" value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Add BGP session with AS64500 on edge01" autoFocus />
            </Field>
            <Field label="Risk" htmlFor="crisk">
              <SimpleSelect id="crisk" value={f.risk} onValueChange={(v) => set("risk", v)} options={CHANGE_RISKS.map((r) => ({ value: r, label: humanize(r) }))} />
            </Field>
            <Field label="External ticket" htmlFor="cticket">
              <Input id="cticket" value={f.external_ticket} onChange={(e) => set("external_ticket", e.target.value)} placeholder="JIRA-1234" />
            </Field>
          </div>
          <Field label="Description" htmlFor="cdesc">
            <Textarea id="cdesc" rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Scheduled start" htmlFor="cstart">
              <Input id="cstart" type="datetime-local" value={f.start} onChange={(e) => set("start", e.target.value)} />
            </Field>
            <Field label="Scheduled end" htmlFor="cend" error={errors.end}>
              <Input id="cend" type="datetime-local" value={f.end} onChange={(e) => set("end", e.target.value)} />
            </Field>
          </div>
          <Field label="Affected devices">
            <DeviceMultiSelect value={f.device_ids} onChange={(ids) => set("device_ids", ids)} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Implementation plan" htmlFor="cimpl">
              <Textarea id="cimpl" rows={5} value={f.implementation_plan} onChange={(e) => set("implementation_plan", e.target.value)} className="font-mono text-xs" />
            </Field>
            <Field label="Rollback plan" htmlFor="croll">
              <Textarea id="croll" rows={5} value={f.rollback_plan} onChange={(e) => set("rollback_plan", e.target.value)} className="font-mono text-xs" />
            </Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              {change ? "Save changes" : "Create change"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
