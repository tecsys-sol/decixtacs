"use client";

import { useQuery } from "@tanstack/react-query";
import { Building, Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import type { Tenant } from "@/lib/types";

/** Shown only to superusers (platform operators); sets the X-Tenant header for all requests. */
export function TenantSwitcher() {
  const { me, tenant, switchTenant } = useAuth();
  const tenants = useQuery({
    queryKey: ["tenants"],
    queryFn: () => api.get<Tenant[]>("/tenants"),
    enabled: !!me?.is_superuser,
    staleTime: 5 * 60_000,
  });
  if (!me?.is_superuser) return null;

  const home = tenants.data?.find((t) => t.id === me.tenant_id);
  const current = tenants.data?.find((t) => t.slug === tenant) ?? home;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-[38px] max-w-[200px] shrink-0 gap-2" aria-label="Switch tenant">
          <Building className="text-muted-foreground" />
          <span className="hidden truncate sm:inline">{current?.name ?? tenant ?? "Tenant"}</span>
          <ChevronsUpDown className="hidden opacity-50 sm:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-80 w-60 overflow-y-auto">
        <DropdownMenuLabel>Act in tenant</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {tenants.isLoading ? <DropdownMenuItem disabled>Loading…</DropdownMenuItem> : null}
        {tenants.data?.map((t) => {
          const selected = current?.id === t.id;
          return (
            <DropdownMenuItem
              key={t.id}
              onSelect={() => switchTenant(t.id === me.tenant_id ? null : t.slug)}
              disabled={!t.is_active}
            >
              <Check className={selected ? "opacity-100" : "opacity-0"} />
              <span className="truncate">{t.name}</span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">{t.slug}</span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
