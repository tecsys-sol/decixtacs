import { Badge } from "@/components/ui/badge";
import { statusVariant } from "@/lib/status";
import { humanize } from "@/lib/utils";

export function StatusBadge({
  status,
  label,
  dot = true,
  className,
}: {
  status: string | null | undefined;
  label?: string;
  dot?: boolean;
  className?: string;
}) {
  return (
    <Badge variant={statusVariant(status)} dot={dot} className={className}>
      {label ?? humanize(status ?? "unknown")}
    </Badge>
  );
}
