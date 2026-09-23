import { cn } from "@/lib/utils";

export function FilterBar({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-end gap-2.5 border-b border-border/80 px-4 py-3 [&>*]:min-w-[140px]", className)}>{children}</div>
  );
}
