"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { Field } from "@/components/common/field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { useOnOpen } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { Site } from "@/lib/types";

const SITE_KINDS = [
  { value: "pop", label: "PoP" },
  { value: "datacenter", label: "Data centre" },
  { value: "ixp", label: "IXP" },
  { value: "office", label: "Office" },
  { value: "customer", label: "Customer site" },
];

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "") // drop combining accents (ü -> u)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

/** Create a site (sites otherwise come from NetBox sync). */
export function SiteFormDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [slugEdited, setSlugEdited] = React.useState(false);
  const [kind, setKind] = React.useState<string>("pop");
  const [address, setAddress] = React.useState("");

  useOnOpen(open, () => {
    setName("");
    setSlug("");
    setSlugEdited(false);
    setKind("pop");
    setAddress("");
  });

  const effectiveSlug = slugEdited ? slug : slugify(name);
  const create = useMutation({
    mutationFn: () => api.post<Site>("/sites", { name: name.trim(), slug: effectiveSlug, kind, address: address.trim() || null }),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["sites"] });
      toast.success("Site created", s.name);
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not create site", errorMessage(e)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add site</DialogTitle>
          <DialogDescription>Sites group devices by location (PoP, data centre, IXP).</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && effectiveSlug.replace(/-/g, "")) create.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="site-name" required>
              <Input id="site-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Frankfurt 1" />
            </Field>
            <Field label="Slug" htmlFor="site-slug" hint="Lower-case identifier">
              <Input
                id="site-slug"
                value={effectiveSlug}
                onChange={(e) => {
                  setSlugEdited(true);
                  // keep what is typed (incl. a trailing "-"); only normalise the character set
                  setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-"));
                }}
                className="font-mono"
                placeholder="fra1"
              />
            </Field>
            <Field label="Kind" htmlFor="site-kind">
              <SimpleSelect id="site-kind" value={kind} onValueChange={setKind} options={SITE_KINDS} />
            </Field>
            <Field label="Address" htmlFor="site-address">
              <Input id="site-address" value={address} onChange={(e) => setAddress(e.target.value)} />
            </Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!name.trim() || !effectiveSlug}>
              Create site
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
