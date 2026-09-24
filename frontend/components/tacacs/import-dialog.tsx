"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, KeyRound } from "lucide-react";
import * as React from "react";

import { CodeViewer } from "@/components/common/code-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api } from "@/lib/api";

export interface TacacsImportResult {
  dry_run: boolean;
  created: Record<string, string[]>;
  skipped: Record<string, string[]>;
  warnings: string[];
  users_needing_password: string[];
  conflicts?: string[];
  updated?: string[];
  rendered: string;
}

const KINDS: [string, string][] = [
  ["nas", "NAS clients"],
  ["groups", "Groups"],
  ["policies", "Policies"],
  ["users", "Portal users"],
  ["mappings", "TACACS+ users"],
];

/** Import a classic Shrubbery tac_plus (F4.0.4.x) configuration: preview (dry run) first, then import. */
export function ImportTacPlusDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const qc = useQueryClient();
  const [content, setContent] = React.useState("");
  const [preview, setPreview] = React.useState<TacacsImportResult | null>(null);
  const [done, setDone] = React.useState<TacacsImportResult | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  useOnOpen(open, () => {
    setContent("");
    setPreview(null);
    setDone(null);
  });

  const run = useMutation({
    mutationFn: (dryRun: boolean) =>
      api.post<TacacsImportResult>("/tacacs/import", {
        content,
        dry_run: dryRun,
      }),
    onSuccess: (r) => {
      if (r.dry_run) {
        setPreview(r);
        return;
      }
      setDone(r);
      void qc.invalidateQueries({ queryKey: ["tacacs"] });
      void qc.invalidateQueries({ queryKey: ["users"] });
      void qc.invalidateQueries({ queryKey: ["groups"] });
      toast.success(
        "tac_plus configuration imported",
        "Review the Config preview, then Deploy.",
      );
    },
    onError: (e) => toast.error("Import failed", e),
  });

  const result = done ?? preview;
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setContent(await f.text());
    setPreview(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import existing tac_plus configuration</DialogTitle>
          <DialogDescription>
            Classic Shrubbery <code>tac_plus</code> (F4.0.4.x). NAS clients keep
            their shared keys and users keep their password hashes, so devices
            and engineers need no changes. Nothing is created until you confirm.
          </DialogDescription>
        </DialogHeader>

        {!done ? (
          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="tacplus-config" className="text-sm font-medium">
                tac_plus.conf
              </label>
              <input
                ref={fileRef}
                type="file"
                accept=".conf,.cfg,.txt,text/plain"
                className="hidden"
                onChange={(e) => void onFile(e.target.files?.[0])}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
              >
                <FileUp /> Upload file
              </Button>
            </div>
            <Textarea
              id="tacplus-config"
              value={content}
              onChange={(e) => {
                setContent(e.target.value);
                setPreview(null);
              }}
              placeholder={
                'key = "…"\nhost = 10.20.0.1 { key = "…" }\ngroup = admins { … }\nuser = alice { login = des … member = admins }'
              }
              className="min-h-[220px] font-mono text-xs"
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">
              The file contains keys and password hashes: it is sent only to
              this portal over HTTPS and stored encrypted.
            </p>
          </div>
        ) : null}

        {result ? (
          <div className="grid gap-3" data-testid="tacacs-import-result">
            <div className="flex items-center gap-2 text-sm font-medium">
              {result.dry_run ? (
                <Badge variant="muted">Preview - nothing changed yet</Badge>
              ) : (
                <Badge variant="success">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Imported
                </Badge>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {KINDS.map(([k, label]) => (
                <div key={k} className="rounded-lg border bg-muted/40 p-3">
                  <div className="font-display text-xl font-semibold">
                    {result.created[k]?.length ?? 0}
                  </div>
                  <div className="text-xs text-muted-foreground">{label}</div>
                  {result.skipped[k]?.length ? (
                    <div className="text-[11px] text-muted-foreground">
                      {result.skipped[k].length} already existed
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            {result.conflicts?.length ? (
              <div
                className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
                role="alert"
                data-testid="tacacs-import-conflicts"
              >
                <p className="mb-1 flex items-center gap-2 font-medium text-destructive">
                  <AlertTriangle className="h-4 w-4" />{" "}
                  {result.conflicts.length} difference(s) with what is already
                  in the portal
                </p>
                <p className="mb-1 text-xs">
                  These objects exist in both but are defined differently. The
                  portal&apos;s version is kept - review each one and edit it in
                  the portal if this file is right.
                </p>
                <ul className="list-inside list-disc text-xs">
                  {result.conflicts.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {result.updated?.length ? (
              <div className="rounded-lg border p-3 text-sm">
                <p className="mb-1 font-medium">
                  {result.updated.length} change(s) to existing objects
                </p>
                <ul className="list-inside list-disc text-xs">
                  {result.updated.map((u, i) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {result.users_needing_password.length ? (
              <div
                className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm"
                role="status"
              >
                <p className="mb-1 flex items-center gap-2 font-medium text-warning">
                  <KeyRound className="h-4 w-4" />{" "}
                  {result.users_needing_password.length} user(s) without an
                  importable password
                </p>
                <p className="text-xs">
                  {result.users_needing_password.join(", ")} - set a password
                  under TACACS+ → Users (or use LDAP) before the cut-over,
                  otherwise they cannot log in.
                </p>
              </div>
            ) : null}
            {result.warnings.length ? (
              <details
                className="rounded-lg border border-warning/40 bg-warning/5 p-3"
                open={result.dry_run}
              >
                <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-warning">
                  <AlertTriangle className="h-4 w-4" /> {result.warnings.length}{" "}
                  note(s) to review
                </summary>
                <ul className="mt-2 list-inside list-disc text-xs">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            <details className="rounded-lg border p-3">
              <summary className="cursor-pointer text-sm font-medium">
                Resulting tac_plus-ng configuration
              </summary>
              <div className="mt-2">
                <CodeViewer
                  content={result.rendered}
                  filename="tac_plus-ng.cfg"
                />
              </div>
            </details>
          </div>
        ) : null}

        <DialogFooter>
          {done ? (
            <Button onClick={() => onOpenChange(false)}>Close</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                variant={preview ? "outline" : "default"}
                disabled={!content.trim()}
                loading={run.isPending && run.variables === true}
                onClick={() => run.mutate(true)}
              >
                Preview import
              </Button>
              {preview ? (
                <Button
                  loading={run.isPending && run.variables === false}
                  onClick={() => run.mutate(false)}
                >
                  Import
                </Button>
              ) : null}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
