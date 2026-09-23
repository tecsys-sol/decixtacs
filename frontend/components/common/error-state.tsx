"use client";

import { AlertOctagon, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const forbidden = error instanceof ApiError && error.status === 403;
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-4 py-10 text-center", className)} role="alert">
      <div className="rounded-[14px] border-2 border-danger/30 bg-danger-soft p-3">
        <AlertOctagon className="h-6 w-6 text-danger" aria-hidden />
      </div>
      <p className="font-display text-[15px] font-semibold">
        {forbidden ? "You do not have access to this resource" : notFound ? "Not found" : "Something went wrong"}
      </p>
      <p className="max-w-md break-words text-[13px] text-ink-3">{errorMessage(error)}</p>
      {onRetry && !forbidden && !notFound ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-2">
          <RotateCw /> Retry
        </Button>
      ) : null}
    </div>
  );
}
