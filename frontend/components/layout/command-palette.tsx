"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Building2, Laptop, Loader2, Moon, Network, Server, Sun, User, Workflow, type LucideIcon } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { useAuth } from "@/hooks/use-auth";
import { useDebounce } from "@/hooks/use-debounce";
import { useOnChange } from "@/hooks/use-reset";
import { api } from "@/lib/api";
import { NAV } from "@/lib/nav";
import type { SearchResult } from "@/lib/types";

const TYPE_ICON: Record<string, LucideIcon> = {
  device: Server,
  site: Building2,
  user: User,
  change: Workflow,
  ixp_member: Network,
};

const TYPE_LABEL: Record<string, string> = {
  device: "Devices",
  site: "Sites",
  user: "Users",
  change: "Change requests",
  ixp_member: "IXP members",
};

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const { can } = useAuth();
  const { setTheme } = useTheme();
  const [query, setQuery] = React.useState("");
  const q = useDebounce(query.trim(), 200);

  useOnChange(open, (o) => {
    if (!o) setQuery("");
  });

  const search = useQuery({
    queryKey: ["search", q],
    queryFn: ({ signal }) => api.get<SearchResult[]>("/search", { q }, { signal }),
    enabled: open && q.length >= 2 && can("devices:read"),
    staleTime: 10_000,
  });

  const grouped = React.useMemo(() => {
    const out = new Map<string, SearchResult[]>();
    for (const r of search.data ?? []) {
      const list = out.get(r.type) ?? [];
      list.push(r);
      out.set(r.type, list);
    }
    return out;
  }, [search.data]);

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  const needle = query.trim().toLowerCase();
  const pages = NAV.flatMap((g) => g.items)
    .filter((i) => !i.permission || can(i.permission))
    .filter(
      (i) =>
        !needle ||
        i.title.toLowerCase().includes(needle) ||
        (i.keywords ?? []).some((k) => k.toLowerCase().includes(needle)),
    );

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} shouldFilter={false}>
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder="Search devices, IPs, sites, users, CHG-123, AS numbers…"
      />
      <CommandList>
        {search.isFetching ? (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Searching…
          </div>
        ) : null}
        <CommandEmpty>{q.length >= 2 ? "No results." : "Type at least two characters to search."}</CommandEmpty>
        {[...grouped.entries()].map(([type, items]) => {
          const Icon = TYPE_ICON[type] ?? Server;
          return (
            <CommandGroup key={type} heading={TYPE_LABEL[type] ?? type}>
              {items.map((r) => (
                <CommandItem key={`${r.type}-${r.id}`} value={`${r.type}-${r.id}`} onSelect={() => go(r.href)}>
                  <Icon className="text-muted-foreground" />
                  <span className="truncate">{r.title}</span>
                  {r.subtitle ? <span className="truncate text-xs text-muted-foreground">{r.subtitle}</span> : null}
                </CommandItem>
              ))}
            </CommandGroup>
          );
        })}
        {pages.length ? (
          <CommandGroup heading="Pages">
            {pages.map((p) => (
              <CommandItem key={p.href} value={`page-${p.href}`} onSelect={() => go(p.href)}>
                <p.icon className="text-muted-foreground" />
                {p.title}
                {p.shortcut ? <CommandShortcut>{p.shortcut}</CommandShortcut> : null}
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}
        {!needle || "theme dark light".includes(needle) ? (
          <CommandGroup heading="Theme">
            <CommandItem value="theme-dark" onSelect={() => { setTheme("dark"); onOpenChange(false); }}>
              <Moon className="text-muted-foreground" /> Dark theme
            </CommandItem>
            <CommandItem value="theme-light" onSelect={() => { setTheme("light"); onOpenChange(false); }}>
              <Sun className="text-muted-foreground" /> Light theme
            </CommandItem>
            <CommandItem value="theme-system" onSelect={() => { setTheme("system"); onOpenChange(false); }}>
              <Laptop className="text-muted-foreground" /> System theme
            </CommandItem>
          </CommandGroup>
        ) : null}
      </CommandList>
    </CommandDialog>
  );
}
