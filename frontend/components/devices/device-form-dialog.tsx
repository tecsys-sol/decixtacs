"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
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
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { useCredentials, useDeviceGroups, usePlatforms, useSites, useVendors } from "@/hooks/use-lookups";
import { api, errorMessage } from "@/lib/api";
import { DEVICE_ROLES, DEVICE_STATUSES } from "@/lib/constants";
import type { Device, DeviceIn } from "@/lib/types";
import { humanize } from "@/lib/utils";

const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const IPV6 = /^[0-9a-fA-F:]+:[0-9a-fA-F:.]*$/;

export function validateDevice(v: { hostname: string; management_ip: string; ssh_port: string }): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!v.hostname.trim()) errors.hostname = "Hostname is required";
  else if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(v.hostname.trim())) errors.hostname = "Letters, digits, '.', '-' and '_' only";
  if (!v.management_ip.trim()) errors.management_ip = "Management IP is required";
  else if (!IPV4.test(v.management_ip.trim()) && !IPV6.test(v.management_ip.trim()))
    errors.management_ip = "Enter a valid IPv4 or IPv6 address";
  const port = Number(v.ssh_port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) errors.ssh_port = "1–65535";
  return errors;
}

interface FormState {
  hostname: string;
  management_ip: string;
  site_id: string;
  platform_id: string;
  vendor_id: string;
  credential_id: string;
  role: string;
  status: string;
  serial: string;
  ssh_port: string;
  tags: string;
  backup_enabled: boolean;
  group_ids: string[];
}

function initial(device?: Device): FormState {
  return {
    hostname: device?.hostname ?? "",
    management_ip: device?.management_ip ?? "",
    site_id: device?.site?.id ?? "",
    platform_id: device?.platform?.id ?? "",
    vendor_id: device?.vendor?.id ?? "",
    credential_id: device?.credential_id ?? "",
    role: device?.role ?? "",
    status: device?.status ?? "active",
    serial: device?.serial ?? "",
    ssh_port: String(device?.ssh_port ?? 22),
    tags: (device?.tags ?? []).join(", "),
    backup_enabled: device?.backup_enabled ?? true,
    group_ids: (device?.groups ?? []).map((g) => g.id),
  };
}

