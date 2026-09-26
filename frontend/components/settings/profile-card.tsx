"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import * as React from "react";

import { Field, KeyValue } from "@/components/common/field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";

/** Your own profile; name and email are editable (they show in greetings, audit trails and change requests). */
export function ProfileCard() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState(false);
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const save = useMutation({
    mutationFn: () => api.patch("/auth/me", { full_name: name, email }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["auth", "me"] });
      toast.success("Profile updated");
      setEditing(false);
    },
    onError: (e) => toast.error("Could not update profile", errorMessage(e)),
  });
  if (!me) return null;
  const start = () => {
    setName(me.full_name ?? "");
    setEmail(me.email ?? "");
    setEditing(true);
  };
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Profile</CardTitle>
        {!editing ? (
          <Button variant="ghost" size="xs" onClick={start}>
            <Pencil /> Edit
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {editing ? (
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <Field label="Name" htmlFor="profile-name" hint={me.auth_source !== "local" ? `Your next ${me.auth_source.toUpperCase()} sign-in may overwrite it` : undefined}>
              <Input id="profile-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={255} autoFocus />
            </Field>
            <Field label="Email" htmlFor="profile-email">
              <Input id="profile-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </Field>
            <div className="flex gap-2">
              <Button type="submit" size="sm" loading={save.isPending}>
                Save
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <KeyValue
            items={[
              ["Username", me.username],
              ["Name", me.full_name],
              ["Email", me.email],
              ["Sign-in", <Badge key="a" variant="outline">{me.auth_source}</Badge>],
              ["Groups", me.groups.length ? me.groups.join(", ") : null],
              ["Permissions", <span key="p" className="text-xs text-muted-foreground">{me.is_superuser ? "all (superuser)" : `${me.permissions.length} granted`}</span>],
            ]}
          />
        )}
      </CardContent>
    </Card>
  );
}
