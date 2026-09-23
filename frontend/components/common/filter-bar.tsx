import { cn } from "@/lib/utils";

export function FilterBar({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-end gap-2 border-b bg-muted/20 p-2 [&>*]:min-w-[140px]", className)}>{children}</div>
  );
}
