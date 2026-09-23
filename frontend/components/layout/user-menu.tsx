"use client";

import Link from "next/link";
import { Keyboard, LogOut, Settings, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";

function initials(name: string): string {
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

export function UserMenu({ onShowShortcuts }: { onShowShortcuts: () => void }) {
  const { me, logout } = useAuth();
  if (!me) return null;
  const display = me.full_name || me.username;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full bg-avatar text-[13px] font-extrabold text-avatar-foreground transition-shadow hover:ring-2 hover:ring-primary/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          aria-label={`Account menu for ${display}`}
        >
          {initials(display)}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate text-sm font-medium">{display}</p>
          <p className="truncate text-xs text-muted-foreground">{me.email ?? me.username}</p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {me.is_superuser ? <Badge variant="warning">Superuser</Badge> : null}
            <Badge variant={me.mfa_enabled ? "success" : "muted"}>
              <ShieldCheck /> MFA {me.mfa_enabled ? "on" : "off"}
            </Badge>
            <Badge variant="outline">{me.auth_source}</Badge>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings /> Account settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onShowShortcuts}>
          <Keyboard /> Keyboard shortcuts
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()} destructive>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
