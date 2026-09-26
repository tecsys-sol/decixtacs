"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { CommandsTable } from "@/components/accounting/commands-table";
import { Pagination } from "@/components/common/pagination";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { CommandLog, Device, Page } from "@/lib/types";

export function CommandsTab({ device }: { device: Device }) {
  const [offset, setOffset] = React.useState(0);
  const q = useQuery({
    queryKey: ["accounting", "device", device.id, offset],
    queryFn: () => api.get<Page<CommandLog>>("/accounting/commands", { device_id: device.id, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
  });
  return (
    <Card>
      <CommandsTable items={q.data?.items ?? []} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} hideDevice />
      {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} /> : null}
    </Card>
  );
}
