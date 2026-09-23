"use client";

import { Check, Copy, KeyRound } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useLastDefined } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { copyToClipboard } from "@/lib/utils";

/** Shows a secret exactly once (agent token, NAS key, API token). */
export function SecretDialog({
  secret,
  title,
  description,
  onClose,
}: {
  secret: string | null;
  title: string;
  description: React.ReactNode;
  onClose: () => void;
}) {
  const [copied, setCopied] = React.useState(false);
  const shown = useLastDefined(secret);
  return (
    <Dialog open={secret !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-warning" /> {title}
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2">
          <code className="flex-1 break-all font-mono text-xs" data-testid="secret-value">
            {shown}
          </code>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Copy secret"
            onClick={async () => {
              if (!secret) return;
              try {
                await copyToClipboard(secret);
                setCopied(true);
              } catch (e) {
                toast.error("Copy failed", e);
              }
            }}
          >
            {copied ? <Check /> : <Copy />}
          </Button>
        </div>
        <p className="text-xs text-warning">This value will not be shown again. Store it in your secrets manager now.</p>
        <DialogFooter>
          <Button onClick={onClose}>I have stored it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
