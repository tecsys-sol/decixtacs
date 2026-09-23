"use client";

import { Kbd } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SHORTCUT_HELP } from "@/lib/nav";

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Shortcuts work anywhere outside text fields.</DialogDescription>
        </DialogHeader>
        <ul className="divide-y rounded-md border">
          {SHORTCUT_HELP.map((s) => (
            <li key={s.description} className="flex items-center justify-between px-3 py-2 text-sm">
              <span>{s.description}</span>
              <span className="flex items-center gap-1">
                {s.keys.map((k, i) => (
                  <span key={`${k}-${i}`} className="flex items-center gap-1">
                    <Kbd>{k}</Kbd>
                    {i < s.keys.length - 1 && /^[a-z]$/.test(s.keys[0]) ? (
                      <span className="text-[10px] text-muted-foreground">then</span>
                    ) : null}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
