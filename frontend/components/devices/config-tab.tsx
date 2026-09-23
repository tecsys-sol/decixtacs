"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";

import { CodeViewer } from "@/components/common/code-viewer";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { SimpleSelect } from "@/components/ui/select";
import { api, ApiError } from "@/lib/api";
import type { Device } from "@/lib/types";
import { formatDateTime, shortSha } from "@/lib/utils";

import { useDeviceHistory } from "./use-device-history";

export function ConfigTab({ device, rev, onRevChange }: { device: Device; rev: string; onRevChange: (rev: string) => void }) {
  const history = useDeviceHistory(device.id);
  const config = useQuery({
    queryKey: ["device", device.id, "config", rev],
    queryFn: () => api.get<string>(`/devices/${device.id}/config`, { rev }, { responseType: "text", headers: { Accept: "text/plain" } }),
  });

  const options = [
    { value: "HEAD", label: "Latest (HEAD)" },
    ...(history.data ?? []).map((c) => ({
      value: c.sha,
      label: `${shortSha(c.sha)} · ${formatDateTime(c.timestamp)} · ${c.author}`,
    })),
  ];

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Revision</span>
        <SimpleSelect aria-label="Revision" value={rev} onValueChange={onRevChange} options={options} className="w-full max-w-md" />
      </div>
      {config.isLoading ? (
        <Skeleton className="h-[60vh]" />
      ) : config.error ? (
        config.error instanceof ApiError && config.error.status === 404 ? (
          <EmptyState icon={FileText} title="No configuration stored" description="Run a backup to collect the device configuration." />
        ) : (
          <ErrorState error={config.error} onRetry={() => void config.refetch()} />
        )
      ) : (
        <CodeViewer content={config.data ?? ""} filename={`${device.hostname}-${rev === "HEAD" ? "latest" : shortSha(rev)}.conf`} />
      )}
    </div>
  );
}
