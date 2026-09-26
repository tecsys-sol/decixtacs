import { ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";

const YEAR = new Date().getFullYear();

/** Copyright line and the preview-licence notice, shown under every page. */
export function AppFooter({ className }: { className?: string }) {
  return (
    <footer
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t px-4 py-3 text-xs text-muted-foreground sm:px-8",
        className,
      )}
      data-testid="app-footer"
    >
      <p>
        © {YEAR}{" "}
        <a
          href="https://www.tecsys.in"
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-foreground/80 hover:text-primary hover:underline"
        >
          Tecsys
        </a>
        . All rights reserved.
      </p>
      <p className="inline-flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning-soft px-2.5 py-0.5 text-[11px] font-medium text-warning">
        <ShieldAlert className="h-3 w-3" aria-hidden />
        Commercial tool preview copy. License Validation Pending
      </p>
    </footer>
  );
}
