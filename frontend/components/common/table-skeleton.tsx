import { ErrorState } from "@/components/common/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { TableCell, TableRow } from "@/components/ui/table";

export function TableSkeletonRows({ rows = 8, cols }: { rows?: number; cols: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <TableRow key={r} className="hover:bg-transparent">
          {Array.from({ length: cols }).map((__, c) => (
            <TableCell key={c}>
              <Skeleton className="h-4" style={{ width: `${40 + ((r * 7 + c * 13) % 50)}%` }} />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/** Loading / error / empty states for a table body in one place. */
export function TableState({
  isLoading,
  error,
  isEmpty,
  cols,
  empty,
  onRetry,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty: boolean;
  cols: number;
  empty: React.ReactNode;
  onRetry?: () => void;
}) {
  if (isLoading) return <TableSkeletonRows cols={cols} />;
  if (!error && !isEmpty) return null;
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={cols} className="p-0">
        {error ? <ErrorState error={error} onRetry={onRetry} /> : empty}
      </TableCell>
    </TableRow>
  );
}
