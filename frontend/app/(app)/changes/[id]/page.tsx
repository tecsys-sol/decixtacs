"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowRightLeft, CheckCircle2, GitCompare, MessageSquare, Pencil, Send, XCircle } from "lucide-react";
import * as React from "react";

import { ChangeFormDialog } from "@/components/changes/change-form-dialog";
import { StateTimeline } from "@/components/changes/state-timeline";
import { ErrorState } from "@/components/common/error-state";
import { Field, KeyValue } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button, type ButtonProps } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { useAllUsers, useDeviceNames } from "@/hooks/use-lookups";
import { useLastDefined, useOnChange } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { Change, ChangeDetail } from "@/lib/types";
import { formatDateTime, humanize, shortSha } from "@/lib/utils";

const TRANSITION_META: Record<string, { label: string; variant: ButtonProps["variant"]; permission: string; icon: React.ReactNode; hint: string }> = {
  submit: { label: "Submit for approval", variant: "default", permission: "changes:write", icon: <Send />, hint: "Sends the change to approvers." },
  approve: { label: "Approve", variant: "success", permission: "changes:approve", icon: <CheckCircle2 />, hint: "Four-eyes: the requester cannot approve their own change. Pre-change backups are taken." },
  reject: { label: "Reject", variant: "destructive", permission: "changes:approve", icon: <XCircle />, hint: "Returns the change to the requester." },
  implement: { label: "Mark implemented", variant: "default", permission: "changes:write", icon: <CheckCircle2 />, hint: "Post-change backups are taken for comparison." },
  close: { label: "Close", variant: "secondary", permission: "changes:write", icon: <CheckCircle2 />, hint: "Completes the change." },
  cancel: { label: "Cancel change", variant: "outline", permission: "changes:write", icon: <XCircle />, hint: "Abandons the change." },
};

