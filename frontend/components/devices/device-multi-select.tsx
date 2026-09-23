"use client";

import { X } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useDeviceNames } from "@/hooks/use-lookups";

export function DeviceMultiSelect({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const devices = useDeviceNames();
  const [filter, setFilter] = React.useState("");
  const list = (devices.data ?? []).filter(
    (d) => !filter || d.hostname.toLowerCase().includes(filter.toLowerCase()) || d.management_ip.includes(filter),
  );
  return (
    <div className="grid gap-2">
      {value.length ? (
        <div className="flex flex-wrap gap-1">
          {value.map((id) => (
            <Badge key={id} variant="secondary" className="gap-1 pr-0.5">
              {devices.map.get(id) ?? id.slice(0, 8)}
              <button type="button" className="rounded p-0.5 hover:bg-background/60" aria-label="Remove device" onClick={() => onChange(value.filter((x) => x !== id))}>
                <X />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
      <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search devices" aria-label="Search devices" className="h-8" />
      <div className="max-h-40 overflow-y-auto rounded-md border p-2">
        {devices.isLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : list.length ? (
          list.slice(0, 200).map((d) => (
            <div key={d.id} className="py-0.5">
              <Checkbox
                label={
                  <span className="text-xs">
                    <span className="font-mono">{d.hostname}</span> <span className="text-muted-foreground">{d.management_ip}</span>
                  </span>
                }
                checked={value.includes(d.id)}
                onCheckedChange={(c) => onChange(c ? [...value, d.id] : value.filter((x) => x !== d.id))}
              />
            </div>
          ))
        ) : (
          <p className="text-xs text-muted-foreground">No devices</p>
        )}
      </div>
    </div>
  );
}
