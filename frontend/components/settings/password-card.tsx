"use client";

import { useMutation } from "@tanstack/react-query";
import * as React from "react";

import { Field } from "@/components/common/field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";

export function PasswordCard() {
  const { me } = useAuth();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const change = useMutation({
    mutationFn: () => api.post("/auth/password", { current_password: current, new_password: next }),
    onSuccess: () => {
      toast.success("Password changed");
      setCurrent("");
      setNext("");
      setConfirm("");
    },
    onError: (e) => toast.error("Could not change password", errorMessage(e)),
  });

  if (me && me.auth_source !== "local") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>Your password is managed by {me.auth_source.toUpperCase()}.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const mismatch = confirm.length > 0 && next !== confirm;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>Recently used passwords cannot be reused.</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid max-w-sm gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!mismatch) change.mutate();
          }}
        >
          {/* hidden username helps password managers */}
          <input type="text" autoComplete="username" value={me?.username ?? ""} readOnly hidden />
          <Field label="Current password" htmlFor="pcur">
            <Input id="pcur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New password" htmlFor="pnew">
            <Input id="pnew" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="Confirm new password" htmlFor="pconf" error={mismatch ? "Passwords do not match" : null}>
            <Input id="pconf" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </Field>
          <div>
            <Button type="submit" loading={change.isPending} disabled={!current || !next || mismatch}>
              Change password
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