function TransitionDialog({ change, transition, onClose }: { change: Change; transition: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [comment, setComment] = React.useState("");
  const [takeBackup, setTakeBackup] = React.useState(true);
  useOnChange(transition, () => {
    setComment("");
    setTakeBackup(true);
  });
  const shown = useLastDefined(transition);
  const meta = shown ? TRANSITION_META[shown] : undefined;
  const run = useMutation({
    mutationFn: () => api.post<Change>(`/changes/${change.id}/transition`, { transition, comment: comment.trim() || null, take_backup: takeBackup }),
    onSuccess: (c) => {
      toast.success(`CHG-${c.number} is now ${humanize(c.state).toLowerCase()}`);
      void qc.invalidateQueries({ queryKey: ["change", change.id] });
      void qc.invalidateQueries({ queryKey: ["changes"] });
      onClose();
    },
    onError: (e) => toast.error("Transition failed", errorMessage(e)),
  });
  const needsComment = shown === "reject";
  return (
    <Dialog open={!!transition} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {meta?.label ?? shown} · CHG-{change.number}
          </DialogTitle>
          <DialogDescription>{meta?.hint}</DialogDescription>
        </DialogHeader>
        <Field label={needsComment ? "Reason" : "Comment"} htmlFor="tcomment" required={needsComment}>
          <Textarea id="tcomment" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        {shown === "approve" || shown === "implement" ? (
          <Checkbox
            label={`Take ${shown === "approve" ? "pre" : "post"}-change backups of ${change.device_ids.length} device(s)`}
            checked={takeBackup}
            onCheckedChange={setTakeBackup}
            disabled={change.device_ids.length === 0}
          />
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Back
          </Button>
          <Button variant={meta?.variant ?? "default"} loading={run.isPending} disabled={needsComment && !comment.trim()} onClick={() => run.mutate()}>
            {meta?.icon} {meta?.label ?? shown}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function ChangeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const { can, me } = useAuth();
  const users = useAllUsers();
  const devices = useDeviceNames();
  const [transition, setTransition] = React.useState<string | null>(null);
  const [editOpen, setEditOpen] = React.useState(false);
  const [comment, setComment] = React.useState("");

  const q = useQuery({ queryKey: ["change", id], queryFn: () => api.get<ChangeDetail>(`/changes/${id}`) });

  const addComment = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/changes/${id}/comments`, { body: comment.trim() }),
    onSuccess: () => {
      setComment("");
      void qc.invalidateQueries({ queryKey: ["change", id] });
    },
    onError: (e) => toast.error("Could not add comment", errorMessage(e)),
  });

  const userName = (uid: string | null) => {
    if (!uid) return "system";
    if (uid === me?.id) return me.username;
    return users.data?.find((u) => u.id === uid)?.username ?? uid.slice(0, 8);
  };

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const { change: c, comments, backups, allowed_transitions } = q.data;
  const transitions = allowed_transitions.filter((t) => can(TRANSITION_META[t]?.permission ?? "changes:write"));
  const editable = can("changes:write") && (c.state === "draft" || c.state === "rejected");

  // Pre/post snapshot pairs per device for quick diffs.
  const pre = backups.filter((b) => c.pre_backup_ids.map(String).includes(b.id));
  const post = backups.filter((b) => c.post_backup_ids.map(String).includes(b.id));
  const other = backups.filter((b) => !pre.includes(b) && !post.includes(b));

  const backupRow = (b: ChangeDetail["backups"][number], kind: string) => {
    const pair = kind === "post" ? pre.find((p) => p.device_id === b.device_id) : undefined;
    return (
      <li key={b.id} className="flex items-center gap-2 px-4 py-2 text-sm">
        <Badge variant={kind === "pre" ? "info" : kind === "post" ? "success" : "muted"}>{kind}</Badge>
        <Link href={`/devices/${b.device_id}`} className="font-medium hover:underline">
          {devices.map.get(b.device_id) ?? b.device_id.slice(0, 8)}
        </Link>
        <code className="font-mono text-xs text-muted-foreground">{shortSha(b.commit_sha)}</code>
        <span className="truncate text-xs text-muted-foreground">{b.reason}</span>
        <span className="ml-auto flex items-center gap-2">
          <RelativeTime value={b.collected_at} className="text-xs text-muted-foreground" />
          {pair?.commit_sha && b.commit_sha && pair.commit_sha !== b.commit_sha ? (
            <Button asChild size="xs" variant="outline">
              <Link href={`/devices/${b.device_id}?tab=diff&old=${pair.commit_sha}&new=${b.commit_sha}`}>
                <GitCompare /> Pre → post diff
              </Link>
            </Button>
          ) : null}
        </span>
      </li>
    );
  };

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Changes", href: "/changes" }, { label: `CHG-${c.number}` }]}
        title={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-muted-foreground">CHG-{c.number}</span> {c.title}
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={c.state} /> <StatusBadge status={c.risk} dot={false} label={`${humanize(c.risk)} risk`} /> requested by {userName(c.requested_by)} ·{" "}
            <RelativeTime value={c.created_at} />
          </span>
        }
        actions={
          <>
            {editable ? (
              <Button variant="outline" onClick={() => setEditOpen(true)}>
                <Pencil /> Edit
              </Button>
            ) : null}
            {transitions.map((t) => (
              <Button key={t} variant={TRANSITION_META[t]?.variant ?? "outline"} onClick={() => setTransition(t)}>
                {TRANSITION_META[t]?.icon ?? <ArrowRightLeft />} {TRANSITION_META[t]?.label ?? humanize(t)}
              </Button>
            ))}
          </>
        }
      />

      <Card className="mb-4">
        <CardContent className="pt-4">
          <StateTimeline detail={q.data} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid content-start gap-4 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Description</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm">{c.description || <span className="text-muted-foreground">No description.</span>}</p>
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Implementation plan</CardTitle>
              </CardHeader>
              <CardContent>
                {c.implementation_plan ? (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 font-mono text-xs">{c.implementation_plan}</pre>
                ) : (
                  <p className="text-sm text-muted-foreground">Not provided.</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Rollback plan</CardTitle>
              </CardHeader>
              <CardContent>
                {c.rollback_plan ? (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 font-mono text-xs">{c.rollback_plan}</pre>
                ) : (
                  <p className="text-sm text-muted-foreground">Not provided.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Configuration snapshots</CardTitle>
              <CardDescription>Backups linked to this change (pre on approval, post on implementation)</CardDescription>
            </CardHeader>
            <CardContent className="px-0">
              {backups.length ? (
                <ul className="divide-y">
                  {pre.map((b) => backupRow(b, "pre"))}
                  {post.map((b) => backupRow(b, "post"))}
                  {other.map((b) => backupRow(b, "linked"))}
                </ul>
              ) : (
                <p className="px-4 py-4 text-sm text-muted-foreground">No snapshots yet.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4" /> Activity
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              {comments.length ? (
                <ol className="relative grid gap-4 border-l pl-5">
                  {comments.map((cm) => (
                    <li key={cm.id} className="relative">
                      <span className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" />
                      <p className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{userName(cm.author_id)}</span>{" "}
                        {cm.transition ? (
                          <>
                            moved {cm.transition.split("->").map((s, i) => (
                              <React.Fragment key={i}>
                                {i ? " → " : ""}
                                <StatusBadge status={s} dot={false} className="mx-0.5" />
                              </React.Fragment>
                            ))}
                          </>
                        ) : (
                          "commented"
                        )}{" "}
                        · <span title={formatDateTime(cm.created_at)}><RelativeTime value={cm.created_at} /></span>
                      </p>
                      {cm.body ? <p className="mt-1 whitespace-pre-wrap text-sm">{cm.body}</p> : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">No activity yet.</p>
              )}
              <form
                className="grid gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (comment.trim()) addComment.mutate();
                }}
              >
                <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment" rows={2} aria-label="Comment" />
                <div>
                  <Button type="submit" size="sm" loading={addComment.isPending} disabled={!comment.trim()}>
                    Comment
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>

        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValue
                items={[
                  ["State", <StatusBadge key="s" status={c.state} />],
                  ["Risk", humanize(c.risk)],
                  ["Requested by", userName(c.requested_by)],
                  ["Approved by", c.approved_by ? `${userName(c.approved_by)} · ${formatDateTime(c.approved_at)}` : null],
                  ["Window", c.scheduled_start ? `${formatDateTime(c.scheduled_start)} → ${c.scheduled_end ? formatDateTime(c.scheduled_end) : "open"}` : null],
                  ["Implemented", c.implemented_at ? formatDateTime(c.implemented_at) : null],
                  ["Closed", c.closed_at ? formatDateTime(c.closed_at) : null],
                  ["Ticket", c.external_ticket],
                ]}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Devices ({c.device_ids.length})</CardTitle>
            </CardHeader>
            <CardContent>
              {c.device_ids.length ? (
                <ul className="grid gap-1 text-sm">
                  {c.device_ids.map((d) => (
                    <li key={String(d)}>
                      <Link href={`/devices/${d}`} className="font-mono text-xs hover:underline">
                        {devices.map.get(String(d)) ?? String(d).slice(0, 8)}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No devices linked.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <TransitionDialog change={c} transition={transition} onClose={() => setTransition(null)} />
      <ChangeFormDialog open={editOpen} onOpenChange={setEditOpen} change={c} />
    </>
  );
}
