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
      <div className="rounded-full border border-destructive/30 bg-destructive/10 p-3">
        <AlertOctagon className="h-5 w-5 text-destructive" aria-hidden />
      </div>
      <p className="text-sm font-medium">
        {forbidden ? "You do not have access to this resource" : notFound ? "Not found" : "Something went wrong"}
      </p>
      <p className="max-w-md break-words text-xs text-muted-foreground">{errorMessage(error)}</p>
      {onRetry && !forbidden && !notFound ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-2">
          <RotateCw /> Retry
        </Button>
      ) : null}
    </div>
  );
}