/** Create (no `device`) or edit a device. */
export function DeviceFormDialog({
  open,
  onOpenChange,
  device,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  device?: Device;
}) {
  const qc = useQueryClient();
  const router = useRouter();
  const sites = useSites();
  const platforms = usePlatforms();
  const vendors = useVendors();
  const credentials = useCredentials();
  const groups = useDeviceGroups();
  const [f, setF] = React.useState<FormState>(() => initial(device));
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  useOnOpen(open, () => {
    setF(initial(device));
    setErrors({});
  });

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const mutation = useMutation({
    mutationFn: async () => {
      const body: DeviceIn = {
        hostname: f.hostname.trim(),
        management_ip: f.management_ip.trim(),
        site_id: f.site_id || null,
        platform_id: f.platform_id || null,
        credential_id: f.credential_id || null,
        role: f.role || null,
        status: f.status,
        ssh_port: Number(f.ssh_port),
        backup_enabled: f.backup_enabled,
        tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
        group_ids: f.group_ids,
      };
      if (device) return api.patch<Device>(`/devices/${device.id}`, body);
      return api.post<Device>("/devices", {
        ...body,
        vendor_id: f.vendor_id || null,
        serial: f.serial.trim() || null,
      });
    },
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ["devices"] });
      qc.setQueryData(["device", d.id], d);
      toast.success(device ? "Device updated" : "Device created", d.hostname);
      onOpenChange(false);
      if (!device) router.push(`/devices/${d.id}`);
    },
    onError: (e) => toast.error(device ? "Could not update device" : "Could not create device", errorMessage(e)),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateDevice(f);
    setErrors(errs);
    if (Object.keys(errs).length === 0) mutation.mutate();
  };

  const opts = <T extends { id: string; name: string }>(xs: T[] | undefined) => (xs ?? []).map((x) => ({ value: x.id, label: x.name }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{device ? `Edit ${device.hostname}` : "Add device"}</DialogTitle>
          <DialogDescription>
            {device ? "Update inventory attributes." : "Register a device for configuration backups, compliance and TACACS+."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Hostname" htmlFor="hostname" required error={errors.hostname}>
              <Input id="hostname" value={f.hostname} onChange={(e) => set("hostname", e.target.value)} autoFocus placeholder="edge01.fra1" />
            </Field>
            <Field label="Management IP" htmlFor="mgmt" required error={errors.management_ip}>
              <Input id="mgmt" value={f.management_ip} onChange={(e) => set("management_ip", e.target.value)} placeholder="192.0.2.10" className="font-mono" />
            </Field>
            <Field label="Site" htmlFor="site">
              <SimpleSelect id="site" value={f.site_id} onValueChange={(v) => set("site_id", v)} options={opts(sites.data)} allowEmpty emptyLabel="None" placeholder="Select site" />
            </Field>
            <Field label="Platform" htmlFor="platform">
              <SimpleSelect id="platform" value={f.platform_id} onValueChange={(v) => set("platform_id", v)} options={opts(platforms.data)} allowEmpty emptyLabel="None" placeholder="Select platform" />
            </Field>
            {device ? null : (
              <Field label="Vendor" htmlFor="vendor">
                <SimpleSelect id="vendor" value={f.vendor_id} onValueChange={(v) => set("vendor_id", v)} options={opts(vendors.data)} allowEmpty emptyLabel="None" placeholder="Select vendor" />
              </Field>
            )}
            <Field label="Credential" htmlFor="cred" hint="Used for SSH backups and restores">
              <SimpleSelect
                id="cred"
                value={f.credential_id}
                onValueChange={(v) => set("credential_id", v)}
                options={(credentials.data ?? []).map((c) => ({ value: c.id, label: `${c.name} (${c.username})` }))}
                allowEmpty
                emptyLabel="None"
                placeholder="Select credential"
              />
            </Field>
            <Field label="Role" htmlFor="role">
              <SimpleSelect id="role" value={f.role} onValueChange={(v) => set("role", v)} options={DEVICE_ROLES.map((r) => ({ value: r, label: humanize(r) }))} allowEmpty emptyLabel="None" placeholder="Select role" />
            </Field>
            <Field label="Status" htmlFor="status">
              <SimpleSelect id="status" value={f.status} onValueChange={(v) => set("status", v)} options={DEVICE_STATUSES.map((s) => ({ value: s, label: humanize(s) }))} />
            </Field>
            {device ? null : (
              <Field label="Serial number" htmlFor="serial">
                <Input id="serial" value={f.serial} onChange={(e) => set("serial", e.target.value)} className="font-mono" />
              </Field>
            )}
            <Field label="SSH port" htmlFor="port" error={errors.ssh_port}>
              <Input id="port" type="number" min={1} max={65535} value={f.ssh_port} onChange={(e) => set("ssh_port", e.target.value)} />
            </Field>
            <Field label="Tags" htmlFor="tags" hint="Comma separated" className="sm:col-span-2">
              <Input id="tags" value={f.tags} onChange={(e) => set("tags", e.target.value)} placeholder="peering, fra1" />
            </Field>
          </div>
          {groups.data?.length ? (
            <Field label="Device groups">
              <div className="flex max-h-32 flex-wrap gap-x-4 gap-y-2 overflow-y-auto rounded-md border p-2">
                {groups.data.map((g) => (
                  <Checkbox
                    key={g.id}
                    label={g.name}
                    checked={f.group_ids.includes(g.id)}
                    onCheckedChange={(c) => set("group_ids", c ? [...f.group_ids, g.id] : f.group_ids.filter((x) => x !== g.id))}
                  />
                ))}
              </div>
            </Field>
          ) : null}
          <Checkbox label="Include in scheduled configuration backups" checked={f.backup_enabled} onCheckedChange={(c) => set("backup_enabled", c)} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {device ? "Save changes" : "Create device"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
